"""App lifecycle: the second-launch probe and the heartbeat watchdog.

See DECISIONS.md 16. Two questions, tested from both ends:

* 16.1 -- can a second launch tell whether the first one is already running?
* 16.2 -- does the server go away when the last browser tab does, and only then?

The watchdog's clock is injected rather than slept through, so the timeout tests
cost nothing. The two end-to-end tests at the bottom do run a real uvicorn on a
real port, because "should_exit was set" and "the server actually stopped and
released the port" are different claims and only the second one is the promise.
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app import config
from app.classes import ClassStore
from app.lifecycle import (
    APP_IDENTITY,
    HeartbeatWatchdog,
    Probe,
    ping_payload,
    probe,
)
from app.main import create_app
from app.quotes import QuoteSource
from app.settings import SettingsStore
from app.storage import Storage


class FakeClock:
    """A clock the tests move by hand. Same shape as time.monotonic."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def free_port() -> int:
    """An unused loopback port. Bound, read, and released."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --------------------------------------------------------------------------- #
# The watchdog: grace, timeout, and reset (DECISIONS.md 16.2)
# --------------------------------------------------------------------------- #


def test_grace_period_holds_before_the_first_heartbeat():
    """A browser takes seconds to launch. The server must still be there when it
    arrives -- construction counts as the first beat, and that IS the grace."""
    clock = FakeClock()
    watchdog = HeartbeatWatchdog(300.0, clock=clock)

    assert not watchdog.expired()
    clock.advance(29.0)  # a slow cold launch, Gatekeeper and all
    assert not watchdog.expired()
    clock.advance(270.0)  # 299s in, still inside the window, still no beat
    assert not watchdog.expired()


def test_timeout_expires_when_no_heartbeat_ever_arrives():
    """Nobody opened the page, or the browser never launched. Five minutes and out."""
    clock = FakeClock()
    watchdog = HeartbeatWatchdog(300.0, clock=clock)

    clock.advance(300.0)
    assert watchdog.expired()


def test_a_heartbeat_resets_the_timer():
    """The whole mechanism: a beat buys another full window, over and over."""
    clock = FakeClock()
    watchdog = HeartbeatWatchdog(300.0, clock=clock)

    for _ in range(20):  # ten minutes of an open tab beating every 30s
        clock.advance(30.0)
        assert not watchdog.expired()
        watchdog.beat()

    assert watchdog.seconds_since_beat() == 0.0

    # And then she closes it.
    clock.advance(299.9)
    assert not watchdog.expired()
    clock.advance(0.1)
    assert watchdog.expired()


def test_the_last_beat_wins_not_the_first():
    """Beating early in a window must not shorten the next one."""
    clock = FakeClock()
    watchdog = HeartbeatWatchdog(300.0, clock=clock)

    watchdog.beat()
    clock.advance(1.0)
    watchdog.beat()
    clock.advance(299.0)

    assert not watchdog.expired()


def test_expiry_fires_once_on_the_watch_thread():
    """start() calls back exactly once and then stops looking."""
    fired = threading.Event()
    calls = []

    watchdog = HeartbeatWatchdog(0.01, poll_seconds=0.01)
    watchdog.start(lambda: (calls.append(1), fired.set()))

    assert fired.wait(2.0), "the watchdog never fired"
    time.sleep(0.1)  # long enough for several more polls, had it kept going
    watchdog.stop()
    assert calls == [1]


def test_stopping_the_watchdog_prevents_expiry():
    """A server that stopped for its own reasons must not be called back."""
    calls = []
    watchdog = HeartbeatWatchdog(0.01, poll_seconds=0.01)
    watchdog.stop()
    watchdog.start(calls.append)

    time.sleep(0.1)
    assert calls == []


def test_a_watchdog_cannot_be_started_twice():
    watchdog = HeartbeatWatchdog(60.0, poll_seconds=0.01)
    watchdog.start(lambda: None)
    with pytest.raises(RuntimeError):
        watchdog.start(lambda: None)
    watchdog.stop()


# --------------------------------------------------------------------------- #
# The probe (DECISIONS.md 16.1)
# --------------------------------------------------------------------------- #


def test_probe_finds_nothing_on_a_free_port():
    """Nothing listening: start normally."""
    verdict, body = probe("127.0.0.1", free_port(), timeout=0.5)
    assert verdict is Probe.NOTHING
    assert body is None


def test_probe_finds_ours(running_server):
    """A real Pink Page Count server, recognised by a real GET /api/ping."""
    verdict, body = probe("127.0.0.1", running_server.port, timeout=2.0)

    assert verdict is Probe.OURS
    assert body is not None
    assert body["app"] == APP_IDENTITY
    assert body["pid"] == ping_payload()["pid"]  # this process is serving it


def test_probe_finds_a_stranger(stranger_server):
    """Something is on the port and it is not us: a 404 to /api/ping."""
    verdict, body = probe("127.0.0.1", stranger_server, timeout=2.0)
    assert verdict is Probe.FOREIGN
    assert body is None


def test_probe_finds_a_stranger_that_answers_with_the_wrong_name(impostor_server):
    """200 and valid JSON, but not our identifier. Still not us."""
    verdict, _ = probe("127.0.0.1", impostor_server, timeout=2.0)
    assert verdict is Probe.FOREIGN


def test_probe_finds_a_stranger_that_never_answers(silent_server):
    """Accepts the connection and then says nothing. Something has the port."""
    verdict, _ = probe("127.0.0.1", silent_server, timeout=0.3)
    assert verdict is Probe.FOREIGN


# --------------------------------------------------------------------------- #
# The two routes (DECISIONS.md 16.1, 16.2)
# --------------------------------------------------------------------------- #


def test_ping_says_who_and_which_process(client):
    response = client.get("/api/ping")
    assert response.status_code == 200
    assert response.json() == {"app": APP_IDENTITY, "pid": ping_payload()["pid"]}


def test_ping_touches_nothing_on_disk(client, tmp_path: Path):
    before = sorted(p.name for p in tmp_path.rglob("*"))
    client.get("/api/ping")
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_heartbeat_is_accepted_with_no_body(client):
    response = client.post("/api/heartbeat")
    assert response.status_code == 204
    assert response.content == b""


def test_heartbeat_touches_nothing_on_disk(client, tmp_path: Path):
    before = sorted(p.name for p in tmp_path.rglob("*"))
    client.post("/api/heartbeat")
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_heartbeat_route_reaches_the_watchdog(
    storage: Storage,
    quotes_file: Path,
    class_store: ClassStore,
    settings_store: SettingsStore,
):
    """The wiring the frozen bundle depends on: POST here, timer reset there."""
    from fastapi.testclient import TestClient

    clock = FakeClock()
    watchdog = HeartbeatWatchdog(300.0, clock=clock)
    app = create_app(
        storage,
        QuoteSource(quotes_file),
        classes=class_store,
        settings=settings_store,
        on_heartbeat=watchdog.beat,
    )

    clock.advance(200.0)
    assert watchdog.seconds_since_beat() == 200.0

    with TestClient(app) as client:
        assert client.post("/api/heartbeat").status_code == 204

    assert watchdog.seconds_since_beat() == 0.0
    clock.advance(299.0)
    assert not watchdog.expired()


# --------------------------------------------------------------------------- #
# End to end: a real server, a real port (DECISIONS.md 16.2)
# --------------------------------------------------------------------------- #


def test_a_server_stops_itself_when_the_beats_stop(server_factory):
    """The promise of 16.2: close the tab, and the app goes away on its own.

    Asserted on the port, not on a flag -- what matters is that the process is
    done and the socket is free for the next double-click.
    """
    instance = server_factory(timeout_seconds=0.4, poll_seconds=0.05)

    assert instance.thread.join(15.0) is None
    assert not instance.thread.is_alive(), "the server never stopped"

    verdict, _ = probe("127.0.0.1", instance.port, timeout=0.5)
    assert verdict is Probe.NOTHING, "the port was not released"


def test_a_beating_page_keeps_the_server_alive(server_factory):
    """The other half: as long as the tab is open, nothing happens."""
    instance = server_factory(timeout_seconds=0.6, poll_seconds=0.05)
    origin = f"http://127.0.0.1:{instance.port}"

    import urllib.request

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        request = urllib.request.Request(f"{origin}/api/heartbeat", method="POST")
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 204
        time.sleep(0.15)

    assert instance.thread.is_alive(), "a beating page was hung up on"
    verdict, _ = probe("127.0.0.1", instance.port, timeout=1.0)
    assert verdict is Probe.OURS

    instance.server.should_exit = True
    instance.thread.join(15.0)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class RunningServer:
    def __init__(self, server: uvicorn.Server, thread: threading.Thread, port: int) -> None:
        self.server = server
        self.thread = thread
        self.port = port


@pytest.fixture
def server_factory(
    storage: Storage,
    quotes_file: Path,
    class_store: ClassStore,
    settings_store: SettingsStore,
    tmp_path: Path,
):
    """Start the real app under real uvicorn, wired to a real watchdog.

    Stores are the tmp_path fixtures, so this never resolves a path under the
    real Application Support directory (DECISIONS.md 14, conftest's guard).
    """
    started: list[RunningServer] = []

    def start(*, timeout_seconds: float, poll_seconds: float) -> RunningServer:
        watchdog = HeartbeatWatchdog(
            timeout_seconds, poll_seconds=poll_seconds
        )
        app = create_app(
            storage,
            QuoteSource(quotes_file),
            classes=class_store,
            settings=settings_store,
            dist_dir=tmp_path / "no-dist",
            on_heartbeat=watchdog.beat,
        )
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )

        def run() -> None:
            server.run()
            watchdog.stop()

        thread = threading.Thread(target=run, name=f"test-server-{port}", daemon=True)
        thread.start()

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if probe("127.0.0.1", port, timeout=0.5)[0] is Probe.OURS:
                break
            time.sleep(0.05)
        else:  # pragma: no cover -- a server that never came up fails the test below
            pytest.fail(f"the test server never answered on {port}")

        # Only now, once the port is genuinely serving, does the clock that
        # matters start: the watchdog was constructed before the bind.
        watchdog.start(lambda: setattr(server, "should_exit", True))
        instance = RunningServer(server, thread, port)
        started.append(instance)
        return instance

    yield start

    for instance in started:
        instance.server.should_exit = True
        instance.thread.join(15.0)


@pytest.fixture
def running_server(server_factory) -> RunningServer:
    """One real server that will not time out during the test."""
    return server_factory(timeout_seconds=3600.0, poll_seconds=1.0)


def _serve(handler_class) -> http.server.ThreadingHTTPServer:
    """Run a throwaway HTTP server on a free port, in a daemon thread."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def stranger_server():
    """A web server that is not us: 404 for everything, /api/ping included."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's spelling
            self.send_error(404)

        def log_message(self, *args):
            pass

    server = _serve(Handler)
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture
def impostor_server():
    """Answers /api/ping with well-formed JSON under someone else's name."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"app": "some.other.app", "pid": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = _serve(Handler)
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture
def silent_server():
    """Accepts connections and never says anything. Holds the port all the same."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept_forever() -> None:
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            held.append(connection)  # kept open, deliberately unanswered

    threading.Thread(target=accept_forever, daemon=True).start()
    yield listener.getsockname()[1]

    stop.set()
    listener.close()
    for connection in held:
        connection.close()


def test_config_host_is_the_only_thing_the_probe_asks_about():
    """The probe must look where the server binds, and nowhere else (5, 15.2)."""
    assert config.HOST == "127.0.0.1"
