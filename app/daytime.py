"""Timestamps and THE day boundary. See DECISIONS.md sections 2.1-2.4.

A "day" runs 4am -> 4am local time. Reading logged at 1am Tuesday counts as Monday.
`day_key` is the single implementation of that rule; pages_today and both streak
calculations call it and nothing else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# DECISIONS.md 2.3
DAY_START_HOUR = 4


class BadTimestamp(ValueError):
    """A timestamp string that cannot be parsed as ISO 8601."""


def now_local() -> datetime:
    """Current time as an aware datetime in the system's local timezone."""
    return datetime.now().astimezone()


def parse_iso(value: str, *, field: str = "read_at") -> datetime:
    """Parse an ISO 8601 timestamp into an aware datetime.

    A naive timestamp (no UTC offset) is interpreted as local time and given the
    system's local offset -- see DECISIONS.md 2.2. Anything unparseable raises.
    """
    if not isinstance(value, str) or not value.strip():
        raise BadTimestamp(
            f"{field} must be an ISO 8601 timestamp string, got {value!r}"
        )
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise BadTimestamp(
            f"{field} is not a valid ISO 8601 timestamp: {value!r} "
            f"(expected something like 2026-08-24T21:12:00-04:00)"
        ) from None
    if parsed.tzinfo is None:
        # Naive input means local time; attach the local offset.
        parsed = parsed.astimezone()
    return parsed


def format_iso(moment: datetime) -> str:
    """Serialize an aware datetime to ISO 8601 with an explicit UTC offset."""
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.isoformat(timespec="seconds")


def day_key(moment: datetime) -> date:
    """The logical day a moment belongs to, under the 4am-to-4am rule.

    This is the ONLY place the day boundary is implemented. It never reads the
    clock itself, so every caller is deterministically testable.
    """
    # .astimezone() converts an aware moment to local, and assumes local for a naive one.
    local = moment.astimezone()
    return (local - timedelta(hours=DAY_START_HOUR)).date()


def day_key_str(day: date) -> str:
    """A day key as a YYYY-MM-DD string."""
    return day.isoformat()
