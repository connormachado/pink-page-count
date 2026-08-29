"""The frozen bundle's entry point. See DECISIONS.md sections 15 and 16.

Probes the port for an instance already running, starts the server *in this
process* if there is none, waits for the port to answer, opens the browser at
it, and returns when the server has stopped -- which now happens on its own,
once the browser tab that was watching it goes away (16.2).

**This module never invokes the uvicorn CLI.** `run.command:107` passes a
literal `--host 127.0.0.1` on the command line, which means that at real launch
time the binding actually enforced there is that literal and not `config.HOST`
(AUDIT.md's binding note calls this out: two independent places, both loopback,
but they are two). A frozen app has no command line for anyone to read, so it
goes through `uvicorn.Config(host=config.HOST)` below and `config.HOST` is the
single authority. There is no argument, no environment variable, and no code
path in this module that can put any other value there.

The app is handed to uvicorn as a *callable*, not as the string
`"app.main:create_default_app"`. uvicorn resolves a string through
`uvicorn.importer.import_from_string`, which is exactly the kind of
import-by-name PyInstaller's static analysis cannot follow (AUDIT.md B6).
Passing the function object means the reference is an ordinary Python import
that the freeze already traced.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from . import config
from .classes import load_class_store_or_exit
from .lifecycle import HeartbeatWatchdog, Probe, probe
from .main import create_default_app
from .notify import alert
from .settings import load_settings_store_or_exit
from .storage import load_storage_or_exit

# How long to wait for the server to answer before giving up on the browser.
# Generous: a cold launch off a slow disk, with Gatekeeper checking the bundle
# on first run, is the slow case this has to cover.
READY_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.1

# Exit code when the port is held by something that is not us. Deliberately the
# same 3 uvicorn already exits with on "address already in use" (DECISIONS.md
# 15.5): the situation is identical, so the code should be too. What changed is
# that it is no longer silent (16.1).
EXIT_PORT_TAKEN = 3


def _emit(line: str) -> None:
    """Write one line straight to file descriptor 1, bypassing `sys.stdout`.

    `sys.stdout` in the frozen bundle is an ordinary `TextIOWrapper` (measured,
    not assumed -- and `sys.stderr` is too, which is why the corrupt-file banner
    of section 3.4 does still render; see 15.5 for what remains wrong about it).
    The problem is buffering, not absence: when stdout is not a terminal it is
    block-buffered, so a `print()` here -- issued once, just before a
    long-running server loop -- would sit unflushed for the entire session and
    appear only at quit, which is precisely when it is no longer useful.

    `os.write` is unbuffered, so the line lands when it is written. It reaches a
    Terminal if someone runs the executable inside the bundle by hand, and
    /dev/null on a Finder launch, harmlessly.
    """
    try:
        os.write(1, (line + "\n").encode("utf-8", "replace"))
    except OSError:
        pass  # fd 1 closed; a diagnostic line is never worth failing a launch over


def _port_taken(port: int) -> None:
    """Something else owns the port. Say so, out loud, and stop.

    DECISIONS.md 16.1: the old behavior here was a Dock bounce and silence, which
    reads as "the app is broken". This does not go looking for another port to
    use -- see 16.1 for why a port-scanning fallback is the wrong fix.

    Nothing about this is a reprimand (§8). It is about a port, it names no
    number she is responsible for, and it says her log is untouched -- which is
    true, because this path has not opened a data file at all.
    """
    message = (
        "Pink Page Count can't start.\n\n"
        f"Another program on this Mac is already using port {port}, "
        "so there's nowhere for the reading tracker to listen.\n\n"
        "Quit that program and open Pink Page Count again.\n\n"
        "Nothing you've logged has been touched."
    )
    _emit_error(message)
    alert("Pink Page Count", message)
    raise SystemExit(EXIT_PORT_TAKEN)


def _emit_error(text: str) -> None:
    """The same message on fd 2, for whoever ran the executable from a Terminal."""
    try:
        os.write(2, (text + "\n").encode("utf-8", "replace"))
    except OSError:
        pass


def _wait_for_ready(health_url: str, server) -> bool:
    """Poll /api/health until it answers, the server gives up, or time runs out.

    Returns True if the browser should be opened. Polling the health route
    rather than merely connecting to the socket means a True here is the server
    actually serving, not just something holding the port.
    """
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        # uvicorn sets should_exit when startup fails -- a port already in use
        # is the case that matters (DECISIONS.md 15.5). Bail immediately rather
        # than polling a port we never got, so a failed launch does not sit
        # there for the full timeout.
        if server.should_exit:
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass  # not up yet; that is the ordinary case on the first few polls
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def main() -> None:
    """Probe, then start the server, open the browser, and block until it stops."""
    import uvicorn

    bind_port = config.port()
    origin = f"http://{config.HOST}:{bind_port}"

    # -- Is one already running? (DECISIONS.md 16.1) ------------------------- #
    #
    # First, before binding and before a single data file is opened. A second
    # double-click must not be able to halt on a corrupt entries.json that the
    # instance already serving has no problem with -- and more simply, a launch
    # that is only going to open a browser tab has no business reading the log.
    verdict, existing = probe(config.HOST, bind_port)
    if verdict is Probe.OURS:
        running_pid = existing.get("pid") if existing else None
        _emit(f"Pink Page Count is already running (pid {running_pid}) -- opening {origin}")
        webbrowser.open(f"{origin}/")
        return  # exit 0. One server, one port, two icons clicked.
    if verdict is Probe.FOREIGN:
        _port_taken(bind_port)  # raises SystemExit

    # Resolve and validate all three data files *before* uvicorn starts, exactly
    # as app.main.main() does, so a corrupt file halts with our banner instead of
    # a traceback buried in server startup logs.
    #
    # AUDIT.md B3 is unfixed and is now reproducible here. The banner itself
    # still renders correctly (verified against a corrupt entries.json inside the
    # bundle: exit code 2, full banner on stderr, file untouched) -- but a
    # Finder-launched .app has no terminal attached to fd 2, so it goes nowhere.
    # This session deliberately does not change that -- see DECISIONS.md 15.5.
    load_storage_or_exit(config.data_file())
    load_class_store_or_exit(config.classes_file())
    load_settings_store_or_exit(config.settings_file())

    # -- Who is still watching? (DECISIONS.md 16.2) -------------------------- #
    #
    # The open page beats; when the beating stops, so does the app. This is the
    # only quit affordance the bundle has -- there is no Dock icon to Cmd-Q and
    # no menu bar to quit from (16.3) -- so the browser tab *is* the window, and
    # closing it closes the app.
    watchdog = HeartbeatWatchdog()

    def _app_factory():
        # A closure, not the string "app.main:create_default_app": uvicorn
        # resolves a string through import_from_string, the import-by-name
        # PyInstaller cannot trace (15.2). This is an ordinary call.
        return create_default_app(watchdog.beat)

    server = uvicorn.Server(
        uvicorn.Config(
            _app_factory,
            factory=True,
            # DECISIONS.md 5: loopback only, never 0.0.0.0. THIS is the line that
            # binds the socket in the frozen build -- config.HOST reaches
            # uvicorn's Config here and nowhere else in the bundle.
            host=config.HOST,
            port=bind_port,
            log_level="warning",
        )
    )

    # For anyone who runs the executable inside the bundle from a Terminal. In a
    # Finder launch it goes to /dev/null, harmlessly. These two lines are how
    # DECISIONS.md 14's "the onedir resolution is not settled" was settled: they
    # are what the frozen bundle actually reports (15.3).
    _emit(f"Pink Page Count -- serving {origin}")
    _emit(f"  frozen:    {getattr(sys, 'frozen', False)}")
    _emit(f"  resources: {config.RESOURCE_ROOT}")
    _emit(f"  quotes:    {config.quotes_file()}")
    _emit(f"  dist:      {config.dist_dir()}")
    _emit(f"  data:      {config.DATA_ROOT}")

    def _open_browser() -> None:
        if _wait_for_ready(f"{origin}/api/health", server):
            webbrowser.open(f"{origin}/")

    # A daemon thread: if the server dies before it ever answers, this must not
    # be the thing that keeps the process alive.
    threading.Thread(target=_open_browser, name="open-browser", daemon=True).start()

    def _no_one_is_watching() -> None:
        """Five minutes without a heartbeat. Leave, quietly.

        `should_exit` is *exactly* the existing clean-shutdown path: it is the
        one field uvicorn's own SIGINT/SIGTERM handler sets, so this takes the
        same graceful route that was already verified to exit 0 and release the
        port with no orphan (15.5). Nothing here signals, cancels, or kills, so
        a write in progress finishes -- uvicorn drains in-flight requests before
        the loop stops, and DECISIONS.md 3.1's write is atomic even if it did
        not. Durability outranks a prompt exit.

        Nothing is said to the user. An app she has finished with going away is
        not an event worth a message (§8).
        """
        _emit("No browser tab has checked in for five minutes -- stopping.")
        server.should_exit = True

    watchdog.start(_no_one_is_watching)

    # Blocks until the server stops. Run from the main thread, which is what lets
    # uvicorn install its own SIGINT/SIGTERM handlers. Both work in the frozen
    # bundle, verified: SIGINT exits 0, SIGTERM exits 143, and in each case the
    # port is released with no orphan left behind.
    #
    # What still does NOT reach this code is the Quit AppleEvent that Cmd-Q and
    # Dock > Quit send -- this process is not a GUI application and never
    # receives it (15.5). It no longer has to: the watchdog above means the
    # browser tab is the quit affordance, and closing it is how the app ends.
    # See DECISIONS.md 16.3 for why that is the design and not a workaround.
    server.run()
    watchdog.stop()


if __name__ == "__main__":
    main()
