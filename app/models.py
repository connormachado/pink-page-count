"""Request/response models and the shared page-range validator.

See DECISIONS.md 1.1 (pages is computed, never stored) and 4.1 (validation placement).
"""

from __future__ import annotations

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


class EntryCreate(BaseModel):
    # extra="ignore": a client that sends `pages` has it silently ignored (DECISIONS 1.1).
    model_config = {"extra": "ignore"}

    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)
    note: str | None = None
    read_at: str | None = None


class EntryUpdate(BaseModel):
    model_config = {"extra": "ignore"}

    page_start: int | None = Field(default=None, ge=0)
    page_end: int | None = Field(default=None, ge=0)
    note: str | None = None
    read_at: str | None = None

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
    created_at: str
    updated_at: str


class StatsOut(BaseModel):
    pages_today: int
    pages_all_time: int
    current_streak_days: int
    longest_streak_days: int
    entry_count: int
    first_entry_date: str | None


def to_out(entry: dict[str, Any]) -> dict[str, Any]:
    """Serialize a stored entry for the API, recomputing `pages` on every read."""
    return {
        "id": entry["id"],
        "page_start": entry["page_start"],
        "page_end": entry["page_end"],
        "pages": compute_pages(entry["page_start"], entry["page_end"]),
        "read_at": entry["read_at"],
        "note": entry["note"],
        "created_at": entry["created_at"],
        "updated_at": entry["updated_at"],
    }
