"""Request/response models and the shared page-range validator.

See DECISIONS.md 1.1 (pages is computed, never stored) and 4.1 (validation placement).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class ValidationProblem(ValueError):
    """A domain validation failure that becomes a 422 with a human readable message."""


def compute_pages(page_start: int, page_end: int) -> int:
    """Page counting is INCLUSIVE: 43-71 is 29 pages, 43-43 is 1 page."""
    return page_end - page_start + 1


def validate_page_range(page_start: int, page_end: int) -> None:
    """The cross-field check, shared by POST and PATCH.

    PATCH validates the *merged* result against the stored entry, so this cannot live
    on a single request model -- see DECISIONS.md 4.1.
    """
    if page_start < 0:
        raise ValidationProblem(f"page_start ({page_start}) must be 0 or greater")
    if page_end < page_start:
        raise ValidationProblem(
            f"page_end ({page_end}) must be greater than or equal to "
            f"page_start ({page_start})"
        )


# DECISIONS.md 12.2: the server has no palette. It checks the shape and stores what
# it is given; web/src/tokens.css is the only place colors are actually chosen.
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

TITLE_MAX = 60


def validate_title(title: Any) -> str:
    """Strip and check a class title, returning the stripped value.

    One helper, used by create, patch, and the on-disk validator, so a title that can
    be stored is exactly a title that could have been posted (DECISIONS.md 4.1).
    """
    if not isinstance(title, str):
        raise ValidationProblem("title must be text")
    clean = title.strip()
    if not clean:
        raise ValidationProblem("A class needs a name.")
    if len(clean) > TITLE_MAX:
        raise ValidationProblem(
            f"A class name can be at most {TITLE_MAX} characters; that one is "
            f"{len(clean)}."
        )
    return clean


def validate_color(color: Any) -> str:
    """Check a hex color, returning it unchanged."""
    if not isinstance(color, str) or not HEX_COLOR.match(color):
        raise ValidationProblem(
            f"color must be a hex value like #RRGGBB, got {color!r}"
        )
    return color


class EntryCreate(BaseModel):
    # extra="ignore": a client that sends `pages` has it silently ignored (DECISIONS 1.1).
    model_config = {"extra": "ignore"}

    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)
    note: str | None = None
    read_at: str | None = None
    class_id: str | None = None


class EntryUpdate(BaseModel):
    model_config = {"extra": "ignore"}

    page_start: int | None = Field(default=None, ge=0)
    page_end: int | None = Field(default=None, ge=0)
    note: str | None = None
    read_at: str | None = None
    class_id: str | None = None

    def provided(self) -> dict[str, Any]:
        """Only the fields the client actually sent, so `note: null` clears the note
        but an omitted `note` leaves it alone."""
        return self.model_dump(exclude_unset=True)


class EntryOut(BaseModel):
    id: str
    page_start: int
    page_end: int
    pages: int
    read_at: str
    note: str | None
    class_id: str | None
    created_at: str
    updated_at: str


class ClassCreate(BaseModel):
    model_config = {"extra": "ignore"}

    title: str
    description: str | None = None
    # Optional: an omitted color falls back to one constant in app/classes.py. The
    # front end always sends one (DECISIONS.md 12.2).
    color: str | None = None


class ClassUpdate(BaseModel):
    model_config = {"extra": "ignore"}

    title: str | None = None
    description: str | None = None
    color: str | None = None
    archived: bool | None = None

    def provided(self) -> dict[str, Any]:
        """Only the fields the client actually sent, so `description: null` clears the
        description but an omitted `description` leaves it alone."""
        return self.model_dump(exclude_unset=True)


class ClassOut(BaseModel):
    """The /api/classes payload.

    No entry count, no page total, no per-class anything. DECISIONS.md 12.5: a field
    absent from the payload cannot be rendered as a scoreboard, which is the same
    structural move as omitting longest_streak_days from StatsOut.
    """

    id: str
    title: str
    description: str | None
    color: str
    archived: bool
    created_at: str
    updated_at: str


class StatsOut(BaseModel):
    """The /api/stats payload.

    `longest_streak_days` is computed by app.stats but deliberately absent here, so the
    API cannot hand a UI the material for a "current 2 / longest 11" comparison. See
    DECISIONS.md 8 -- this omission is what makes that section structural. FastAPI drops
    any field not declared on the response model.
    """

    pages_today: int
    pages_all_time: int
    current_streak_days: int
    entry_count: int
    first_entry_date: str | None


class SettingsUpdate(BaseModel):
    """extra='forbid': an unknown settings key is a 422, not silently dropped.

    This is the deliberate opposite of EntryCreate/ClassCreate's extra='ignore'
    (DECISIONS.md 1.1) -- those exist to swallow a stray `pages` field on purpose;
    a typo'd settings key deserves to be seen, not to vanish quietly.
    """

    model_config = {"extra": "forbid"}

    theme: str | None = None
    custom_theme: dict[str, str] | None = None
    default_chip: str | None = None

    def provided(self) -> dict[str, Any]:
        """Only the fields the client actually sent (DECISIONS.md 13)."""
        return self.model_dump(exclude_unset=True)


class SettingsOut(BaseModel):
    theme: str
    custom_theme: dict[str, str] | None
    default_chip: str


class QuoteOut(BaseModel):
    """The /api/quote payload. Words and a name, never anything from the entry log.

    DECISIONS.md 10: the quote path and the reading log are separate by
    construction. This model carries no entry data because the handler that
    fills it has none.

    DECISIONS.md 10.1 (amended): `text` replaces the old bare `quote` string
    and `attribution` joins it. `attribution` is null far more often than not
    -- every hand-written line in the user's own file has none -- so null is
    the ordinary case, and the front end renders nothing at all for it (10.2).
    """

    text: str
    attribution: str | None


def to_out(entry: dict[str, Any]) -> dict[str, Any]:
    """Serialize a stored entry for the API, recomputing `pages` on every read."""
    return {
        "id": entry["id"],
        "page_start": entry["page_start"],
        "page_end": entry["page_end"],
        "pages": compute_pages(entry["page_start"], entry["page_end"]),
        "read_at": entry["read_at"],
        "note": entry["note"],
        # .get(): an entry loaded from a version 1 file has no class_id key at all
        # and reads as null (DECISIONS.md 1.4).
        "class_id": entry.get("class_id"),
        "created_at": entry["created_at"],
        "updated_at": entry["updated_at"],
    }
