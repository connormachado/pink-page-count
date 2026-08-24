# DECISIONS.md

Frozen design decisions for the reading tracker. **Future sessions: read this file
instead of redesigning the schema.** If you need to change something here, change
*this file* in the same commit and say why.

Project shape: single user, single machine, macOS, fully offline. No auth, no
multi-user, no cloud, no database. **Durability of `data/entries.json` matters more
than anything else in this project.**

Status: Phase 3a of 4 — quotes, animations, and milestones on the main page. `web/`
holds a Vite + React + TypeScript front end built against section 9's tokens.

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
| `GET` | `/api/quote` | — | `200` + `{"quote": "..."}` |

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
  routes. It links to nothing external. **Phase 4** replaces the root route with the
  built UI. Phase 2 runs the front end on Vite's own dev server instead, proxying `/api`
  here, so nothing in `app/` had to change and no CORS middleware was needed.
- `GET /api/health` returns `{"status": "ok"}` for the launcher's readiness poll.

### 5.1 Environment variables

| Var | Default | Meaning |
|---|---|---|
| `PAGECOUNT_PORT` | `8420` | port to bind |
| `PAGECOUNT_DATA_FILE` | `data/entries.json` | data file path |
| `PAGECOUNT_QUOTES_FILE` | `quotes.txt` | quote file path (section 10) |

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
  quotes.py             quotes.txt -> today's quote. Imports no storage (10)
  main.py               FastAPI app, routes, error handlers
tests/
web/                    the front end (Phase 2). Vite + React + TypeScript,
                        Tailwind v4; no component library, router, or state
                        manager. `web/node_modules` and `web/dist` are
                        gitignored -- the built output is Phase 4's business.
  public/fonts/         Fraunces, vendored per 9.4
  src/tokens.css        section 9, and the only place a hex literal appears
  src/milestones.ts     crossedMilestone(). Arrivals only, never distances (11)
  src/useCountUp.ts     rAF count-up toward a server value (11)
  src/motion.ts         prefers-reduced-motion + duration tokens
quotes.txt              the quotes, one per line. Source, not entry data (10)
data/
  entries.json          the data (gitignored)
```

`requirements.txt` holds runtime dependencies only, so `run.command` installs the
minimum; `requirements-dev.txt` adds `pytest` and `httpx` (needed by FastAPI's
`TestClient`).

`data/` is gitignored. The reading log is personal data, not source.

---

## 7. Phase boundaries

**Phase 1: storage and API only.** No front-end code, HTML, CSS, or React. The JSON
status route at `/` is a placeholder, not a UI.

**Phase 2: the main page.** The number, the three chips, the motivational
message (a hardcoded string until Phase 3), the two page inputs with their live preview,
and the entry list with edit, delete, and backdating. Nothing in `app/` changed: the
schema in section 1 and the boundary rule in 2.3 both held.

**Phase 3a (this one): quotes, animations, milestones.** The rotating daily quote
(section 10), the count-up on save, the save confirmation, and the milestone
celebrations (section 11), plus the empty state that shows an invitation instead of a
numeral before the first entry. Nothing in `app/` changed except one added route:
`quotes.py` is new, and no existing module was touched.

Still ahead: the stats/graphs page, the export button, per-class tags, the pixel dog,
and serving the built files from FastAPI (Phase 4).

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

**This section binds Phases 2-4. Do not relax it without changing this file.**

---

## 9. Visual tokens

Frozen starting values, implemented in Phase 2 as `web/src/tokens.css`. Every token
below is a CSS custom property defined there and referenced everywhere else; **a hex
literal appears in that file and nowhere else in the repo.**

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
