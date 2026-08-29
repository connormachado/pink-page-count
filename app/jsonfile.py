"""The atomic write path and the corrupt-file halt. See DECISIONS.md 3.1-3.5.1.

The whole point of this module: a crash mid-write must never produce a truncated or
empty data file, and a file this code cannot interpret is never modified. And when a
write cannot happen at all, the caller hears about it -- `DataWriteError`, never a
silent success and never a bare OSError nobody upstream is expecting (3.5.1).

Both data files go through here. There is **one** implementation, not one per file:
this is the most safety-critical code in the project, and two copies of it means one
of them eventually drifts and only one of them is tested (DECISIONS.md 3.1).
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class DataWriteError(Exception):
    """A data file could not be written. DECISIONS.md 3.5.1: the inverse case.

    3.5 promises that a request which returned 2xx is a request whose data is
    already on disk. This is the other half of that promise, and it is the half
    that used to lie: the write did not land, so the request must not return
    2xx, and what it returns instead has to say so.

    Raised by `atomic_write_json` for the whole family of reasons a write can
    fail from outside this program -- a read-only directory, a full disk, a
    volume that went away mid-write, a path owned by another user. They differ
    only in the errno, and the errno is a fact for the log, never for the
    screen (4.5).

    Carries the original OSError as `cause` rather than replacing it: the
    handler that turns this into a response logs the cause in full, because a
    failure nobody can diagnose is barely better than one nobody is told about.

    There is deliberately no retry and no second location to write to. A write
    that cannot land must fail loudly, not land somewhere she will never find.
    """

    def __init__(self, path: Path, cause: OSError) -> None:
        self.path = Path(path)
        self.cause = cause
        self.errno = getattr(cause, "errno", None)
        super().__init__(f"{self.path}: {cause}")


class CorruptDataFile(Exception):
    """A data file cannot be safely interpreted. DECISIONS.md 3.4: halt, don't recover.

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
            "  READING TRACKER WILL NOT START: a data file cannot be read.",
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

    Every OSError raised along that path -- from the directory that will not take a
    temp file, the device with no space left, the volume that went away, the file
    owned by somebody else -- comes back out as `DataWriteError` (3.5.1). One
    exception for one situation: the data did not land. The caller does not branch on
    which errno it was, and neither does the response; only the log does.
    """
    path = Path(path)
    directory = path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=directory, prefix=f".{path.name}.", suffix=".tmp"
        )
    except OSError as exc:
        # Nothing was created, so there is nothing to clean up -- this is the
        # read-only-directory case, and it fails before the temp file exists.
        raise DataWriteError(path, exc) from exc

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
    except BaseException as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise DataWriteError(path, exc) from exc
        raise
    _sync_directory(directory)


# --------------------------------------------------------------------------- #
# Reading and validating what is already on disk (DECISIONS.md 3.4)
# --------------------------------------------------------------------------- #


def is_int(value: Any) -> bool:
    # bool is a subclass of int; `true` is not a page number.
    return isinstance(value, int) and not isinstance(value, bool)


def read_json_document(path: Path) -> Any:
    """Read and parse a data file, or raise CorruptDataFile naming what went wrong.

    Keeps the line/column of a JSON syntax error so the banner can point at it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptDataFile(path, f"is not valid UTF-8 text: {exc}") from None
    except OSError as exc:
        raise CorruptDataFile(path, f"could not be read: {exc}") from None

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptDataFile(
            path,
            f"is not valid JSON: {exc.msg}",
            line=exc.lineno,
            column=exc.colno,
            position=exc.pos,
        ) from None


def envelope_list(
    document: Any, path: Path, *, list_key: str, schema_version: int
) -> list[Any]:
    """Validate the {schema_version, <list_key>} wrapper both data files share.

    DECISIONS.md 1.2: a version NEWER than this code understands is a halt -- the app
    refuses to touch data written by a future version of itself. An OLDER version is
    never a halt. It loads, is served correctly, and is rewritten at the current
    version by the next ordinary mutation and at no other time.
    """
    if not isinstance(document, dict):
        raise CorruptDataFile(
            path, f"top level must be a JSON object, found {type(document).__name__}"
        )

    version = document.get("schema_version")
    if version is None:
        raise CorruptDataFile(path, "top level is missing 'schema_version'")
    if not is_int(version):
        raise CorruptDataFile(
            path, f"'schema_version' must be a whole number, got {version!r}"
        )
    if version > schema_version:
        raise CorruptDataFile(
            path,
            f"file uses schema_version {version}, but this code understands only "
            f"{schema_version}. It was written by a newer version of this app.",
        )

    records = document.get(list_key)
    if records is None:
        raise CorruptDataFile(path, f"top level is missing '{list_key}'")
    if not isinstance(records, list):
        raise CorruptDataFile(
            path, f"'{list_key}' must be a list, found {type(records).__name__}"
        )
    return records


def reject_duplicate_ids(
    records: list[dict[str, Any]], path: Path, *, label: str
) -> None:
    seen: set[str] = set()
    for record in records:
        if record["id"] in seen:
            raise CorruptDataFile(path, f"duplicate {label} id: {record['id']}")
        seen.add(record["id"])
