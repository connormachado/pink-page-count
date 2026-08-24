"""The 4am day boundary (DECISIONS.md 2.3)."""

from __future__ import annotations

from datetime import date

from app.daytime import day_key, parse_iso

from .conftest import local


def test_one_am_tuesday_counts_as_monday():
    # 2026-08-24 is a Monday, so 1am on the 25th is a Tuesday.
    assert day_key(local("2026-08-25 01:00")) == date(2026, 8, 24)


def test_three_fifty_nine_am_belongs_to_the_previous_day():
    assert day_key(local("2026-08-25 03:59")) == date(2026, 8, 24)


def test_four_am_starts_the_new_day():
    assert day_key(local("2026-08-25 04:00")) == date(2026, 8, 25)


def test_midday_belongs_to_its_own_day():
    assert day_key(local("2026-08-25 12:00")) == date(2026, 8, 25)


def test_late_evening_belongs_to_its_own_day():
    assert day_key(local("2026-08-25 23:59")) == date(2026, 8, 25)


def test_boundary_uses_local_time_not_utc():
    """01:00 local is 05:00 UTC; a UTC-based boundary would get this wrong."""
    assert day_key(parse_iso("2026-08-25T01:00:00-04:00")) == date(2026, 8, 24)
    assert day_key(parse_iso("2026-08-25T05:00:00+00:00")) == date(2026, 8, 24)
