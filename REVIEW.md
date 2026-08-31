# REVIEW.md

Read-only V1 review of the seams between the eight shipping sessions. Nothing in the
repo was modified except this file; the working tree was clean at the start and is
clean now apart from it.

**What was actually exercised, not just read:**

- `.venv/bin/python -m pytest` — **298 passed**. `cd web && npm test -- --run` —
  **139 passed**. `npx tsc --noEmit` — clean. All three match DECISIONS.md 17.7.
- The two-rapid-launch race, run for real: two `PAGECOUNT_SERVE=1` servers started
  concurrently against a scratch `DATA_ROOT`, exit codes and both output streams
  captured. The real `~/Library/Application Support/PinkPageCount/` was verified
  byte-for-byte unchanged afterwards.
- `otool -l` / `codesign -dv` over all 60 Mach-O files in
  `packaging/dist/Pink Page Count.app` **and** inside `PinkPageCount.zip` — the
  artifact that actually gets AirDropped.
- The import graph that decides whether the frozen app starts, traced by importing
  `app.launcher` and reading `sys.modules`.
- `git log -S` to date each DECISIONS.md claim against the commit that fixed or
  broke it.

**What could not be exercised:** this session has no browser automation tool, so
every layout figure below is computed from the source and the built CSS, not read off
a rendered page. Anything I could not measure is labelled as such. No Mac running a
macOS version other than this one was available, so BLOCKER 1 is established from the
binaries rather than from a failed launch.

---

## SHIP BLOCKERS

### 1. The bundle only runs on macOS 26. Three of four recipients will see nothing at all.

`packaging/dist/Pink Page Count.app/Contents/Frameworks/libssl.3.dylib` and
`libcrypto.3.dylib` carry `LC_BUILD_VERSION minos 26.0`;
`Contents/Frameworks/Python.framework/Versions/3.14/Python` and 56 other bundled
binaries carry `minos 15.0`. dyld refuses to load a library built for a newer OS than
the one running, so on macOS 14 or earlier the CPython framework never loads and the
bootloader dies before any of our code runs, and on macOS 15 through 25 `_ssl` cannot
dlopen the two OpenSSL libraries.

That second one is not survivable, because the `import ssl` on the path is unguarded:
`app/launcher.py:43` imports `app.main`, which reaches `anyio/_core/_sockets.py:6`
(`import ssl`, no try/except) through fastapi and starlette. Verified by trace —
importing `app.launcher` alone already puts `_ssl` in `sys.modules`. `uvicorn/config.py:10`
is a second unguarded `import ssl` on the same path. `urllib.request` and `hashlib`
guard theirs and would have been fine; these two do not.

Confirmed present in `PinkPageCount.zip` as well as in `packaging/dist/`, so the
already-built artifact has it.

Failure on someone else's machine: the icon bounces once and stops. No tab, no dialog,
no log — the launched process dies at import time, which is upstream of `app/notify.py`
and of every branch in `app/launcher.py:299`. It is exactly the "the app is broken"
outcome DECISIONS.md 16 was written to eliminate, arriving through a door 16 does not
cover.

Root cause is `packaging/build_app.sh:118`: nothing in the build asserts a deployment
target, so the bundle inherits whatever the Homebrew bottles on the build machine were
compiled for — and this machine is on Darwin 25.5 (macOS 26), with an openssl@3 bottle
newer than its python@3.14 bottle.

### 2. The install instructions describe a Gatekeeper flow Apple removed.

`how-to-install.md:7` tells the recipient to right-click, choose Open, and "click Open
again". macOS 15 removed the Control-click bypass for unsigned apps; the first dialog
now offers only Move to Trash and Done. The same stale advice appears at
`README.md:267`, `packaging/build_app.sh:133`, and `DECISIONS.md:1643`.

Failure on someone else's machine: on any recipient running macOS 15 or later, step 3
produces a dialog with no Open button and the documented path stops there. The fallback
at `how-to-install.md:9` is the correct Sequoia-and-later route, but it is written as
the exception rather than the rule, and these four people have no help desk.

### 3. `quotes.txt` ships a block its own header says must be reviewed first, and several quotes that §10.5 forbids.

`quotes.txt:66` — "TIER B — widely circulated, sourcing looser. **Review before
shipping.**" — and `quotes.txt:8` repeats the instruction. Eight quotes sit under it
(`:69`–`:76`) and the bundle shipped. `quotes.txt:69` ("Lost causes are the only ones
worth fighting for", attributed to Clarence Darrow) is a line from *Mr. Smith Goes to
Washington*, not Darrow. §10.1.2's whole argument for attribution is that an unnamed
quote reads as the app claiming it; a *mis*named one is the same defect pointed the
other way, and this app is going to four law students.

Separately, the list has changed character completely since AUDIT.md's §8 pass (which
found it "warm and undemanding", 20 quotes; there are now 51), and several now read as
instructions about her effort:

- `quotes.txt:40` — "The leading rule for the lawyer … is **diligence**." §10.5 names
  discipline explicitly.
- `quotes.txt:49` — "**It is not enough to be busy.** The question is: what are we busy
  about?" A reprimand in shape, sitting directly above her reading log.
- `quotes.txt:33` — "Don't be distracted by emotions like anger, envy, resentment.
  These just zap energy and **waste time**." A pace judgement.
- `quotes.txt:37` — "Success **is to be measured** not so much by the position one has
  reached as by the obstacles overcome." §8 forbids measuring her; this one says the
  word.
- `quotes.txt:55` — "Wake up, humanity. **We're out of time.**" §8 rules out alarm
  states; read at 1am above a page count, this is one.
- `quotes.txt:39`, `:35`, `:50`, `:70` are weaker versions of the same thing.

Failure on someone else's machine: not a crash — a violation of the one constraint
CLAUDE.md says binds every phase, on the one surface a recipient sees first, every day.
The rotation (§10.3) guarantees each of these lands on someone eventually.

---

## FIX SOON

### 4. The rail width is declared twice, in two units, and only one of them tracks the browser's font size.

`web/src/index.css:44` sets `--rail-expanded: 20rem` (confirmed as `20rem` in the built
`web/dist/assets/index-z61L2BU5.css`). `web/src/useNumeralFit.ts:53` hard-codes
`RAIL_OPEN_PX = 320`. Those agree only while the root font size is 16px. A recipient
with Chrome's or Firefox's font size set to Large (20px), or Safari's minimum font size
raised, gets 400px rails against a fit that reserved 336px — and the numeral's ink runs
under the right rail.

Computed, not measured (no browser tool this session): at a 20px root, a three-digit
total with both rails open overlaps from roughly 1090px downward — 44px of the numeral
covered at 1000px. `web/src/__tests__/numeral.test.ts:22` cannot catch this, because it
imports the same `RAIL_OPEN_PX` it is checking against; jsdom has no layout and no
concept of the setting.

Failure on someone else's machine: for a recipient with larger-text turned on, the
last digits of their all-time total sit underneath the Classes rail — the exact defect
§17.2 removed the breakpoint to prevent.

### 5. DECISIONS.md's newest section says B4 is still broken.

`DECISIONS.md:2738` (§17.7, added by `afc631f`, the most recent substantive commit) and
`DECISIONS.md:1624` (§15.5, present tense: "a failed write is still a bare `500` the UI
reports as 'the reading tracker isn't running right now'") both contradict §3.5.1 and
§4.5, which describe the fix that landed three commits earlier in `f2c7c8e`. §16.4's
copy of the same list (`:2191`) is a fair historical record of that session; §17.7's is
not — it was written after the fix.

Failure on someone else's machine: none directly. It is the failure mode CLAUDE.md's
"DECISIONS.md is authoritative" rule exists to prevent — the next session reads §17.7,
believes a failed save still reports an outage, and either re-fixes it or designs around
a bug that is gone.

### 6. README.md predates the §14 storage move entirely and still leaks the developer's home directory.

`README.md:6` tells the reader their data lives in `data/entries.json`; `README.md:48`
documents `PAGECOUNT_DATA_FILE`'s default as the relative string `data/entries.json`
(it is `~/Library/Application Support/PinkPageCount/entries.json`, §5.1);
`README.md:37` and `README.md:208` still contain `cd /Users/connormachado/Desktop/pink-page-count`
(AUDIT.md S4, unfixed); `README.md:233` gives a corrupt-file drill that writes to a path
nothing reads any more. The file has zero mentions of Application Support, the `.app`
bundle, the heartbeat, the rails, `my-quotes.txt`, or quote attribution.

Failure on someone else's machine: a recipient — or the developer six months from now —
who follows the backup instructions at `README.md:191` copies an empty or stale
`data/entries.json` and believes their reading log is backed up. There is in fact a
stale copy sitting at `data/entries.json` right now (see NOTES) which makes the wrong
instruction look like it worked.

### 7. A one-second probe budget can call our own instance a stranger.

`app/lifecycle.py:50` sets `PROBE_TIMEOUT_SECONDS = 1.0` for both the TCP connect and
the `GET /api/ping`, and `app/lifecycle.py:94` documents that a port which accepts and
does not answer inside that window is `FOREIGN`. `app/launcher.py:325` routes `FOREIGN`
straight to the port-taken dialog.

Failure on someone else's machine: a server that has been idle for hours and is paged
out, on a Mac under memory pressure, can miss a 1s loopback round trip — and the
recipient gets a modal saying "Another program on this Mac is already using port 8420 …
Quit that program", naming a program that is Pink Page Count itself. The instruction is
unfollowable and the app will not start until the real instance is killed.

### 8. `_wait_for_ready`'s bail-out does not fire on the case its comment names.

`app/launcher.py:182-187` says "uvicorn sets `should_exit` when startup fails — a port
already in use is the case that matters". It does not: `uvicorn/server.py:183` calls
`sys.exit(STARTUP_FAILURE)` on the bind `OSError` and never touches `should_exit`. The
`server.should_exit` check at `app/launcher.py:186` is therefore dead on that path, and
the browser thread started at `app/launcher.py:264` keeps polling `/api/health` — which
the *winning* server answers with a 200.

Verified against the real race: two concurrent servers, one listener, loser exits **3**
with nothing but `[Errno 48]` on stderr, and in that run the loser's browser thread lost
the race so no stray tab appeared. It is a race, not a guarantee.

Failure on someone else's machine: at worst one extra browser tab on a double
double-click — harmless, since both tabs point at the one live server. Worth fixing
because the comment is load-bearing documentation of behavior that isn't there.

### 9. The heartbeat margin is reasoned about Chrome only.

`app/lifecycle.py:36-43` and `web/src/App.tsx:32-36` both justify the 30s/5min window
entirely with Chrome's throttling tiers ("The margin is not generosity, it is Chrome" —
`DECISIONS.md` §16.2). Safari suspends timers in fully occluded windows rather than
merely throttling them, and Firefox's background-tab handling is a different mechanism
again. Neither was measured. The prompt states recipients have different default
browsers.

Failure on someone else's machine: a Safari user who leaves the tab open behind another
window for ten minutes comes back to "The reading tracker isn't running right now"
(`web/src/App.tsx:183`) and has to relaunch. Recoverable in one double-click, and §16.2
already accepts this outcome for Chrome's freeze case — but it may be the *common* case
on Safari rather than the rare one, and nobody has looked.

### 10. `app/config.py:34-37` still says the onedir resolution is unsettled.

The comment says "the exact resolution for a onedir/.app build is not settled yet
(AUDIT.md B6 -- next session's build machinery)". §14 settled it — `sys._MEIPASS` is
`Contents/Frameworks` — and B6 is closed. The code below the comment is correct; only
the comment is stale.

Failure on someone else's machine: none. It sends the next reader to a question that
has an answer forty lines away in DECISIONS.md.

---

## NOTES

**PART 1, item 1 — a failed or slow heartbeat cannot surface anything. Clean.**
`web/src/App.tsx:143` is `void api.heartbeat().catch(() => {})`; the rejection never
reaches `setUnreachable` or `setLoadFailed`, which are only written inside `refresh()`
(`web/src/App.tsx:111-121`). The B4 change is upstream of that catch and cannot
matter: a 500 now becomes `ServerFault` instead of `ServerUnreachable`
(`web/src/api.ts:85`) and both are swallowed identically. Asserted at
`web/src/__tests__/heartbeat.test.tsx:90`. The heartbeat POST also carries no body, so
`web/src/api.ts:59` sends no Content-Type and there is no 415 path.

**PART 1, item 2 — the loser shows nothing, and the stranger dialog cannot appear.**
Run for real. The second child is spawned with `PAGECOUNT_SERVE=1`, and
`app/launcher.py:309` returns from `main()` into `serve()` *before* the probe, so the
`FOREIGN` branch is unreachable in the child by construction. Observed: one listener,
winner opened the browser, loser exited 3 with `[Errno 48]` on a stderr that a Finder
launch discards. The one thing §16.5's race paragraph gets wrong is "exits, and is
gone" — the loser first runs `load_storage_or_exit` on all three data files
(`app/launcher.py:216-218`), so a corrupt file would halt it at exit 2 instead. Both
are silent; neither loses data.

**PART 1, item 3 — the detached child cannot orphan or outlive a parent shutdown.**
There is no parent shutdown path to outlive: `app/launcher.py:344` returns immediately
after `os.posix_spawn`, the child is reparented to launchd, and the parent never waits
on it, so no zombie. The child's only exits are the watchdog flag
(`app/launcher.py:281`), SIGINT/SIGTERM, and a failed bind. Worst case — the browser
never opens — it exits on its own five minutes later, because
`HeartbeatWatchdog.__init__` seeds the clock at construction
(`app/lifecycle.py:150`). Double-start is prevented by the kernel, not by the probe,
and one server always survives. The one path that re-creates the 16.5 bug is the
spawn-failure fallback at `app/launcher.py:340`, which serves in the launched process
and puts the app back on LaunchServices' running list; it is commented in place and
tested.

**PART 1, item 4 — there is no permutation anywhere; §10.3 describes the code, but §10.4 now contradicts §10.1.1.**
`app/quotes.py:172-175` is `sha256(day_key)[:8] % count`, a plain modulo over the
unioned list, with no shuffle, no seed, and no permutation — `grep -riI "permut|shuffle"`
over the tree returns only prose. So the premise in the brief does not hold, and there
is no mid-cycle permutation behavior to check. What is actually true: because
`QuoteSource.load()` re-reads both files on every request (`app/quotes.py:166`), adding
or removing one line in `my-quotes.txt` changes `count` and therefore changes *today's*
quote on the next page load. That is a reasonable behavior, but `DECISIONS.md:1013`
states without qualification that "the same logical day always yields the same quote",
which is only true for a list that does not change — and §10.1.1 is the amendment that
made it change at runtime. Related: `DECISIONS.md:1026` (§10.4) and the docstring at
`app/main.py:432-434` both still say editing `quotes.txt` shows up on the next page
load, which §10.1.1 made false for the bundle — that file is inside the read-only
`RESOURCE_ROOT` now.

**PART 1, item 5 — the numeral fit is theme-independent by construction; the overlap risk is elsewhere.**
Every `[data-theme]` block in `web/src/tokens.css:45-101` declares exactly six
`--theme-*` colors and nothing else; `--font-number` and `--font-ui` are declared once,
outside every theme block (`web/src/tokens.css:155-158`). `numeralFontSizePx`
(`web/src/useNumeralFit.ts:75`) takes only a viewport width and a digit count. So all
six presets are geometrically identical and there is no theme-specific overlap width to
find. The two real overlap sources are finding 4 above, and the sub-900px band §17.2
already declares out of scope (`DECISIONS.md:2732`).

**§17.2's 856px is off by 32px, in the safe direction.** `DECISIONS.md:2572` and the
comment at `web/src/useNumeralFit.ts:12` both say a nine-digit total is "fitted, not
floored, down to 856px". Solving `available/(9 × 0.668) = 36` gives `W = 888.4px` for
the floor; `856.4px` is where a rail first reaches a floored nine-digit numeral. The
claim that "the floor and the overlap begin at the same width" is not quite right — they
are 32px apart, with 32px of extra clearance. Both numbers are below the swept range, so
nothing user-visible turns on it.

**A stale tab that says the app is closed keeps the app open.** The heartbeat effect
(`web/src/App.tsx:142`) is declared above every early return, so it keeps beating while
the "isn't running" screen (`:183`) is displayed. Relaunch the app and that tab silently
starts feeding the new server, while still showing the outage screen until "Try again"
is pressed. Consistent with §16.1's "the tabs are the window", but the consequence is
that closing the visible tab will not quit the app.

**`web/src/App.tsx:185` says "or the Dock".** §16.3 is explicit that this app has no
Dock icon while running. Dragging the bundle to the Dock and clicking it does work, so
the sentence is not false — it may still confuse the one person reading it at the one
moment everything else has gone wrong.

**The port-taken dialog holds the launched process for up to 135 seconds.**
`app/notify.py:53` waits `GIVE_UP_SECONDS + 15`, during which LaunchServices considers
the app running and a second double-click is routed to it as a reopen event that nothing
receives (§16.5). Only reachable on the already-broken path.

**§14's quoting rationale is wrong, though the code is right.** `DECISIONS.md:1411` says
the directory name `PinkPageCount` has "no spaces, no apostrophes, so it never needs
quoting in a shell command or a `mv` remedy". The full path contains
`Application Support`, which has a space; the banner quotes it anyway
(`app/jsonfile.py:107`), so nothing breaks.

**DECISIONS.md's own status line is three sections out of date.** `DECISIONS.md:11-19`
still says "Status: Phase 5 of 5", places `settings.json` in `data/`, and describes
`run.command` as the only thing to double-click. Sections 1, 3.3, 12.1 and 13.1 likewise
still write `data/entries.json`, `data/classes.json`, `data/settings.json`; §6 corrects
all of them in one paragraph, but it is the last place a reader looks.

**`web/index.html:6` sets the browser tab title to "Page Count".** The app, the bundle
and every instruction call it Pink Page Count.

**`ClassPicker` dims text with opacity rather than a token.**
`web/src/components/ClassPicker.tsx:36` (`opacity-80` on "(optional)") and `:56`
(`opacity-70` on "(archived)") blend `--rose-muted` toward the background, which is the
one thing `DailyQuote.tsx`'s comment (`web/src/components/DailyQuote.tsx:17-20`) argues
against for exactly the right reason. Pre-existing since Phase 3.5, not a regression,
and not a §8 issue — the contrast suite does not cover it because it reads tokens, not
painted opacity.

### Dead code and files that no longer apply to the shipped bundle

- **`update.command`** (whole file) — AUDIT.md B5, unfixed. `:26`, `:34` and `:37`
  require a `.git` directory a bundle does not have. Still tracked, still documented as
  live behavior at `DECISIONS.md` §5.2 and §6 and at `README.md:280-291`. The bundle has
  no update story at all.
- **`run.command`** (whole file) — repo-only dev launcher, not in the bundle, still
  carrying S1 (`:54`), S3 (`:85`, `:105`) and S6 (`:78-86`).
- **`data/`** — `data/entries.json` (1,238 bytes) and `data/classes.json`, last written
  25 Aug, before the §14 move. The live log at
  `~/Library/Application Support/PinkPageCount/entries.json` is 2,037 bytes. Nothing in
  the code reads the repo copy; it is a stale fork of real reading data sitting exactly
  where `README.md:191` still tells you to back up from.
- **`app/config.py:40`** — the `Path(sys.executable).resolve().parent` fallback. §14
  already records it as dead on this build path and keeps it deliberately; noted only so
  it is not rediscovered as a bug.
- **`scripts/make_icon.py`, `scales-mark.svg`, `scripts/icon-preview/*.png`** (7 tracked
  PNGs) — build-time only, correctly absent from the bundle.
- **`.claude/worktrees/`** — 525 MB of three complete stale repo copies
  (`phase6-build-bundle`, `phase6-lifecycle`, `phase7-rails`), hidden only by
  `.git/info/exclude:11`, which is local and not committed. They contain older copies of
  DECISIONS.md that `grep` will happily find; not shipped.
- **`PinkPageCount.zip`** (15 MB) and **`packaging/dist/` + `packaging/build/`** — the
  release artifacts, gitignored, present in the tree.
- **`server.log`** (0 bytes) — written only by `run.command:105`.
- Confirmed genuinely gone, as §17.2 and §17.4 claim: `web/src/useRailLayout.ts`,
  `RAIL_MIN_WIDTH_PX`, `setRailLayout()`, and the `chrome?: "details" | "bare"` prop.
  No dangling references anywhere, and `tsc --noEmit` is clean.

---

## STILL OPEN FROM AUDIT.md

Verified against the current tree, one by one. AUDIT.md itself was not edited.

| Finding | Status | Where it stands now |
|---|---|---|
| **B1** — data paths anchored to `__file__` | **Fixed** | `app/config.py:49` — `DATA_ROOT` is Application Support, one code path, no dev branch (§14). |
| **B2** — resources and data share one base | **Fixed** | `app/config.py:38-42` splits `RESOURCE_ROOT` from `DATA_ROOT`; `packaging/PinkPageCount.spec:32-35` lands both where config asks. |
| **B3** — the corrupt-file halt has nowhere to show | **STILL OPEN** | `app/storage.py:302`, `app/classes.py:276`, `app/settings.py:224` still print to stderr and `SystemExit(2)`. §16.5 makes it slightly narrower: the halt now happens in the detached child, and the launched process is already gone, so there is not even a Dock tile left to stop bouncing. `app/notify.py` exists and is the mechanism, but nothing on this path calls it. |
| **B4** — failed write reported as an outage | **Fixed** | `app/main.py:201-234` (the `DataWriteError` handler), `web/src/api.ts:42,85` (`ServerFault`), `web/src/App.tsx:119,204` (load-failed state). Covered by `tests/test_write_failures.py` and `web/src/__tests__/errors.test.tsx`. Note DECISIONS.md has not caught up — see finding 5. |
| **B5** — `update.command` cannot work in a bundle | **STILL OPEN** | Unchanged file. Nothing ships it; nothing replaced it. There is still no update story for the four recipients. |
| **B6** — no PyInstaller machinery | **Fixed** | `packaging/build_app.sh`, `packaging/PinkPageCount.spec`, `packaging/entry.py`, `app/launcher.py`. Note it is the *absence* of a deployment-target check in that machinery that is BLOCKER 1. |
| **S1** — "Python too old" message never prints | **STILL OPEN** | `run.command:54` is still a bare assignment under `set -euo pipefail`. Dev-only; no bundle path touches it. |
| **S2** — startup write failure gives a traceback | **STILL OPEN** | `app/storage.py:301`, `app/classes.py:275`, `app/settings.py:223` still catch only `CorruptDataFile`. §3.5.1 names this as deliberately out of scope. |
| **S3** — launcher writes into its own directory unguarded | **STILL OPEN** | `run.command:85` and `:105`. Dev-only. |
| **S4** — committed username-bearing absolute path | **STILL OPEN** | `README.md:37` and `README.md:208`, both unchanged, and still the only two such lines in the tree. |
| **S5** — UI names a file recipients won't have | **Fixed** | `web/src/App.tsx:185` now says "Open `Pink Page Count` from your Applications folder or the Dock". See the "or the Dock" note above. |
| **S6** — first run needs the network | **STILL OPEN for `run.command`, moot for the bundle** | `run.command:78-86` still pip-installs. The frozen bundle carries its dependencies and needs no network, which is what §15.4 predicted. |
| **S7** — `.command` files Gatekeeper-blocked in transit | **STILL OPEN, and now the delivery path's main obstacle** | The bundle is ad-hoc signed only (`codesign -dv` reports `flags=0x2(adhoc)`, `TeamIdentifier=not set`), unsigned by any identity and un-notarized, exactly as §15.6 says. The workaround §15.6 offers no longer exists on macOS 15+ — see BLOCKER 2. |

**Not previously in AUDIT.md and worth carrying forward:** §15.6's second half —
`target_arch=None` in `packaging/PinkPageCount.spec:138` means arm64-only — remains
true and remains fine, since all four recipients are stated to be arm64.
