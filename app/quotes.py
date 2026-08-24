"""The daily quote. See DECISIONS.md sections 10 and 8.

This module is deliberately tiny and deliberately isolated. Look at the import
list: `hashlib`, `pathlib`, and one function from `daytime`. It does not import
`storage`, it does not import `config`, and it never learns the path to
`data/entries.json`. That is not restraint at call time -- it is the structural
guarantee DECISIONS.md 10 asks for. Editing quotes cannot touch the reading log
because nothing in this file knows the reading log exists.
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


class QuoteSource:
    """Reads quotes.txt on every request. Injectable, like Storage (DECISIONS.md 3.7).

    Read-on-request rather than read-at-startup is a feature: editing quotes.txt
    shows up on the next page load with no restart.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> list[str]:
        """The usable lines of the quote file, or [] if there are none.

        Blank lines and lines starting with '#' are ignored. A missing or
        unreadable file is an empty list, never an exception -- the caller turns
        that into the fallback.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(COMMENT_PREFIX):
                continue
            lines.append(stripped)
        return lines

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
