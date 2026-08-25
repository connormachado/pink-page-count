"""The entry log: load, CRUD, write-through. See DECISIONS.md section 3.

The durable write path and the corrupt-file halt live in `app/jsonfile.py` and are
shared with the class store -- there is one implementation of them, not one per file
(DECISIONS.md 3.1). They are re-exported here because this module is where the rest
of the project has always reached for them.

This module knows nothing about classes beyond `class_id` being a string or null. It
does not import the class store, and there is no path through it that opens
classes.json (DECISIONS.md 1.3).
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import ENTRIES_SCHEMA_VERSION
from .daytime import BadTimestamp, format_iso, now_local, parse_iso
from .jsonfile import (
    CorruptDataFile,
    atomic_write_json,
    envelope_list,
    is_int,
    read_json_document,
    reject_duplicate_ids,
)
from .models import ValidationProblem, validate_page_range

__all__ = [
    "CorruptDataFile",
    "ENTRY_FIELDS",
    "Storage",
    "atomic_write_json",
    "load_storage_or_exit",
]

# Storage order, and therefore the key order written to disk.
ENTRY_FIELDS = (
    "id",
    "page_start",
    "page_end",
    "read_at",
    "note",
    "class_id",
    "created_at",
    "updated_at",
)

# DECISIONS.md 1.4: class_id is recognized but OPTIONAL on read. An entry written by
# Phase 3 code has no such key and reads as None. Nothing is rewritten to add it --
# that happens on the next ordinary mutation and at no other time.
OPTIONAL_ENTRY_FIELDS = ("class_id",)
REQUIRED_ENTRY_FIELDS = tuple(
    field for field in ENTRY_FIELDS if field not in OPTIONAL_ENTRY_FIELDS
)

# The fields a PATCH may touch. `pages` is not among them and never will be (1.1).
PATCHABLE_FIELDS = ("page_start", "page_end", "note", "read_at", "class_id")


# --------------------------------------------------------------------------- #
# Validation of what is already on disk (DECISIONS.md 3.4)
# --------------------------------------------------------------------------- #


def _validate_entry(raw: Any, index: int, path: Path) -> dict[str, Any]:
    where = f"entries[{index}]"
    if not isinstance(raw, dict):
        raise CorruptDataFile(path, f"{where} is not a JSON object")

    missing = [field for field in REQUIRED_ENTRY_FIELDS if field not in raw]
    if missing:
        raise CorruptDataFile(
            path, f"{where} is missing required field(s): {', '.join(missing)}"
        )
    unknown = [key for key in raw if key not in ENTRY_FIELDS]
    if unknown:
        # Strict on purpose: a typo'd key ("not" instead of "note") would otherwise be
        # silently discarded the next time the file is written.
        raise CorruptDataFile(
            path,
            f"{where} has unrecognized field(s): {', '.join(sorted(unknown))}. "
            f"Recognized fields are: {', '.join(ENTRY_FIELDS)}",
        )

    if not isinstance(raw["id"], str) or not raw["id"].strip():
        raise CorruptDataFile(path, f"{where}.id must be a non-empty string")
    for field in ("page_start", "page_end"):
        if not is_int(raw[field]):
            raise CorruptDataFile(
                path, f"{where}.{field} must be a whole number, got {raw[field]!r}"
            )
    try:
        validate_page_range(raw["page_start"], raw["page_end"])
    except ValidationProblem as exc:
        raise CorruptDataFile(path, f"{where}: {exc}") from None

    if raw["note"] is not None and not isinstance(raw["note"], str):
        raise CorruptDataFile(path, f"{where}.note must be a string or null")

    # A class_id that names a class not in classes.json is NOT corruption and does not
    # stop the server (DECISIONS.md 1.3) -- only the shape is checked here. Nothing in
    # this module can see classes.json to check anything else.
    class_id = raw.get("class_id")
    if class_id is not None:
        if not isinstance(class_id, str):
            raise CorruptDataFile(path, f"{where}.class_id must be a string or null")
        if not class_id.strip():
            raise CorruptDataFile(
                path, f"{where}.class_id must be null rather than an empty string"
            )

    for field in ("read_at", "created_at", "updated_at"):
        try:
            parse_iso(raw[field], field=field)
        except BadTimestamp as exc:
            raise CorruptDataFile(path, f"{where}: {exc}") from None

    return {field: raw.get(field) for field in ENTRY_FIELDS}


def _validate_document(document: Any, path: Path) -> list[dict[str, Any]]:
    raw_entries = envelope_list(
        document, path, list_key="entries", schema_version=ENTRIES_SCHEMA_VERSION
    )
    validated = [_validate_entry(raw, i, path) for i, raw in enumerate(raw_entries)]
    reject_duplicate_ids(validated, path, label="entry")
    return validated


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


class Storage:
    """The entries list, held in memory and written through on every mutation.

    A request that returned 2xx is a request whose data is already on disk -- there is
    no write-behind, no batching, no dirty flag (DECISIONS.md 3.5).
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._load()

    # -- loading ---------------------------------------------------------- #

    def _load(self) -> None:
        if not self.path.exists():
            # DECISIONS.md 3.3: missing file is not an error. It is created at the
            # current version -- a first write, not a migration.
            self._entries = []
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, self._document())
            return

        # DECISIONS.md 1.4: an older file is read into the current shape and left
        # alone on disk. Loading never persists.
        self._entries = _validate_document(read_json_document(self.path), self.path)

    def _document(self) -> dict[str, Any]:
        return {"schema_version": ENTRIES_SCHEMA_VERSION, "entries": self._entries}

    def _persist(self) -> None:
        atomic_write_json(self.path, self._document())

    # -- reads ------------------------------------------------------------ #

    def all(self) -> list[dict[str, Any]]:
        """Every entry, in insertion order (storage order, not display order)."""
        with self._lock:
            return [dict(entry) for entry in self._entries]

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Entries newest first: by read_at descending, created_at descending as tiebreak."""
        entries = self.all()
        entries.sort(
            key=lambda entry: (
                parse_iso(entry["read_at"]),
                parse_iso(entry["created_at"]),
            ),
            reverse=True,
        )
        return entries[:limit] if limit is not None else entries

    def get(self, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            for entry in self._entries:
                if entry["id"] == entry_id:
                    return dict(entry)
        return None

    # -- mutations -------------------------------------------------------- #

    def create(
        self,
        *,
        page_start: int,
        page_end: int,
        note: str | None = None,
        read_at: str | None = None,
        class_id: str | None = None,
    ) -> dict[str, Any]:
        stamp = format_iso(now_local())
        entry = {
            "id": str(uuid.uuid4()),
            "page_start": page_start,
            "page_end": page_end,
            "read_at": read_at if read_at is not None else stamp,
            "note": note,
            "class_id": class_id,
            "created_at": stamp,
            "updated_at": stamp,
        }
        with self._lock:
            self._entries.append(entry)
            try:
                self._persist()
            except BaseException:
                self._entries.pop()  # keep memory consistent with disk
                raise
        return dict(entry)

    def update(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for index, entry in enumerate(self._entries):
                if entry["id"] != entry_id:
                    continue
                updated = dict(entry)
                for field in PATCHABLE_FIELDS:
                    if field in changes:
                        updated[field] = changes[field]
                updated["updated_at"] = format_iso(now_local())
                self._entries[index] = updated
                try:
                    self._persist()
                except BaseException:
                    self._entries[index] = entry
                    raise
                return dict(updated)
        return None

    def clear_class(self, class_id: str) -> int:
        """Set class_id to null on every entry that carries it. Returns how many.

        DECISIONS.md 12.3: this is what deleting a class does to entries, and it is
        the ONLY thing it does to them. page_start, page_end, read_at, note, and
        created_at are not touched. There is no code path here that removes an entry.

        updated_at IS bumped, because section 1 defines it as bumped on every mutation
        and this is one. That is a stated choice, not an oversight.
        """
        with self._lock:
            stamp = format_iso(now_local())
            previous = list(self._entries)
            cleared = 0
            for index, entry in enumerate(self._entries):
                if entry.get("class_id") != class_id:
                    continue
                self._entries[index] = {
                    **entry,
                    "class_id": None,
                    "updated_at": stamp,
                }
                cleared += 1

            if cleared == 0:
                return 0
            try:
                self._persist()
            except BaseException:
                self._entries[:] = previous  # keep memory consistent with disk
                raise
            return cleared

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            for index, entry in enumerate(self._entries):
                if entry["id"] == entry_id:
                    del self._entries[index]
                    try:
                        self._persist()
                    except BaseException:
                        self._entries.insert(index, entry)
                        raise
                    return True
        return False


def load_storage_or_exit(path: Path | str) -> Storage:
    """Open the data file, or print the banner and halt (DECISIONS.md 3.4)."""
    try:
        return Storage(path)
    except CorruptDataFile as exc:
        print(exc.banner(), file=sys.stderr, flush=True)
        raise SystemExit(2) from None
