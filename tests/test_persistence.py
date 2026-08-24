"""Restart survival, atomic writes, and refusing to start on a corrupt file.

See DECISIONS.md 3.1-3.5. This is the most important test file in the project.
"""

from __future__ import annotations

import json
import os

import pytest

from app.storage import CorruptDataFile, Storage, atomic_write_json, load_storage_or_exit


def test_entries_survive_a_restart(data_file):
    first = Storage(data_file)
    created = [
        first.create(page_start=43, page_end=71, note="chapter 4"),
        first.create(page_start=72, page_end=90, note=None),
        first.create(page_start=91, page_end=91, note="one page"),
    ]
    del first  # the process is gone; nothing is in memory any more

    reloaded = Storage(data_file)
    survivors = reloaded.all()

    assert len(survivors) == 3
    assert [entry["id"] for entry in survivors] == [entry["id"] for entry in created]
    assert survivors == created


def test_restart_through_the_api_keeps_the_entries(data_file):
    """Write through one app, throw it away, and read through a fresh one."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(Storage(data_file))) as first:
        first.post("/api/entries", json={"page_start": 43, "page_end": 71})
        first.post("/api/entries", json={"page_start": 100, "page_end": 100})

    with TestClient(create_app(Storage(data_file))) as second:
        entries = second.get("/api/entries").json()

    assert len(entries) == 2
    assert {entry["pages"] for entry in entries} == {29, 1}


def test_missing_file_is_created_empty(data_file):
    assert not data_file.exists()
    storage = Storage(data_file)
    assert storage.all() == []
    document = json.loads(data_file.read_text(encoding="utf-8"))
    assert document == {"schema_version": 1, "entries": []}


def test_file_is_pretty_printed_and_hand_editable(data_file):
    storage = Storage(data_file)
    storage.create(page_start=1, page_end=2, note="hello")
    text = data_file.read_text(encoding="utf-8")
    assert "\n  " in text  # indented, not one long line
    assert text.endswith("\n")
    assert json.loads(text)["schema_version"] == 1


def test_a_hand_edit_is_picked_up_on_restart(data_file):
    storage = Storage(data_file)
    storage.create(page_start=1, page_end=2, note="before")
    document = json.loads(data_file.read_text(encoding="utf-8"))
    document["entries"][0]["note"] = "edited by hand"
    data_file.write_text(json.dumps(document, indent=2), encoding="utf-8")

    assert Storage(data_file).all()[0]["note"] == "edited by hand"


def test_updates_and_deletes_are_persisted(data_file):
    storage = Storage(data_file)
    keep = storage.create(page_start=1, page_end=2)
    doomed = storage.create(page_start=3, page_end=4)
    storage.update(keep["id"], {"note": "kept"})
    storage.delete(doomed["id"])

    reloaded = Storage(data_file).all()
    assert len(reloaded) == 1
    assert reloaded[0]["note"] == "kept"


def test_no_temp_files_are_left_behind(data_file):
    storage = Storage(data_file)
    for page in range(5):
        storage.create(page_start=page, page_end=page)
    leftovers = [name for name in os.listdir(data_file.parent) if name != data_file.name]
    assert leftovers == []


def test_a_failed_write_leaves_the_original_file_intact(data_file):
    """Serialization happens before anything is written, so an unserializable payload
    cannot truncate the real file."""
    storage = Storage(data_file)
    storage.create(page_start=43, page_end=71)
    before = data_file.read_bytes()

    with pytest.raises(TypeError):
        atomic_write_json(data_file, {"schema_version": 1, "entries": [{1, 2, 3}]})

    assert data_file.read_bytes() == before
    assert [name for name in os.listdir(data_file.parent) if name != data_file.name] == []


# --------------------------------------------------------------------------- #
# DECISIONS.md 3.4: a corrupt file is a halt, not a recovery.
# --------------------------------------------------------------------------- #

CORRUPT_FILES = {
    "truncated": '{"schema_version": 1, "entries": [{"id": "a"',
    "not_json": "this is not json at all",
    "empty": "",
    "top_level_list": "[]",
    "missing_entries": '{"schema_version": 1}',
    "entries_not_a_list": '{"schema_version": 1, "entries": {}}',
    "entry_missing_field": '{"schema_version": 1, "entries": [{"id": "a"}]}',
    "entry_bad_pages": (
        '{"schema_version": 1, "entries": [{"id": "a", "page_start": 40, '
        '"page_end": 12, "read_at": "2026-08-24T12:00:00-04:00", "note": null, '
        '"created_at": "2026-08-24T12:00:00-04:00", '
        '"updated_at": "2026-08-24T12:00:00-04:00"}]}'
    ),
    "entry_bad_timestamp": (
        '{"schema_version": 1, "entries": [{"id": "a", "page_start": 1, '
        '"page_end": 2, "read_at": "yesterday", "note": null, '
        '"created_at": "2026-08-24T12:00:00-04:00", '
        '"updated_at": "2026-08-24T12:00:00-04:00"}]}'
    ),
    "future_schema_version": '{"schema_version": 99, "entries": []}',
}


@pytest.mark.parametrize("name", sorted(CORRUPT_FILES))
def test_corrupt_file_raises_instead_of_loading(data_file, name):
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(CORRUPT_FILES[name], encoding="utf-8")
    with pytest.raises(CorruptDataFile):
        Storage(data_file)


@pytest.mark.parametrize("name", sorted(CORRUPT_FILES))
def test_corrupt_file_is_never_modified_moved_or_copied(data_file, name):
    """The file stays exactly where it is, byte for byte, and nothing is created
    beside it -- no quarantine copy, no fresh empty file."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_bytes(CORRUPT_FILES[name].encode("utf-8"))
    before = data_file.read_bytes()

    with pytest.raises(CorruptDataFile):
        Storage(data_file)

    assert data_file.read_bytes() == before
    assert os.listdir(data_file.parent) == [data_file.name]


def test_corrupt_file_exits_non_zero_with_a_banner(data_file, capsys):
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(CORRUPT_FILES["truncated"], encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        load_storage_or_exit(data_file)

    assert exit_info.value.code != 0
    banner = capsys.readouterr().err
    assert str(data_file) in banner
    assert "WILL NOT START" in banner
    assert "NOT been changed" in banner


def test_banner_names_the_line_of_a_json_syntax_error(data_file):
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(
        '{\n  "schema_version": 1,\n  "entries": [ oops ]\n}\n', encoding="utf-8"
    )
    with pytest.raises(CorruptDataFile) as caught:
        Storage(data_file)
    assert caught.value.line == 3
    assert "line 3" in caught.value.banner()


def test_an_unknown_field_is_corruption_not_a_silent_drop(data_file):
    """A typo'd key would otherwise be discarded on the next write."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    good = Storage(data_file)
    good.create(page_start=1, page_end=2, note="keep me")
    document = json.loads(data_file.read_text(encoding="utf-8"))
    document["entries"][0]["note_typo"] = "important"
    data_file.write_text(json.dumps(document, indent=2), encoding="utf-8")

    with pytest.raises(CorruptDataFile):
        Storage(data_file)
