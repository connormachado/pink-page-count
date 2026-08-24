# Reading Tracker

A local-first reading tracker. Log what you read, page range by page range, and see
how the pages add up. Runs entirely on this Mac: no account, no cloud, no internet.

Your data lives in one plain JSON file — `data/entries.json` — that you can open and
edit in any text editor.

**Phase 1 of 4: this is the backend only.** There is no user interface yet. The server
runs and answers API requests; the browser will show a small JSON status page. The
interface comes in Phase 2.

---

## Running it

Double-click **`run.command`**.

The first run takes a minute: it builds a Python environment and downloads the two
packages the server needs (this one step needs the internet; nothing afterward does).
Later runs start immediately and quietly.

The tracker opens at **http://127.0.0.1:8420/**. To stop it, close the window or press
**Control-C**.

You can put an alias of `run.command` on the Desktop and double-click that instead —
it resolves its own location, so it works from anywhere.

### If you prefer the terminal

```bash
cd /Users/connormachado/Desktop/pink-page-count
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.main
```

### Settings

| Environment variable | Default | What it does |
|---|---|---|
| `PAGECOUNT_PORT` | `8420` | Port to run on. Use this if 8420 is taken. |
| `PAGECOUNT_DATA_FILE` | `data/entries.json` | Where the reading log is stored. |

```bash
PAGECOUNT_PORT=8421 ./run.command
```

The server binds to `127.0.0.1` only. Nothing else on the network can reach it.

---

## Running the tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

For more detail, or to run one area:

```bash
.venv/bin/python -m pytest -v
.venv/bin/python -m pytest tests/test_persistence.py -v   # the durability tests
```

The tests never touch your real `data/entries.json` — each one gets its own temporary
file.

---

## The API

| Method | Path | Body / parameters |
|---|---|---|
| `POST` | `/api/entries` | `page_start`, `page_end`, `note?`, `read_at?` |
| `GET` | `/api/entries` | `?limit` optional — newest first |
| `PATCH` | `/api/entries/{id}` | any of `page_start`, `page_end`, `note`, `read_at` |
| `DELETE` | `/api/entries/{id}` | — |
| `GET` | `/api/stats` | — |

**Page counting is inclusive.** Pages 43–71 is 29 pages. Pages 43–43 is 1 page.

**A day runs 4am to 4am.** Reading logged at 1am Tuesday counts toward Monday, so a
late night still counts as the day it felt like.

`GET /api/stats` returns `pages_today`, `pages_all_time`, `current_streak_days`,
`longest_streak_days`, `entry_count`, and `first_entry_date`.

Errors come back as `{"error": "a human readable message"}`.

FastAPI's `/docs` page is deliberately disabled — it loads its JavaScript from a CDN
and would render blank offline. The raw schema is at `/openapi.json`.

---

## About your data

`data/entries.json` is the only thing that matters here. Everything else can be deleted
and rebuilt. Three rules the code follows:

**Writes are atomic.** Every save is written to a temporary file, flushed all the way to
the physical disk, and then moved into place in a single step. If the power cuts out
mid-save, you get either the complete old file or the complete new one — never a
half-written one.

**A file it cannot read is never touched.** If `entries.json` is damaged or hand-edited
into something invalid, the server prints a loud message naming the file and the exact
problem, and then refuses to start. It does not rename your file, copy it, or start over
with an empty one. Fix the file and start again; your data will still be there.

**Every change is saved immediately.** There is no "save" step and nothing held in memory
waiting to be written.

Back it up by copying `data/entries.json` anywhere you like.

---

## Verifying persistence by hand

Start the server, then run these in a second terminal window.

```bash
cd /Users/connormachado/Desktop/pink-page-count

# 1. Log a reading session: pages 43 to 71.
curl -sS -X POST localhost:8420/api/entries \
  -H 'content-type: application/json' \
  -d '{"page_start":43,"page_end":71,"note":"inclusive check"}'
# -> "pages":29   (43 to 71 inclusive)

# 2. Look at the file on disk. Note there is no "pages" key -- it is always
#    recomputed, so it can never disagree with page_start and page_end.
cat data/entries.json

# 3. Stop the server (Control-C in its window) and start it again.
#    Then confirm the entry survived:
curl -sS localhost:8420/api/entries
curl -sS localhost:8420/api/stats
```

To confirm a damaged file is never overwritten:

```bash
# 1. Stop the server, then keep a copy you can restore from.
cp data/entries.json /tmp/entries.backup.json

# 2. Break the file on purpose.
printf '{"schema_version": 1, "entries": [ broken ]}' > data/entries.json

# 3. Try to start. It prints a banner naming the file and exits without starting.
./run.command

# 4. The file is untouched -- byte for byte what you just wrote, and nothing
#    new was created next to it.
cat data/entries.json
ls data/

# 5. Put your real data back.
cp /tmp/entries.backup.json data/entries.json
```

---

## Where things are

```
DECISIONS.md      the schema and every design decision -- read this first
README.md         this file
run.command       the launcher
requirements.txt  what the server needs to run
app/
  config.py       paths, port, environment variables
  daytime.py      timestamps and the 4am day boundary
  storage.py      atomic writes and loading -- the durability code
  models.py       request and response shapes, page-range validation
  stats.py        pages today, streaks
  main.py         the API routes
tests/
data/
  entries.json    your reading log
```

**`DECISIONS.md` is the reference.** It records the data schema and the reasoning behind
every decision in this project, so later work builds on it instead of guessing.
