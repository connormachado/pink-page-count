# DECISIONS.md

Frozen design decisions for the reading tracker. **Future sessions: read this file
instead of redesigning the schema.** If you need to change something here, change
*this file* in the same commit and say why.

Project shape: single user, single machine, macOS, fully offline. No auth, no
multi-user, no cloud, no database. **Durability of `data/entries.json` matters more
than anything else in this project.**

Status: Phase 1 of 4 — storage and API only. No front-end code exists yet.

---

## 1. Data schema

`data/entries.json` — pretty-printed (2-space indent), UTF-8, trailing newline:

```json
{
  "schema_version": 1,
  "entries": [
    {
      "id": "3f2a1c8e-5b7d-4e19-9c02-8a6f1d4b7e30",
      "page_start": 43,
      "page_end": 71,
      "read_at": "2026-08-24T21:12:00-04:00",
      "note": "chapter 4",
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

Currently `1`. Bump it only when the on-disk entry shape changes incompatibly, and
record the migration in this file. A file whose `schema_version` is *newer* than the
running code understands is treated as an error, not as corruption — the app refuses to
start rather than touching data written by a future version of itself. This is the same
halt-don't-recover policy §3.4 applies to a corrupt file.

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

Every mutation writes the whole file through this path:

1. `tempfile.mkstemp` in the **same directory** as the target (same filesystem, so the
   rename is atomic).
2. Write the serialized JSON, `flush()`.
3. **Durably sync the file descriptor** (see 3.2).
4. `close()`.
5. `os.replace(tmp, entries.json)` — atomic on POSIX; readers see either the entire old
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
`{"schema_version": 1, "entries": []}` through the same atomic path. Not an error.

### 3.4 Corrupt file: refuse to start

A file is **corrupt** if it fails to parse as JSON, parses to something that is not a
top-level object, is missing `entries` / `entries` is not a list, or contains any entry
that fails schema validation.

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
`PAGECOUNT_DATA_FILE` (default `data/entries.json`). Tests construct their own against a
`tmp_path`. **No test ever touches the real data file.**

---

## 4. API

Base path `/api`. All request and response bodies are JSON.

| Method | Path | Body / params | Success |
|---|---|---|---|
| `POST` | `/api/entries` | `page_start`, `page_end`, `note?`, `read_at?` | `201` + entry |
| `GET` | `/api/entries` | `?limit` optional, `>= 1` | `200` + entry list |
| `PATCH` | `/api/entries/{id}` | any of `page_start`, `page_end`, `note`, `read_at` | `200` + entry |
| `DELETE` | `/api/entries/{id}` | — | `204` |
| `GET` | `/api/stats` | — | `200` + stats |

`GET /api/entries` returns **newest first**, sorted by `read_at` descending with
`created_at` descending as the tiebreak.

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
| unknown `id` on `PATCH` / `DELETE` | `404` |

Type and range checks (`page_start >= 0`, integer-ness) live in the pydantic models.
The cross-field `page_end >= page_start` check lives in **one shared helper** used by
both POST and PATCH, because PATCH must validate the *merged* result against the stored
entry — patching only `page_start` to a value above the existing `page_end` must fail.

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

---

## 5. Server

- Binds to **`127.0.0.1` only. Never `0.0.0.0`.** Hard-coded, not configurable.
- Port **8420**, override with the `PAGECOUNT_PORT` env var.
- **No CORS middleware is installed at all.** Same-origin only, by construction.
- **FastAPI's auto-docs are disabled** (`docs_url=None`, `redoc_url=None`). The default
  `/docs` and `/redoc` pages fetch Swagger UI / ReDoc JavaScript and CSS from a CDN and
  render blank with no network. **This project runs fully offline; no route may depend on
  the internet.** Self-hosting the Swagger assets was the alternative and was rejected —
  it means vendoring ~1MB of third-party JS into the repo to document a five-endpoint API
  that one person uses. The schema stays available as `/openapi.json`, which FastAPI
  generates locally and serves with no external requests.
- `GET /` returns a small JSON status: app name, `schema_version`, and the list of API
  routes. It links to nothing external. Phase 2 replaces the root route with the UI.
- `GET /api/health` returns `{"status": "ok"}` for the launcher's readiness poll.

### 5.1 Environment variables

| Var | Default | Meaning |
|---|---|---|
| `PAGECOUNT_PORT` | `8420` | port to bind |
| `PAGECOUNT_DATA_FILE` | `data/entries.json` | data file path |

---

## 6. Stack and layout

Python 3.11+, FastAPI, uvicorn. **No database, no ORM, no migrations.**

```
DECISIONS.md            this file
README.md
requirements.txt        runtime only: fastapi, uvicorn
requirements-dev.txt    pytest, httpx
run.command             double-clickable launcher
app/
  config.py             paths, port, env var names
  daytime.py            day_key() + ISO parse/format
  storage.py            atomic write, load, corruption halt, CRUD
  models.py             pydantic request/response models
  stats.py              pages_today, streaks, first_entry_date
  main.py               FastAPI app, routes, error handlers
tests/
data/
  entries.json          the data (gitignored)
```

`requirements.txt` holds runtime dependencies only, so `run.command` installs the
minimum; `requirements-dev.txt` adds `pytest` and `httpx` (needed by FastAPI's
`TestClient`).

`data/` is gitignored. The reading log is personal data, not source.

---

## 7. Phase boundaries

**Phase 1 (this one): storage and API only.** No front-end code, HTML, CSS, or React.
The JSON status route at `/` is a placeholder, not a UI.

Phases 2–4 build the interface on top of this API. They should not need to change the
schema in section 1 or the boundary rule in section 2.3. If they do, update this file.

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

**This section binds Phases 2-4. Do not relax it without changing this file.**

---

## 9. Visual tokens

Frozen starting values for Phase 2. **No CSS exists yet** — this section is the
reference the stylesheet will be built from.

### 9.1 Color

| Token | Value | Used for |
|---|---|---|
| `--pink-hot` | `#FF2E88` | the big number, and nothing else |
| `--pink-wash` | `#FFF5F8` | page background |
| `--pink-surface` | `#FFE8F0` | cards |
| `--pink-edge` | `#FFC2DA` | chips, rules, borders |
| `--ink` | `#2B1A22` | all primary text |
| `--rose-muted` | `#7A2E52` | secondary text (dates, "that's N pages") |

**`--pink-hot` is reserved for the primary number. It is never used for body text,
buttons, borders, or chips. At body size it fails contrast against `--pink-wash`; this is
intentional and is the enforcement mechanism.**

### 9.2 Motion

| Token | Value | Used for |
|---|---|---|
| `--dur-ui` | `180ms` | chips, hovers, focus states |
| `--dur-count` | `900ms` | number count-up on save |

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
