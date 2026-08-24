"""Durable JSON storage. See DECISIONS.md section 3.

The whole point of this module: a crash mid-write must never produce a truncated or
empty entries.json, and a file this code cannot interpret is never modified.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION
from .daytime import BadTimestamp, format_iso, now_local, parse_iso
from .models import ValidationProblem, validate_page_range

ENTRY_FIELDS = (
    "id",
    "page_start",
    "page_end",
    "read_at",
    "note",
    "created_at",
    "updated_at",
)


class CorruptDataFile(Exception):
    """The data file cannot be safely interpreted. DECISIONS.md 3.4: halt, don't recover.

    Carries enough detail to print a banner that tells the user what to open and where
    to look. The file itself is never touched.
    """

    def __init__(
        self,
        path: Path,
        reason: str,
        *,
        line: int | None = None,
        column: int | None = None,
        position: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.reason = reason
        self.line = line
        self.column = column
        self.position = position
        super().__init__(f"{self.path}: {reason}")

    def location(self) -> str | None:
        if self.line is not None and self.column is not None:
            where = f"line {self.line}, column {self.column}"
            if self.position is not None:
                where += f" (character {self.position})"
            return where
        return None

    def banner(self) -> str:
        """The loud multi-line stderr message required by DECISIONS.md 3.4."""
        rule = "!" * 72
        lines = [
            "",
            rule,
            "  READING TRACKER WILL NOT START: the data file cannot be read.",
            rule,
            "",
            f"  File:  {self.path}",
            f"  Problem: {self.reason}",
        ]
        where = self.location()
        if where:
            lines.append(f"  Where: {where}")
        lines += [
            "",
            "  Your data has NOT been changed, moved, renamed, or overwritten.",
            "  The file is exactly as it was. Nothing was lost.",
            "",
            "  This server refuses to start rather than show you an empty log that",
            "  looks like the truth. Open the file above, fix it, and start again.",
            "",
            "  If you want to set it aside and start over, move it yourself:",
            f"    mv '{self.path}' '{self.path.with_suffix('.json.bak')}'",
            "",
            rule,
            "",
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Atomic write (DECISIONS.md 3.1, 3.2)
# --------------------------------------------------------------------------- #


def _durable_sync(fd: int) -> None:
    """Flush a file descriptor all the way to the physical device.

    On macOS a plain os.fsync() returns once the data reaches the drive's write cache,
    not once it is durably stored. Only F_FULLFSYNC guarantees survival of a power cut.
    Falls back to os.fsync on volumes that reject it (non-APFS, network mounts).
    """
    full_fsync = getattr(fcntl, "F_FULLFSYNC", None)
    if full_fsync is not None:
        try:
            fcntl.fcntl(fd, full_fsync)
            return
        except OSError:
            pass
    os.fsync(fd)


def _sync_directory(directory: Path) -> None:
    """fsync the directory so the rename itself survives a power cut."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write `payload` to `path` atomically and durably.

    temp file in the same directory -> write -> flush -> F_FULLFSYNC -> close ->
    os.replace -> fsync the directory. Readers see either the entire old file or the
    entire new one, never a truncated one. On any failure the temp file is removed,
    so a crashed write leaves no litter beside the real data file.
    """
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        # Serialize before writing anything, so a serialization error cannot leave a
        # half-written temp file behind.
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            _durable_sync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
    _sync_directory(directory)


# --------------------------------------------------------------------------- #
# Validation of what is already on disk (DECISIONS.md 3.4)
# --------------------------------------------------------------------------- #


def _is_int(value: Any) -> bool:
    # bool is a subclass of int; `true` is not a page number.
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_entry(raw: Any, index: int, path: Path) -> dict[str, Any]:
    where = f"entries[{index}]"
    if not isinstance(raw, dict):
        raise CorruptDataFile(path, f"{where} is not a JSON object")

    missing = [field for field in ENTRY_FIELDS if field not in raw]
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
        if not _is_int(raw[field]):
            raise CorruptDataFile(
                path, f"{where}.{field} must be a whole number, got {raw[field]!r}"
            )
    try:
        validate_page_range(raw["page_start"], raw["page_end"])
    except ValidationProblem as exc:
        raise CorruptDataFile(path, f"{where}: {exc}") from None

    if raw["note"] is not None and not isinstance(raw["note"], str):
        raise CorruptDataFile(path, f"{where}.note must be a string or null")

    for field in ("read_at", "created_at", "updated_at"):
        try:
            parse_iso(raw[field], field=field)
        except BadTimestamp as exc:
            raise CorruptDataFile(path, f"{where}: {exc}") from None

    return {field: raw[field] for field in ENTRY_FIELDS}


def _validate_document(document: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise CorruptDataFile(
            path, f"top level must be a JSON object, found {type(document).__name__}"
        )

    version = document.get("schema_version")
    if version is None:
        raise CorruptDataFile(path, "top level is missing 'schema_version'")
    if not _is_int(version):
        raise CorruptDataFile(
            path, f"'schema_version' must be a whole number, got {version!r}"
        )
    if version > SCHEMA_VERSION:
        # DECISIONS.md 1.2: newer-than-known is an error, not corruption -- but the
        # response is the same halt, and the file is likewise never touched.
        raise CorruptDataFile(
            path,
            f"file uses schema_version {version}, but this code understands only "
            f"{SCHEMA_VERSION}. It was written by a newer version of this app.",
        )

    entries = document.get("entries")
    if entries is None:
        raise CorruptDataFile(path, "top level is missing 'entries'")
    if not isinstance(entries, list):
        raise CorruptDataFile(
            path, f"'entries' must be a list, found {type(entries).__name__}"
        )

    validated = [_validate_entry(raw, i, path) for i, raw in enumerate(entries)]

    seen: set[str] = set()
    for entry in validated:
        if entry["id"] in seen:
            raise CorruptDataFile(path, f"duplicate entry id: {entry['id']}")
        seen.add(entry["id"])

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
            # DECISIONS.md 3.3: missing file is not an error.
            self._entries = []
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, self._document())
            return

        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CorruptDataFile(self.path, f"could not be read: {exc}") from None
        except UnicodeDecodeError as exc:
            raise CorruptDataFile(self.path, f"is not valid UTF-8 text: {exc}") from None

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptDataFile(
                self.path,
                f"is not valid JSON: {exc.msg}",
                line=exc.lineno,
                column=exc.colno,
                position=exc.pos,
            ) from None

        self._entries = _validate_document(document, self.path)

    def _document(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "entries": self._entries}

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
    ) -> dict[str, Any]:
        stamp = format_iso(now_local())
        entry = {
            "id": str(uuid.uuid4()),
            "page_start": page_start,
            "page_end": page_end,
            "read_at": read_at if read_at is not None else stamp,
            "note": note,
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
                for field in ("page_start", "page_end", "note", "read_at"):
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
