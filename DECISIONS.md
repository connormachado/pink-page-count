# DECISIONS.md

Frozen design decisions for the reading tracker. **Future sessions: read this file
instead of redesigning the schema.** If you need to change something here, change
*this file* in the same commit and say why.

Project shape: single user, single machine, macOS, fully offline. No auth, no
multi-user, no cloud, no database. **Durability of the reading log
(`entries.json`) matters more than anything else in this project.**

Status: Phase 5 of 5 — settings and themes. A third data file,
`data/settings.json`, holds theme choice, custom theme overrides, and the default
chip (section 13). `web/src/tokens.css` is now two layers — a theme layer and the
same semantic layer components have always referenced — so six preset themes and
a custom theme editor exist without any component touching a token name it didn't
already use. FastAPI serves the built `web/dist` directly at `/`, so `run.command`
is the only thing to double-click; there is no more two-server dance. An entry can
carry an optional class for grouping and color; `data/classes.json` is a second
file beside the entry log, and `data/entries.json` is at schema_version 2. `web/`
holds a Vite + React + TypeScript front end built against section 9's tokens.

---

## 1. Data schema

`data/entries.json` — pretty-printed (2-space indent), UTF-8, trailing newline:

```json
{
  "schema_version": 2,
  "entries": [
    {
      "id": "3f2a1c8e-5b7d-4e19-9c02-8a6f1d4b7e30",
      "page_start": 43,
      "page_end": 71,
      "read_at": "2026-08-24T21:12:00-04:00",
      "note": "chapter 4",
      "class_id": "b81d0e4a-2c9f-4a13-8f77-1e5c9d3a2b60",
      "created_at": "2026-08-24T21:12:03-04:00",
      "updated_at": "2026-08-24T21:12:03-04:00"
    }
  ]
}
```

An **append-only event log**. One entry = one reading session. Entries are stored in
insertion order; sorting is a read-time concern, never a storage concern.

| Field | Type | Rules |
|---|---|---|
| `id` | string | uuid4, server-generated, never reused |
| `page_start` | int | `>= 0` |
| `page_end` | int | `>= page_start` |
| `read_at` | string | ISO 8601 **with** UTC offset. Defaults to now; client may supply it for backdating |
| `note` | string \| null | free text, no length cap |
| `class_id` | string \| null | `id` of a class in `classes.json` (12), or null. **Optional on read**: an entry with no `class_id` key reads as null (1.4) |
| `created_at` | string | ISO 8601 with offset, server-set, never changes |
| `updated_at` | string | ISO 8601 with offset, server-set, bumped on every PATCH |

### 1.1 `pages` is computed, never stored

```
pages = page_end - page_start + 1
```

**Page counting is INCLUSIVE.** Pages 43–71 is **29** pages. Pages 43–43 is **1** page.

`pages` appears in every API response and in **no** stored entry. It is never accepted
from the client — a request body containing `pages` has that field silently ignored.
Storing it would let the file contradict its own inputs after a hand-edit; recomputing
on every read makes that impossible.

### 1.2 `schema_version`

`entries.json` is at `2`; `classes.json` is at `1` (12.1). Bump one only when that
file's on-disk shape changes incompatibly, and record the migration in this file.

**The refuse-to-start rule is one-directional.** A file whose `schema_version` is
*newer* than the running code understands is treated as an error, not as corruption —
the app refuses to start rather than touching data written by a future version of
itself. This is the same halt-don't-recover policy §3.4 applies to a corrupt file.

A file whose version is *older* is never a halt. It loads, it is served correctly, and
it is rewritten at the current version by the next ordinary mutation and at no other
time. A file written by Phase 3 code opens cleanly here — see 1.4.

### 1.3 `class_id` is a reference, and a dangling one is not corruption

`class_id` holds the `id` of a class in `data/classes.json` (12), or `null`. The entry
file knows nothing else about classes: `app/storage.py` does not import the class store,
and there is no path through it that reads or writes `classes.json`.

A `class_id` naming a class that is **not** in `classes.json` — after a hand edit, or a
crash between the two writes of §3.8 — **is not corruption and does not stop the
server.** It loads, and the front end renders that entry with no class.

Referential integrity across two files is not schema validity, and halting over a
missing dot would lock her out of the app to protect nothing. §3.4 is for a file this
code cannot interpret; a dangling reference is one it interprets fine.

### 1.4 Migration to version 2 is read-time only

An entry with no `class_id` key reads as `class_id: null`. That is the whole migration.

**Nothing is rewritten at startup.** A `schema_version` 1 file loads, serves correctly,
and becomes version 2 on the next ordinary mutation — a save, an edit, a delete — and at
no other time. A file written by Phase 3 code opens cleanly here and stays byte-identical
until she next changes something.

A startup migration would make the app's first act on the one file this project exists
to protect a write nobody asked for, at the moment she is least able to notice it went
wrong. Reading the old shape correctly costs one `dict.get` and cannot lose data.

---

## 2. Timestamps and the day boundary

### 2.1 Format

All three timestamps are ISO 8601 with an explicit UTC offset, e.g.
`2026-08-24T21:12:00-04:00`. Never bare UTC, never naive. Local timezone is the system
timezone (`datetime.astimezone()`); tests pin it with `TZ` + `time.tzset()`.

### 2.2 Naive `read_at` input is interpreted as local time

A client-supplied `read_at` with no offset (`2026-08-20T21:30:00`) gets the system's
local offset attached and is **stored normalized with that offset**. This keeps
hand-editing and quick `curl` backdating easy while guaranteeing everything on disk is
fully qualified. Only genuinely unparseable strings produce a 422.

### 2.3 A "day" runs 4am → 4am local

Reading logged at 1am Tuesday counts as **Monday**.

This lives in exactly one function, `app/daytime.py::day_key(dt) -> datetime.date`:
convert the aware datetime to system local time, subtract 4 hours, return the calendar
date. `pages_today`, `current_streak_days`, and `longest_streak_days` all call this and
nothing else. There is no second implementation of the boundary anywhere.

`day_key` takes an explicit datetime argument — it never reads the clock itself — so
every caller is testable without freezing time globally.

### 2.4 Streaks

Build the set of `day_key`s that have at least one entry.

- **`current_streak_days`**: start the cursor at today's key if it is in the set,
  otherwise at yesterday's. Walk backward while the cursor stays in the set.
  Today having no entry yet does **not** break the streak; two consecutive empty days
  does. Empty log → `0`.
- **`longest_streak_days`**: the longest consecutive run anywhere in history.
- **`first_entry_date`**: the earliest `day_key`, as a `YYYY-MM-DD` string, or `null`.

---

## 3. Storage

### 3.1 Atomic writes

Both data files — `entries.json` and `classes.json` — write through **one shared
implementation**, `app/jsonfile.py::atomic_write_json`. It is not duplicated per file
and never will be; this path is the most safety-critical code in the project, and two
copies of it means one of them eventually drifts and only one of them is tested.

Every mutation writes the whole file through this path:

1. `tempfile.mkstemp` in the **same directory** as the target (same filesystem, so the
   rename is atomic).
2. Write the serialized JSON, `flush()`.
3. **Durably sync the file descriptor** (see 3.2).
4. `close()`.
5. `os.replace(tmp, target)` — atomic on POSIX; readers see either the entire old
   file or the entire new one, never a truncated one.
6. `open()` the containing directory and sync **that** fd, so the rename itself survives
   a power cut.

On any failure the temp file is removed, so a crashed write leaves no litter beside the
real data file.

**A crash mid-write must never produce a truncated or empty `entries.json`.** That is
the whole point of this section.

### 3.2 macOS needs `F_FULLFSYNC`

On macOS a plain `os.fsync()` returns once the data reaches the drive's write cache, not
once it is actually on the platter/flash. Only `fcntl(fd, F_FULLFSYNC)` guarantees
survival of a power cut. Given that durability is this project's top priority, the sync
step uses `F_FULLFSYNC` and falls back to `os.fsync()` when it raises `OSError`
(non-APFS or network volumes reject it). The extra few milliseconds per write are
irrelevant for a single user logging a handful of entries a day.

### 3.3 Missing file

If `data/entries.json` does not exist, create `data/` if needed and write
`{"schema_version": 2, "entries": []}` through the same atomic path. Not an error.
Likewise `data/classes.json` gets `{"schema_version": 1, "classes": []}`.

A missing file is created at the **current** version. That is a first write, not a
migration, and it is the only write that ever happens at startup (1.4).

### 3.4 Corrupt file: refuse to start

A file is **corrupt** if it fails to parse as JSON, parses to something that is not a
top-level object, is missing its list key (`entries` / `classes`) or that key is not a
list, or contains any record that fails schema validation.

**This applies to `data/classes.json` exactly as it applies to `data/entries.json`.**
Coming up with an empty class list would strip the grouping off every entry on screen
and present that as the truth, which is the same category of lie §3.4 exists to refuse.

A `class_id` that names a class not present in `classes.json` is **not** corruption and
does not stop the server — see 1.3.

On corruption:

1. **Do not rename the file. Do not create a quarantine copy. Do not write anything.**
   The file stays exactly where it is, byte for byte.
2. Print a loud multi-line banner to **stderr** naming the file path, the parse error,
   and the line/offset if available.
3. **Exit non-zero. The server does not come up.**

Rationale: this is the same policy §1.2 already applies to a too-new `schema_version` —
a file this code cannot safely interpret is a **halt, not a recovery**. Starting fresh
would present an empty log as if it were the truth, and an empty log is a lie that looks
like data. Refusing to start puts the file in front of the user, unmodified, with the
error that explains it. **Nothing is ever moved or overwritten.**

### 3.5 Load once, write through

The entries list is loaded into memory at startup and held there. Reads are served from
memory; **every mutation persists the whole file before returning**. There is no
write-behind, no batching, no dirty flag — a request that returned 200 is a request
whose data is already on disk.

### 3.6 Concurrency

One `threading.Lock` wraps each read-modify-write-persist cycle. uvicorn runs a single
worker. No cross-process locking is attempted; this is a single-user local tool and two
concurrent servers are a user error, not a supported case.

### 3.7 Storage is injectable

`Storage(path)` is a class. `app/main.py` instantiates exactly one, from
`PAGECOUNT_DATA_FILE` (default `data/entries.json`). `ClassStore(path)` is the same
shape, from `PAGECOUNT_CLASSES_FILE`. Tests construct their own against a `tmp_path`.
**No test ever touches the real data file.**

### 3.8 Two files, two locks, and the order a class delete writes them

`entries.json` and `classes.json` are separate store objects with separate locks.
Nothing takes both locks at once, so there is no lock ordering to get wrong.

Deleting a class is the one operation that writes both files, and two files cannot be
replaced atomically together. **The order is fixed, and it is not arbitrary:**

1. Null `class_id` on every affected entry, and persist `entries.json`.
2. Remove the class, and persist `classes.json`.

If the second write fails, the result is entries with no class and a class still listed —
harmless, visible, and fixed by pressing delete again. The reverse order would leave
entries pointing at a class that no longer exists. **Neither order can lose a page
range**, because step 1 rewrites exactly one field per entry (12.3).

---

## 4. API

Base path `/api`. All request and response bodies are JSON.

| Method | Path | Body / params | Success |
|---|---|---|---|
| `POST` | `/api/entries` | `page_start`, `page_end`, `note?`, `read_at?`, `class_id?` | `201` + entry |
| `GET` | `/api/entries` | `?limit` optional, `>= 1` | `200` + entry list |
| `PATCH` | `/api/entries/{id}` | any of `page_start`, `page_end`, `note`, `read_at`, `class_id` | `200` + entry |
| `DELETE` | `/api/entries/{id}` | — | `204` |
| `GET` | `/api/classes` | — | `200` + class list |
| `POST` | `/api/classes` | `title`, `description?`, `color?` | `201` + class |
| `PATCH` | `/api/classes/{id}` | any of `title`, `description`, `color`, `archived` | `200` + class |
| `DELETE` | `/api/classes/{id}` | — | `204` |
| `GET` | `/api/stats` | — | `200` + stats |
| `GET` | `/api/quote` | — | `200` + `{"quote": "..."}` |
| `GET` | `/api/export` | — | `200` + `{"entries": [...], "classes": [...]}`, as a download |

`GET /api/entries` returns **newest first**, sorted by `read_at` descending with
`created_at` descending as the tiebreak. The front end relies on this: the class picker's
default is the first entry in that list (12.4).

`GET /api/classes` returns **non-archived first, then archived**, each group in
case-insensitive title order.

`DELETE /api/classes/{id}` returns `204` and **never deletes an entry** — see 12.3.

`GET /api/stats` returns:

```json
{
  "pages_today": 29,
  "pages_all_time": 412,
  "current_streak_days": 5,
  "entry_count": 17,
  "first_entry_date": "2026-07-30"
}
```

Every entry in every response carries the computed `pages` field.

### 4.1 Validation

| Condition | Status |
|---|---|
| `page_end < page_start` | `422`, message names **both** values |
| `page_start < 0` | `422` |
| unparseable `read_at` | `422` |
| `limit < 1` or non-integer | `422` |
| unknown `id` on entry `PATCH` / `DELETE` | `404` |
| unknown `class_id` on entry `POST` / `PATCH` | `422`, message **names the id** |
| empty or whitespace-only class `title` | `422` |
| class `title` longer than 60 characters after strip | `422` |
| duplicate class `title`, case-insensitive, among non-archived | `422` |
| malformed class `color` (not `#RGB` or `#RRGGBB`) | `422` |
| unknown `id` on class `PATCH` / `DELETE` | `404` |

Type and range checks (`page_start >= 0`, integer-ness) live in the pydantic models.
The cross-field `page_end >= page_start` check lives in **one shared helper** used by
both POST and PATCH, because PATCH must validate the *merged* result against the stored
entry — patching only `page_start` to a value above the existing `page_end` must fail.

Class title validation follows the same rule for the same reason: one helper, used by
both POST and PATCH, checking the *merged* result. Un-archiving a class whose title now
collides with a live one is the same 422 as creating a duplicate. A title may duplicate
an **archived** class — the constraint is only among non-archived, so putting a class
away and starting a fresh one with the same name works.

### 4.2 Error bodies

Every error response is:

```json
{"error": "human readable message"}
```

FastAPI's default is `{"detail": ...}`, so handlers for `RequestValidationError`,
`HTTPException`, and the domain validation error are installed to normalize all of them.
The page-order message names both numbers, e.g.

```
page_end (12) must be greater than or equal to page_start (40)
```

### 4.3 Per-class stats are deliberately absent

`/api/stats?class_id=` and `/api/stats/by-class` **do not exist.** They land with the
stats page in a later phase, and they have no consumer before it.

An endpoint built ahead of its consumer gets shaped by guesses instead of by a screen.
This one has a second reason: a per-class breakdown is exactly where this app would grow
a scoreboard, so its absence is a §8 decision to be made deliberately with a real design
in front of us, not a gap to fill in passing. See 12.5.

### 4.4 Export is a backup, not a feature

`GET /api/export` returns exactly what the live endpoints would return for "give me
everything" — `storage.list()` through the same `to_out()` transform `GET /api/entries`
uses, plus `classes.list()`, the same list `GET /api/classes` returns. There is no
separate export-shaping code to drift from the real payload.

The response carries `Content-Disposition: attachment; filename="reading-log-
YYYY-MM-DD.json"`, using the calendar date `now_local().date()` — a file timestamp,
not the 4am-shifted day-key §2.3 uses for streaks.

**There is no import or restore endpoint.** Restoring means hand-copying the
downloaded file back over `data/entries.json` and `data/classes.json` with the server
stopped. Building an import path would mean re-deriving the atomic-write and
corrupt-file rules of §3 for a second entry point into the same files; the front door
those files already have is enough, and this is a backup mechanism, not a feature to
grow.

---

## 5. Server

- Binds to **`127.0.0.1` only. Never `0.0.0.0`.** Hard-coded, not configurable.
- Port **8420**, override with the `PAGECOUNT_PORT` env var.
- **No CORS middleware is installed at all.** Same-origin only, by construction.
- **FastAPI's auto-docs are disabled** (`docs_url=None`, `redoc_url=None`). The default
  `/docs` and `/redoc` pages fetch Swagger UI / ReDoc JavaScript and CSS from a CDN and
  render blank with no network. **This project runs fully offline; no route may depend on
  the internet.** Self-hosting the Swagger assets was the alternative and was rejected —
  it means vendoring ~1MB of third-party JS into the repo to document a small API that
  one person uses. The schema stays available as `/openapi.json`, which FastAPI
  generates locally and serves with no external requests.
- `GET /` serves the built UI: `web/dist/index.html`, read off disk on every request
  and sent with `Cache-Control: no-store` so a rebuilt file is never served stale from
  the browser. If `web/dist` hasn't been built yet, it serves a small self-contained
  "not built yet" page instead — a `200`, never a `500` or a JSON body, since a missing
  build is a setup step, not a server error. The Phase 1-3 JSON status placeholder is
  gone; this is what §5 always said would replace it.
- `GET /assets/*` and `GET /fonts/*` are two narrow `StaticFiles` mounts onto
  `web/dist/assets` and `web/dist/fonts`. Each is added only if its directory exists,
  so a missing `web/dist` never crashes startup. Both prefixes are disjoint from `/api`,
  so there is no shadowing risk by construction — and every `/api/*` route, `/api/health`
  included, is still declared before this static section as a second line of defense.
  There is still no SPA catch-all for unknown paths: §6 and §12.4 mean `/` is the only
  meaningful HTML route, so an unknown path keeps producing the ordinary `{"error": "Not
  Found"}` 404.
- The dev-mode Vite proxy (`web/vite.config.ts`) is unchanged: running `npm run dev`
  still forwards `/api` to this server on its own port, for front-end work without a
  rebuild.
- `GET /api/health` returns `{"status": "ok"}` for the launcher's readiness poll, and
  now also for `run.command`'s pre-flight "is it already running" check (5.2).

### 5.1 Environment variables

Defaults below use `RESOURCE_ROOT` and `DATA_ROOT` as defined in section 14 --
identically in dev and frozen. A value given through the env var is resolved
to an absolute path (`.expanduser().resolve()`) regardless of which default it
replaces.

| Var | Default | Meaning |
|---|---|---|
| `PAGECOUNT_PORT` | `8420` | port to bind |
| `PAGECOUNT_DATA_FILE` | `DATA_ROOT/entries.json` | entry data file path |
| `PAGECOUNT_CLASSES_FILE` | `DATA_ROOT/classes.json` | class data file path (section 12) |
| `PAGECOUNT_SETTINGS_FILE` | `DATA_ROOT/settings.json` | settings data file path (section 13) |
| `PAGECOUNT_QUOTES_FILE` | `RESOURCE_ROOT/quotes.txt` | bundled quote file path (section 10) |
| `PAGECOUNT_DIST_DIR` | `RESOURCE_ROOT/web/dist` | built front end path (section 5) |

`DATA_ROOT/my-quotes.txt` (10.1.1) has no env override -- see section 14.

### 5.2 `run.command` and `update.command`

`run.command` polls `/api/health` **before** touching Python or the virtualenv. If
something answers, it opens the browser and exits — a second double-click while the
tracker is already running must not attempt a second server on the same port.

`update.command` is a separate script that only pulls new code: `git status` must be
clean or it refuses outright, then `git pull --ff-only` so a failure (diverged history,
no network) is atomic and leaves the tree untouched rather than landing a conflict. It
reinstalls Python dependencies if `requirements.txt` was among the pulled changes, and
it never starts or stops the server — `run.command` remains the only thing that runs
uvicorn, so a bad pulled commit can't break an already-working launch.

---

## 6. Stack and layout

Python 3.11+, FastAPI, uvicorn. **No database, no ORM, no migrations.**

```
DECISIONS.md            this file
README.md
requirements.txt        runtime only: fastapi, uvicorn
requirements-dev.txt    pytest, httpx
run.command             double-clickable launcher
update.command          pulls new code; never touches a dirty tree, never
                        starts or stops the server (Phase 4, 5.2)
AppIcon.icns            the Desktop launcher's icon, applied by hand via
                        Finder -> Get Info (Phase 4)
scripts/
  make_icon.py          regenerates AppIcon.icns from the --pink-hot /
                        --pink-surface tokens. stdlib only (struct + zlib);
                        no new dependency
app/
  config.py             paths, port, env var names
  daytime.py            day_key() + ISO parse/format
  jsonfile.py           THE atomic write path + the corrupt-file halt (3.1-3.4).
                        One implementation, used by both data files.
  storage.py            entries.json: load, CRUD, write-through
  classes.py            classes.json: load, CRUD, write-through (12)
  settings.py           settings.json: load, validate, write-through (13).
                        Imports no storage, no classes
  models.py             pydantic request/response models
  stats.py              pages_today, streaks, first_entry_date
  quotes.py             quotes.txt + my-quotes.txt -> today's quote. Imports
                        no storage, no config (10, 10.1.1)
  main.py               FastAPI app, routes, error handlers
tests/
web/                    the front end (Phase 2). Vite + React + TypeScript,
                        Tailwind v4; no component library, router, or state
                        manager. `web/dist` is committed as of Phase 4 --
                        FastAPI serves it directly (5). `web/node_modules`
                        stays gitignored.
  public/fonts/         Fraunces, vendored per 9.4
  src/tokens.css        section 9 and 13: the theme layer (raw values, one
                        block per preset) and the semantic layer components
                        reference, plus the eight --class-* swatches (12.2)
                        and the fixed --chrome-safe-* set (13.4). The only
                        place a hex literal appears anywhere in the repo
  src/theme.ts          preset ids/labels, the semantic token list, and
                        apply/read/paint-cache functions (13). No hex literal
  src/contrast.ts       WCAG relative-luminance and contrast-ratio, hand
                        rolled, no dependency (13.2)
  src/milestones.ts     crossedMilestone(). Arrivals only, never distances (11)
  src/useCountUp.ts     rAF count-up toward a server value (11)
  src/motion.ts         prefers-reduced-motion + duration tokens
  src/components/
    ClassPicker.tsx     inline, optional, never blocks a save (12.4)
    ClassManager.tsx    the collapsed <details>. Owns the palette (12.2)
    SettingsPanel.tsx   the collapsed <details> beside it. Owns default_chip;
                        mounts ThemeEditor (13)
    ThemeEditor.tsx     preset picker, custom color inputs, contrast
                        warnings, the reset-to-preset escape hatch (13.3)
quotes.txt              the canonical quotes, one per line. Source, not entry
                        data (10) -- and, as of section 14, a read-only
                        resource: this file ships inside RESOURCE_ROOT and is
                        replaced on every update, not user-editable.
```

None of the three data files or `my-quotes.txt` live in this tree at all (section
14). They are not repo-relative and there is no `data/` directory in a fresh
checkout:

```
~/Library/Application Support/PinkPageCount/     DATA_ROOT
  entries.json          the reading log
  classes.json          the classes
  settings.json         theme, custom_theme, default_chip
  my-quotes.txt         the user's own quotes, unioned with quotes.txt (10.1.1)
```

`requirements.txt` holds runtime dependencies only, so `run.command` installs the
minimum; `requirements-dev.txt` adds `pytest` and `httpx` (needed by FastAPI's
`TestClient`).

`data/` is gitignored. The reading log and her class names are personal data, not
source.

---

## 7. Phase boundaries

**Phase 1: storage and API only.** No front-end code, HTML, CSS, or React. The JSON
status route at `/` is a placeholder, not a UI.

**Phase 2: the main page.** The number, the three chips, the motivational
message (a hardcoded string until Phase 3), the two page inputs with their live preview,
and the entry list with edit, delete, and backdating. Nothing in `app/` changed: the
schema in section 1 and the boundary rule in 2.3 both held.

**Phase 3a: quotes, animations, milestones.** The rotating daily quote
(section 10), the count-up on save, the save confirmation, and the milestone
celebrations (section 11), plus the empty state that shows an invitation instead of a
numeral before the first entry. Nothing in `app/` changed except one added route:
`quotes.py` is new, and no existing module was touched.

**Phase 3.5 (this one): classes.** An optional class on an entry, a colored dot in the
list, an inline picker that never blocks a save, and a small manager tucked into a
collapsed `<details>` (section 12). This is the first phase to change `app/`: the entry
schema gained `class_id` and went to version 2 (1.4), `classes.json` and its store are
new, and the atomic write path was factored into `app/jsonfile.py` so both files share
one implementation (3.1). No existing endpoint changed shape; entry create and patch
gained one optional field.

**Phase 4: deployment.** FastAPI serves the built `web/dist` directly at `/`,
with two narrow static mounts for `/assets` and `/fonts` and a friendly page if the
front end hasn't been built yet -- so `run.command` is the only thing left to
double-click, with no dev server and no second port. Added a backup/export button
(`GET /api/export`, 4.4), a pre-flight "already running" check in `run.command`,
`update.command` for pulling new code without ever touching a dirty tree or starting
the server, and `AppIcon.icns` for the Desktop launcher. `app/` gained one route and
one config path; no existing schema, storage semantics, or endpoint shape changed.

**Phase 5 (this one): settings and themes.** A settings system (section 13):
`data/settings.json` is a third data file, storing `theme`, `custom_theme`, and
`default_chip`; `app/settings.py` is new, shares the atomic write path and
corrupt-file halt with the other two files, and cannot reach either of them.
`GET`/`PATCH /api/settings` are new routes; no existing route, schema, or storage
semantics changed. `web/src/tokens.css` was restructured into a theme layer and a
semantic layer so six preset themes and a custom theme editor could be added
without renaming a single token a component already used -- see 9 and 13.1 for why
the semantic names are frozen even though this is the first phase where "pink" is
no longer the only look. A first-paint localStorage cache was added, explicitly
documented as a paint cache only, never a data source (13.4). `CLAUDE.md`'s phase
count and this file's own status line are updated in this same commit for the same
reason every other phase boundary gets written down here: so a future session does
not have to guess whether "4 phases" or "the app is complete" is still true.

Still ahead: the stats/graphs page and the pixel dog.

### 7.1 The client never does arithmetic on a total

The server is the only source of truth for every displayed number. After any successful
create, edit, or delete the front end refetches `/api/stats` and `/api/entries` and
renders what comes back; it never adjusts a displayed total itself and keeps no running
count in component state.

The one exception is the unsaved-input preview -- "that's 29 pages" under the page boxes
-- which is `end - start + 1` on two numbers that have not been sent anywhere. It is
display-only, and `pages` is still never sent to the server (1.1).

---

## 8. Non-scolding constraint (binds all phases)

**The app must be structurally incapable of scolding the user.**

No red or alarm states. No "behind pace." No projections of what she should have read.
No broken-streak messaging. **If a stat can only be read as a reprimand, it is not
built.**

A UI that shows "current 2 / longest 11" violates this section. The comparison is the
reprimand — the number alone is not.

"Structurally incapable" means the constraint is enforced by what exists, not by
restraint at render time. The safest way to satisfy this section is to not compute or
pass the offending comparison anywhere it could be displayed.

`longest_streak_days` is computed but deliberately not returned by the API in v1. A field
absent from the payload cannot be rendered next to `current_streak_days`, which makes §8
structural rather than a convention the UI layer is trusted to follow. Re-adding it is a
deliberate decision to be made with §8 in view, not a default.

Sections 10 and 11 are where this binds Phase 3a: a quote that could be read as a
reprimand does not go in the file, and the distance to the next milestone is never
computed.

Section 12 is where it binds Phase 3.5. **Classes are for grouping and color, not for
measuring her against a number.** No per-class target, quota, goal, or
assigned-vs-completed anything; no per-class comparison; not even a count of entries
next to a class name in the manager. The endpoint that would feed a per-class breakdown
does not exist (4.3), which is the same structural move as omitting
`longest_streak_days`.

**This section binds Phases 2-4. Do not relax it without changing this file.**

---

## 9. Visual tokens

Implemented in `web/src/tokens.css`, and since Phase 5 (section 13) in **two layers**:

1. **The theme layer** (`--theme-*`): raw hex values, one block per preset id,
   selected by a `data-theme` attribute on the root element.
2. **The semantic layer** (`--pink-hot`, `--pink-wash`, `--ink`, etc.): the names
   every component references, declared exactly once, each indirecting through the
   theme layer via `var()`.

Every token a component actually uses is in the semantic layer; **a hex literal
still appears in `tokens.css` and nowhere else in the repo** -- every preset's raw
values, the fixed `--chrome-safe-*` set (13.3), and the `--class-*` swatches (12.2)
all live there exclusively, same as before Phase 5.

**The semantic names do not change when the active theme isn't pink.** A green or a
near-black theme still populates `--pink-hot`. This is a deliberate wart: renaming
the semantic tokens to something theme-neutral would touch every component that
references them, for a purely cosmetic win, the first time this project would ever
have made that trade. Section 13 is where this decision actually bites; it is
recorded here because it amends this section's naming, not because §9 is where a
future session should look to understand *why* -- that reasoning lives in 13.1.

### 9.1 Color

The values below are the **`pink` preset** -- the original Phase 2 look, still the
default, and still what the semantic layer resolves to whenever `data-theme` is
absent (before JS runs) or explicitly `"pink"`. See 13.2 for the other five presets.

| Token | Value | Used for |
|---|---|---|
| `--pink-hot` | `#FF2E88` | the big number, and nothing else |
| `--pink-wash` | `#FFF5F8` | page background |
| `--pink-surface` | `#FFE8F0` | cards |
| `--pink-edge` | `#FFC2DA` | chips, rules, borders |
| `--ink` | `#2B1A22` | all primary text |
| `--rose-muted` | `#7A2E52` | secondary text (dates, "that's N pages") |

**`--pink-hot` is reserved for the primary number. It is never used for body text,
buttons, borders, or chips. At body size it fails contrast against `--pink-wash` in
every preset; this is intentional and is the enforcement mechanism.** Every preset
is instead checked against the large-text (3:1) threshold for this pair, matching
the numeral's actual display size -- see 13.2.

### 9.2 Motion

| Token | Value | Used for |
|---|---|---|
| `--dur-ui` | `180ms` | chips, hovers, focus states |
| `--dur-count` | `900ms` | number count-up on save |
| `--dur-confirm` | `2600ms` | how long the save confirmation stays before it fades |

### 9.3 Typography

| Token | Value | Used for |
|---|---|---|
| (system default) | system sans | all UI text |
| `--font-number` | Fraunces | the primary numeral |

System sans for UI. A serif face for the primary numeral.

### 9.4 Fonts are vendored, never fetched

**All font files are vendored into the repo and served locally via `@font-face`. No Google
Fonts link, no CDN, no external stylesheet anywhere in this project.**

Same reason `/docs` was disabled in §5: **this app must render identically with the
network cable pulled.** A webfont that arrives over the network is a webfont that does not
arrive at all offline, and the layout it was measured against shifts underneath the user.

---

## 10. Quotes

A quote at the top of the page, one per day, from a file she owns.

### 10.1 `quotes.txt` is a separate file from entry data, and always will be

Quotes live in `quotes.txt` at the repo root. **Nothing in the quote path may open,
read, or write `data/entries.json`.** Editing quotes must be *structurally* incapable of
touching the reading log — not careful about it, incapable of it.

The enforcement is `app/quotes.py`'s import list. It imports `hashlib`, `pathlib`, and
one function from `daytime`. It does not import `storage`, does not import `config`, and
never names the data file, so there is no path through it that reaches an entry.
`tests/test_quotes.py` parses the module and asserts that import list, and separately
asserts `entries.json` is byte-identical after hammering the endpoint.

This mirrors §3: the reading log is the thing this project protects. A feature about
*text on a page* has no business being anywhere near it.

Quotes are **source** and tracked in git; entries are **personal data** and gitignored.
That difference is why they are two files.

### 10.1.1 Amendment: a second, optional quote file, unioned at read time

Ahead of distributing this app to people outside the developer's household as a
frozen bundle (AUDIT.md), `quotes.txt` moves inside the read-only bundle
(`RESOURCE_ROOT`, section 14) so it can be replaced cleanly on every update. That
makes it **no longer user-editable** — a real change from "a file she owns,"
which is why this is a numbered amendment and not a silent edit.

To keep quotes user-editable at all, a second file is added:
`DATA_ROOT/my-quotes.txt` (section 14) — optional, user-owned, survives an app
update the same way `entries.json` does. `QuoteSource` now takes both paths and
reads both **on every request**, same as before (10.4): bundled lines first,
then the user's own, blank lines and exact duplicates dropped, order otherwise
preserved. A missing `my-quotes.txt` is normal, never an error — same rule 10.4
already gives a missing `quotes.txt`.

The file is created empty-of-quotes (comment lines only, explaining itself) on
first run, the same "not an error, not a migration" spirit as 3.3's first write
of a missing data file — except this one is never required for the app to
function, so a failed write (e.g. a read-only volume) is silently skipped rather
than halting anything.

`app/quotes.py`'s isolation from the reading log (10.1) is unchanged: both paths
are handed in by the caller, and the module still never imports `config` or
`storage` and never names `entries.json` — enforced by the same
`tests/test_quotes.py` AST check as before.

### 10.2 Format

One quote per line, UTF-8. Blank lines and lines whose first non-space character is `#`
are ignored, so the file can carry a comment header explaining itself. Lines are
stripped. No escaping, no front matter, no JSON — she should be able to open it in
TextEdit, type a sentence, and save.

### 10.3 Selection is deterministic from the day key

`index = sha256(day_key) % len(quotes)`. The same logical day always yields the same
quote, so reloading the page never shuffles it.

**sha256, not the builtin `hash()`.** Python randomizes string hashing per process
(`PYTHONHASHSEED`), so `hash(day_key) % len` would silently hand her a different quote
every time the server restarts. sha256 of the day key is stable across processes,
machines, and years.

The day key comes from `daytime.day_key` — the same 4am boundary as everything else,
per §2.3. There is no second implementation of it here either.

### 10.4 Read on request, and never an error

`GET /api/quote` reads the file on **every request**, not once at startup, so editing
`quotes.txt` shows up on the next page load with no restart.

A missing, empty, unreadable, or comments-only file returns a hardcoded fallback string
with a `200`. **Never an error, never an empty message area.** This is the one place in
the project where a missing file is not a halt (§3.4) — because the failure mode of a
missing quote is a blank line of text, not a lie about her data.

### 10.5 §8 applies to the file's contents

A quote that could be read as a reprimand does not go in the file. Nothing about
discipline, grinding, catching up, falling behind, or what she should be doing. The
shipped set is warm and undemanding; anything added later is held to the same bar.

---

## 11. Motion, the empty state, and milestones

### 11.1 No animation library

`requestAnimationFrame` and CSS, hand-rolled. No animation dependency, no confetti
package, no remote asset — §5 and §9.4 apply to motion exactly as they apply to fonts.

**Every animation is wrapped in `prefers-reduced-motion: no-preference`.** With reduced
motion on, values change instantly and correctly and messages still appear; only the
movement is dropped. Reduced motion is never a degraded experience, just a still one.

**Any looping or idle animation stops on `visibilitychange` when the tab is hidden.**
She reads on battery in a library.

### 11.2 The count-up animates toward a server value; it never produces one

After a successful save the primary number counts from the previously displayed value to
the value `/api/stats` returned, easing out slightly past the target and settling back,
over `--dur-count`. §7.1 is unchanged and unbent: the target is always a number the
server sent, and the animation always ends on exactly that number, never on a rounded
frame of it.

Switching a chip changes the number instantly. Only a save counts up.

The animating numeral is `aria-hidden`; a separate live region carries the final value,
so a screen reader is told the result once rather than read every frame of it.

### 11.3 The empty state shows an invitation, not a zero

When `entry_count == 0` the numeral is not rendered at all — the invitation stands in
its place, and the chips are hidden with it. The number appears on the first save.

**The condition is `entry_count == 0`, never "the displayed value is zero."** A Today of
0 at 7am is an ordinary morning and must still render `0`. A big pink `0` on a first run
is not a stat, it is a verdict on someone who has not started yet (§8).

### 11.4 Milestones: celebrate arrivals, never announce distances

Thresholds are **100 and 500** for the early wins, then **every 1,000 pages all-time**,
forever.

Firing is **stateless**. A milestone fires only by comparing the `pages_all_time` from
before a save to the value the server returned after it; if a threshold falls between
them, celebrate. Nothing is persisted, so:

- a page reload can never re-fire a celebration,
- an edit or delete that drops the total back below a threshold fires nothing,
- and only a **new entry** celebrates. An edit that happens to cross a threshold stays
  quiet — a correction is not an arrival.

`crossedMilestone(before, after)` returns `null` whenever `after <= before`, which is
what makes the second and third of those true by construction rather than by a guard.

**The distance to the next milestone is never computed.** No "40 pages to go", no
progress bar, no countdown, no percentage. This is the specific trap in this feature —
a progress bar toward a goal is a reprimand with a shape — so `web/src/milestones.ts`
exports exactly one function and that function can only answer *did she just arrive*.
There is nothing in the module capable of answering *how far*, and a test asserts its
export list to keep it that way.

---

## 12. Classes

Grouping and color for entries. A class is a label with a dot. It is not a target and
never will be (§8).

### 12.1 A second file, never a nested list

Classes live in `data/classes.json`, **never inside `entries.json`**:

```json
{
  "schema_version": 1,
  "classes": [
    {
      "id": "b81d0e4a-2c9f-4a13-8f77-1e5c9d3a2b60",
      "title": "Bio 12",
      "description": null,
      "color": "#E4557F",
      "archived": false,
      "created_at": "2026-08-25T09:04:11-04:00",
      "updated_at": "2026-08-25T09:04:11-04:00"
    }
  ]
}
```

| Field | Type | Rules |
|---|---|---|
| `id` | string | uuid4, server-generated, never reused |
| `title` | string | required, 1–60 characters after strip |
| `description` | string \| null | free text |
| `color` | string | `#RGB` or `#RRGGBB`. See 12.2 |
| `archived` | bool | defaults `false` |
| `created_at` | string | ISO 8601 with offset, server-set, never changes |
| `updated_at` | string | ISO 8601 with offset, server-set, bumped on every PATCH |

Two files rather than one nested list, for the reason §10 gives about quotes: a feature
about *labels* has no business being able to rewrite the reading log. Renaming a class
does not open `entries.json` at all. Storage, durability, and the corrupt-file halt are
identical for both files because they share one implementation (3.1, 3.4).

### 12.2 Color comes from the front end, and §9 is not amended

The palette is eight pink-forward `--class-*` custom properties in
`web/src/tokens.css`. **A hex literal still appears in that file and nowhere else in
this repo** — §9 stands exactly as written, with no carve-out. `--pink-hot` is not among
them; it stays reserved for the primary number (9.1).

`web/src/components/ClassManager.tsx` owns the palette. Creating a class pre-selects the
first palette color not already used by a non-archived class, wrapping by count once all
eight are taken, and sends it as an explicit `color`.

**The server has no palette and no color-picking logic.** It validates that `color` is a
well-formed hex and stores what it was given. An omitted `color` falls back to a single
hardcoded constant in `app/classes.py`, which exists for `curl` and hand-edits and is
commented as saying so. A color arriving from the API into a `style` attribute is data
flowing through the app; it is not a literal in a source file.

### 12.3 Deletion is never a cascade

**`DELETE /api/classes/{id}` must never delete or alter an entry beyond its `class_id`.**

It sets `class_id` to `null` on every affected entry. `page_start`, `page_end`,
`read_at`, `note`, and `created_at` are untouched. There is no cascade in the code — not
a disabled one, not a guarded one. No function in this project deletes an entry because
of anything to do with a class.

`updated_at` **is** bumped on an entry whose `class_id` was cleared. That is a stated
choice, not an oversight: §1 defines `updated_at` as server-set and bumped on every
mutation, and this is a mutation. The five fields above are the ones carrying what she
actually read, and none of them moves.

The two files are written in the order §3.8 fixes: entries first, then the class.

The confirmation in the UI says this in plain words — *everything you logged under it is
kept* — because a delete button that might eat reading history is the one thing in this
app worth a second tap.

### 12.4 The picker is never on the critical path

Friction on the save path is the enemy. So:

- The picker is **inline** on the entry form. No modal, no second screen, one tap.
- It is **never required**. Saving with nothing selected is an ordinary, complete save.
- **"No class" is always present**, always first, always reachable.
- It **pre-selects the class of the newest entry** — which `GET /api/entries` already
  returns first (§4) — so the common case is zero taps. If that entry has no class, or
  names an archived or dangling one, "No class" is the default.

  The picker mirrors what she did last time, so a deliberate "no class" sticks too.
  Walking back through older entries to find the last *classified* one was rejected for
  exactly that reason: it would make "no class" impossible to keep.
- **Archived classes vanish from the picker and stay valid on existing entries.** Editing
  an old entry shows its own class even if archived, so an edit can never silently strip
  it.

Management — create, rename, recolor, archive, delete — lives in a collapsed `<details>`
below the entry list, off the save path. There is still no router (§6).

### 12.5 What classes deliberately are not

No per-class target, quota, goal, or assigned-vs-completed anything. No per-class
comparison. No per-class total in the manager, **not even a count of entries** next to a
class name.

`/api/stats?class_id=` and `/api/stats/by-class` are not built (4.3).

§8 applies unchanged. A per-class breakdown is where this feature would turn into a
scoreboard, and the way to prevent that is for the thing that would feed it to not
exist.

---

## 13. Settings and themes

A third file, `data/settings.json`, for the things that change how the app looks
and which chip loads -- not what she has read. Nothing about how she reads is
here; §8 does not need to say anything new for this section because nothing in it
measures her.

### 13.1 The file, and its isolation from the other two

```json
{
  "schema_version": 1,
  "settings": {
    "theme": "pink",
    "custom_theme": null,
    "default_chip": "all_time"
  }
}
```

| Field | Type | Rules |
|---|---|---|
| `theme` | string | a preset id (13.2) or `"custom"`. Not nullable |
| `custom_theme` | object \| null | semantic-token-name -> hex overrides (13.3), or null |
| `default_chip` | string | `"all_time"` \| `"today"` \| `"streak"`. Not nullable |

Shares `app/jsonfile.py`'s atomic write path and corrupt-file halt with the other
two files (3.1, 3.4) -- there is still one implementation of both, not three. It
does **not** reuse `envelope_list`: that helper's `<list_key>` is always a JSON
array, and `settings` is an object, so `app/settings.py` validates the
`{schema_version, settings: {...}}` wrapper with its own small check instead.

A missing file is created with the defaults above (3.3). A file present but
missing one of the three keys, or failing a per-field check, is corruption (3.4) --
this file follows the same strict rule `classes.py`/`storage.py` already apply to
a missing required record field, rather than inventing a lenient "fill in the
default" exception just for this one file.

**`app/settings.py` imports nothing from `storage` or `classes`, and neither of
those imports it.** A feature about how the page looks has no business being able
to touch the reading log or the class list -- the same structural separation §10
gives quotes and §12.1 gives classes. Enforced by an AST-based test, the same way
10 and 12.1 are.

### 13.2 Preset themes

Six presets, each defining the full six-token semantic set (9.1). `pink` is the
original Phase 2 look and the default. The other five have genuine range -- a deep
jewel tone, a warm neutral, a cool one, a high-contrast one with no tint at all,
and a genuine dark theme -- not six shades of pink.

| id | description |
|---|---|
| `pink` | the original look, default |
| `jewel` | deep emerald |
| `neutral` | warm sand |
| `cool` | cool slate blue |
| `contrast` | pure black, white, and gray |
| `midnight` | dark: light text on near-black |

**The server has no colors.** It validates that `theme` is one of these six ids or
`"custom"`, and nothing more -- the same "no palette" rule 12.2 gives classes. The
actual hex values live in `web/src/tokens.css` exclusively (9), named by id in
`web/src/theme.ts`. The two id lists (`app/settings.py::THEME_IDS` and
`web/src/theme.ts::PRESETS`) must be kept in sync by hand; each side has a comment
pointing at the other.

Every preset is tested for contrast: body text (`--ink` or `--rose-muted`) against
its background clears 4.5:1, and `--pink-hot` against `--pink-wash` clears 3:1 --
the large-text threshold, matching the numeral's actual display size. A theme that
makes her log unreadable is a bug, the test asserts it for all six presets, and it
reads the real `tokens.css` rather than a hex fixture that could drift from it.

### 13.3 Custom themes and the escape hatch

`theme: "custom"` with a `custom_theme` object of one-or-more `{semantic-token-name:
hex}` overrides -- the semantic token's own CSS custom-property name
(`--pink-hot`, `--ink`, ...), used verbatim as the JSON key, not a second encoding
of it. A PATCH's `custom_theme` replaces the field wholesale, the same "a field
that was sent is the new value in full" rule every other field in this API already
follows -- there is no partial merge inside the object.

Applied as inline style properties on the document root, which win over the active
preset's stylesheet rule for that token unconditionally (this project never uses
`!important`) -- so a one-token override composes with any preset underneath it,
and an untouched token still falls through to whatever preset is selected.

The editor warns, in `--rose-muted`, when a chosen pair falls under 4.5:1. It never
blocks -- it's her app, and a warning is not a scolding (§8's spirit, applied to a
color picker rather than a reading stat).

**The reset-to-preset control is the one piece of UI in this app styled with
tokens no theme or override can ever reach:** three fixed properties,
`--chrome-safe-bg`/`--chrome-safe-text`/`--chrome-safe-border`, declared once in
`tokens.css` outside every `[data-theme]` block. `custom_theme`'s recognized keys
never include them, by construction -- so this is the one control guaranteed
legible no matter how illegible the rest of the page has become, which is the
whole point of an escape hatch.

### 13.4 First paint: a cache, never a second source of truth

The theme must apply before first paint, and `GET /api/settings` cannot answer
before the page has painted something. The resolved theme is mirrored into
`localStorage` as a **paint cache only**, read synchronously by a small inline
script in `web/index.html` -- before any module script runs, so the key name and
token list there are necessarily literal, not imported.

**This is not a second place data lives.** `settings.json` remains the sole source
of truth; a cleared or corrupted cache loses nothing -- it simply means one extra
frame at the `pink` default before the real fetch resolves and reconciles it. Every
other place in this project that touches the browser's storage does not exist
(§7.1, §10, §12); this is the first, and the reason it's safe is that nothing here
is ever read back as data, only as a guess to paint quickly.

### 13.5 `default_chip`

The chip shown when the page loads comes from this setting, defaulting to
`all_time`. Note the vocabulary mismatch with the front end's own `StatKey`
(`"all"`, not `"all_time"`) -- `web/src/stat.ts::chipFromSetting` is the one place
that translates between them.

Selecting a chip during a session is exactly what it was before this phase: local
state, gone on reload, and it never writes the setting. Only the settings panel
does that. Changing the setting does not retroactively move whatever chip she's
currently looking at -- it takes effect on the next load, matching "the chip
selected on load" and nothing more.

### 13.6 The settings panel

Same collapsed `<details>` pattern as the class manager (12.4), beside it, closed
by default, off any save path. No router -- §6 still says no router.

---

## 14. Distribution: two path bases, not one

AUDIT.md (read-only audit ahead of distributing this app to ~5 people outside
the developer's household, as a frozen macOS app bundle) found that every
default path in `app/config.py` was derived from `__file__` via one
`REPO_ROOT` — correct for a git checkout, and wrong for a frozen bundle two
different ways at once (AUDIT.md B1, B2): a PyInstaller onefile bundle's
`__file__` points inside a temp directory deleted on quit (silent data loss,
every launch), and a onedir/`.app` bundle's `__file__` points inside the
bundle itself (the log gets stranded inside an app the user will eventually
replace). There is no single base that is correct for both a writable log and
a read-only resource, so this splits `REPO_ROOT` into two.

**`RESOURCE_ROOT`** — read-only, ships with the app: `quotes.txt`, `web/dist`.
Unfrozen (every dev run, and every test run), it is the repo root, unchanged
from before this split. Frozen (`sys.frozen` with `sys._MEIPASS` set, as a
PyInstaller onefile build does), it is the bundle's extracted resource
directory. **The exact resolution for a onedir/`.app` build is not settled —
see the open problem below.** No PyInstaller machinery exists yet (AUDIT.md
B6); that is the next session's work, and this split does not attempt it.

**`DATA_ROOT`** — writable, owned by the user, survives an app replacement:
`entries.json`, `classes.json`, `settings.json`, `my-quotes.txt` (10.1.1).
Always `~/Library/Application Support/PinkPageCount/` — **identically in dev
and frozen, one code path, no branch for development.** Given that durability
of the reading log is this project's top priority (section 3's header), the
one thing worse than "this session doesn't special-case dev" would be a dev
path that silently diverges from what actually gets tested. Directory name is
exactly `PinkPageCount`: no spaces, no apostrophes, so it never needs quoting
in a shell command or a `mv` remedy (AUDIT.md B3's note on the banner's
`mv '<path>' '<path>.bak'`).

The five existing `PAGECOUNT_*` path/dir env overrides (`DATA_FILE`,
`CLASSES_FILE`, `SETTINGS_FILE`, `QUOTES_FILE`, `DIST_DIR`) are unchanged in
what they override, and now additionally apply `.resolve()` after
`.expanduser()`, so a relative value can never silently create a second file
next to whatever the working directory happened to be (AUDIT.md's env-override
note). `DATA_ROOT` itself has no env override — nothing needs one, since every
test constructs its stores directly against a `tmp_path` fixture rather than
going through `config` at all (3.7), the same pattern this section's own test
guard (`tests/conftest.py::guard_real_application_support`) exists to enforce
for the future.

### 14.1 No migration path exists, by design

Nothing in this codebase finds or copies an old `data/` directory into
`DATA_ROOT`. Every recipient of the frozen build is a first install; the one
person with an existing `data/entries.json` (the developer) moves it by hand.
A missing `DATA_ROOT` is not a migration to run — it is the ordinary
missing-file case section 3.3 already handles, and the app creates fresh files
exactly as it does today.

### 14.2 Open problem: `DATA_ROOT` lives under a Finder-hidden directory

`~/Library` is hidden in Finder by default. AUDIT.md B3 already flags that the
corrupt-file halt's remedy (`mv '<path>' '<path>.bak'`) names a path a
non-technical recipient cannot navigate to without knowing Cmd+Shift+. or
`~/Library`'s existence at all. This section does not solve that — it is
explicitly left for the next session, alongside the PyInstaller build
machinery (B6) that has to exist before any of this can be verified on a
recipient's actual machine.
