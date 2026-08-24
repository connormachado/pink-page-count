#!/bin/bash
#
# Reading Tracker launcher. Double-click this file, or a Desktop alias of it.
#
# Sets up a virtualenv on first run, starts the server on 127.0.0.1, waits for it
# to answer, opens your browser, and shuts the server down cleanly when you quit.

set -euo pipefail

# --- Resolve our own directory, following symlinks so a Desktop alias works ---
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
APP_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$APP_DIR"

PORT="${PAGECOUNT_PORT:-8420}"
URL="http://127.0.0.1:${PORT}/"
VENV="$APP_DIR/.venv"
STAMP="$VENV/.installed"
LOG="$APP_DIR/server.log"

say()  { printf '%s\n' "$*"; }
fail() { printf '\n%s\n\n' "$*" >&2; say "Press return to close this window."; read -r _ || true; exit 1; }

# --- Find Python ---------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  fail "I could not find Python on this Mac.

Python 3.11 or newer is required to run the reading tracker.

The easiest way to install it:
  1. Open the Terminal app.
  2. Type this and press return:  xcode-select --install
  3. Click Install and wait for it to finish.
  4. Double-click this file again.

Or download an installer from https://www.python.org/downloads/"
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  CURRENT="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  fail "Your Python is version ${CURRENT}, but 3.11 or newer is required.

Download a newer version from https://www.python.org/downloads/ and then
double-click this file again."
fi

# --- Set up the virtualenv (first run only) -------------------------------------
if [ ! -d "$VENV" ]; then
  say "First run: setting up. This takes a minute and only happens once."
  "$PYTHON" -m venv "$VENV" || fail "Could not create the Python environment in:
  $VENV

Check that you have permission to write to this folder, then try again."
fi

PY="$VENV/bin/python"
[ -x "$PY" ] || fail "The Python environment in $VENV looks broken.

Delete the .venv folder inside:
  $APP_DIR
and double-click this file again to rebuild it."

# Reinstall only when requirements.txt is newer than the stamp, so later runs are quiet.
if [ ! -f "$STAMP" ] || [ "$APP_DIR/requirements.txt" -nt "$STAMP" ]; then
  say "Installing dependencies..."
  "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$PY" -m pip install --quiet -r "$APP_DIR/requirements.txt" || fail "Could not install the required packages.

If this Mac is offline, connect to the internet for this one-time setup and
double-click this file again. After that the tracker runs fully offline."
  : > "$STAMP"
fi

# --- Start the server -----------------------------------------------------------
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    say ""
    say "Shutting down..."
    kill -TERM "$SERVER_PID" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -0 "$SERVER_PID" 2>/dev/null && kill -KILL "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM HUP

say "Starting the reading tracker on ${URL}"
: > "$LOG"
"$PY" -m uvicorn app.main:create_default_app --factory \
  --host 127.0.0.1 --port "$PORT" --log-level warning >>"$LOG" 2>&1 &
SERVER_PID=$!

# --- Wait for the port to answer, then open the browser --------------------------
READY=""
for _ in $(seq 1 100); do   # up to ~20 seconds
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    break                    # the server exited; fall through to the error below
  fi
  if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    READY=yes
    break
  fi
  sleep 0.2
done

if [ -z "$READY" ]; then
  SERVER_PID=""   # it is already gone, or about to be killed by the trap
  printf '\n' >&2
  say "The server did not start. Here is what it reported:" >&2
  printf '\n' >&2
  cat "$LOG" >&2 || true
  fail "If the message above mentions the data file, open it and fix it -- your
reading log was not changed. If it mentions the port, something else may
already be using port ${PORT}; you can pick another one by running:

  PAGECOUNT_PORT=$((PORT + 1)) '$APP_DIR/run.command'"
fi

open "$URL"

say ""
say "The reading tracker is running."
say "Close this window, or press Control-C, to stop it."
say ""
wait "$SERVER_PID"
