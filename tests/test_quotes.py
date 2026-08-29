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
from datetime import date, timedelta
from pathlib import Path

from app import quotes as quotes_module
from app.quotes import (
    FALLBACK,
    FALLBACK_QUOTE,
    Quote,
    QuoteSource,
    ensure_user_quotes_file,
    parse_line,
    parse_text,
    quote_index,
)

SAMPLE = ["first quote", "second quote", "third quote", "fourth quote"]
SAMPLE_RECORDS = [Quote(text, None) for text in SAMPLE]

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


def test_index_is_sha256_not_the_builtin_hash(quotes_file: Path):
    """Pins process-stability.

    Python randomizes str hashing per process (PYTHONHASHSEED), so an index built
    on the builtin hash() would hand her a different quote after every restart.
    Recomputing the expected index here independently locks sha256 in.
    """
    day = date(2026, 8, 24)
    digest = hashlib.sha256(day.isoformat().encode("utf-8")).digest()
    expected = int.from_bytes(digest[:8], "big") % len(SAMPLE)

    assert quote_index(day, len(SAMPLE)) == expected

    write_quotes(quotes_file, SAMPLE)
    assert QuoteSource(quotes_file).for_day(day).text == SAMPLE[expected]


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
    # (DECISIONS.md 10.1, amended). It is stdlib, knows nothing about the file
    # system, and cannot reach a path -- the forbidden list below is what this
    # test is actually defending.
    assert imported <= {"hashlib", "datetime", "date", "pathlib", "Path",
                        "dataclasses", "dataclass",
                        "daytime", "day_key_str", "annotations", "__future__"}
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
