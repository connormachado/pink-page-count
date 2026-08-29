"""The daily quote. See DECISIONS.md sections 10 and 8.

This module is deliberately tiny and deliberately isolated. Look at the import
list: `hashlib`, `pathlib`, `dataclasses`, and one function from `daytime`. It
does not import `storage`, it does not import `config`, and it never learns the
path to the reading log. That is not restraint at call time -- it is the
structural guarantee DECISIONS.md 10 asks for. Editing quotes cannot touch the
reading log because nothing in this file knows the reading log exists.

DECISIONS.md 10.1 (amended): a `QuoteSource` reads two files -- the bundled,
canonical list and an optional file the user owns -- and unions them. Both
paths are handed in by the caller; this module still never names the reading
log or any other file under the user's directory.

DECISIONS.md 10.2 (amended): a line is `<quote text>||<attributor>`. The
attributor is optional and a line without one is an ordinary, valid record --
never a warning, never a skip. A hand-written file of bare sentences parses
exactly as it did before this feature existed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .daytime import day_key_str

# Shown when the quote files are missing, empty, or hold nothing but comments.
# The message area is never blank and this path never raises -- DECISIONS.md 10.
FALLBACK = "Every page you read is one you didn't have before."

COMMENT_PREFIX = "#"

# DECISIONS.md 10.2 (amended). Two pipes, because a single one shows up inside
# ordinary prose and a quote is prose. Split on the FIRST occurrence only: a
# second "||" belongs to the attributor, which is where a construction like
# "Sarah Grimke, quoted by RBG" would put one if it ever needed to.
DELIMITER = "||"


@dataclass(frozen=True, slots=True)
class Quote:
    """One record: the words, and optionally who said them.

    `attribution` is None far more often than it is a string -- every
    hand-written line in a user's own file will be one -- so None is the
    ordinary case here, not a degraded one.
    """

    text: str
    attribution: str | None


FALLBACK_QUOTE = Quote(FALLBACK, None)


def parse_line(line: str) -> Quote | None:
    """One raw line to one record, or None if there is nothing usable on it.

    None covers three different nothings, deliberately collapsed into one: a
    blank line, a comment, and a line whose quote text is empty after
    stripping ("||Someone"). Only the third is malformed; see `parse_text`,
    which is the caller that needs to tell them apart.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(COMMENT_PREFIX):
        return None
    # partition() splits on the first occurrence and hands back everything
    # after it untouched, which is exactly the rule: later delimiters stay
    # inside the attributor.
    text, found, attribution = stripped.partition(DELIMITER)
    text = text.strip()
    if not text:
        return None
    attribution = attribution.strip() if found else ""
    # "foo||" is a quote whose attributor is absent, not a quote attributed to
    # the empty string. It normalizes to the same None a bare line produces, so
    # nothing downstream has two ways to say "nobody".
    return Quote(text, attribution or None)


def parse_text(raw: str) -> tuple[list[Quote], list[str]]:
    """Parse a whole file's text into (records, lines skipped as malformed).

    The second element is what makes a typo'd delimiter loud instead of silent:
    a line that carried words but produced no record is returned rather than
    dropped, so a check over the shipped file can name it. Blank lines and
    comments are not malformed and never appear there.
    """
    records: list[Quote] = []
    malformed: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIX):
            continue
        record = parse_line(line)
        if record is None:
            malformed.append(stripped)
        else:
            records.append(record)
    return records, malformed


def _records(path: Path) -> list[Quote]:
    """The usable records of one quote file, or [] if there are none.

    A missing or unreadable file is an empty list, never an exception. Reads
    exactly the one path it is handed and nothing else.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return parse_text(raw)[0]


class QuoteSource:
    """Reads the quote files on every request. Injectable, like Storage (DECISIONS.md 3.7).

    Read-on-request rather than read-at-startup is a feature: editing a quote
    file shows up on the next page load with no restart.

    `user_path` is optional (DECISIONS.md 10.1, amended): when given, its
    records are unioned after `path`'s -- bundled quotes first, then the user's
    own, order otherwise preserved. A missing `user_path` is normal, not an
    error: it behaves exactly as it did before that file existed.
    """

    def __init__(self, path: Path | str, user_path: Path | str | None = None) -> None:
        self.path = Path(path)
        self.user_path = Path(user_path) if user_path is not None else None

    def load(self) -> list[Quote]:
        """The usable, deduplicated union of the bundled and user quote files.

        Deduplication keys on the QUOTE TEXT ALONE, case-sensitive, first
        occurrence winning (DECISIONS.md 10.1, amended). Keying on the whole
        record instead would let a user line that repeats a bundled quote with
        a different attributor -- or with none -- show up as a second copy of
        the same sentence, which is the one thing dedup exists to prevent. The
        bundled record's attribution wins because it is first, and the bundled
        list is the one that is reviewed.
        """
        records = _records(self.path)
        if self.user_path is not None:
            records += _records(self.user_path)
        seen: set[str] = set()
        union: list[Quote] = []
        for record in records:
            if record.text in seen:
                continue
            seen.add(record.text)
            union.append(record)
        return union

    def for_day(self, day: date) -> Quote:
        """The quote for one logical day. Same day in, same quote out. Always.

        The index is derived with sha256 rather than the builtin hash(): Python
        randomizes string hashing per process (PYTHONHASHSEED), so hash() would
        hand back a different quote after every server restart. sha256 of the
        day key is stable across processes, machines, and years.
        """
        quotes = self.load()
        if not quotes:
            return FALLBACK_QUOTE
        return quotes[quote_index(day, len(quotes))]


def quote_index(day: date, count: int) -> int:
    """Which quote a logical day maps to. Deterministic, process-independent."""
    digest = hashlib.sha256(day_key_str(day).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


USER_QUOTES_TEMPLATE = (
    "# Add your own quotes here, one per line.\n"
    "# Lines starting with # are ignored, same as this one.\n"
    "#\n"
    "# To credit someone, put two pipes and their name after the quote:\n"
    "#     A sentence worth keeping.||Who said it\n"
    "# Leaving that off is completely fine -- a plain line is a real quote.\n"
    "#\n"
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
