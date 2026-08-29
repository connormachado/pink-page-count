"""FastAPI app, routes, and error handlers. See DECISIONS.md sections 4 and 5.

uvicorn entry point is the `create_default_app` factory:
    uvicorn app.main:create_default_app --factory --host 127.0.0.1 --port 8420
Importing this module has no side effects, so tests can build their own app against a
temporary data file without ever touching the real one (DECISIONS.md 3.7).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .classes import ClassStore, load_class_store_or_exit
from .daytime import BadTimestamp, day_key, format_iso, now_local, parse_iso
from .lifecycle import ping_payload
from .models import (
    ClassCreate,
    ClassOut,
    ClassUpdate,
    EntryCreate,
    EntryOut,
    EntryUpdate,
    QuoteOut,
    SettingsOut,
    SettingsUpdate,
    StatsOut,
    ValidationProblem,
    to_out,
    validate_page_range,
)
from .quotes import QuoteSource, ensure_user_quotes_file
from .settings import SettingsStore, load_settings_store_or_exit
from .stats import compute_stats
from .storage import Storage, load_storage_or_exit

# Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY; use the literal so this works on
# both old and new versions without a deprecation warning.
UNPROCESSABLE = 422

# Shown at "/" when web/dist hasn't been built yet. Self-contained -- it cannot
# depend on the very assets that are missing -- and a 200, not a 500 or a
# JSON body: a missing build is a setup step, not a server error.
_NOT_BUILT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Reading Tracker</title>
<style>
  body { background: #fff5f8; color: #2b1a22; font: 16px system-ui, sans-serif;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }
  main { max-width: 32rem; padding: 2rem; text-align: center; }
  code { background: #ffe8f0; border-radius: 4px; padding: 0.15rem 0.4rem; }
</style></head>
<body><main>
  <p>The front end hasn't been built yet.</p>
  <p>From the repo root, run:</p>
  <p><code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code></p>
  <p>Then reload this page.</p>
</main></body></html>"""


def _error(message: str, status_code: int) -> JSONResponse:
    """Every error body is {"error": "..."} -- DECISIONS.md 4.2."""
    return JSONResponse(status_code=status_code, content={"error": message})


def _humanize(errors: list[dict[str, Any]]) -> str:
    """Turn pydantic's error list into one readable sentence."""
    parts = []
    for err in errors:
        location = [str(piece) for piece in err.get("loc", ()) if piece != "body"]
        name = ".".join(location) if location else "request"
        message = err.get("msg", "is invalid")
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        parts.append(f"{name}: {message}")
    return "; ".join(parts) or "The request body was not valid."


def _normalize_read_at(value: str | None) -> str | None:
    """Parse and re-serialize a client timestamp so what lands on disk always carries
    an explicit UTC offset (DECISIONS.md 2.1-2.2)."""
    if value is None:
        return None
    try:
        return format_iso(parse_iso(value))
    except BadTimestamp as exc:
        raise ValidationProblem(str(exc)) from None


def create_app(
    storage: Storage,
    quotes: QuoteSource | None = None,
    *,
    classes: ClassStore,
    settings: SettingsStore,
    dist_dir: Path | None = None,
    on_heartbeat: Callable[[], None] | None = None,
) -> FastAPI:
    """Build the app around injected stores (DECISIONS.md 3.7).

    `classes` and `settings` are REQUIRED and have no default, unlike `quotes`. A
    default would mean `create_app(storage)` silently opens -- and, if missing,
    WRITES -- the real classes.json or settings.json (3.3). The bundled quotes.txt
    is only ever read, and the one write the quotes default can trigger --
    `my-quotes.txt`'s first-run instructions (10.1, amended) -- touches nothing but
    that one optional file, so a default here still cannot damage the reading log.
    A store defaulted into existence would put a test one forgotten argument away
    from touching real data. Requiring `classes` and `settings` makes "no test
    ever touches the real data file" structural rather than a habit; passing an
    explicit `quotes` (as every test does) skips this branch entirely.

    `on_heartbeat` is where the frozen bundle hangs its watchdog (DECISIONS.md
    16.2). Left None -- every test, and `run.command` -- /api/heartbeat still
    exists and still answers, and nothing is listening to it. There is no
    frozen-only route and no frozen-only branch anywhere in this file; the one
    difference between the two launches is whether anyone subscribed.
    """
    if quotes is None:
        user_quotes_path = config.user_quotes_file()
        ensure_user_quotes_file(user_quotes_path)
        quotes = QuoteSource(config.quotes_file(), user_quotes_path)
    dist_dir = dist_dir or config.dist_dir()
    app = FastAPI(
        title="Reading Tracker",
        version="1.0.0",
        # DECISIONS.md 5: the default docs pages pull Swagger UI / ReDoc from a CDN and
        # render blank offline. This app runs fully offline; no route may need the
        # internet. /openapi.json is generated locally and still available.
        docs_url=None,
        redoc_url=None,
    )
    # DECISIONS.md 5: no CORS middleware is installed at all. Same-origin only.

    # -- error handlers ------------------------------------------------- #

    @app.exception_handler(ValidationProblem)
    async def _handle_validation_problem(_request, exc: ValidationProblem):
        return _error(str(exc), UNPROCESSABLE)

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(_request, exc: RequestValidationError):
        return _error(_humanize(exc.errors()), UNPROCESSABLE)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_request, exc: StarletteHTTPException):
        return _error(str(exc.detail), exc.status_code)

    # -- helpers that need the stores ------------------------------------ #

    def check_class_id(value: str | None) -> str | None:
        """A class_id on an entry must name a class that exists, or be null.

        Shared by entry create and patch. The message names the id, per
        DECISIONS.md 4.1 -- a client that sent a stale id needs to see which one.
        """
        if value is None:
            return None
        if classes.get(value) is None:
            raise ValidationProblem(f"No class with id {value}")
        return value

    # -- routes ----------------------------------------------------------- #
    # Every /api/* route, including /api/health, is declared before the static
    # section at the bottom of this function. The two StaticFiles mounts live at
    # disjoint prefixes (/assets, /fonts) so there is no shadowing risk by
    # construction, but this ordering is the belt to that mount design's
    # suspenders.

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/ping")
    async def ping() -> dict[str, Any]:
        """Who is on this port -- DECISIONS.md 16.1.

        Distinct from /api/health, which answers "are you serving yet?" and is
        what the launcher and `run.command` poll during *their own* startup. This
        one answers "are you *me*?", asked by a second launch about a first one,
        and it is the only route whose answer a stranger's web server on port
        8420 cannot accidentally imitate.

        Touches no store and no file: it must be answerable before -- and
        independently of -- anything under DATA_ROOT being readable.
        """
        return ping_payload()

    @app.post("/api/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
    async def heartbeat() -> Response:
        """The open page saying it is still open -- DECISIONS.md 16.2.

        Reads nothing, writes nothing, and returns no body. In the frozen bundle
        this is the *only* thing keeping the process alive; in dev nobody is
        subscribed and it is an accepted no-op (see `create_app`).
        """
        if on_heartbeat is not None:
            on_heartbeat()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/api/entries",
        response_model=EntryOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_entry(payload: EntryCreate) -> dict[str, Any]:
        validate_page_range(payload.page_start, payload.page_end)
        entry = storage.create(
            page_start=payload.page_start,
            page_end=payload.page_end,
            note=payload.note,
            read_at=_normalize_read_at(payload.read_at),
            class_id=check_class_id(payload.class_id),
        )
        return to_out(entry)

    @app.get("/api/entries", response_model=list[EntryOut])
    async def list_entries(
        limit: int | None = Query(default=None, ge=1),
    ) -> list[dict[str, Any]]:
        return [to_out(entry) for entry in storage.list(limit=limit)]

    @app.patch("/api/entries/{entry_id}", response_model=EntryOut)
    async def update_entry(entry_id: str, payload: EntryUpdate) -> dict[str, Any]:
        existing = storage.get(entry_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No entry with id {entry_id}",
            )

        changes = payload.provided()
        if "class_id" in changes:
            check_class_id(changes["class_id"])
        if "read_at" in changes:
            changes["read_at"] = _normalize_read_at(changes["read_at"])
            if changes["read_at"] is None:
                raise ValidationProblem("read_at cannot be null")

        # Validate the MERGED result, not just what was sent (DECISIONS.md 4.1).
        merged_start = changes.get("page_start", existing["page_start"])
        merged_end = changes.get("page_end", existing["page_end"])
        validate_page_range(merged_start, merged_end)

        updated = storage.update(entry_id, changes)
        if updated is None:  # deleted between the read and the write
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No entry with id {entry_id}",
            )
        return to_out(updated)

    @app.delete("/api/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_entry(entry_id: str) -> Response:
        if not storage.delete(entry_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No entry with id {entry_id}",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/classes", response_model=list[ClassOut])
    async def list_classes() -> list[dict[str, Any]]:
        """Non-archived first, then archived (DECISIONS.md 4).

        Archived classes are still returned: the picker hides them, but the entry list
        needs their name and color for entries that already carry them (12.4).
        """
        return classes.list()

    @app.post(
        "/api/classes",
        response_model=ClassOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_class(payload: ClassCreate) -> dict[str, Any]:
        return classes.create(
            title=payload.title,
            description=payload.description,
            color=payload.color,
        )

    @app.patch("/api/classes/{class_id}", response_model=ClassOut)
    async def update_class(class_id: str, payload: ClassUpdate) -> dict[str, Any]:
        changes = payload.provided()
        # `description: null` clears the description. The other three are not
        # nullable -- a class always has a name, a color, and an archived flag.
        for field in ("title", "color", "archived"):
            if field in changes and changes[field] is None:
                raise ValidationProblem(f"{field} cannot be null")

        updated = classes.update(class_id, changes)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No class with id {class_id}",
            )
        return updated

    @app.delete("/api/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_class(class_id: str) -> Response:
        """Delete a class. NEVER deletes an entry (DECISIONS.md 12.3).

        Entries that referenced it keep their page range, date, note, and created_at;
        only class_id is cleared.

        The order of the two writes is fixed by DECISIONS.md 3.8 and is not
        arbitrary: entries first, then the class. If the second write fails, the
        result is entries with no class and a class still listed -- harmless, visible,
        and fixed by pressing delete again. The reverse order would leave entries
        pointing at a class that no longer exists.
        """
        if classes.get(class_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No class with id {class_id}",
            )

        storage.clear_class(class_id)
        classes.delete(class_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/settings", response_model=SettingsOut)
    async def read_settings() -> dict[str, Any]:
        return settings.get()

    @app.patch("/api/settings", response_model=SettingsOut)
    async def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
        changes = payload.provided()
        # theme and default_chip are not nullable -- a settings object always has
        # both. custom_theme IS nullable: null clears any override (DECISIONS.md 13).
        for field in ("theme", "default_chip"):
            if field in changes and changes[field] is None:
                raise ValidationProblem(f"{field} cannot be null")
        return settings.update(changes)

    @app.get("/api/stats", response_model=StatsOut)
    async def read_stats() -> dict[str, Any]:
        return compute_stats(storage.all(), now_local())

    @app.get("/api/quote", response_model=QuoteOut)
    async def read_quote() -> dict[str, str | None]:
        """Today's quote and who said it, read off disk on every request.

        Reading per-request rather than caching at startup means editing
        quotes.txt shows up on the next page load with no restart. The same
        logical day always yields the same quote, so reloading never shuffles it
        (DECISIONS.md 10).

        `attribution` is null whenever the line carried no attributor, which is
        an ordinary line and not a degraded one (DECISIONS.md 10.1, amended).
        The front end renders nothing at all for a null -- no dash, no empty
        element, no reserved space.

        This handler touches `quotes` and nothing else. It has no access to
        `storage` and no failure mode -- a missing or empty file is a fallback
        string with a 200, never an error.
        """
        quote = quotes.for_day(day_key(now_local()))
        return {"text": quote.text, "attribution": quote.attribution}

    @app.get("/api/export")
    async def export() -> JSONResponse:
        """A backup, not a feature: the same data the live endpoints already
        serve, bundled into one file to download. There is no matching import
        route -- restoring means hand-copying the file back over data/*.json.
        """
        payload = {
            "entries": [to_out(entry) for entry in storage.list()],
            "classes": classes.list(),
        }
        filename = f"reading-log-{now_local().date().isoformat()}.json"
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # -- static: the built front end -------------------------------------- #
    # Two narrow mounts rather than one StaticFiles(html=True) mount at "/" --
    # a mount at "/" would match every path, including /api/*, before routing
    # ever got a chance to prefer the more specific route. /assets and /fonts
    # are disjoint prefixes from /api, so there is nothing to shadow.
    #
    # Each mount is added only if its directory exists: StaticFiles raises at
    # construction time otherwise, and a missing web/dist must never crash
    # startup (the front end may simply not be built yet).
    if (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")
    if (dist_dir / "fonts").is_dir():
        app.mount("/fonts", StaticFiles(directory=dist_dir / "fonts"), name="fonts")

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        """Serve the built UI (DECISIONS.md 5). Phase 1-3 status/placeholder is
        gone -- this is what it was always meant to become.

        Read off disk per request rather than cached: this is a single-user app,
        the file is small, and Cache-Control: no-store means a rebuilt index.html
        is never served stale from the browser either.
        """
        index = dist_dir / "index.html"
        if not index.is_file():
            return HTMLResponse(_NOT_BUILT_HTML)
        return HTMLResponse(
            index.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )

    return app


def create_default_app(on_heartbeat: Callable[[], None] | None = None) -> FastAPI:
    """uvicorn factory: open the real data files, or print the banner and halt.

    The argument has a default so this stays a zero-argument factory for the
    uvicorn CLI in `run.command`. `app/launcher.py` is the only caller that
    passes one (DECISIONS.md 16.2).
    """
    return create_app(
        load_storage_or_exit(config.data_file()),
        classes=load_class_store_or_exit(config.classes_file()),
        settings=load_settings_store_or_exit(config.settings_file()),
        on_heartbeat=on_heartbeat,
    )


def main() -> None:
    import uvicorn

    # Resolve (and validate) all three data files before uvicorn starts, so a corrupt
    # file halts with our banner instead of a traceback buried in server startup logs.
    load_storage_or_exit(config.data_file())
    load_class_store_or_exit(config.classes_file())
    load_settings_store_or_exit(config.settings_file())
    uvicorn.run(
        "app.main:create_default_app",
        factory=True,
        host=config.HOST,
        port=config.port(),
        log_level="info",
    )


if __name__ == "__main__":
    main()
