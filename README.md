# Reading Tracker

A local-first reading tracker. Log what you read, page range by page range, and see
how the pages add up. Runs entirely on this Mac: no account, no cloud, no internet.

Your data lives in one plain JSON file — `data/entries.json` — that you can open and
edit in any text editor.

**Phase 5 of 5: settings and themes.** The app is self-contained: double-click
`run.command`, no terminal, no Node, works with wifi off. FastAPI serves the built
front end directly — there is no separate dev server to run alongside it, and no
port but 8420 involved. Six preset color themes plus a custom theme editor live in
a collapsed "Settings" panel, alongside a default-chip preference.

---

## Running it

Double-click **`run.command`** (or a Desktop alias of it — see *Deployment* below).

The first run takes a minute: it builds a Python environment and downloads the two
packages the server needs (this one step needs the internet; nothing afterward does).
Later runs start immediately and quietly.

The tracker opens at **http://127.0.0.1:8420/**. To stop it, close the window or press
**Control-C**.

Double-clicking `run.command` (or its Desktop alias) while the tracker is already
running just opens a new browser tab to it — it will not try to start a second server.

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

## Working on the front end

Day to day, you don't need any of this — `run.command` already serves the built UI.
This section is only for making changes to `web/src`.

The front end lives in `web/`. In development it runs on its own server and forwards
every `/api` request to the Python server, so **both need to be running**.

```bash
# Terminal 1 -- the API
./run.command

# Terminal 2 -- the front end
cd web
npm install        # first time only
npm run dev
```

`npm run dev` prints a URL (usually <http://localhost:5173/>). Open that one, not
port 8420 — 8420 serves whatever was last built into `web/dist`, not your unbuilt
changes.

If the front end says the tracker isn't running, terminal 1 is what's missing.

Once you're happy with a change, rebuild and commit the result:

```bash
cd web
npm run build       # writes web/dist, which is committed and served by run.command
```

### Front-end tests

```bash
cd web
npm test
```

They stub the network, so they pass with no server running and never touch your log.

### Nothing is fetched from the internet

The Fraunces face used for the big number is committed to the repo at
`web/public/fonts/` and loaded from there. There is no CDN link, no Google Fonts tag,
and no external stylesheet or script anywhere in `web/` — pull the network cable and
the page looks exactly the same.

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
| `GET` | `/api/quote` | — |
| `GET` | `/api/export` | — downloads a backup of everything, see below |
| `GET` | `/api/settings` | — theme, custom theme overrides, default chip |
| `PATCH` | `/api/settings` | any of `theme`, `custom_theme`, `default_chip` |

**Page counting is inclusive.** Pages 43–71 is 29 pages. Pages 43–43 is 1 page.

**A day runs 4am to 4am.** Reading logged at 1am Tuesday counts toward Monday, so a
late night still counts as the day it felt like.

`GET /api/stats` returns `pages_today`, `pages_all_time`, `current_streak_days`,
`entry_count`, and `first_entry_date`.

Errors come back as `{"error": "a human readable message"}`.

FastAPI's `/docs` page is deliberately disabled — it loads its JavaScript from a CDN
and would render blank offline. The raw schema is at `/openapi.json`.

---

## The quotes

The line at the top of the page comes from **`quotes.txt`** in this folder. Open it in
any text editor and make it yours — add your own, delete the ones you don't like. One
quote per line; blank lines and lines starting with `#` are ignored.

You get the same quote all day, and a different one tomorrow. Reloading the page won't
shuffle it.

Save the file and reload the page — no restart needed. If the file goes missing or ends
up empty, the page shows a default line rather than an error.

**`quotes.txt` has nothing to do with `data/entries.json`.** Nothing you do to your
quotes can affect a single page you've logged; the code that reads quotes has no way to
reach your reading log at all.

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

Back it up by copying `data/entries.json` and `data/classes.json` anywhere you like, or
click **Download a backup** at the bottom of the page — it downloads one JSON file with
everything in it. There's no matching "restore" button; if you ever need it back,
stop the tracker and copy the entries/classes back out of the downloaded file into
`data/entries.json` and `data/classes.json` by hand.

`data/settings.json` (your theme and default chip) follows the same atomic-write and
damaged-file rules as the other two, but it's cosmetic, not reading history — losing it
just means the app reverts to the pink default on next launch.

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

## Deployment

Setting this up fresh on a Mac, in order:

1. **Prerequisites.** macOS with Python 3.11+ (`xcode-select --install` gets you one)
   and, only for building the front end, [Node.js](https://nodejs.org/).
2. **Clone the repo** somewhere permanent — `~/Desktop/pink-page-count` is what these
   docs assume, but anywhere works.
3. **Build the front end once:**
   ```bash
   cd web && npm install && npm run build
   ```
4. **Make the launchers executable** (git preserves the executable bit on most clones,
   but if double-clicking does nothing, run this once):
   ```bash
   chmod +x run.command update.command
   ```
5. **First launch:** double-click `run.command`. macOS Gatekeeper will likely refuse
   the first time since the script isn't signed — right-click (or Control-click)
   `run.command`, choose **Open**, and confirm in the dialog that appears. After that,
   plain double-clicks work.
6. **Put it on the Desktop:** select `run.command` in Finder, ⌘L to make an alias
   (or Option-⌘-drag it to the Desktop), and rename the alias to whatever you like.
   It resolves its own real location, so the alias works from anywhere.
7. **Apply the pink icon:** select `run.command` (or its Desktop alias) in Finder,
   press ⌘I to open **Get Info**, then drag `AppIcon.icns` onto the small icon in the
   top-left corner of that panel. This can't be scripted reliably, so it's a one-time
   manual step.

### Updating

Double-click **`update.command`**. It pulls the latest code and reports what changed.
It refuses outright — and changes nothing — if you have any uncommitted edits in the
folder. It never starts or stops the server; run `run.command` yourself afterward.

### Rolling back

If you ever check out an older commit by hand: `data/entries.json` is at
`schema_version` 2 (§1.2 in `DECISIONS.md`), and any code from before the classes
phase only understands version 1. §1.2's refuse-to-start rule means that older code
will halt rather than touch a version-2 file — it won't corrupt anything, but it also
won't run. Rolling back past the classes commit isn't supported for that reason;
stay on `update.command`'s forward-only pulls instead.

---

## Where things are

```
DECISIONS.md      the schema and every design decision -- read this first
README.md         this file
run.command       the launcher
update.command    pulls new code; never touches a dirty tree or the server
AppIcon.icns      the Desktop launcher's icon
requirements.txt  what the server needs to run
scripts/
  make_icon.py    regenerates AppIcon.icns: a flat pink plate, scales mark
app/
  config.py       paths, port, environment variables
  daytime.py      timestamps and the 4am day boundary
  storage.py      atomic writes and loading -- the durability code
  classes.py      classes.json: load, CRUD, write-through
  settings.py     settings.json: theme, custom theme, default chip
  models.py       request and response shapes, page-range validation
  stats.py        pages today, streaks
  quotes.py       picks the day's quote. Cannot reach your reading log
  main.py         the API routes, and the built UI at "/"
quotes.txt        the quotes. Yours to edit -- see below
web/
  vite.config.ts  dev server, and the /api proxy to port 8420
  public/fonts/   Fraunces, vendored -- never fetched
  dist/           the built front end -- committed, and what run.command serves
  src/
    tokens.css    theme layer + semantic layer -- every color, duration, and
                  font, defined once (six preset themes live here)
    theme.ts      preset ids/labels and the theme-applying functions
    contrast.ts   the WCAG contrast check behind the theme editor's warnings
    api.ts        the API calls and the two kinds of failure
    milestones.ts which thousand you just passed -- never how far to the next
    App.tsx       the page
    components/   ClassManager, SettingsPanel + ThemeEditor, and the rest
    __tests__/
tests/
data/
  entries.json    your reading log
  classes.json    your classes
  settings.json   your theme and default chip
```

**`DECISIONS.md` is the reference.** It records the data schema and the reasoning behind
every decision in this project, so later work builds on it instead of guessing.
