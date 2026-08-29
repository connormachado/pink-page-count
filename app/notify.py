"""Saying something to a person who has no terminal. See DECISIONS.md 16.1.

A Finder-launched `.app` has nothing attached to fd 1 or fd 2. Everything this
app prints on the way to a failed launch -- the corrupt-file banner of 3.4, the
port-taken message of 16.1 -- goes to /dev/null, and the recipient sees an icon
bounce once and stop. That is AUDIT.md B3, and it is why "it exited with a clear
message" and "the user saw a clear message" are not the same claim.

`/usr/bin/osascript` is the only way to show a person something without becoming
a GUI application. It ships with macOS: **nothing here is a new runtime
dependency.** No package is added to requirements.txt, no module is added to the
freeze, and if the binary is missing the call is a no-op rather than an error.

This module is deliberately separate from `app/launcher.py`, which
`tests/test_packaging.py` forbids from importing `subprocess` at all -- a frozen
app that spawns `sys.executable` re-executes its own bundle, and the cheapest way
to never do that by accident is for launch logic to have no subprocess in reach.
The one command line built here is a constant with the text passed as `argv`.
"""

from __future__ import annotations

import subprocess

OSASCRIPT = "/usr/bin/osascript"

# The dialog dismisses itself rather than waiting forever for someone who may
# have walked away. Long enough to read four short lines many times over.
GIVE_UP_SECONDS = 120


def alert(title: str, message: str) -> None:
    """Put a message on screen. Best effort, and never raises.

    The text is passed as `argv` and read back inside the script with
    `item 1 of argv`, never interpolated into the script source, so a message
    containing a quote or a backslash cannot become AppleScript.

    Every caller is already on a path that is failing. If the dialog cannot be
    shown -- no osascript, no window server, a hung process -- that failure is
    not worth making the first one worse, so it is swallowed.
    """
    script = (
        "display dialog (item 1 of argv) with title (item 2 of argv) "
        'buttons {"OK"} default button "OK" with icon caution '
        f"giving up after {GIVE_UP_SECONDS}"
    )
    try:
        subprocess.run(
            [OSASCRIPT, "-e", "on run argv", "-e", script, "-e", "end run", message, title],
            check=False,
            capture_output=True,
            timeout=GIVE_UP_SECONDS + 15,
        )
    except (OSError, subprocess.SubprocessError):
        pass
