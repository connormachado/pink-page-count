"""The class list: load, CRUD, write-through. See DECISIONS.md section 12.

Shaped exactly like `app/storage.py` and sharing its durable write path and
corrupt-file halt through `app/jsonfile.py` (DECISIONS.md 3.1, 3.4).

**This module never opens entries.json.** Renaming, recoloring, or archiving a class
cannot touch the reading log, because there is no path from here to it -- the same
structural separation section 10 gives the quote file. Deleting a class does clear
`class_id` off entries, but that write is issued by the route, against the entry
store, in the order DECISIONS.md 3.8 fixes.
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import CLASSES_SCHEMA_VERSION
from .daytime import BadTimestamp, format_iso, now_local, parse_iso
from .jsonfile import (
    CorruptDataFile,
    atomic_write_json,
    envelope_list,
    read_json_document,
    reject_duplicate_ids,
)
from .models import ValidationProblem, validate_color, validate_title

# The palette lives in web/src/tokens.css and nowhere else (DECISIONS.md 12.2). This
# single fallback exists only so `curl` and hand-edits have a color; the front end
# always sends one explicitly, chosen from those tokens.
FALLBACK_COLOR = "#E4557F"

# Storage order, and therefore the key order written to disk.
CLASS_FIELDS = (
    "id",
    "title",
    "description",
    "color",
    "archived",
    "created_at",
    "updated_at",
)


# --------------------------------------------------------------------------- #
# Validation of what is already on disk (DECISIONS.md 3.4)
# --------------------------------------------------------------------------- #


def _validate_class(raw: Any, index: int, path: Path) -> dict[str, Any]:
    where = f"classes[{index}]"
    if not isinstance(raw, dict):
        raise CorruptDataFile(path, f"{where} is not a JSON object")

    missing = [field for field in CLASS_FIELDS if field not in raw]
    if missing:
        raise CorruptDataFile(
            path, f"{where} is missing required field(s): {', '.join(missing)}"
        )
    unknown = [key for key in raw if key not in CLASS_FIELDS]
    if unknown:
        raise CorruptDataFile(
            path,
            f"{where} has unrecognized field(s): {', '.join(sorted(unknown))}. "
            f"Recognized fields are: {', '.join(CLASS_FIELDS)}",
        )

    if not isinstance(raw["id"], str) or not raw["id"].strip():
        raise CorruptDataFile(path, f"{where}.id must be a non-empty string")

    for field in ("title", "color"):
        if not isinstance(raw[field], str):
            raise CorruptDataFile(
                path, f"{where}.{field} must be a string, got {raw[field]!r}"
            )
    try:
        validate_title(raw["title"])
        validate_color(raw["color"])
    except ValidationProblem as exc:
        raise CorruptDataFile(path, f"{where}: {exc}") from None

    if raw["description"] is not None and not isinstance(raw["description"], str):
        raise CorruptDataFile(path, f"{where}.description must be a string or null")
    if not isinstance(raw["archived"], bool):
        raise CorruptDataFile(path, f"{where}.archived must be true or false")

    for field in ("created_at", "updated_at"):
        try:
            parse_iso(raw[field], field=field)
        except BadTimestamp as exc:
            raise CorruptDataFile(path, f"{where}: {exc}") from None

    return {field: raw[field] for field in CLASS_FIELDS}


def _validate_document(document: Any, path: Path) -> list[dict[str, Any]]:
    raw_classes = envelope_list(
        document, path, list_key="classes", schema_version=CLASSES_SCHEMA_VERSION
    )
    validated = [_validate_class(raw, i, path) for i, raw in enumerate(raw_classes)]
    # Duplicate ids are corruption -- an entry could not say which class it meant.
    # Duplicate *titles* are not: uniqueness is a constraint the API enforces on new
    # input, not a property a hand-edited file forfeits its readability by breaking.
    reject_duplicate_ids(validated, path, label="class")
    return validated


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


class ClassStore:
    """The class list, held in memory and written through on every mutation."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._classes: list[dict[str, Any]] = []
        self._load()

    # -- loading ---------------------------------------------------------- #

    def _load(self) -> None:
        if not self.path.exists():
            self._classes = []
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, self._document())
            return
        self._classes = _validate_document(read_json_document(self.path), self.path)

    def _document(self) -> dict[str, Any]:
        return {"schema_version": CLASSES_SCHEMA_VERSION, "classes": self._classes}

    def _persist(self) -> None:
        atomic_write_json(self.path, self._document())

    # -- reads ------------------------------------------------------------ #

    def list(self) -> list[dict[str, Any]]:
        """Non-archived first, then archived; case-insensitive title order within each.

        Archived classes stay in the payload because entries still reference them --
        the picker filters them out, the entry list still needs their name and color
        (DECISIONS.md 12.4).
        """
        with self._lock:
            classes = [dict(item) for item in self._classes]
        classes.sort(key=lambda item: (item["archived"], item["title"].casefold()))
        return classes

    def get(self, class_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._classes:
                if item["id"] == class_id:
                    return dict(item)
        return None

    # -- validation that needs the whole list ------------------------------ #

    def _require_available_title(
        self, title: str, *, archived: bool, exclude_id: str | None
    ) -> None:
        """One helper, used by both create and update, on the MERGED result.

        Duplicates are rejected among non-archived classes only, so archiving a class
        frees its name and un-archiving into a collision is the same 422 as creating
        a duplicate (DECISIONS.md 4.1). Callers hold the lock.
        """
        if archived:
            return
        folded = title.casefold()
        for other in self._classes:
            if other["id"] == exclude_id or other["archived"]:
                continue
            if other["title"].casefold() == folded:
                raise ValidationProblem(
                    f"There is already a class called {other['title']!r}."
                )

    # -- mutations -------------------------------------------------------- #

    def create(
        self,
        *,
        title: str,
        description: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        clean_title = validate_title(title)
        clean_color = validate_color(color) if color is not None else FALLBACK_COLOR
        stamp = format_iso(now_local())
        item = {
            "id": str(uuid.uuid4()),
            "title": clean_title,
            "description": description,
            "color": clean_color,
            "archived": False,
            "created_at": stamp,
            "updated_at": stamp,
        }
        with self._lock:
            self._require_available_title(
                clean_title, archived=False, exclude_id=None
            )
            self._classes.append(item)
            try:
                self._persist()
            except BaseException:
                self._classes.pop()  # keep memory consistent with disk
                raise
        return dict(item)

    def update(self, class_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for index, item in enumerate(self._classes):
                if item["id"] != class_id:
                    continue

                updated = dict(item)
                if "title" in changes:
                    updated["title"] = validate_title(changes["title"])
                if "color" in changes:
                    updated["color"] = validate_color(changes["color"])
                if "description" in changes:
                    updated["description"] = changes["description"]
                if "archived" in changes:
                    updated["archived"] = changes["archived"]

                # The merged result, not just what was sent: un-archiving alone can
                # collide with a title that was fine while this class was away.
                self._require_available_title(
                    updated["title"],
                    archived=updated["archived"],
                    exclude_id=class_id,
                )

                updated["updated_at"] = format_iso(now_local())
                self._classes[index] = updated
                try:
                    self._persist()
                except BaseException:
                    self._classes[index] = item
                    raise
                return dict(updated)
        return None

    def delete(self, class_id: str) -> bool:
        """Remove the class. Entries are the caller's business, and are cleared FIRST.

        DECISIONS.md 3.8 and 12.3: this deletes one record from one file. There is no
        cascade here -- this module cannot reach an entry even if it wanted to.
        """
        with self._lock:
            for index, item in enumerate(self._classes):
                if item["id"] == class_id:
                    del self._classes[index]
                    try:
                        self._persist()
                    except BaseException:
                        self._classes.insert(index, item)
                        raise
                    return True
        return False


def load_class_store_or_exit(path: Path | str) -> ClassStore:
    """Open the class file, or print the banner and halt (DECISIONS.md 3.4)."""
    try:
        return ClassStore(path)
    except CorruptDataFile as exc:
        print(exc.banner(), file=sys.stderr, flush=True)
        raise SystemExit(2) from None
