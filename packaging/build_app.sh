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
#
# The deployment target is DECLARED here and CHECKED at the end (15.8). It is
# never inherited from whatever the build machine happens to be running, which
# is how a bundle nobody below macOS 26 could launch shipped once already.

set -euo pipefail

# --- The deployment target: declared, not inherited (DECISIONS.md 15.8) ----------
#
# macOS 11.0 Big Sur -- every Apple Silicon Mac ever sold shipped with it or
# later, so this covers every possible recipient.
#
# MACOSX_DEPLOYMENT_TARGET is exported so that anything which *compiles* during
# this build declares 11.0 rather than picking up the host's version. It does
# not, and cannot, rewrite a prebuilt binary: the Homebrew OpenSSL bottles that
# caused REVIEW.md BLOCKER 1 were already stamped `minos 26.0` on disk. What
# actually keeps them out is step 3 (a build interpreter whose own binaries
# target 11.0) and step 5 (the check that fails the build if one gets in
# anyway). The export is here so the value is stated in one place and the two
# real mechanisms both read it from here.
DEPLOYMENT_TARGET="11.0"
export MACOSX_DEPLOYMENT_TARGET="$DEPLOYMENT_TARGET"

# --- The target architecture: also declared, for the same reason (15.8) ----------
#
# The spec sets `target_arch=None`, and PyInstaller resolves that to
# `platform.machine()` OF THE BUILD PROCESS (building/api.py:464). With a
# universal2 build interpreter that is no longer a constant: macOS gives a
# universal2 binary the architecture its PARENT is running as, so the build
# takes its target from whatever launched it.
#
# That is not hypothetical on this machine. `/usr/local/bin/make` is an x86_64
# binary running under Rosetta and it shadows /usr/bin/make on PATH, so
# `./packaging/build_app.sh` freezes arm64 while `make build` -- the documented
# command -- freezes x86_64, from the same spec and the same virtualenv. pip is
# affected first and worse: run under Rosetta it resolves x86_64 wheels, so the
# environment the bundle is assembled from is Intel before PyInstaller ever
# looks at it.
#
# Under the old Homebrew interpreter this could not happen -- it was arm64-only,
# so there was no other slice to fall into. Adopting a universal2 Python is what
# opened it, which makes pinning it part of this change and not a separate one.
#
# `arch` is applied to every use of the build interpreter below, and the result
# is asserted before freezing rather than assumed.
#
# `uname -m` cannot be used to find the host architecture here, which is the
# part of this that is genuinely easy to get wrong: under Rosetta it reports
# x86_64 too, so it agrees with the wrong answer and an assertion built on it
# passes while the bundle is frozen for Intel. `hw.optional.arm64` is a property
# of the machine rather than of the calling process and reads 1 either way.
# Rosetta only ever translates arm64 -> x86_64, so this is the whole test; an
# Intel Mac has no such sysctl and falls through to `uname -m`, which is honest
# there because nothing is being translated.
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = "1" ]; then
  HOST_ARCH="arm64"
else
  HOST_ARCH="$(uname -m)"
fi

# Run the given command as HOST_ARCH regardless of what this script was launched
# from.
as_host_arch() { arch -"$HOST_ARCH" "$@"; }

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

# The BUILD virtualenv, which is deliberately not the dev one (.venv). See 15.8:
# whatever interpreter freezes the bundle is the interpreter the bundle ships,
# down to its bundled OpenSSL, so it cannot be "whatever python3 is on PATH".
# .venv stays Homebrew's and stays the one that runs pytest and run.command.
VENV="$REPO/.venv-build"
PY="$VENV/bin/python"

CHECK="$PACKAGING/check_deployment_target.py"
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

# --- 3. The build virtualenv, and the interpreter underneath it ------------------
#
# PyInstaller does not compile a Python -- it COPIES the one it is running
# under, together with every dylib that Python links against, into the bundle.
# So the build interpreter's own deployment target IS the bundle's deployment
# target, and picking it up from `python3` on PATH is what shipped a bundle that
# only ran on macOS 26 (REVIEW.md BLOCKER 1). Homebrew builds its bottles for
# the machine that pours them; this machine is on macOS 26, so its openssl@3
# bottle is stamped `minos 26.0` and its python@3.14 bottle `minos 15.0`.
#
# python.org's universal2 installer build is compiled against an old SDK on
# purpose and carries its OWN OpenSSL inside the framework, at 11.0. That is the
# interpreter this build wants, and it is required rather than preferred: there
# is no way to relink a prebuilt dylib to an older target, so a wrong
# interpreter here cannot be corrected later in the build.
#
# Override with PAGECOUNT_BUILD_PYTHON if the framework lives somewhere else.
# Whatever is chosen still has to pass the same check the bundle does, below --
# the path is a search hint, never the evidence.
step "Build environment"

# Prints a path, or nothing. It always exits 0: `set -e` kills the script on a
# bare assignment whose command substitution failed, and losing the explanatory
# `fail` below to a silent exit is exactly AUDIT.md S1's shape.
find_build_python() {
  local v p
  if [ -n "${PAGECOUNT_BUILD_PYTHON:-}" ]; then
    printf '%s\n' "$PAGECOUNT_BUILD_PYTHON"
    return 0
  fi
  # Newest first. 3.11 is the floor DECISIONS.md 6 sets for app/.
  for v in 3.14 3.13 3.12 3.11; do
    p="/Library/Frameworks/Python.framework/Versions/$v/bin/python$v"
    if [ -x "$p" ]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 0
}

BASE_PY="$(find_build_python)"
{ [ -n "$BASE_PY" ] && [ -x "$BASE_PY" ]; } || fail \
"No python.org framework Python found under /Library/Frameworks/Python.framework.

The build interpreter is copied wholesale into the bundle, so it decides which
macOS versions the app can run on (DECISIONS.md 15.8). Homebrew's Python is
built for THIS machine's macOS and produces a bundle only this machine can
launch.

Install the universal2 build from https://www.python.org/downloads/macos/ and
run this script again, or point PAGECOUNT_BUILD_PYTHON at one."

BASE_PREFIX="$(as_host_arch "$BASE_PY" -c 'import sys; print(sys.base_prefix)')" \
  || fail "$BASE_PY is not a working Python, or cannot run as $HOST_ARCH."

# The interpreter has to clear the bar before it is worth spending a build on
# it. Same script, same threshold as the check over the finished bundle -- if
# the framework's own Python, its bundled libssl/libcrypto or any of its
# extension modules are stamped too new, everything copied out of them will be.
say "Candidate build interpreter: $BASE_PY"
as_host_arch "$BASE_PY" "$CHECK" --max "$DEPLOYMENT_TARGET" "$BASE_PREFIX" >/dev/null || fail \
"The build interpreter at

  $BASE_PY

is itself built for a macOS newer than $DEPLOYMENT_TARGET (listing above), so every
binary copied out of it would be too. Point PAGECOUNT_BUILD_PYTHON at a
python.org universal2 install instead."

# A virtualenv remembers the interpreter it was made from. Recreate it whenever
# that is not the one we just vetted, so a .venv-build left over from a
# different Python cannot quietly go on being used.
if [ -x "$PY" ] && [ "$(as_host_arch "$PY" -c 'import sys; print(sys.base_prefix)' 2>/dev/null)" != "$BASE_PREFIX" ]; then
  say "$VENV was built from a different Python; recreating it."
  rm -rf "$VENV"
fi

if [ ! -x "$PY" ]; then
  say "Creating $VENV ..."
  as_host_arch "$BASE_PY" -m venv "$VENV" || fail "Could not create the build virtualenv."
fi

# `as_host_arch` matters here as much as at the freeze: pip run under Rosetta
# resolves x86_64 wheels, and a pydantic_core built for the wrong architecture
# is discovered as a build failure at best and shipped at worst.
if ! as_host_arch "$PY" -c 'import PyInstaller' >/dev/null 2>&1; then
  say "Installing build dependencies (needs the network, once)..."
  as_host_arch "$PY" -m pip install -r "$REPO/requirements-build.txt" \
    || fail "Could not install build dependencies from requirements-build.txt."
fi

# Assert rather than assume. This is the value the spec's `target_arch=None`
# actually resolves to (PyInstaller building/api.py:464), so it decides the
# architecture of the shipped bundle.
BUILD_ARCH="$(as_host_arch "$PY" -c 'import platform; print(platform.machine())')" \
  || fail "The build virtualenv's Python does not run."
[ "$BUILD_ARCH" = "$HOST_ARCH" ] || fail \
"the build interpreter reports architecture '$BUILD_ARCH' but this Mac is '$HOST_ARCH'.

The spec leaves target_arch=None, which PyInstaller resolves to exactly this
value, so the bundle would be frozen for the wrong architecture. See
DECISIONS.md 15.8."

say "PyInstaller $(as_host_arch "$PY" -c 'import PyInstaller; print(PyInstaller.__version__)')"
say "Python      $(as_host_arch "$PY" -c 'import platform, sys; print(platform.python_version(), "--", sys.base_prefix)')"
say "Target      macOS $MACOSX_DEPLOYMENT_TARGET, $BUILD_ARCH"

# --- 4. Freeze -------------------------------------------------------------------
step "Building $APP_NAME.app"

rm -rf "$PACKAGING/dist" "$PACKAGING/build"

as_host_arch "$PY" -m PyInstaller \
  --noconfirm \
  --clean \
  --log-level WARN \
  --distpath "$PACKAGING/dist" \
  --workpath "$PACKAGING/build" \
  "$PACKAGING/PinkPageCount.spec" \
  || fail "PyInstaller failed."

[ -d "$OUT" ] || fail "PyInstaller reported success but $OUT does not exist."

# --- 5. The deployment target check: fail, never warn ----------------------------
#
# This is the gate REVIEW.md BLOCKER 1 got through. Two dylibs stamped
# `minos 26.0` went out in a bundle that dyld refuses to load anywhere below
# macOS 26, and because the refusal happens at `import ssl` -- upstream of
# app/launcher.py and of every message app/notify.py can put on screen -- the
# recipient sees one Dock bounce and nothing else. There is no log to ask them
# for.
#
# It is a `fail`, not a warning, on purpose. A warning at the end of a build
# whose last line is the path to a finished .app is a warning that gets shipped:
# nothing downstream of here (make install, make zip, AirDrop) reads it, and
# the artifact is already sitting there looking complete.
step "Deployment target"

as_host_arch "$PY" "$CHECK" --max "$DEPLOYMENT_TARGET" --expect-arch "$BUILD_ARCH" \
  --relative-to "$OUT" "$OUT" || fail \
"the bundle carries a binary built for a newer macOS than $DEPLOYMENT_TARGET, or for the
wrong architecture (listed above).

Nothing later in this build can fix it -- a prebuilt dylib's minimum cannot be
relinked downward. The binary came out of the build interpreter or out of a
wheel; see DECISIONS.md 15.8."

say "Per-binary listing: $CHECK --max $DEPLOYMENT_TARGET --report '$OUT'"

step "Done"
say "$OUT"
say ""
say "$(du -sh "$OUT" | cut -f1) -- unsigned and not notarized. Gatekeeper will"
say "block it on another Mac unless it is signed, or the recipient right-clicks"
say "and chooses Open (DECISIONS.md 15.6)."
