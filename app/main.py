"""FastAPI app, routes, and error handlers. See DECISIONS.md sections 4 and 5.

uvicorn entry point is the `create_default_app` factory:
    uvicorn app.main:create_default_app --factory --host 127.0.0.1 --port 8420
Importing this module has no side effects, so tests can build their own app against a
temporary data file without ever touching the real one (DECISIONS.md 3.7).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .daytime import BadTimestamp, day_key, format_iso, now_local, parse_iso
from .models import (
    EntryCreate,
    EntryOut,
    EntryUpdate,
    QuoteOut,
    StatsOut,
    ValidationProblem,
    to_out,
    validate_page_range,
)
from .quotes import QuoteSource
from .stats import compute_stats
from .storage import Storage, load_storage_or_exit

# Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY; use the literal so this works on
# both old and new versions without a deprecation warning.
UNPROCESSABLE = 422

API_ROUTES = [
    "POST   /api/entries",
    "GET    /api/entries",
    "PATCH  /api/entries/{id}",
    "DELETE /api/entries/{id}",
    "GET    /api/stats",
    "GET    /api/quote",
]


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


def create_app(storage: Storage, quotes: QuoteSource | None = None) -> FastAPI:
    # The quote source is injectable for the same reason storage is (DECISIONS.md
    # 3.7): no test ever reads the real quotes.txt.
    quotes = quotes or QuoteSource(config.quotes_file())
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

    # -- routes --------------------------------------------------------- #

    @app.get("/")
    async def root() -> dict[str, Any]:
        """A local status page in JSON. Links to nothing external; Phase 2 replaces
        this route with the UI."""
        return {
            "app": "Reading Tracker",
            "status": "ok",
            "schema_version": config.SCHEMA_VERSION,
            "data_file": str(storage.path),
            "api": API_ROUTES,
        }

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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

    @app.get("/api/stats", response_model=StatsOut)
    async def read_stats() -> dict[str, Any]:
        return compute_stats(storage.all(), now_local())

    @app.get("/api/quote", response_model=QuoteOut)
    async def read_quote() -> dict[str, str]:
        """Today's quote, read off disk on every request.

        Reading per-request rather than caching at startup means editing
        quotes.txt shows up on the next page load with no restart. The same
        logical day always yields the same quote, so reloading never shuffles it
        (DECISIONS.md 10).

        This handler touches `quotes` and nothing else. It has no access to
        `storage` and no failure mode -- a missing or empty file is a fallback
        string with a 200, never an error.
        """
        return {"quote": quotes.for_day(day_key(now_local()))}

    return app


def create_default_app() -> FastAPI:
    """uvicorn factory: open the real data file, or print the banner and halt."""
    return create_app(load_storage_or_exit(config.data_file()))


def main() -> None:
    import uvicorn

    # Resolve (and validate) the data file before uvicorn starts, so a corrupt file
    # halts with our banner instead of a traceback buried in server startup logs.
    load_storage_or_exit(config.data_file())
    uvicorn.run(
        "app.main:create_default_app",
        factory=True,
        host=config.HOST,
        port=config.port(),
        log_level="info",
    )


if __name__ == "__main__":
    main()
