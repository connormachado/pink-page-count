"""Second-launch probe and heartbeat watchdog. See DECISIONS.md section 16.

Two halves of one question -- *when does this app exist?* -- kept in one module
because they are the same story from opposite ends:

* :func:`probe` answers "is an instance of me already running on this port?",
  which is what makes a second double-click open the browser instead of
  bouncing the icon once and vanishing (DECISIONS.md 15.5's last bullet).
* :class:`HeartbeatWatchdog` answers "is anyone still looking at me?", which is
  what makes closing the browser tab quit the app -- the only quit affordance a
  process with no Dock icon and no menu bar can have (16.2).

Nothing here touches DATA_ROOT, imports a store, or knows a data path exists.
That is deliberate: lifecycle is about the process, and the reading log is not
allowed to depend on it.
"""

from __future__ import annotations

import enum
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

# What GET /api/ping returns under "app". Matches the bundle identifier (15) so
# there is one name for this program, not two. A different app that happens to
# hold port 8420 will not answer with this string, which is the whole point: the
# probe identifies *us*, it does not merely detect *a* web server.
APP_IDENTITY = "com.connormachado.pinkpagecount"

# DECISIONS.md 16.2. The front end beats every 30s; the server gives up after
# five minutes of silence. Ten missed beats before anything happens, and Chrome's
# most aggressive background-tab throttling still only slows a hidden tab's
# timers to once a minute -- five beats inside the window. The cost of being
# wrong is asymmetric and this is the cheap side of it: quitting too eagerly
# takes away an app someone was still using, while quitting too late leaves an
# idle process nobody can see.
HEARTBEAT_TIMEOUT_SECONDS = 300.0

# How often the watchdog thread wakes to look at the clock. Small enough that
# shutdown follows the deadline closely, large enough to be free.
WATCHDOG_POLL_SECONDS = 5.0

# The probe's budget. Loopback either answers immediately or is not there.
PROBE_TIMEOUT_SECONDS = 1.0


def ping_payload() -> dict[str, object]:
    """The body of GET /api/ping: who we are, and which process is answering.

    Reads no file and no store. It exists so a *second* launch can recognise a
    *first* one before either of them has any reason to open the reading log.
    """
    return {"app": APP_IDENTITY, "pid": os.getpid()}


class Probe(enum.Enum):
    """What was found on the port."""

    NOTHING = "nothing"
    """Nothing is listening. Start normally."""

    OURS = "ours"
    """A Pink Page Count server is already running. Open the browser at it."""

    FOREIGN = "foreign"
    """Something is holding the port, and it is not us."""


def probe(
    host: str,
    port: int,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> tuple[Probe, dict | None]:
    """Ask what, if anything, owns `host:port`.

    Returns the verdict and, for :attr:`Probe.OURS`, the ping body -- so the pid
    of the instance already running is available to whoever wants to report it.

    Two steps rather than one, because "connection refused" and "answered with
    something unexpected" are genuinely different answers, and collapsing them
    into a single exception clause is how the FOREIGN branch becomes unreachable
    by accident:

    1. a bare TCP connect -- refused means nothing is there, full stop;
    2. GET /api/ping -- our identifier means ours, anything else means foreign.

    A port that accepts a connection and then does not answer HTTP inside the
    timeout is FOREIGN: something has it, and we cannot have it. There is no
    retry and no second port -- see DECISIONS.md 16.1 on why this deliberately
    does not go looking for somewhere else to listen.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return (Probe.NOTHING, None)

    url = f"http://{host}:{port}/api/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return (Probe.FOREIGN, None)
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError):
        # Anything at all that is not a clean 200 carrying our own JSON. A 404
        # lands here too (urllib raises HTTPError, a URLError subclass), which is
        # the answer any other web server on this port would give.
        return (Probe.FOREIGN, None)

    if isinstance(body, dict) and body.get("app") == APP_IDENTITY:
        return (Probe.OURS, body)
    return (Probe.FOREIGN, None)


class HeartbeatWatchdog:
    """Exits the app when the browser stops saying it is still there.

    The front end POSTs /api/heartbeat on an interval for as long as the page is
    open; :meth:`beat` is what that route calls. When no beat has arrived for
    `timeout_seconds`, the callback handed to :meth:`start` runs exactly once.

    **Construction counts as the first beat, and that is the startup grace
    period.** The server must not exit before a browser has had a chance to
    launch, load the page, and beat once -- so the clock starts at startup rather
    than at negative infinity, and that opening grace is the same five minutes as
    every later gap. One rule, one constant, one thing to reason about: *no
    heartbeat in the last five minutes*, where starting up counts as a heartbeat.

    `clock` is injectable so the tests can move time without spending it.
    """

    def __init__(
        self,
        timeout_seconds: float = HEARTBEAT_TIMEOUT_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        poll_seconds: float = WATCHDOG_POLL_SECONDS,
    ) -> None:
        self._timeout = timeout_seconds
        self._clock = clock
        self._poll = poll_seconds
        self._lock = threading.Lock()
        self._last_beat = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self) -> None:
        """Record a heartbeat.

        Called from a request handler, so it is cheap and it cannot raise: a
        failure here would turn a keepalive into a 500, and the front end would
        have no idea the thing it was keeping alive had stopped listening.
        """
        with self._lock:
            self._last_beat = self._clock()

    def seconds_since_beat(self) -> float:
        with self._lock:
            return self._clock() - self._last_beat

    def expired(self) -> bool:
        return self.seconds_since_beat() >= self._timeout

    def start(self, on_expiry: Callable[[], None]) -> None:
        """Run the watch on a daemon thread.

        A daemon, because this thread must never be the reason the process stays
        alive. It only ever *reads* a clock and calls `on_expiry` once -- it does
        not kill anything, does not touch a socket, and cannot interrupt a write
        in progress. See DECISIONS.md 16.2 on why shutdown is a flag, not a signal.
        """
        if self._thread is not None:
            raise RuntimeError("watchdog already started")

        def _watch() -> None:
            while not self._stop.wait(self._poll):
                if self.expired():
                    on_expiry()
                    return

        self._thread = threading.Thread(
            target=_watch, name="heartbeat-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop watching. Idempotent, and safe to call from anywhere."""
        self._stop.set()
