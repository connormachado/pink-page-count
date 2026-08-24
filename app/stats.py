"""Stats over the entry log. See DECISIONS.md 2.4.

Every day-bucketing decision here goes through daytime.day_key -- there is no second
implementation of the 4am boundary.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from .daytime import day_key, day_key_str, parse_iso
from .models import compute_pages


def _day_keys(entries: Iterable[dict[str, Any]]) -> list[date]:
    return [day_key(parse_iso(entry["read_at"])) for entry in entries]


def current_streak(days_with_entries: set[date], today: date) -> int:
    """Consecutive days with at least one entry, counting backward from today.

    Today not yet having an entry does not break the streak -- the count simply starts
    at yesterday. Two consecutive empty days does break it.
    """
    if not days_with_entries:
        return 0
    if today in days_with_entries:
        cursor = today
    elif (today - timedelta(days=1)) in days_with_entries:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in days_with_entries:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def longest_streak(days_with_entries: set[date]) -> int:
    """The longest consecutive run of days with entries, anywhere in history."""
    if not days_with_entries:
        return 0
    best = 1
    run = 1
    ordered = sorted(days_with_entries)
    for previous, current in zip(ordered, ordered[1:]):
        run = run + 1 if current - previous == timedelta(days=1) else 1
        best = max(best, run)
    return best


def compute_stats(entries: list[dict[str, Any]], now) -> dict[str, Any]:
    """Build the /api/stats payload.

    NOTE (DECISIONS.md 8): `longest_streak_days` is returned here, but Phases 2-4 must
    never render it adjacent to or in comparison with `current_streak_days`. The
    comparison is the reprimand; the number alone is not.
    """
    today = day_key(now)
    keys = _day_keys(entries)
    days_with_entries = set(keys)

    pages_today = sum(
        compute_pages(entry["page_start"], entry["page_end"])
        for entry, key in zip(entries, keys)
        if key == today
    )
    pages_all_time = sum(
        compute_pages(entry["page_start"], entry["page_end"]) for entry in entries
    )

    return {
        "pages_today": pages_today,
        "pages_all_time": pages_all_time,
        "current_streak_days": current_streak(days_with_entries, today),
        "longest_streak_days": longest_streak(days_with_entries),
        "entry_count": len(entries),
        "first_entry_date": day_key_str(min(keys)) if keys else None,
    }
