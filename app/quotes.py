"""The daily quote. See DECISIONS.md sections 10 and 8.

This module is deliberately tiny and deliberately isolated. Look at the import
list: `hashlib`, `pathlib`, and `dataclasses`, all stdlib and none of them able
to name a file on their own. It does not import `storage`, it does not import
`config`, and it never learns the path to the reading log. That is not restraint
at call time -- it is the structural guarantee DECISIONS.md 10 asks for. Editing
quotes cannot touch the reading log because nothing in this file knows the
reading log exists.

DECISIONS.md 10.1 (amended): a `QuoteSource` reads two files -- the bundled,
canonical list and an optional file the user owns -- and unions them. Both
paths are handed in by the caller; this module still never names the reading
log or any other file under the user's directory.

DECISIONS.md 10.2 (amended): a line is `<quote text>||<attributor>`. The
attributor is optional and a line without one is an ordinary, valid record --
never a warning, never a skip. A hand-written file of bare sentences parses
exactly as it did before this feature existed.

DECISIONS.md 10.3 (amended): rotation is a walk through a shuffled deck, not
`sha256(day) % len`. Every quote is dealt once before any is dealt twice. The
walk is derived from the day count and the list length and is written down
nowhere -- there is no rotation state on disk, and the module's import list got
SHORTER as a result, not longer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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

        Reads the files first, so a list that grew since the last request is the
        list this day is resolved against. The index can therefore never point
        past the end: it is computed from the count that was just measured.
        """
        quotes = self.load()
        if not quotes:
            return FALLBACK_QUOTE
        return quotes[quote_index(day, len(quotes))]


# -- rotation, DECISIONS.md 10.3 (amended) ------------------------------- #
#
# Deal a shuffled deck, one card a day, and shuffle a fresh one when the deck
# runs out. The old form -- sha256(day_key) % len -- was a fresh independent
# draw every day, which is not a rotation at all: it could repeat a quote a
# fortnight apart while another had never been shown once.

# Everything about the deal hangs off this string. Changing it reshuffles every
# deck in every year, which is exactly why it is a named constant with a version
# in it: a future change to the shuffle has to be made on purpose.
DECK_NAMESPACE = "pink-page-count/quote-deck/v1"


def day_number(day: date) -> int:
    """The logical day as a plain count of days.

    `date.toordinal()` counts from an arbitrary origin, which is all a rotation
    needs -- it only ever looks at differences. The 4am boundary (DECISIONS.md
    2.3) is applied by `daytime.day_key` before a date ever reaches this module,
    so there is still no second implementation of it here; this function does
    arithmetic on an answer someone else already gave.
    """
    return day.toordinal()


def cycle_position(day: date, count: int) -> tuple[int, int]:
    """(which pass through the list, how far into that pass) for one logical day.

    Both fall out of one floor division, so the walk needs nothing remembered
    between days: day N+1 lands on the next card because 'the next card' is
    arithmetic, not a saved cursor.
    """
    return divmod(day_number(day), count)


def deck(cycle: int, count: int) -> list[int]:
    """The order one pass through the list is dealt in: a permutation of range(count).

    Fisher-Yates, with every draw pulled from a sha256 stream keyed on the cycle
    number instead of from `random`. Hand-rolled for the reason 10.3 already
    gives for preferring sha256 to the builtin hash(): the answer has to be
    identical across processes, machines, Python versions and years, and
    `random`'s internals promise none of that. It also means this module needs
    no import it did not already have.

    Every index appears exactly once, so a pass deals every quote exactly once.

    The draw is a 64-bit number reduced modulo at most `count`; for any list a
    person would keep in a text file the resulting bias is on the order of
    1e-17, which is not a number that shows up as a quote you saw too often.
    """
    order = list(range(count))
    for i in range(count - 1, 0, -1):
        j = _draw(cycle, count, i) % (i + 1)
        order[i], order[j] = order[j], order[i]
    return order


def _draw(cycle: int, count: int, step: int) -> int:
    """One deterministic 64-bit draw for one step of one deck's shuffle."""
    material = f"{DECK_NAMESPACE}|{count}|{cycle}|{step}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def quote_index(day: date, count: int) -> int:
    """Which quote a logical day maps to. Deterministic, process-independent.

    `count` must be at least 1; `for_day` returns the fallback before it gets
    here when the list is empty.
    """
    cycle, position = cycle_position(day, count)
    return deck(cycle, count)[position]


def cycle_bounds(day: date, count: int) -> tuple[date, date]:
    """First and last day of the pass through the list that `day` falls in.

    The second date is the day the list is exhausted -- the last day of the
    current deck, after which a new one is shuffled. Exposed because "when do we
    run out of quotes" is a question worth being able to answer without running
    the rotation by hand for a year.
    """
    _, position = cycle_position(day, count)
    first = date.fromordinal(day_number(day) - position)
    return first, date.fromordinal(day_number(first) + count - 1)


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
