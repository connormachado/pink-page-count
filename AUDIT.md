# AUDIT.md

Read-only audit of `pink-page-count` ahead of distribution to ~5 people outside the
developer's household, as a frozen macOS app bundle (PyInstaller), moving the data
directory to `~/Library/Application Support/`.

Nothing in this audit was fixed. Nothing in the repo was modified. Working tree was
clean at the start and is clean now apart from this file.

Scope of what was actually exercised, not just read:

- `.venv/bin/python -m pytest` — **183 passed** on Python 3.14.6.
- Startup and a `POST /api/entries` against a read-only data directory.
- Server startup and static serving from a working directory outside the repo.
- Port conflict against an already-bound 8420-class port.
- `python -m venv` and pip invocation inside a directory named `Connor's Test Folder`.
- `git log --all -- data/` and `git grep` over every tracked file.

**Verdict: do not freeze yet.** Six items below must be resolved first. The largest —
BLOCKER 1 — is that every default data path is derived from the location of the source
file, which is exactly the assumption PyInstaller invalidates.

---

## BLOCKERS

Must fix before shipping. Each of these fails on a recipient's machine, not on yours.

### B1. Every data path is anchored to the source tree, via `__file__`

`app/config.py:30`

```python
REPO_ROOT = Path(__file__).resolve().parent.parent
```

`DEFAULT_DATA_FILE` (`config.py:31`), `DEFAULT_CLASSES_FILE` (`:33`) and
`DEFAULT_SETTINGS_FILE` (`:37`) are all `REPO_ROOT / "data" / ...`. Under PyInstaller
`__file__` for a bundled module points inside the frozen bundle, not at a checkout:

- **onefile:** `REPO_ROOT` becomes `sys._MEIPASS`, a temporary directory created at
  launch and **deleted when the process exits**. `entries.json` is created empty on
  every launch, written to all session, and destroyed on quit. The app would appear to
  work perfectly and lose every entry, every time, with no error at any point.
- **onedir / `.app`:** `REPO_ROOT` becomes `MyApp.app/Contents/…`. The reading log is
  written *inside the application bundle*. Replacing the app with a new version, or
  dragging it to a different folder, silently leaves the only copy of the data behind
  in the old bundle. It also breaks the code signature and fails outright if the app
  is quarantined (App Translocation mounts it read-only) or in `/Applications` under a
  non-admin account.

Failure on someone else's machine: the reading log is either destroyed on every quit
or stranded inside a bundle they will eventually replace, with nothing on screen ever
indicating a problem.

### B2. Bundle resources and writable data share one base, so the move can't be partial

Same line, `app/config.py:30`. `DEFAULT_QUOTES_FILE` (`:40`) and `DEFAULT_DIST_DIR`
(`:42`) hang off the same `REPO_ROOT` as the three data files, but they belong on the
*opposite* side of the split: `quotes.txt` and `web/dist` are read-only resources that
must stay inside the bundle, while the three JSON files must move to Application
Support. There is currently one base where there need to be two.

Failure on someone else's machine: a fix that repoints `REPO_ROOT` at Application
Support also repoints the front end and the quote file there, and the app serves the
"hasn't been built yet" page (`app/main.py:362`) to all five recipients.

Note that `quotes.txt` becoming a read-only bundle resource is itself a behavior
change worth deciding deliberately: DECISIONS.md §10.1 describes it as "a file she
owns," editable in TextEdit with no restart (`app/quotes.py:36`, read on every
request). Inside a signed bundle it is no longer editable. That is a §10 change and
belongs in DECISIONS.md, per CLAUDE.md's rule about edits in the same commit.

### B3. The corrupt-file halt is printed to stderr, which a `.app` has nowhere to show

`app/storage.py:302`, `app/classes.py:276`, `app/settings.py:224` — all three print
`exc.banner()` to `sys.stderr` and `raise SystemExit(2)`.

Today that is correct and, frankly, excellent: `run.command` runs in Terminal, the
banner is visible, and it is well written. Once the app is a Finder-launched bundle,
stderr goes to the unified log. The halt becomes an app that bounces once in the Dock
and disappears with no window and no message.

Failure on someone else's machine: a single hand-edit or a truncated file turns the
app into one that "just doesn't open," with no path to the explanation. Part 3 asks
that the halt message tell a non-technical user what to do; under the new distribution
model it tells them nothing.

The banner also needs revisiting for its new audience even when it *is* visible: its
remedy is `mv '<path>' '<path>.bak'` (`app/jsonfile.py:76`), a Terminal command, and
after the move the path it names is under `~/Library`, which Finder hides by default.

### B4. A failed write returns a bare 500, and the UI reports it as "the app isn't running"

Verified end to end. With the data directory read-only, startup succeeds and then:

```
POST /api/entries -> 500
body: Internal Server Error
```

`atomic_write_json` raises `OSError`, no handler catches it (`app/main.py:129-139`
installs handlers for `ValidationProblem`, `RequestValidationError` and
`StarletteHTTPException` only), so Starlette returns a plain-text 500 with no JSON
body. `web/src/api.ts:55` then converts any JSON-less 5xx into `ServerUnreachable`,
and `web/src/App.tsx:136` renders:

> The reading tracker isn't running right now.

Failure on someone else's machine: whenever the data directory is read-only, full, on
a disconnected volume, or owned by another user, every save is lost and the user is
told the app is not running — while it is running, answering, and showing them their
old total. DECISIONS.md §3.5 promises "a request that returned 200 is a request whose
data is already on disk"; the inverse case is the one that lies. This is the finding I
would fix first after B1, because it is the one that costs trust in the number.

### B5. `update.command` cannot work at all in a frozen bundle

`update.command:26` runs `git status --porcelain`, `:34` runs `git rev-parse HEAD`,
`:37` runs `git pull --ff-only`. A distributed `.app` has no `.git` directory. The
`if` at `:26` swallows git's failure (set -e is suspended in a condition), so control
reaches the bare assignment at `:34`, which fails under `set -euo pipefail` and exits
the script silently — after git has printed `fatal: not a git repository` to stderr.

Failure on someone else's machine: a double-clickable that prints a raw git error and
closes. Either ship it with a real update story or don't ship it.

### B6. There is no PyInstaller machinery in the repo

`grep -riI "pyinstaller|\.spec|py2app|codesign|notariz"` over the whole tree returns
nothing. No spec file, no build script, no hidden-import handling for uvicorn's
dynamically-imported protocol/loop modules (`uvicorn.protocols.*`, `uvicorn.loops.*`),
no datas entry for `web/dist` or `quotes.txt`, no signing or notarization step.

Failure on someone else's machine: `uvicorn` in particular imports its worker classes
by string name, which PyInstaller's static analysis does not follow — the naive freeze
builds cleanly and then fails at startup on the recipient's Mac. This is not a defect
in existing code; it is the missing half of the premise, and B1/B2 cannot be validated
until something actually produces a bundle.

---

## SHOULD FIX

### S1. The "your Python is too old" message is never printed on a Mac without developer tools

`run.command:53-58`. On a stock Mac with no Xcode CLT, `/usr/bin/python3` exists as a
stub, so `command -v python3` at `:37` succeeds, but running it fails. The check at
`:53` correctly enters the failure branch, and then `:54` is a bare assignment:

```bash
CURRENT="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
```

Under `set -euo pipefail` a failed command substitution in an assignment exits the
script. Verified with an equivalent harness: exit code 1, friendly message never
printed. The recipient gets a GUI prompt to install developer tools and a Terminal
window that closes with nothing in it.

### S2. Startup write failures produce a Python traceback, not the banner

`app/storage.py:299-303`, `app/classes.py:273-277`, `app/settings.py:221-225` catch
only `CorruptDataFile`. A first run where the data directory cannot be written raises
`PermissionError` out of `jsonfile.py:132`. Verified:

```
PermissionError: [Errno 13] Permission denied:
  '…/data/.settings.json.25cju22q.tmp'
```

`run.command:128` does `cat "$LOG"` before its own message, so a Terminal user sees a
traceback followed by helpful text — survivable today, invisible under B3 tomorrow.

### S3. The launcher writes three things into its own directory

`run.command:22` (`.venv`), `:23`/`:85` (`.installed` stamp), `:24`/`:105`
(`server.log`). From `/Applications` under a non-admin account, `: > "$LOG"` at `:105`
fails and `set -e` exits the script with no message at all. The venv failure at `:62`
is handled nicely (`:64-67`); the log and stamp writes are not guarded.

### S4. A username-bearing absolute path is committed

`README.md:37` and `README.md:208` both contain
`cd /Users/connormachado/Desktop/pink-page-count`. It leaks the developer's account
name and is wrong on every recipient's machine. This is the only such path in the
repo — `git grep "/Users/"` over tracked files returns exactly these two lines.

### S5. The UI's recovery instruction names a file recipients won't have

`web/src/App.tsx:138`: "Start it by double-clicking `run.command` in the project
folder." A recipient has an app icon, not a project folder. This string is the one
piece of the UI that has to be right precisely when everything else has gone wrong.

### S6. First run requires the network, which contradicts the offline promise

`run.command:78-86` pip-installs on first launch. The failure message (`:81-84`) is
honest about needing the internet once. But README.md and DECISIONS.md §9.4 tell the
user this app is fully offline, and campus wifi with a captive portal is exactly where
a silent pip failure lands. Freezing removes this entirely — which is a good argument
for finishing B6 rather than shipping the current launcher.

### S7. `.command` files will be Gatekeeper-blocked in transit

A `.command` distributed by zip, AirDrop, or email arrives quarantined, and several
transports drop the executable bit. Recipients get "cannot be opened because it is
from an unidentified developer," or a file that opens in TextEdit. Signing and
notarization is the real answer and is part of B6.

---

## NOTES

Confirmations, direct answers, and things that are fine but worth knowing.

**Binding — confirmed loopback-only, no path widens it.** The exact lines:

- `app/config.py:20` — `HOST = "127.0.0.1"`, consumed at `app/main.py:391`
  (`host=config.HOST`).
- `run.command:107` — `--host 127.0.0.1`, a literal.

Both are hard-coded. There is no `PAGECOUNT_HOST`; `app/config.py:23-28` defines env
names for port, four paths, and nothing else. One structural caveat worth writing
down: `run.command` invokes the uvicorn CLI directly rather than `app.main:main`, so
at real launch time the binding actually enforced is the literal on `run.command:107`,
not `config.HOST`. Two independent places, both loopback, but they are two.

**No CORS middleware.** Confirmed absent — no `add_middleware` call anywhere in
`app/`, and `app/main.py:125` records the decision as a comment.

**No personal data committed.** `git log --all --name-only -- data/` returns nothing;
`data/` has never been tracked. Working-tree `data/entries.json` and
`data/classes.json` (containing a real class, "torts") are untracked and ignored.

**`.gitignore` covers what it must.** Verified with `git check-ignore -v`:
`data/` → `.gitignore:7`, `.venv/` → `:1`, `web/node_modules/` → `:11`,
`server.log` → `:8`, `.pytest_cache/` → `:4`, `web/*.tsbuildinfo` → `:12`.
`web/dist` is deliberately tracked (6 files), per DECISIONS.md §6.

**Zero network calls, CDN references, telemetry, or auto-update.** As expected. The
built bundle contains only `w3.org` XML namespace URIs and one `react.dev/errors/`
string inside React's minified error message — neither is ever fetched. The font is
self-hosted: `src:url(/fonts/fraunces-latin-var.woff2)`. `docs_url=None` /
`redoc_url=None` at `app/main.py:122-123` keeps the CDN-dependent Swagger pages off.
`update.command` is a manual git pull, not an auto-updater. Nothing phones home.

**Minimum Python is genuinely 3.10, effectively 3.11.** PEP 604 unions (`str | None`)
in `app/models.py` are evaluated by pydantic despite `from __future__ import
annotations`, requiring 3.10. `datetime.fromisoformat` (`app/daytime.py:36`) needs
3.11 to accept `Z`-suffixed and extended ISO forms, which a hand-edited file can
easily contain. `run.command:53` checks `>= (3, 11)` and prints a genuinely good
human-readable message — except in the S1 case, where it prints nothing. Tests pass on
3.14.6, so the upper end is not a concern.

**Spaces and apostrophes in the app path — fine.** Verified with a real venv created
at `…/Connor's Test Folder/`. Modern pip console scripts use a `#!/bin/sh` wrapper
shebang, so both `.venv/bin/pip` (the form `update.command:61` uses) and
`python -m pip` (the form `run.command:80` uses) work. Every expansion in both scripts
is quoted, and both resolve their own directory through symlinks (`run.command:11-17`,
`update.command:11-18`). The single exception is cosmetic: `run.command:133` wraps
`$APP_DIR` in single quotes inside its port-conflict advice, so an apostrophe in the
path yields an unrunnable suggested command.

**Static serving does not depend on the working directory.** Verified by starting the
app from an unrelated directory: `GET /` → 200 with the built UI, `/assets/…` → 200
(227,011 bytes), `/fonts/…` → 200 (67,388 bytes), `/api/quote` → 200. Everything
routes through `config.dist_dir()`, which is `__file__`-derived — correct today, and
subject to B1/B2 tomorrow.

**Port conflict is handled well.** Verified: with the port already bound, uvicorn exits
3 with `[Errno 48] … address already in use`. `run.command:112-134` notices the server
died, prints the log, and suggests `PAGECOUNT_PORT=$((PORT + 1))`. The pre-flight
already-running check at `:30` also works as designed. This is one of the better-built
paths in the project; the only wrinkle is S7's quoting.

**Corrupt-file policy is halt, not recover — confirmed.** `read_json_document` and the
per-record validators raise; nothing renames, quarantines, or writes. All three
`load_*_or_exit` functions print the banner and `SystemExit(2)`. The banner itself
(rendered and inspected) names the file, the problem, the line/column, and states
plainly that nothing was changed. The caveats are B3 (nowhere to show it) and the
`mv` remedy noted there.

**§8 compliance — clean. No scolding surface has crept in.** Every user-visible string
was reviewed.

- `longest_streak_days` is computed at `app/stats.py:80` but omitted from `StatsOut`
  (`app/models.py:152-165`), so it cannot reach a client. Still structural.
- `ClassOut` (`app/models.py:135-149`) carries no entry count or page total.
  `/api/stats?class_id=` and `/api/stats/by-class` do not exist.
- `web/src/milestones.ts` exports only `crossedMilestone`; no distance, no remainder,
  no percentage. `crossedMilestone` returns null when `after <= before`.
- Errors render in `--rose-muted`, never a danger color — `web/src/components/Field.tsx:27`,
  with the reasoning at `:13-15`. No red anywhere in the components or tokens.
- Empty state is gated on `entry_count === 0` (`web/src/App.tsx:167`), not on a zero
  value.
- Chip labels are bare values — "pages today", "pages, all time", "days in a row"
  (`web/src/stat.ts:39-51`). No comparison, no pace, no goal, no projection.
- `quotes.txt` (20 quotes) contains nothing about discipline, catching up, or falling
  behind. "No one is grading this." is representative.
- The one string in the app containing a warning is
  `web/src/components/ThemeEditor.tsx:185` — "… is hard to read at this contrast." It
  is about a color the user picked, never about their reading, it never blocks, and
  DECISIONS.md §13.3 sanctions it explicitly. Not a §8 issue.

The one §8-adjacent thing to keep in view: B4's "The reading tracker isn't running
right now" is not a reprimand, but it *is* the app telling the user something false
about their own data. §8's spirit — never present a lie that looks like data — is
the reason to fix it, not just correctness.

**Env overrides are not resolved to absolute paths.** `app/config.py:48` (and `:57`,
`:67`, `:76`, `:85`) apply `.expanduser()` but not `.resolve()`. A relative value is
therefore interpreted against the working directory. README.md:48 documents the
default as `data/entries.json` — a relative-looking string — so a user who copies it
into a `PAGECOUNT_DATA_FILE` export gets a second, empty log wherever they happened to
launch from. Low likelihood, silent, and cheap to close by resolving in `config`.

**`server.log` is truncated on every launch** (`run.command:105`). A crash report
survives only until the next double-click, which is usually the very next thing a
confused user does.

**localStorage paint cache is keyed per origin.** `web/index.html:18` uses
`ppc:theme-cache`, guarded by try/catch there and at `web/src/theme.ts:96-98`. Running
on a different port (the S7/port-conflict path) means a different origin and a
one-frame flash of the pink default. Harmless, and §13.4 already says the cache is
never a data source.

---

## Part 1 — Storage path inventory

Every location referencing a data, resource, or launcher path. "Derived" means
computed from `__file__` or `BASH_SOURCE`. The last column answers Part 1's question:
does it assume the file sits next to the source code, and would running from
`/Applications` break it or silently fork the data?

| File:line | References | Kind | Next to source? | Risk if run from `/Applications` |
|---|---|---|---|---|
| `app/config.py:30` | `REPO_ROOT` | derived (`__file__`) | **Yes — the root assumption** | **B1/B2. Becomes a temp dir (onefile) or the bundle interior (onedir).** |
| `app/config.py:31` | `data/entries.json` | derived | **Yes** | **Silent data loss or a log stranded inside the bundle.** |
| `app/config.py:33` | `data/classes.json` | derived | **Yes** | **Same.** |
| `app/config.py:37` | `data/settings.json` | derived | **Yes** | **Same.** |
| `app/config.py:40` | `quotes.txt` | derived | Yes | Correct to keep in the bundle; loses editability (B2). |
| `app/config.py:42` | `web/dist` | derived | Yes | Correct to keep in the bundle; breaks if repointed (B2). |
| `app/config.py:45-48` | `data_file()` env override | absolute if set, else derived | via default | Relative env value resolves against cwd — silent second copy. |
| `app/config.py:51-57` | `classes_file()` env override | same | via default | Same. |
| `app/config.py:60-67` | `settings_file()` env override | same | via default | Same. |
| `app/config.py:70-76` | `quotes_file()` env override | same | via default | Same. |
| `app/config.py:79-85` | `dist_dir()` env override | same | via default | Same. |
| `app/main.py:114` | quotes default → `config.quotes_file()` | derived | Yes | Inherits B2. |
| `app/main.py:115` | dist default → `config.dist_dir()` | derived | Yes | Inherits B2. |
| `app/main.py:346,348` | `dist_dir/assets`, `dist_dir/fonts` mounts | derived | Yes | Silently skipped if absent — UI loads unstyled, no error. |
| `app/main.py:360` | `dist_dir/index.html` | derived | Yes | Falls back to the "not built yet" page, a 200. |
| `app/main.py:373-377` | `create_default_app()` opens all three real files | derived | Yes | Entry point for B1. |
| `app/main.py:385-387` | `main()` pre-resolves all three before uvicorn | derived | Yes | Same. |
| `app/storage.py:160-161` | mkdir + first write of `entries.json` | derived | Yes | **Creates a fresh empty log wherever `REPO_ROOT` lands.** |
| `app/classes.py:131-132` | mkdir + first write of `classes.json` | derived | Yes | Same. |
| `app/settings.py:172-173` | mkdir + first write of `settings.json` | derived | Yes | Same; this is the one that raised `PermissionError` in testing. |
| `app/jsonfile.py:130` | `directory.mkdir(parents=True)` | from caller | — | Creates the data dir at whatever path it is handed. |
| `app/jsonfile.py:132-134` | `mkstemp(dir=directory)` | from caller | — | Requires write permission on the data dir; B4/S2. |
| `app/jsonfile.py:76` | `mv '<path>' '<path>.bak'` in the halt banner | from caller | — | Names the live data path; a Terminal remedy under a hidden dir (B3). |
| `app/main.py:331` | export filename `reading-log-<date>.json` | no path | No | Download only; browser chooses the location. No server-side backup path exists. |
| `run.command:11-17` | `APP_DIR` | derived (`BASH_SOURCE`, symlink-resolved) | **Yes** | Alias-safe; assumes a writable checkout. |
| `run.command:18` | `cd "$APP_DIR"` | derived | Yes | Makes `-m uvicorn app.main` at `:106` resolvable. |
| `run.command:22` | `$APP_DIR/.venv` | derived | **Yes** | **Non-admin write failure; handled with a message at `:64-67`.** |
| `run.command:23,85` | `$VENV/.installed` stamp | derived | Yes | Unguarded write; S3. |
| `run.command:24,105` | `$APP_DIR/server.log` | derived | **Yes** | **Unguarded write; silent `set -e` exit. S3.** |
| `run.command:78,81` | `$APP_DIR/requirements.txt` | derived | Yes | Absent in a frozen bundle. |
| `run.command:106` | `app.main:create_default_app` module path | cwd-relative | Yes | Depends on the `cd` at `:18`. |
| `run.command:133` | `'$APP_DIR/run.command'` in advice text | derived | Yes | Breaks on an apostrophe; message only. S7. |
| `update.command:11-19` | `APP_DIR` + `cd` | derived | Yes | Same resolution as `run.command`. |
| `update.command:26,34,37` | `git status` / `rev-parse` / `pull` | requires `.git` | **Yes** | **B5. No repo in a bundle — silent exit after a raw git error.** |
| `update.command:58,61` | `$VENV/bin/pip`, `$APP_DIR/requirements.txt` | derived | Yes | Neither exists in a bundle. |
| `tests/conftest.py:14` | `sys.path` insert from `__file__` | derived | Yes | Dev-only; never packaged. |
| `tests/conftest.py:41,51,61` | `tmp_path/data/*.json` fixtures | absolute, per-test | No | **Correctly isolated. No test touches real data — verified.** |
| `tests/conftest.py:73` | `tmp_path/quotes.txt`, deliberately not created | absolute, per-test | No | Correctly isolated. |
| `tests/test_static.py:19-32` | own `dist_dir` per test | absolute, per-test | No | Correctly isolated from the real `web/dist`. |
| `scripts/make_icon.py:22,133` | `REPO_ROOT`, writes `AppIcon.icns` | derived | Yes | Dev tool; not shipped. |
| `web/index.html:18` | `localStorage["ppc:theme-cache"]` | browser, per-origin | No | Paint cache only; a port change loses it harmlessly. |
| `.gitignore:7` | `data/` | relative to repo root | Yes | Correct today; must follow the directory when it moves. |

### The three that would silently fork or destroy the data

`app/config.py:31`, `:33`, `:37`. Nothing else in the inventory can create a second
copy of the reading log without saying so. Those three, plus the first-write paths
they feed at `app/storage.py:161`, `app/classes.py:132`, and `app/settings.py:173`,
are the whole of B1 — and the reason the storage-path move should land, with its
DECISIONS.md amendment, before anything is frozen.
