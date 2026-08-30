"""The daily quote. See DECISIONS.md section 10.

Two things are being protected here. The first is that the quote she sees does
not change when she reloads the page. The second, and the more important one, is
that the quote path cannot touch the reading log -- not by accident, not after a
refactor, not ever.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from app import quotes as quotes_module
from app.quotes import (
    DECK_NAMESPACE,
    FALLBACK,
    FALLBACK_QUOTE,
    Quote,
    QuoteSource,
    cycle_bounds,
    cycle_position,
    day_number,
    deck,
    ensure_user_quotes_file,
    parse_line,
    parse_text,
    quote_index,
)

SAMPLE = ["first quote", "second quote", "third quote", "fourth quote"]
SAMPLE_RECORDS = [Quote(text, None) for text in SAMPLE]

# A realistic cycle length rather than a toy one. The walks below hardcode 51
# alongside it, so this number and those are one unit -- it is not meant to
# track the shipped count, which moves whenever quotes.txt is edited.
DECK_SAMPLE = [f"quote number {n:02d}" for n in range(51)]

# The one file this repo actually ships, checked as itself further down.
SHIPPED_QUOTES = Path(__file__).resolve().parent.parent / "quotes.txt"


def write_quotes(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def texts(records: list[Quote]) -> list[str]:
    return [record.text for record in records]


# -- rotation ----------------------------------------------------------- #


def test_same_day_gives_the_same_quote(quotes_file: Path):
    """Reloading the page all day never shuffles it."""
    write_quotes(quotes_file, SAMPLE)
    source = QuoteSource(quotes_file)
    day = date(2026, 8, 24)
    first = source.for_day(day)
    assert first.text in SAMPLE
    for _ in range(20):
        assert source.for_day(day) == first


def test_different_days_give_different_quotes(quotes_file: Path):
    """Rotation actually rotates: a month of days is not one repeated quote."""
    write_quotes(quotes_file, SAMPLE)
    source = QuoteSource(quotes_file)
    start = date(2026, 8, 1)
    seen = {source.for_day(start + timedelta(days=n)) for n in range(30)}
    assert len(seen) > 1


def test_the_deck_is_derived_with_sha256_not_the_builtin_hash():
    """Pins process-stability, which is the whole reason the shuffle is hand-rolled.

    Python randomizes str hashing per process (PYTHONHASHSEED), so a deck built
    on the builtin hash() would deal her a different order after every restart --
    and `random.shuffle` promises nothing across Python versions either.
    Recomputing the Fisher-Yates draws here from sha256 alone locks the
    derivation in: if the implementation ever reaches for another source of
    randomness, this fails.
    """
    cycle, count = 14507, len(DECK_SAMPLE)
    expected = list(range(count))
    for i in range(count - 1, 0, -1):
        material = f"{DECK_NAMESPACE}|{count}|{cycle}|{i}".encode("utf-8")
        j = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (i + 1)
        expected[i], expected[j] = expected[j], expected[i]

    assert deck(cycle, count) == expected


def test_the_deck_is_pinned_so_no_refactor_can_quietly_move_a_quote():
    """A literal, not a recomputation.

    Every other test here would still pass if the seed string changed, because
    they all check shape. This one checks the actual answer, so a change that
    moves every quote in every year onto a different day has to be made on
    purpose and shows up in this diff.
    """
    assert deck(0, 4) == [0, 2, 3, 1]
    assert deck(1, 4) == [3, 1, 0, 2]
    assert deck(0, 1) == [0]
    assert deck(14507, 51)[:6] == [42, 23, 30, 27, 13, 1]


def test_the_deck_is_always_a_permutation():
    """Dealing every card exactly once is the property the whole fix rests on."""
    for count in range(1, 60):
        for cycle in (0, 1, 2, 14507, 999_999):
            assert sorted(deck(cycle, count)) == list(range(count))


def test_quote_index_walks_the_deck_one_card_a_day():
    """Consecutive days are consecutive positions in the same deck."""
    count = len(DECK_SAMPLE)
    first, _ = cycle_bounds(date(2026, 8, 30), count)
    order = deck(cycle_position(first, count)[0], count)
    for position in range(count):
        day = date.fromordinal(day_number(first) + position)
        assert quote_index(day, count) == order[position]


# -- the promise: no repeat until the list is exhausted ------------------ #


def test_a_full_cycle_deals_every_quote_exactly_once(quotes_file: Path):
    """51 consecutive days, 51 quotes, no repeats. This is the bug's fix.

    The walk starts on a cycle boundary because that is what the promise is
    about: a *pass through the list*. An arbitrary 51-day window cannot have
    this property and never could -- if every window of length N were a
    permutation then s[i] would equal s[i+N] for every i, which is to say the
    list would be dealt in the same order forever and never reshuffle at all.
    """
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file)
    first, last = cycle_bounds(date(2026, 8, 30), len(DECK_SAMPLE))
    assert (last - first).days == len(DECK_SAMPLE) - 1

    walk = [source.for_day(first + timedelta(days=n)).text for n in range(51)]

    assert len(walk) == 51
    assert sorted(walk) == sorted(DECK_SAMPLE)
    assert len(set(walk)) == 51


def test_two_full_cycles_deal_every_quote_exactly_twice(quotes_file: Path):
    """102 days: two complete passes, each one complete on its own."""
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file)
    first, _ = cycle_bounds(date(2026, 8, 30), len(DECK_SAMPLE))

    walk = [source.for_day(first + timedelta(days=n)).text for n in range(102)]

    assert Counter(walk) == Counter({text: 2 for text in DECK_SAMPLE})
    assert len(set(walk[:51])) == 51
    assert len(set(walk[51:])) == 51


def test_consecutive_cycles_are_dealt_in_different_orders(quotes_file: Path):
    """A new deck is shuffled when the old one runs out -- not replayed."""
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file)
    first, _ = cycle_bounds(date(2026, 8, 30), len(DECK_SAMPLE))

    one = [source.for_day(first + timedelta(days=n)).text for n in range(51)]
    two = [source.for_day(first + timedelta(days=51 + n)).text for n in range(51)]

    assert sorted(one) == sorted(two)
    assert one != two


def test_no_quote_ever_waits_longer_than_two_cycles(quotes_file: Path):
    """What the promise buys over the old sha256 % len: a bounded wait.

    Worst case is last card of one deck to first card of the next, which is
    2N-1 days apart. The old form had no bound at all -- a quote could sit
    unshown for years while another turned up twice in a fortnight.
    """
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file)
    count = len(DECK_SAMPLE)
    first, _ = cycle_bounds(date(2026, 1, 1), count)

    last_seen: dict[str, int] = {}
    worst = 0
    for n in range(count * 12):
        text = source.for_day(first + timedelta(days=n)).text
        if text in last_seen:
            worst = max(worst, n - last_seen[text])
        last_seen[text] = n

    assert worst <= 2 * count - 1
    assert len(last_seen) == count


def test_the_shipped_list_is_dealt_completely_in_one_cycle():
    """The real file, the real count, the real walk."""
    source = QuoteSource(SHIPPED_QUOTES)
    quotes = source.load()
    first, last = cycle_bounds(date(2026, 8, 30), len(quotes))

    walk = [source.for_day(first + timedelta(days=n)).text for n in range(len(quotes))]

    assert sorted(walk) == sorted(texts(quotes))
    assert len(set(walk)) == len(quotes)
    assert first + timedelta(days=len(quotes) - 1) == last


def test_cycle_bounds_frames_the_pass_the_day_falls_in():
    count = len(DECK_SAMPLE)
    first, last = cycle_bounds(date(2026, 8, 30), count)
    assert first <= date(2026, 8, 30) <= last
    assert (last - first).days == count - 1
    # Every day inside those bounds reports the same bounds; the day after
    # reports the next pass.
    for n in range(count):
        assert cycle_bounds(first + timedelta(days=n), count) == (first, last)
    assert cycle_bounds(last + timedelta(days=1), count)[0] == last + timedelta(days=1)


def test_a_one_quote_list_is_that_quote_every_day(quotes_file: Path):
    """count == 1 must not divide by zero, wrap oddly, or blank the line."""
    write_quotes(quotes_file, ["the only one"])
    source = QuoteSource(quotes_file)
    for n in range(10):
        assert source.for_day(date(2026, 8, 30) + timedelta(days=n)).text == "the only one"


# -- the list changing underneath a cycle -------------------------------- #
#
# She edits my-quotes.txt whenever she likes, and the files are read on every
# request (10.4), so the length can change between one page load and the next.
# None of that may raise, and none of it may leave the message area blank.


def test_adding_a_quote_mid_cycle_does_not_crash(quotes_file: Path, user_quotes_file: Path):
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file, user_quotes_file)
    day = date(2026, 9, 15)
    assert source.for_day(day).text in DECK_SAMPLE

    write_quotes(user_quotes_file, ["a line she just typed"])
    after = source.for_day(day)
    assert after.text in DECK_SAMPLE + ["a line she just typed"]


def test_a_list_that_grows_every_day_never_indexes_past_the_end(
    quotes_file: Path, user_quotes_file: Path
):
    """The index is computed from the count that was just measured, so a list
    that changes size between requests can never point off the end."""
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file, user_quotes_file)
    mine: list[str] = []
    for n in range(60):
        mine.append(f"mine {n}")
        write_quotes(user_quotes_file, mine)
        quote = source.for_day(date(2026, 9, 1) + timedelta(days=n))
        assert quote.text in DECK_SAMPLE + mine


def test_a_list_that_shrinks_to_nothing_mid_cycle_falls_back(quotes_file: Path):
    """Emptying the file is not an error and never leaves a blank line (10.4)."""
    write_quotes(quotes_file, DECK_SAMPLE)
    source = QuoteSource(quotes_file)
    day = date(2026, 9, 15)
    assert source.for_day(day).text in DECK_SAMPLE

    quotes_file.write_text("", encoding="utf-8")
    assert source.for_day(day) == FALLBACK_QUOTE

    quotes_file.unlink()
    assert source.for_day(day) == FALLBACK_QUOTE


def test_the_grown_list_is_itself_dealt_completely(
    quotes_file: Path, user_quotes_file: Path
):
    """A quote added mid-cycle is not stranded: the next full pass over the new
    length deals it along with everything else, exactly once."""
    write_quotes(quotes_file, DECK_SAMPLE)
    write_quotes(user_quotes_file, ["hers, added late"])
    source = QuoteSource(quotes_file, user_quotes_file)
    grown = DECK_SAMPLE + ["hers, added late"]

    first, _ = cycle_bounds(date(2026, 9, 15), len(grown))
    walk = [source.for_day(first + timedelta(days=n)).text for n in range(len(grown))]

    assert sorted(walk) == sorted(grown)


def test_the_endpoint_survives_the_file_changing_between_requests(
    client, quotes_file: Path
):
    """The list shrinking one line at a time under a live server, down to
    nothing and back. Every response is a 200 with words in it."""
    for n in range(len(DECK_SAMPLE), 0, -1):
        write_quotes(quotes_file, DECK_SAMPLE[:n])
        response = client.get("/api/quote")
        assert response.status_code == 200
        assert response.json()["text"] in DECK_SAMPLE

    quotes_file.write_text("", encoding="utf-8")
    assert client.get("/api/quote").json() == {"text": FALLBACK, "attribution": None}

    write_quotes(quotes_file, DECK_SAMPLE)
    assert client.get("/api/quote").json()["text"] in DECK_SAMPLE


# -- the file format ---------------------------------------------------- #


def test_blank_lines_and_comments_are_ignored(quotes_file: Path):
    write_quotes(
        quotes_file,
        ["# a header comment", "", "   ", "only real quote", "  # indented comment  "],
    )
    source = QuoteSource(quotes_file)
    assert source.load() == [Quote("only real quote", None)]
    assert source.for_day(date(2026, 8, 24)).text == "only real quote"


def test_utf8_survives_the_round_trip(quotes_file: Path):
    write_quotes(quotes_file, ["Leer es soñar — con los ojos abiertos ✨||Anónimo"])
    assert QuoteSource(quotes_file).load() == [
        Quote("Leer es soñar — con los ojos abiertos ✨", "Anónimo")
    ]


# -- never an error, never an empty message area ------------------------ #


def test_missing_file_returns_the_fallback(quotes_file: Path):
    assert not quotes_file.exists()
    assert QuoteSource(quotes_file).for_day(date(2026, 8, 24)) == FALLBACK_QUOTE


def test_empty_file_returns_the_fallback(quotes_file: Path):
    quotes_file.write_text("", encoding="utf-8")
    assert QuoteSource(quotes_file).for_day(date(2026, 8, 24)) == FALLBACK_QUOTE


def test_comments_only_file_returns_the_fallback(quotes_file: Path):
    write_quotes(quotes_file, ["# nothing but comments", "#", ""])
    assert QuoteSource(quotes_file).for_day(date(2026, 8, 24)) == FALLBACK_QUOTE


def test_missing_file_is_a_200_not_an_error(client, quotes_file: Path):
    assert not quotes_file.exists()
    response = client.get("/api/quote")
    assert response.status_code == 200
    assert response.json() == {"text": FALLBACK, "attribution": None}


# -- the endpoint ------------------------------------------------------- #


def test_endpoint_returns_a_quote_and_is_stable_across_requests(client, quotes_file):
    write_quotes(quotes_file, SAMPLE)
    first = client.get("/api/quote").json()["text"]
    assert first in SAMPLE
    for _ in range(5):
        assert client.get("/api/quote").json()["text"] == first


def test_editing_the_file_shows_up_without_a_restart(client, quotes_file: Path):
    """Read-on-request, not read-at-startup: she edits quotes.txt, reloads, done."""
    write_quotes(quotes_file, ["the old one"])
    assert client.get("/api/quote").json()["text"] == "the old one"

    write_quotes(quotes_file, ["the new one"])
    assert client.get("/api/quote").json()["text"] == "the new one"


def test_response_carries_the_quote_and_nothing_else(client, quotes_file: Path):
    write_quotes(quotes_file, SAMPLE)
    assert set(client.get("/api/quote").json()) == {"text", "attribution"}


# -- the union with the user's own file, DECISIONS.md 10.1 amended ------ #


def test_bundled_only_when_user_file_absent(quotes_file: Path, user_quotes_file: Path):
    write_quotes(quotes_file, SAMPLE)
    assert not user_quotes_file.exists()
    source = QuoteSource(quotes_file, user_quotes_file)
    assert source.load() == SAMPLE_RECORDS


def test_bundled_and_user_lines_are_unioned_bundled_first(
    quotes_file: Path, user_quotes_file: Path
):
    write_quotes(quotes_file, ["bundled one", "bundled two"])
    write_quotes(user_quotes_file, ["my own quote"])
    source = QuoteSource(quotes_file, user_quotes_file)
    assert texts(source.load()) == ["bundled one", "bundled two", "my own quote"]


def test_exact_duplicates_between_bundled_and_user_are_dropped(
    quotes_file: Path, user_quotes_file: Path
):
    write_quotes(quotes_file, ["shared quote", "bundled only"])
    write_quotes(user_quotes_file, ["shared quote", "user only"])
    source = QuoteSource(quotes_file, user_quotes_file)
    assert texts(source.load()) == ["shared quote", "bundled only", "user only"]


def test_blank_lines_and_comments_in_user_file_are_ignored(
    quotes_file: Path, user_quotes_file: Path
):
    write_quotes(quotes_file, ["bundled quote"])
    write_quotes(user_quotes_file, ["# a comment", "", "   ", "my quote"])
    source = QuoteSource(quotes_file, user_quotes_file)
    assert texts(source.load()) == ["bundled quote", "my quote"]


def test_missing_user_file_is_normal_not_an_error(quotes_file: Path, user_quotes_file: Path):
    write_quotes(quotes_file, SAMPLE)
    assert not user_quotes_file.exists()
    assert QuoteSource(quotes_file, user_quotes_file).for_day(date(2026, 8, 24)).text in SAMPLE


def test_unreadable_user_file_falls_back_to_bundled_only(
    quotes_file: Path, user_quotes_file: Path
):
    write_quotes(quotes_file, SAMPLE)
    user_quotes_file.mkdir()  # a directory where a file is expected -> OSError on read
    source = QuoteSource(quotes_file, user_quotes_file)
    assert source.load() == SAMPLE_RECORDS


def test_user_only_lines_still_work_with_no_bundled_quotes(
    quotes_file: Path, user_quotes_file: Path
):
    assert not quotes_file.exists()
    write_quotes(user_quotes_file, ["only mine"])
    source = QuoteSource(quotes_file, user_quotes_file)
    assert source.load() == [Quote("only mine", None)]


def test_no_user_path_at_all_behaves_exactly_as_before(quotes_file: Path):
    """The single-argument constructor -- what every other test in this file
    still uses -- is unaffected by the union feature."""
    write_quotes(quotes_file, SAMPLE)
    assert QuoteSource(quotes_file).load() == SAMPLE_RECORDS


# -- creating the user's file on first run ------------------------------- #


def test_ensure_user_quotes_file_creates_instructions_only(user_quotes_file: Path):
    assert not user_quotes_file.exists()
    ensure_user_quotes_file(user_quotes_file)
    assert user_quotes_file.exists()
    lines = user_quotes_file.read_text(encoding="utf-8").splitlines()
    assert all(line.strip() == "" or line.strip().startswith("#") for line in lines)
    # The freshly created file contributes nothing to the union yet.
    assert QuoteSource(user_quotes_file).load() == []


def test_ensure_user_quotes_file_never_touches_an_existing_one(user_quotes_file: Path):
    write_quotes(user_quotes_file, ["her own quote, already there"])
    ensure_user_quotes_file(user_quotes_file)
    assert user_quotes_file.read_text(encoding="utf-8").splitlines()[0] == (
        "her own quote, already there"
    )


def test_ensure_user_quotes_file_is_never_an_error_when_unwritable(
    tmp_path: Path,
):
    """A read-only parent directory must not raise -- the invitation simply
    doesn't appear, same as every other missing-file case in this module."""
    missing_parent = tmp_path / "does" / "not" / "exist" / "my-quotes.txt"
    ensure_user_quotes_file(missing_parent)  # must not raise
    assert not missing_parent.exists()


# -- the separation, which is the point --------------------------------- #


def test_quote_requests_never_touch_the_data_file(client, storage, quotes_file, data_file):
    """The reading log is byte-for-byte identical after hammering /api/quote."""
    write_quotes(quotes_file, SAMPLE)
    client.post("/api/entries", json={"page_start": 1, "page_end": 10})

    before_bytes = data_file.read_bytes()
    before_mtime = data_file.stat().st_mtime_ns

    for _ in range(25):
        assert client.get("/api/quote").status_code == 200

    assert data_file.read_bytes() == before_bytes
    assert data_file.stat().st_mtime_ns == before_mtime
    assert len(json.loads(before_bytes)["entries"]) == 1


def test_quotes_module_cannot_reach_the_reading_log():
    """The structural guarantee, asserted rather than trusted.

    DECISIONS.md 10 says editing quotes must be structurally incapable of
    touching the reading log. The enforcement is app/quotes.py's import list: no
    storage, no config, no json, nothing that knows where entries.json lives.
    Checking the parsed imports rather than the raw text means prose about the
    rule does not trip the test that enforces it.

    If a future change makes this fail, that change is the bug.
    """
    tree = ast.parse(inspect.getsource(quotes_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            imported.update(alias.name for alias in node.names)

    # `dataclasses` joined the list when a quote stopped being a bare string
    # (DECISIONS.md 10.1, amended). `daytime` LEFT it when rotation became a
    # walk over day numbers (10.3, amended) -- the module is handed a resolved
    # logical date and only needs its ordinal, so it no longer imports anything
    # from this project at all. Everything left is stdlib that knows nothing
    # about the file system; the forbidden list below is what this test is
    # actually defending.
    assert imported <= {"hashlib", "datetime", "date", "pathlib", "Path",
                        "dataclasses", "dataclass",
                        "annotations", "__future__"}
    for forbidden in ("storage", "Storage", "config", "json"):
        assert forbidden not in imported

    # And no string literal in it names the data file. Docstrings are excluded --
    # this module's prose explains the rule, which is not the same as breaking it.
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]
    for text in literals:
        assert "entries.json" not in text
        assert "data" not in text


# -- the attribution delimiter, DECISIONS.md 10.2 amended --------------- #
#
# The rule that matters most in this block is the SECOND test. Her own
# hand-written lines will have no delimiter at all, and a parser that treated
# that as an error -- or even as something to warn about -- would turn her own
# file into a source of complaints. A bare line is a whole, valid record.


def test_a_line_with_a_delimiter_splits_into_text_and_attributor():
    assert parse_line("A sentence worth keeping.||Someone") == Quote(
        "A sentence worth keeping.", "Someone"
    )


def test_a_line_with_no_delimiter_is_a_valid_record_with_no_attributor():
    """Her hand-written lines look like this. Never an error, never a warning."""
    assert parse_line("Just the words.") == Quote("Just the words.", None)


def test_whitespace_is_stripped_from_both_fields_independently():
    assert parse_line("   spaced out   ||   Someone Else   ") == Quote(
        "spaced out", "Someone Else"
    )
    assert parse_line("\ttabbed\t||\tName\t") == Quote("tabbed", "Name")


def test_an_empty_attributor_normalizes_to_none():
    """"foo||" is a quote with no attributor, not one attributed to "" --
    there is exactly one way to say "nobody" downstream."""
    assert parse_line("foo||") == Quote("foo", None)
    assert parse_line("foo||    ") == Quote("foo", None)


def test_empty_quote_text_is_skipped_as_malformed():
    assert parse_line("||Someone") is None
    assert parse_line("   ||Someone") is None


def test_the_split_is_on_the_first_delimiter_only():
    """A later "||" belongs to the attributor and stays inside it."""
    assert parse_line("the words||Someone||and another") == Quote(
        "the words", "Someone||and another"
    )
    assert parse_line("a||b||c||d") == Quote("a", "b||c||d")


def test_a_delimiter_inside_the_attributor_survives_a_round_trip(quotes_file: Path):
    write_quotes(quotes_file, ["quoted line||A, quoted by B||C"])
    assert QuoteSource(quotes_file).load() == [Quote("quoted line", "A, quoted by B||C")]


def test_comments_and_blank_lines_are_not_malformed():
    """Only a line that carried words but produced no record is malformed."""
    records, malformed = parse_text("# a comment\n\n   \n  # indented\nreal||Name\n")
    assert records == [Quote("real", "Name")]
    assert malformed == []


def test_parse_text_reports_the_malformed_lines_it_skipped():
    """A typo'd delimiter must be loud, not silent -- the skipped line comes
    back so a check over the shipped file can name it."""
    records, malformed = parse_text("good||Name\n||orphan\nalso good\n   ||  \n")
    assert records == [Quote("good", "Name"), Quote("also good", None)]
    assert malformed == ["||orphan", "||"]


def test_a_mixed_file_parses_both_shapes(quotes_file: Path):
    write_quotes(quotes_file, ["attributed||Someone", "bare line", "another||Else"])
    assert QuoteSource(quotes_file).load() == [
        Quote("attributed", "Someone"),
        Quote("bare line", None),
        Quote("another", "Else"),
    ]


# -- dedupe keys on the quote text alone -------------------------------- #


def test_dedupe_keys_on_quote_text_not_the_whole_line(
    quotes_file: Path, user_quotes_file: Path
):
    """A user line that repeats a bundled quote with a different attributor is
    still a duplicate: the same sentence must not appear twice."""
    write_quotes(quotes_file, ["the same words||Bundled Attributor"])
    write_quotes(user_quotes_file, ["the same words||Someone Else Entirely"])
    assert QuoteSource(quotes_file, user_quotes_file).load() == [
        Quote("the same words", "Bundled Attributor")
    ]


def test_first_occurrence_wins_so_a_bundled_quote_is_never_displaced(
    quotes_file: Path, user_quotes_file: Path
):
    """Union order is unchanged: bundled first, and the bundled record's
    attribution is the one that survives."""
    write_quotes(quotes_file, ["shared||Reviewed Name"])
    write_quotes(user_quotes_file, ["shared", "shared||Third Name", "genuinely new"])
    assert QuoteSource(quotes_file, user_quotes_file).load() == [
        Quote("shared", "Reviewed Name"),
        Quote("genuinely new", None),
    ]


def test_a_user_line_may_add_an_attributor_only_to_a_quote_that_is_not_bundled(
    quotes_file: Path, user_quotes_file: Path
):
    write_quotes(quotes_file, ["bundled one"])
    write_quotes(user_quotes_file, ["mine||My Attributor"])
    assert QuoteSource(quotes_file, user_quotes_file).load() == [
        Quote("bundled one", None),
        Quote("mine", "My Attributor"),
    ]


def test_dedupe_is_case_sensitive(quotes_file: Path, user_quotes_file: Path):
    """Two spellings are two quotes. Case-folding would silently drop a line
    she deliberately capitalized differently."""
    write_quotes(quotes_file, ["The Words"])
    write_quotes(user_quotes_file, ["the words"])
    assert texts(QuoteSource(quotes_file, user_quotes_file).load()) == [
        "The Words",
        "the words",
    ]


def test_duplicates_within_one_file_are_dropped_too(quotes_file: Path):
    write_quotes(quotes_file, ["repeated||First", "other", "repeated||Second"])
    assert QuoteSource(quotes_file).load() == [
        Quote("repeated", "First"),
        Quote("other", None),
    ]


# -- the API response shape --------------------------------------------- #


def test_endpoint_returns_the_attribution_when_there_is_one(client, quotes_file: Path):
    write_quotes(quotes_file, ["the only quote||Someone Real"])
    assert client.get("/api/quote").json() == {
        "text": "the only quote",
        "attribution": "Someone Real",
    }


def test_endpoint_returns_a_null_attribution_when_there_is_none(client, quotes_file: Path):
    """Null, and present. An absent key would make the front end's "render
    nothing" branch depend on a key check instead of a value check."""
    write_quotes(quotes_file, ["the only quote"])
    body = client.get("/api/quote").json()
    assert body == {"text": "the only quote", "attribution": None}
    assert "attribution" in body


def test_the_openapi_schema_describes_the_new_shape(client):
    """The schema is generated locally and is the only API documentation this
    app ships (DECISIONS.md 5), so it has to be right."""
    schema = client.get("/openapi.json").json()
    quote_out = schema["components"]["schemas"]["QuoteOut"]
    assert set(quote_out["properties"]) == {"text", "attribution"}
    assert quote_out["properties"]["text"]["type"] == "string"
    # attribution is nullable: anyOf[string, null] in OpenAPI 3.1.
    assert {"type": "null"} in quote_out["properties"]["attribution"]["anyOf"]
    assert "quote" not in quote_out["properties"]


# -- the shipped file actually parses ------------------------------------ #


def test_every_line_of_the_shipped_quotes_file_parses(capsys):
    """A typo'd delimiter drops a quote silently. This is what makes it loud.

    Counts are printed so a build or a review can read them off directly:
    run with -s, or read the captured output on failure.
    """
    raw = SHIPPED_QUOTES.read_text(encoding="utf-8")
    records, malformed = parse_text(raw)

    candidates = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    with capsys.disabled():
        print(f"\nshipped quotes.txt: {len(records)} parsed, {len(malformed)} malformed")

    assert malformed == [], f"malformed lines in quotes.txt: {malformed}"
    assert len(records) == len(candidates)
    assert records, "the shipped file must carry at least one quote"
    # Every record has real text; that is what "valid" means here.
    assert all(record.text for record in records)


def test_the_shipped_file_survives_the_union_without_losing_a_quote(
    tmp_path: Path,
):
    """Dedupe must not silently eat a shipped line -- if two bundled lines ever
    carry identical text, this is where it surfaces."""
    records, _ = parse_text(SHIPPED_QUOTES.read_text(encoding="utf-8"))
    assert len(QuoteSource(SHIPPED_QUOTES).load()) == len(records)


# -- the parser touches nothing but the two paths it is handed ----------- #


def test_the_parser_reads_only_the_two_paths_it_is_given(monkeypatch, tmp_path: Path):
    """DECISIONS.md 10.1: nothing in the quote path may open anything else.

    The AST test above proves this module cannot NAME another file. This one
    proves it does not READ or WRITE one either, by recording every path that
    goes through Path's read/write methods while a whole request's worth of
    quote work runs.
    """
    bundled = tmp_path / "quotes.txt"
    mine = tmp_path / "my-quotes.txt"
    write_quotes(bundled, ["bundled||Name"])
    write_quotes(mine, ["mine"])

    reads: list[Path] = []
    writes: list[Path] = []
    real_read = Path.read_text
    real_write = Path.write_text
    real_read_bytes = Path.read_bytes
    real_write_bytes = Path.write_bytes

    def spy_read(self, *args, **kwargs):
        reads.append(self)
        return real_read(self, *args, **kwargs)

    def spy_write(self, *args, **kwargs):
        writes.append(self)
        return real_write(self, *args, **kwargs)

    def spy_read_bytes(self, *args, **kwargs):
        reads.append(self)
        return real_read_bytes(self, *args, **kwargs)

    def spy_write_bytes(self, *args, **kwargs):
        writes.append(self)
        return real_write_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read)
    monkeypatch.setattr(Path, "write_text", spy_write)
    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    monkeypatch.setattr(Path, "write_bytes", spy_write_bytes)

    source = QuoteSource(bundled, mine)
    source.load()
    source.for_day(date(2026, 8, 24))
    ensure_user_quotes_file(mine)

    assert set(reads) <= {bundled, mine}
    # ensure_user_quotes_file short-circuits on an existing file, so nothing is
    # written at all here -- and when it does write, only to the path given.
    assert set(writes) <= {mine}


def test_the_only_path_under_the_user_directory_is_the_one_it_is_handed(
    monkeypatch, tmp_path: Path
):
    """The write side, exercised: a first run creates my-quotes.txt and
    touches nothing else beside it."""
    data_root = tmp_path / "PinkPageCount"
    data_root.mkdir()
    # Files that would be next to it in the real DATA_ROOT (DECISIONS.md 14).
    for neighbour in ("entries.json", "classes.json", "settings.json"):
        (data_root / neighbour).write_text("{}", encoding="utf-8")
    before = {
        path.name: path.read_bytes() for path in data_root.iterdir()
    }

    mine = data_root / "my-quotes.txt"
    touched: list[Path] = []
    real_write = Path.write_text

    def spy_write(self, *args, **kwargs):
        touched.append(self)
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write)
    ensure_user_quotes_file(mine)

    assert touched == [mine]
    assert mine.exists()
    for name, content in before.items():
        assert (data_root / name).read_bytes() == content
