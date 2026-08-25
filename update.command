#!/bin/bash
#
# Pulls new code for the reading tracker. Double-click this file.
#
# Never starts or stops the server -- run.command is the only thing that runs
# uvicorn, and it never pulls, so a bad commit here can't break a launch that's
# already working.

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

say()  { printf '%s\n' "$*"; }
fail() { printf '\n%s\n\n' "$*" >&2; say "Press return to close this window."; read -r _ || true; exit 1; }
finish() { say ""; say "Press return to close this window."; read -r _ || true; exit 0; }

# --- Refuse to touch a tree with anything uncommitted ---------------------------
if [ -n "$(git status --porcelain)" ]; then
  fail "There are uncommitted changes in:
  $APP_DIR

Not pulling, so nothing gets overwritten or lost. If these changes are not
meant to be here, resolve or discard them yourself, then run this again."
fi

OLD_HEAD="$(git rev-parse HEAD)"

say "Checking for updates..."
if ! git pull --ff-only; then
  fail "Could not update. This usually means your local history and the
remote have diverged, or there is no network connection right now.

Nothing was changed."
fi

NEW_HEAD="$(git rev-parse HEAD)"

if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
  say "Already up to date."
  finish
fi

say ""
say "Updated. Here's what changed:"
git log --oneline "$OLD_HEAD..HEAD"

# --- Reinstall Python dependencies if requirements.txt changed ------------------
if git diff --name-only "$OLD_HEAD" "$NEW_HEAD" | grep -qx "requirements.txt"; then
  VENV="$APP_DIR/.venv"
  if [ -x "$VENV/bin/pip" ]; then
    say ""
    say "requirements.txt changed -- reinstalling dependencies..."
    "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
  else
    say ""
    say "requirements.txt changed, but there is no .venv yet -- run run.command
first to create it, then run this again."
  fi
fi

finish
