"""The daily quote. See DECISIONS.md sections 10 and 8.

This module is deliberately tiny and deliberately isolated. Look at the import
list: `hashlib`, `pathlib`, and one function from `daytime`. It does not import
`storage`, it does not import `config`, and it never learns the path to
`entries.json`. That is not restraint at call time -- it is the structural
guarantee DECISIONS.md 10 asks for. Editing quotes cannot touch the reading log
because nothing in this file knows the reading log exists.

DECISIONS.md 10.1 (amended): a `QuoteSource` reads two files -- the bundled,
canonical list and an optional file the user owns -- and unions them. Both
paths are handed in by the caller; this module still never names the reading
log or any other file under the user's data directory.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from .daytime import day_key_str

# Shown when quotes.txt is missing, empty, or holds nothing but comments. The
# message area is never blank and this path never raises -- DECISIONS.md 10.
FALLBACK = "Every page you read is one you didn't have before."

COMMENT_PREFIX = "#"


def _usable_lines(path: Path) -> list[str]:
    """The usable lines of one quote file, or [] if there are none.

    Blank lines and lines starting with '#' are ignored. A missing or
    unreadable file is an empty list, never an exception.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIX):
            continue
        lines.append(stripped)
    return lines


class QuoteSource:
    """Reads quotes.txt on every request. Injectable, like Storage (DECISIONS.md 3.7).

    Read-on-request rather than read-at-startup is a feature: editing quotes.txt
    shows up on the next page load with no restart.

    `user_path` is optional (DECISIONS.md 10.1, amended): when given, its lines
    are unioned after `path`'s -- bundled quotes first, then the user's own,
    blank lines and exact duplicates dropped, order otherwise preserved. A
    missing `user_path` is normal, not an error: it behaves exactly as it did
    before this file existed.
    """

    def __init__(self, path: Path | str, user_path: Path | str | None = None) -> None:
        self.path = Path(path)
        self.user_path = Path(user_path) if user_path is not None else None

    def load(self) -> list[str]:
        """The usable, deduplicated union of the bundled and user quote files."""
        lines = _usable_lines(self.path)
        if self.user_path is not None:
            lines += _usable_lines(self.user_path)
        seen: set[str] = set()
        union = []
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            union.append(line)
        return union

    def for_day(self, day: date) -> str:
        """The quote for one logical day. Same day in, same quote out. Always.

        The index is derived with sha256 rather than the builtin hash(): Python
        randomizes string hashing per process (PYTHONHASHSEED), so hash() would
        hand back a different quote after every server restart. sha256 of the
        day key is stable across processes, machines, and years.
        """
        quotes = self.load()
        if not quotes:
            return FALLBACK
        return quotes[quote_index(day, len(quotes))]


def quote_index(day: date, count: int) -> int:
    """Which quote a logical day maps to. Deterministic, process-independent."""
    digest = hashlib.sha256(day_key_str(day).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


USER_QUOTES_TEMPLATE = (
    "# Add your own quotes here, one per line.\n"
    "# Lines starting with # are ignored, same as this one.\n"
    "# These are yours -- an update never replaces this file.\n"
)


def ensure_user_quotes_file(path: Path) -> None:
    """Create the user's optional quote file, instructions only, on first run.

    Called once at startup, never from `QuoteSource` itself, so a unit test
    building a `QuoteSource` directly never gets a surprise write. Never an
    error (DECISIONS.md 10.4's spirit): if `path` can't be written -- a
    read-only volume, a missing parent -- the invitation just doesn't appear
    yet, same as a missing file behaves everywhere else in this module.

    Touches exactly the one path it is given, and nothing else.
    """
    if path.exists():
        return
    try:
        path.write_text(USER_QUOTES_TEMPLATE, encoding="utf-8")
    except OSError:
        pass
