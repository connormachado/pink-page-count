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
from app.quotes import FALLBACK, QuoteSource, quote_index

SAMPLE = ["first quote", "second quote", "third quote", "fourth quote"]


def write_quotes(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- rotation ----------------------------------------------------------- #


def test_same_day_gives_the_same_quote(quotes_file: Path):
    """Reloading the page all day never shuffles it."""
    write_quotes(quotes_file, SAMPLE)
    source = QuoteSource(quotes_file)
    day = date(2026, 8, 24)
    first = source.for_day(day)
    assert first in SAMPLE
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
    assert QuoteSource(quotes_file).for_day(day) == SAMPLE[expected]


# -- the file format ---------------------------------------------------- #


def test_blank_lines_and_comments_are_ignored(quotes_file: Path):
    write_quotes(
        quotes_file,
        ["# a header comment", "", "   ", "only real quote", "  # indented comment  "],
    )
    source = QuoteSource(quotes_file)
    assert source.load() == ["only real quote"]
    assert source.for_day(date(2026, 8, 24)) == "only real quote"


def test_utf8_survives_the_round_trip(quotes_file: Path):
    write_quotes(quotes_file, ["Leer es soñar — con los ojos abiertos ✨"])
    assert QuoteSource(quotes_file).load() == ["Leer es soñar — con los ojos abiertos ✨"]


# -- never an error, never an empty message area ------------------------ #


def test_missing_file_returns_the_fallback(quotes_file: Path):
    assert not quotes_file.exists()
    assert QuoteSource(quotes_file).for_day(date(2026, 8, 24)) == FALLBACK


def test_empty_file_returns_the_fallback(quotes_file: Path):
    quotes_file.write_text("", encoding="utf-8")
    assert QuoteSource(quotes_file).for_day(date(2026, 8, 24)) == FALLBACK


def test_comments_only_file_returns_the_fallback(quotes_file: Path):
    write_quotes(quotes_file, ["# nothing but comments", "#", ""])
    assert QuoteSource(quotes_file).for_day(date(2026, 8, 24)) == FALLBACK


def test_missing_file_is_a_200_not_an_error(client, quotes_file: Path):
    assert not quotes_file.exists()
    response = client.get("/api/quote")
    assert response.status_code == 200
    assert response.json() == {"quote": FALLBACK}


# -- the endpoint ------------------------------------------------------- #


def test_endpoint_returns_a_quote_and_is_stable_across_requests(client, quotes_file):
    write_quotes(quotes_file, SAMPLE)
    first = client.get("/api/quote").json()["quote"]
    assert first in SAMPLE
    for _ in range(5):
        assert client.get("/api/quote").json()["quote"] == first


def test_editing_the_file_shows_up_without_a_restart(client, quotes_file: Path):
    """Read-on-request, not read-at-startup: she edits quotes.txt, reloads, done."""
    write_quotes(quotes_file, ["the old one"])
    assert client.get("/api/quote").json()["quote"] == "the old one"

    write_quotes(quotes_file, ["the new one"])
    assert client.get("/api/quote").json()["quote"] == "the new one"


def test_response_carries_the_quote_and_nothing_else(client, quotes_file: Path):
    write_quotes(quotes_file, SAMPLE)
    assert set(client.get("/api/quote").json()) == {"quote"}


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

    assert imported <= {"hashlib", "datetime", "date", "pathlib", "Path",
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
