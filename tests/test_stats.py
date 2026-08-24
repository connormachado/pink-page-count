"""pages_today, streaks across a gap, and first_entry_date (DECISIONS.md 2.4)."""

from __future__ import annotations

from app.daytime import format_iso
from app.stats import compute_stats

from .conftest import local


def entry(day: str, page_start: int = 1, page_end: int = 10, hour: str = "12:00"):
    stamp = format_iso(local(f"{day} {hour}"))
    return {
        "id": f"{day}-{hour}",
        "page_start": page_start,
        "page_end": page_end,
        "read_at": stamp,
        "note": None,
        "created_at": stamp,
        "updated_at": stamp,
    }


NOW = local("2026-08-24 12:00")


def test_empty_log_is_all_zeroes():
    stats = compute_stats([], NOW)
    assert stats == {
        "pages_today": 0,
        "pages_all_time": 0,
        "current_streak_days": 0,
        "longest_streak_days": 0,
        "entry_count": 0,
        "first_entry_date": None,
    }


def test_streak_across_a_gap():
    """Aug 16-20 is a run of 5, Aug 21 is empty, Aug 22-24 is a run of 3 ending today."""
    days = ["2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"]
    days += ["2026-08-22", "2026-08-23", "2026-08-24"]
    stats = compute_stats([entry(day) for day in days], NOW)
    assert stats["current_streak_days"] == 3
    assert stats["longest_streak_days"] == 5
    assert stats["entry_count"] == 8
    assert stats["first_entry_date"] == "2026-08-16"


def test_today_without_an_entry_does_not_break_the_streak():
    days = ["2026-08-21", "2026-08-22", "2026-08-23"]  # nothing yet today
    stats = compute_stats([entry(day) for day in days], NOW)
    assert stats["current_streak_days"] == 3
    assert stats["pages_today"] == 0


def test_two_empty_days_does_break_the_streak():
    days = ["2026-08-20", "2026-08-21", "2026-08-22"]  # nothing on the 23rd or 24th
    stats = compute_stats([entry(day) for day in days], NOW)
    assert stats["current_streak_days"] == 0
    assert stats["longest_streak_days"] == 3


def test_a_single_day_is_a_streak_of_one():
    stats = compute_stats([entry("2026-08-24")], NOW)
    assert stats["current_streak_days"] == 1
    assert stats["longest_streak_days"] == 1


def test_multiple_entries_on_one_day_count_as_one_day():
    same_day = [entry("2026-08-24", hour="09:00"), entry("2026-08-24", hour="21:00")]
    stats = compute_stats(same_day, NOW)
    assert stats["current_streak_days"] == 1
    assert stats["entry_count"] == 2


def test_pages_today_uses_the_4am_boundary():
    """1am on the 25th still counts as the 24th, so it lands in 'today'."""
    now = local("2026-08-25 02:00")  # still the 24th by the 4am rule
    entries = [
        entry("2026-08-24", 43, 71),  # 29 pages, midday on the 24th
        entry("2026-08-25", 1, 10, hour="01:00"),  # 10 pages, 1am -> still the 24th
        entry("2026-08-23", 1, 100),  # 100 pages, a different day
    ]
    stats = compute_stats(entries, now)
    assert stats["pages_today"] == 39
    assert stats["pages_all_time"] == 139


def test_pages_today_is_inclusive(client):
    client.post("/api/entries", json={"page_start": 43, "page_end": 71})
    assert client.get("/api/stats").json()["pages_today"] == 29


def test_stats_endpoint_shape(client):
    client.post("/api/entries", json={"page_start": 1, "page_end": 5})
    stats = client.get("/api/stats").json()
    assert set(stats) == {
        "pages_today",
        "pages_all_time",
        "current_streak_days",
        "longest_streak_days",
        "entry_count",
        "first_entry_date",
    }
    assert stats["entry_count"] == 1
    assert stats["current_streak_days"] == 1
