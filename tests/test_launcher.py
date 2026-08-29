"""What the frozen app does at the moment the icon is double-clicked.

See DECISIONS.md 16.1 and 16.5. The process LaunchServices launches decides one
of three things and then leaves:

    nothing listening  -> spawn a detached server, exit 0
    ours listening     -> open the browser at it, exit 0
    something else     -> say so on screen, exit 3

**Leaving is load-bearing** (16.5): a `.app` whose launched process stays alive
is an app LaunchServices calls *running*, and the next double-click is routed to
it as a reopen AppleEvent no process without an AppKit event loop can receive --
so no second process is created and none of the three branches above ever runs.
That is what `test_nothing_listening_*` pins.

None of these tests start a server or spawn a process. They pin the *decision*,
and in particular that all three launched-process branches take it before a
single data file is opened -- serving, and the data files that come with it,
belongs to the child.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app import launcher, notify
from app.lifecycle import Probe


@pytest.fixture(autouse=True)
def not_the_server(monkeypatch):
    """No test in this file is the detached child unless it says so.

    The marker is an ordinary environment variable, so a developer who exported
    it to run the frozen server in the foreground (16.5) would otherwise send
    every launched-process test down the serve branch.
    """
    monkeypatch.delenv(launcher.SERVE_ENV, raising=False)


@pytest.fixture
def no_stores(monkeypatch):
    """Fail loudly if the launcher opens a data file on a path that must not.

    A second launch has no business reading the reading log -- and must not be
    able to halt on a corrupt file that the instance already running is happily
    serving (DECISIONS.md 16.1).
    """

    def forbidden(path):
        raise AssertionError(f"the launcher opened {path} before deciding to launch")

    monkeypatch.setattr(launcher, "load_storage_or_exit", forbidden)
    monkeypatch.setattr(launcher, "load_class_store_or_exit", forbidden)
    monkeypatch.setattr(launcher, "load_settings_store_or_exit", forbidden)


@pytest.fixture
def no_server(monkeypatch):
    """Fail loudly if a second uvicorn is constructed."""

    def forbidden(*args, **kwargs):
        raise AssertionError("the launcher started a second server")

    monkeypatch.setattr("uvicorn.Server", forbidden)
    monkeypatch.setattr("uvicorn.Config", forbidden)


@pytest.fixture
def spawned(monkeypatch):
    """Record the spawn without spawning. Returns the (argv, env) list.

    Unpatched this would really start a second Pink Page Count, so every test
    that can reach the NOTHING branch takes this fixture.
    """
    calls: list[tuple[list[str], dict]] = []

    def fake_posix_spawn(path, argv, env, **kwargs):
        calls.append((list(argv), dict(env), dict(kwargs)))
        return 424242

    monkeypatch.setattr(launcher.os, "posix_spawn", fake_posix_spawn)
    return calls


@pytest.fixture
def opened(monkeypatch):
    """Record what the launcher asked the browser to open."""
    urls: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", urls.append)
    return urls


@pytest.fixture
def alerts(monkeypatch):
    """Record what the launcher put on screen, without putting it on screen."""
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher, "alert", lambda title, message: shown.append((title, message))
    )
    return shown


def _probe_returns(monkeypatch, verdict, body=None):
    monkeypatch.setattr(
        launcher, "probe", lambda host, port, **kwargs: (verdict, body)
    )


def test_second_launch_opens_the_browser_and_starts_nothing(
    monkeypatch, no_stores, no_server, opened, alerts
):
    """The fix: a second double-click while it is running opens the app.

    It used to do nothing visible at all -- uvicorn would fail to bind, log to a
    stderr nobody is attached to, and vanish (DECISIONS.md 15.5).
    """
    _probe_returns(monkeypatch, Probe.OURS, {"app": "x", "pid": 4242})

    launcher.main()  # returns; exit 0

    assert opened == [f"http://127.0.0.1:{launcher.config.port()}/"]
    assert alerts == [], "a working second launch is not an event worth a dialog"


def test_a_stranger_on_the_port_exits_loudly(
    monkeypatch, no_stores, no_server, opened, alerts
):
    """Not our port, and not silence. Exit 3, the same code uvicorn used to."""
    _probe_returns(monkeypatch, Probe.FOREIGN)

    with pytest.raises(SystemExit) as exit_info:
        launcher.main()

    assert exit_info.value.code == launcher.EXIT_PORT_TAKEN == 3
    assert len(alerts) == 1, "the recipient was told nothing"
    assert opened == [], "there was nothing to open"

    title, message = alerts[0]
    assert title == "Pink Page Count"
    assert str(launcher.config.port()) in message


def test_the_port_taken_message_does_not_scold(monkeypatch, no_stores, no_server, alerts):
    """DECISIONS.md 8. It is about a port, not about her.

    The message names no number she is responsible for, blames nobody, and says
    the log is untouched -- which is true: this path never opened it.
    """
    _probe_returns(monkeypatch, Probe.FOREIGN)
    with pytest.raises(SystemExit):
        launcher.main()

    message = alerts[0][1].lower()
    assert "nothing you've logged has been touched" in message
    for scold in ("failed", "error", "you should", "you must", "invalid", "wrong"):
        assert scold not in message


def test_nothing_listening_spawns_a_detached_server_and_returns(
    monkeypatch, no_stores, no_server, spawned, opened, alerts
):
    """The ordinary cold start: hand the server to a child, and get out.

    DECISIONS.md 16.5. The launched process must not become the server and must
    not linger, because LaunchServices treats a live process as "this app is
    already running" and silently turns the next double-click into a reopen
    AppleEvent instead of a launch. `no_stores` and `no_server` are the
    assertions that matter here: opening the reading log and binding the socket
    are now the child's job, not this process's.
    """
    _probe_returns(monkeypatch, Probe.NOTHING)

    launcher.main()  # returns promptly; exit 0

    assert len(spawned) == 1, "exactly one server, spawned exactly once"
    assert alerts == [], "an ordinary cold start is not an event worth a dialog"
    assert opened == [], "the child opens the browser once it is actually serving"


def test_the_spawned_child_is_this_same_program_told_to_serve(
    monkeypatch, no_stores, no_server, spawned, opened, alerts
):
    """The child is us, re-run with the marker -- and detached from this session."""
    _probe_returns(monkeypatch, Probe.NOTHING)

    launcher.main()

    argv, env, kwargs = spawned[0]
    assert argv[0] == sys.executable, "the child is this program, not a second one"
    assert argv == launcher._server_argv()
    assert env[launcher.SERVE_ENV] == "1", "without the marker the child would re-probe"
    assert kwargs.get("setsid") is True, (
        "the child must not be in the process group of a parent that is about to exit"
    )


def test_the_serve_marker_makes_this_process_the_server(monkeypatch, alerts):
    """The other side of the same coin: with the marker set, serve -- never probe.

    The child must not probe the port it is about to bind, and it *is* the
    process that validates all three data files (DECISIONS.md 3.4 still halts a
    launch that is going to serve).
    """

    def no_probing(*args, **kwargs):
        raise AssertionError("the server probed the port it was about to bind")

    monkeypatch.setattr(launcher, "probe", no_probing)
    monkeypatch.setenv(launcher.SERVE_ENV, "1")

    opened_paths: list[object] = []
    monkeypatch.setattr(launcher, "load_storage_or_exit", opened_paths.append)
    monkeypatch.setattr(launcher, "load_class_store_or_exit", opened_paths.append)
    monkeypatch.setattr(launcher, "load_settings_store_or_exit", opened_paths.append)

    class Stop(Exception):
        pass

    def stop_here(*args, **kwargs):
        raise Stop

    monkeypatch.setattr("uvicorn.Config", stop_here)

    with pytest.raises(Stop):
        launcher.main()

    assert len(opened_paths) == 3, "a real launch validates all three data files first"
    assert alerts == []


def test_a_spawn_that_fails_still_gets_the_app_running(
    monkeypatch, no_server, spawned, alerts
):
    """A tracker that starts beats one that relaunches cleanly.

    If the spawn itself fails there is nothing useful to say to her, so the
    launched process serves in place: the app works and only the *second*
    double-click is back to being broken.
    """
    _probe_returns(monkeypatch, Probe.NOTHING)

    def boom(*args, **kwargs):
        raise OSError("cannot spawn here")

    monkeypatch.setattr(launcher.os, "posix_spawn", boom)

    served: list[bool] = []
    monkeypatch.setattr(launcher, "serve", lambda *a, **k: served.append(True))

    launcher.main()

    assert served == [True], "the fallback is to serve, not to give up"
    assert alerts == [], "§8: nothing here is her problem to solve"


# --------------------------------------------------------------------------- #
# The dialog itself (app/notify.py)
# --------------------------------------------------------------------------- #


def test_alert_only_ever_runs_osascript(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append(argv))

    notify.alert("Title", "Message")

    assert len(calls) == 1
    assert calls[0][0] == "/usr/bin/osascript" == notify.OSASCRIPT


def test_alert_passes_text_as_argv_never_as_script(monkeypatch):
    """A message with a quote in it must not be able to become AppleScript."""
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append(argv))

    hostile = 'it\'s "quoted" \\ and buttons {"Delete everything"}'
    notify.alert("Pink Page Count", hostile)

    argv = calls[0]
    assert argv[-2] == hostile, "the text is an argument, verbatim"
    script_parts = [part for part in argv if part.startswith("display dialog")]
    assert len(script_parts) == 1
    assert "quoted" not in script_parts[0], "the message was interpolated into the script"
    assert "item 1 of argv" in script_parts[0]


def test_alert_never_raises(monkeypatch):
    """It is called on a path that is already failing. It cannot make it worse."""

    def boom(*args, **kwargs):
        raise OSError("no osascript on this machine")

    monkeypatch.setattr(subprocess, "run", boom)
    notify.alert("Pink Page Count", "Message")  # no exception


def test_alert_gives_up_rather_than_waiting_forever(monkeypatch):
    """Nobody may be at the keyboard. The dialog dismisses itself."""
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: calls.append(argv))

    notify.alert("Pink Page Count", "Message")

    script = next(part for part in calls[0] if part.startswith("display dialog"))
    assert f"giving up after {notify.GIVE_UP_SECONDS}" in script
