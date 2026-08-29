"""What the frozen app does at the moment the icon is double-clicked.

See DECISIONS.md 16.1. Three outcomes, and the whole point of this file is that
the third one -- a stranger on the port -- is no longer silence:

    nothing listening  -> start the server
    ours listening     -> open the browser at it, exit 0
    something else     -> say so on screen, exit 3

None of these tests start a server. They pin the *decision*, and in particular
that the two non-starting branches take it before a single data file is opened.
"""

from __future__ import annotations

import subprocess

import pytest

from app import launcher, notify
from app.lifecycle import Probe


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


def test_nothing_listening_falls_through_to_a_real_launch(monkeypatch, opened, alerts):
    """The ordinary case must not be swallowed by the two new branches.

    Stores ARE opened here -- that is the difference -- so this stops at the
    first thing after them rather than starting a server.
    """
    _probe_returns(monkeypatch, Probe.NOTHING)

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
