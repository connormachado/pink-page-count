#!/bin/bash
#
# Build "Pink Page Count.app" -- the one command. See DECISIONS.md section 15.
#
#   packaging/build_app.sh
#
# Produces packaging/dist/Pink Page Count.app from a clean tree. The bundle is
# NOT signed and NOT notarized (15.6).
#
# The front end is rebuilt first. If it cannot be rebuilt (no npm on this
# machine) the script refuses to continue with a web/dist that is older than
# web/src, because shipping a bundle wrapped around a stale front end is a
# failure nobody would notice until a recipient reported a bug that was already
# fixed.

set -euo pipefail

# --- Locate the repo, following symlinks, the way run.command does ---------------
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
PACKAGING="$(cd -P "$(dirname "$SOURCE")" && pwd)"
REPO="$(cd -P "$PACKAGING/.." && pwd)"

WEB="$REPO/web"
DIST="$WEB/dist"
VENV="$REPO/.venv"
PY="$VENV/bin/python"
APP_NAME="Pink Page Count"
OUT="$PACKAGING/dist/$APP_NAME.app"

say()  { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nBuild failed: %s\n' "$*" >&2; exit 1; }

cd "$REPO"

# --- 1. The front end ------------------------------------------------------------
step "Front end"

if command -v npm >/dev/null 2>&1; then
  if [ ! -d "$WEB/node_modules" ]; then
    say "Installing front-end dependencies (needs the network, once)..."
    ( cd "$WEB" && npm ci ) || fail "npm ci failed."
  fi
  say "Rebuilding web/dist..."
  ( cd "$WEB" && npm run build ) || fail "npm run build failed."
else
  # No npm. web/dist is committed (DECISIONS.md 6), so a build is still
  # possible -- but only if what is committed is not older than the source it
  # was built from.
  say "npm not found; cannot rebuild the front end."
  say "Checking whether the committed web/dist is stale..."

  [ -f "$DIST/index.html" ] || fail \
"web/dist has not been built and npm is not available to build it.

Install Node, then run this script again."

  STALE="$(find "$WEB/src" "$WEB/public" "$WEB/index.html" "$WEB/package.json" \
                "$WEB/vite.config.ts" "$WEB/tsconfig.json" \
                -newer "$DIST/index.html" -print -quit 2>/dev/null || true)"
  if [ -n "$STALE" ]; then
    fail \
"web/dist is STALE -- at least one source file is newer than the built output:

  $STALE

Refusing to wrap a bundle around a front end that does not match the source.
Install Node and run this script again, or run 'cd web && npm run build' on a
machine that has it and commit the result."
  fi
  say "web/dist is not stale; continuing with the committed build."
fi

# --- 2. Everything the server actually serves must be there ----------------------
# app/main.py adds the /assets and /fonts mounts only if the directories exist,
# and skips them SILENTLY otherwise (AUDIT.md's note on main.py:346,348). A
# bundle missing one of these renders an unstyled page with no error anywhere,
# so it is checked here rather than discovered by a recipient.
step "Checking the built front end is complete"

[ -f "$DIST/index.html" ]                  || fail "web/dist/index.html is missing."
[ -d "$DIST/assets" ]                      || fail "web/dist/assets/ is missing -- the /assets mount would be skipped silently."
[ -d "$DIST/fonts" ]                       || fail "web/dist/fonts/ is missing -- the /fonts mount would be skipped silently."
ls "$DIST"/assets/*.js  >/dev/null 2>&1    || fail "web/dist/assets holds no .js -- the front end would not load."
ls "$DIST"/assets/*.css >/dev/null 2>&1    || fail "web/dist/assets holds no .css -- the front end would render unstyled."
# DECISIONS.md 9.4: the font is vendored and served locally. If it is missing the
# page still renders, in a fallback face, with nothing on screen saying so.
ls "$DIST"/fonts/*.woff2 >/dev/null 2>&1   || fail "web/dist/fonts holds no .woff2 -- the vendored font (9.4) would not load."
[ -f "$REPO/quotes.txt" ]                  || fail "quotes.txt is missing."
say "index.html, assets/*.js, assets/*.css, fonts/*.woff2, quotes.txt -- all present."

# --- 3. The build virtualenv -----------------------------------------------------
step "Build environment"

if [ ! -x "$PY" ]; then
  say "Creating $VENV ..."
  python3 -m venv "$VENV" || fail "Could not create the virtualenv."
fi

if ! "$PY" -c 'import PyInstaller' >/dev/null 2>&1; then
  say "Installing build dependencies (needs the network, once)..."
  "$PY" -m pip install -r "$REPO/requirements-build.txt" \
    || fail "Could not install build dependencies from requirements-build.txt."
fi
say "PyInstaller $("$PY" -c 'import PyInstaller; print(PyInstaller.__version__)')"
say "Python     $("$PY" -c 'import platform; print(platform.python_version(), platform.machine())')"

# --- 4. Freeze -------------------------------------------------------------------
step "Building $APP_NAME.app"

rm -rf "$PACKAGING/dist" "$PACKAGING/build"

"$PY" -m PyInstaller \
  --noconfirm \
  --clean \
  --log-level WARN \
  --distpath "$PACKAGING/dist" \
  --workpath "$PACKAGING/build" \
  "$PACKAGING/PinkPageCount.spec" \
  || fail "PyInstaller failed."

[ -d "$OUT" ] || fail "PyInstaller reported success but $OUT does not exist."

step "Done"
say "$OUT"
say ""
say "$(du -sh "$OUT" | cut -f1) -- unsigned and not notarized. Gatekeeper will"
say "block it on another Mac unless it is signed, or the recipient right-clicks"
say "and chooses Open (DECISIONS.md 15.6)."
