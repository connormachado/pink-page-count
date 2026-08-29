"""Classes: the schema bump, the picker's contract, and above all that deleting a
class never touches a reading entry.

See DECISIONS.md section 12, plus 1.4 (read-time migration) and 3.8 (write order).
"""

from __future__ import annotations

import json

import pytest

from app.classes import ClassStore, load_class_store_or_exit
from app.jsonfile import CorruptDataFile
from app.storage import Storage

# A file exactly as Phase 3 code would have written it: version 1, no class_id keys.
V1_DOCUMENT = {
    "schema_version": 1,
    "entries": [
        {
            "id": "3f2a1c8e-5b7d-4e19-9c02-8a6f1d4b7e30",
            "page_start": 43,
            "page_end": 71,
            "read_at": "2026-08-20T21:12:00-04:00",
            "note": "chapter 4",
            "created_at": "2026-08-20T21:12:03-04:00",
            "updated_at": "2026-08-20T21:12:03-04:00",
        },
        {
            "id": "9c1b7e40-3a2d-4f88-b015-7e6d2c9a4f11",
            "page_start": 72,
            "page_end": 90,
            "read_at": "2026-08-21T08:04:00-04:00",
            "note": None,
            "created_at": "2026-08-21T08:04:02-04:00",
            "updated_at": "2026-08-21T08:04:02-04:00",
        },
        {
            "id": "b2d5f913-8c47-4a60-9de1-05f3a7b6c284",
            "page_start": 91,
            "page_end": 91,
            "read_at": "2026-08-22T22:40:00-04:00",
            "note": "one page",
            "created_at": "2026-08-22T22:40:01-04:00",
            "updated_at": "2026-08-22T22:40:01-04:00",
        },
    ],
}


def write_v1(data_file):
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(V1_DOCUMENT, indent=2) + "\n", encoding="utf-8")
    return data_file


def make_class(client, title="Bio 12", **extra):
    response = client.post("/api/classes", json={"title": title, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


# --------------------------------------------------------------------------- #
# DECISIONS.md 1.4: migration is read-time only.
# --------------------------------------------------------------------------- #


def test_a_version_1_file_loads_with_null_class_ids_and_correct_pages(data_file):
    write_v1(data_file)
    entries = Storage(data_file).all()

    assert len(entries) == 3
    assert [entry["class_id"] for entry in entries] == [None, None, None]
    assert [entry["page_start"] for entry in entries] == [43, 72, 91]
    assert [entry["page_end"] for entry in entries] == [71, 90, 91]


def test_loading_a_version_1_file_writes_nothing(data_file):
    """The app's first act on her data is never a write nobody asked for."""
    write_v1(data_file)
    before = data_file.read_bytes()

    Storage(data_file)

    assert data_file.read_bytes() == before
    assert json.loads(data_file.read_text(encoding="utf-8"))["schema_version"] == 1


def test_a_version_1_file_becomes_version_2_on_the_next_mutation(data_file):
    write_v1(data_file)
    storage = Storage(data_file)
    originals = storage.all()

    storage.update(originals[1]["id"], {"note": "edited"})

    document = json.loads(data_file.read_text(encoding="utf-8"))
    assert document["schema_version"] == 2

    # Every original entry is still there, in order, with its page range and dates.
    assert len(document["entries"]) == 3
    for stored, original in zip(document["entries"], V1_DOCUMENT["entries"]):
        assert stored["id"] == original["id"]
        assert stored["page_start"] == original["page_start"]
        assert stored["page_end"] == original["page_end"]
        assert stored["read_at"] == original["read_at"]
        assert stored["created_at"] == original["created_at"]
        assert stored["class_id"] is None

    assert document["entries"][1]["note"] == "edited"
    assert document["entries"][0]["note"] == "chapter 4"
    assert document["entries"][2]["note"] == "one page"


def test_a_version_1_file_serves_correct_pages_through_the_api(
    data_file, classes_file, settings_file
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import SettingsStore

    write_v1(data_file)
    with TestClient(
        create_app(
            Storage(data_file),
            classes=ClassStore(classes_file),
            settings=SettingsStore(settings_file),
        )
    ) as client:
        entries = client.get("/api/entries").json()

    assert [entry["pages"] for entry in entries] == [1, 19, 29]  # newest first
    assert all(entry["class_id"] is None for entry in entries)


def test_a_version_newer_than_the_code_still_refuses_to_start(data_file):
    """DECISIONS.md 1.2 is one-directional: older loads, newer halts."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text('{"schema_version": 3, "entries": []}', encoding="utf-8")
    with pytest.raises(CorruptDataFile):
        Storage(data_file)


# --------------------------------------------------------------------------- #
# DECISIONS.md 12.3: deletion is never a cascade. The most important test here.
# --------------------------------------------------------------------------- #

PROTECTED = ("page_start", "page_end", "pages", "read_at", "note", "created_at")


def test_deleting_a_class_keeps_every_entry_it_touched(client, data_file):
    subject = make_class(client, "Bio 12", color="#E4557F")

    logged = []
    for page_start, page_end, note, read_at in [
        (1, 20, "intro", "2026-08-20T09:00:00-04:00"),
        (21, 44, None, "2026-08-21T09:00:00-04:00"),
        (45, 45, "one page", "2026-08-22T09:00:00-04:00"),
    ]:
        response = client.post(
            "/api/entries",
            json={
                "page_start": page_start,
                "page_end": page_end,
                "note": note,
                "read_at": read_at,
                "class_id": subject["id"],
            },
        )
        assert response.status_code == 201
        logged.append(response.json())

    assert all(entry["class_id"] == subject["id"] for entry in logged)

    assert client.delete(f"/api/classes/{subject['id']}").status_code == 204

    survivors = {entry["id"]: entry for entry in client.get("/api/entries").json()}
    assert len(survivors) == 3

    for original in logged:
        survivor = survivors[original["id"]]
        assert survivor["class_id"] is None
        for field in PROTECTED:
            assert survivor[field] == original[field], field

    assert client.get("/api/classes").json() == []

    # And on disk, not just in the response.
    document = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(document["entries"]) == 3
    assert all(entry["class_id"] is None for entry in document["entries"])


def test_deleting_a_class_leaves_other_classes_entries_alone(client):
    kept = make_class(client, "Kept")
    doomed = make_class(client, "Doomed")

    safe = client.post(
        "/api/entries", json={"page_start": 1, "page_end": 5, "class_id": kept["id"]}
    ).json()
    client.post(
        "/api/entries", json={"page_start": 6, "page_end": 9, "class_id": doomed["id"]}
    )
    loose = client.post("/api/entries", json={"page_start": 10, "page_end": 12}).json()

    client.delete(f"/api/classes/{doomed['id']}")

    entries = {entry["id"]: entry for entry in client.get("/api/entries").json()}
    assert len(entries) == 3
    assert entries[safe["id"]]["class_id"] == kept["id"]
    assert entries[safe["id"]]["updated_at"] == safe["updated_at"]
    assert entries[loose["id"]]["updated_at"] == loose["updated_at"]


def test_clear_class_touches_nothing_but_class_id_and_updated_at(storage):
    entry = storage.create(
        page_start=43, page_end=71, note="chapter 4", class_id="some-class"
    )

    assert storage.clear_class("some-class") == 1

    after = storage.get(entry["id"])
    assert after["class_id"] is None
    for field in ("page_start", "page_end", "read_at", "note", "created_at"):
        assert after[field] == entry[field], field


def test_deleting_an_unknown_class_is_a_404(client):
    assert client.delete("/api/classes/nope").status_code == 404
    assert "nope" in client.delete("/api/classes/nope").json()["error"]


# --------------------------------------------------------------------------- #
# class_id on entries
# --------------------------------------------------------------------------- #


def test_class_id_round_trips_as_null_and_as_a_value(client, data_file):
    subject = make_class(client)

    plain = client.post("/api/entries", json={"page_start": 1, "page_end": 2}).json()
    assert plain["class_id"] is None

    tagged = client.patch(
        f"/api/entries/{plain['id']}", json={"class_id": subject["id"]}
    ).json()
    assert tagged["class_id"] == subject["id"]

    cleared = client.patch(
        f"/api/entries/{plain['id']}", json={"class_id": None}
    ).json()
    assert cleared["class_id"] is None

    retagged = client.patch(
        f"/api/entries/{plain['id']}", json={"class_id": subject["id"]}
    ).json()
    assert retagged["class_id"] == subject["id"]

    assert Storage(data_file).all()[0]["class_id"] == subject["id"]


def test_an_omitted_class_id_on_patch_leaves_it_alone(client):
    subject = make_class(client)
    entry = client.post(
        "/api/entries",
        json={"page_start": 1, "page_end": 2, "class_id": subject["id"]},
    ).json()

    patched = client.patch(f"/api/entries/{entry['id']}", json={"note": "hi"}).json()
    assert patched["class_id"] == subject["id"]


def test_an_unknown_class_id_is_rejected_and_the_message_names_it(client):
    response = client.post(
        "/api/entries",
        json={"page_start": 1, "page_end": 2, "class_id": "b81d0e4a-nope"},
    )
    assert response.status_code == 422
    assert "b81d0e4a-nope" in response.json()["error"]


def test_an_unknown_class_id_on_patch_is_rejected_and_changes_nothing(client):
    entry = client.post("/api/entries", json={"page_start": 1, "page_end": 2}).json()

    response = client.patch(
        f"/api/entries/{entry['id']}", json={"note": "new", "class_id": "ghost"}
    )
    assert response.status_code == 422
    assert "ghost" in response.json()["error"]

    unchanged = client.get("/api/entries").json()[0]
    assert unchanged["note"] is None
    assert unchanged["updated_at"] == entry["updated_at"]


def test_an_archived_class_stays_valid_on_an_entry(client):
    subject = make_class(client)
    entry = client.post(
        "/api/entries",
        json={"page_start": 1, "page_end": 2, "class_id": subject["id"]},
    ).json()

    client.patch(f"/api/classes/{subject['id']}", json={"archived": True})

    assert client.get("/api/entries").json()[0]["class_id"] == subject["id"]
    # Still returned by the list, so the entry row can show its name and color.
    assert [item["id"] for item in client.get("/api/classes").json()] == [subject["id"]]


def test_a_dangling_class_id_is_not_corruption(data_file):
    """DECISIONS.md 1.3: a reference across two files is not schema validity."""
    storage = Storage(data_file)
    storage.create(page_start=1, page_end=2, class_id="a-class-that-is-gone")

    reloaded = Storage(data_file).all()
    assert reloaded[0]["class_id"] == "a-class-that-is-gone"


# --------------------------------------------------------------------------- #
# Class validation (DECISIONS.md 4.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("title", ["", "   ", "\t\n", "x" * 61])
def test_a_bad_title_is_rejected(client, title):
    assert client.post("/api/classes", json={"title": title}).status_code == 422


def test_a_title_is_stored_stripped(client):
    assert make_class(client, "  Bio 12  ")["title"] == "Bio 12"
    assert make_class(client, "x" * 60)["title"] == "x" * 60


def test_a_duplicate_title_is_rejected_case_insensitively(client):
    make_class(client, "Bio 12")
    for attempt in ("Bio 12", "bio 12", "  BIO 12  "):
        response = client.post("/api/classes", json={"title": attempt})
        assert response.status_code == 422, attempt
        assert "Bio 12" in response.json()["error"]


def test_a_title_may_duplicate_an_archived_class(client):
    first = make_class(client, "Bio 12")
    client.patch(f"/api/classes/{first['id']}", json={"archived": True})

    fresh = make_class(client, "Bio 12")
    assert fresh["id"] != first["id"]

    # ...and un-archiving back into the collision is the same 422.
    response = client.patch(f"/api/classes/{first['id']}", json={"archived": False})
    assert response.status_code == 422


def test_renaming_onto_another_live_title_is_rejected_but_onto_itself_is_fine(client):
    first = make_class(client, "Bio 12")
    second = make_class(client, "Latin 3")

    assert (
        client.patch(f"/api/classes/{second['id']}", json={"title": "Bio 12"}).status_code
        == 422
    )
    assert (
        client.patch(f"/api/classes/{first['id']}", json={"title": "Bio 12"}).status_code
        == 200
    )
    assert (
        client.patch(f"/api/classes/{first['id']}", json={"title": "bio 12"}).status_code
        == 200
    )


@pytest.mark.parametrize("color", ["blue", "#12", "FF2E88", "#GGGGGG", "#1234567", ""])
def test_a_malformed_color_is_rejected(client, color):
    response = client.post("/api/classes", json={"title": "Bio 12", "color": color})
    assert response.status_code == 422
    assert "hex" in response.json()["error"]


@pytest.mark.parametrize("color", ["#E4557F", "#e4557f", "#abc"])
def test_a_well_formed_color_is_stored_verbatim(client, color):
    assert make_class(client, f"Class {color}", color=color)["color"] == color


def test_an_omitted_color_falls_back_without_the_server_owning_a_palette(client):
    from app.classes import FALLBACK_COLOR

    assert make_class(client)["color"] == FALLBACK_COLOR


def test_patching_an_unknown_class_is_a_404(client):
    response = client.patch("/api/classes/nope", json={"title": "x"})
    assert response.status_code == 404
    assert "nope" in response.json()["error"]


@pytest.mark.parametrize("field", ["title", "color", "archived"])
def test_the_non_nullable_class_fields_reject_null(client, field):
    subject = make_class(client)
    response = client.patch(f"/api/classes/{subject['id']}", json={field: None})
    assert response.status_code == 422


def test_description_is_nullable_and_clearable(client):
    subject = make_class(client, "Bio 12", description="mitochondria etc")
    assert subject["description"] == "mitochondria etc"

    cleared = client.patch(
        f"/api/classes/{subject['id']}", json={"description": None}
    ).json()
    assert cleared["description"] is None


# --------------------------------------------------------------------------- #
# Listing, storage, and the halt policy
# --------------------------------------------------------------------------- #


def test_classes_list_non_archived_first_then_archived(client):
    zebra = make_class(client, "Zebra")
    apple = make_class(client, "apple")
    away = make_class(client, "Away")
    client.patch(f"/api/classes/{away['id']}", json={"archived": True})

    listed = client.get("/api/classes").json()
    assert [item["id"] for item in listed] == [apple["id"], zebra["id"], away["id"]]
    assert [item["archived"] for item in listed] == [False, False, True]


def test_classes_survive_a_restart(classes_file):
    first = ClassStore(classes_file)
    created = first.create(title="Bio 12", color="#E4557F", description="notes")
    del first

    survivors = ClassStore(classes_file).list()
    assert survivors == [created]


def test_a_missing_class_file_is_created_empty(classes_file):
    assert not classes_file.exists()
    ClassStore(classes_file)
    document = json.loads(classes_file.read_text(encoding="utf-8"))
    assert document == {"schema_version": 1, "classes": []}


CORRUPT_CLASS_FILES = {
    "not_json": "nope",
    "empty": "",
    "top_level_list": "[]",
    "missing_classes": '{"schema_version": 1}',
    "classes_not_a_list": '{"schema_version": 1, "classes": {}}',
    "future_schema_version": '{"schema_version": 99, "classes": []}',
    "class_missing_field": '{"schema_version": 1, "classes": [{"id": "a"}]}',
    "class_blank_title": (
        '{"schema_version": 1, "classes": [{"id": "a", "title": "  ", '
        '"description": null, "color": "#E4557F", "archived": false, '
        '"created_at": "2026-08-24T12:00:00-04:00", '
        '"updated_at": "2026-08-24T12:00:00-04:00"}]}'
    ),
    "class_bad_color": (
        '{"schema_version": 1, "classes": [{"id": "a", "title": "Bio", '
        '"description": null, "color": "blue", "archived": false, '
        '"created_at": "2026-08-24T12:00:00-04:00", '
        '"updated_at": "2026-08-24T12:00:00-04:00"}]}'
    ),
    "class_bad_archived": (
        '{"schema_version": 1, "classes": [{"id": "a", "title": "Bio", '
        '"description": null, "color": "#E4557F", "archived": "yes", '
        '"created_at": "2026-08-24T12:00:00-04:00", '
        '"updated_at": "2026-08-24T12:00:00-04:00"}]}'
    ),
}


@pytest.mark.parametrize("name", sorted(CORRUPT_CLASS_FILES))
def test_a_corrupt_class_file_halts_and_is_never_modified(classes_file, name):
    classes_file.parent.mkdir(parents=True, exist_ok=True)
    classes_file.write_bytes(CORRUPT_CLASS_FILES[name].encode("utf-8"))
    before = classes_file.read_bytes()

    with pytest.raises(CorruptDataFile):
        ClassStore(classes_file)

    assert classes_file.read_bytes() == before
    assert __import__("os").listdir(classes_file.parent) == [classes_file.name]


def test_a_corrupt_class_file_exits_non_zero_with_a_banner(classes_file, capsys):
    classes_file.parent.mkdir(parents=True, exist_ok=True)
    classes_file.write_text('{"schema_version": 1, "classes": [', encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        load_class_store_or_exit(classes_file)

    assert exit_info.value.code != 0
    banner = capsys.readouterr().err
    assert str(classes_file) in banner
    assert "WILL NOT START" in banner


# --------------------------------------------------------------------------- #
# Structural guarantees
# --------------------------------------------------------------------------- #


def test_create_app_will_not_default_to_the_real_class_file(storage):
    """DECISIONS.md 3.7: a forgotten argument must not reach real data.

    `classes` is keyword-only with no default, so this is a TypeError rather than a
    silent write to data/classes.json.
    """
    from app.main import create_app

    with pytest.raises(TypeError):
        create_app(storage)


def test_the_class_store_cannot_reach_the_entry_log():
    """Renaming a class cannot touch the reading log, because there is no path from
    app/classes.py to it (DECISIONS.md 12.1).

    Asserted the way section 10 asserts it for quotes: on the import list, so a
    refactor that reaches for the entry store fails here rather than in production.
    """
    import ast
    import inspect

    import app.classes as classes_module

    tree = ast.parse(inspect.getsource(classes_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert "storage" not in imported
    assert not any("storage" in name for name in imported), imported
    assert not hasattr(classes_module, "Storage")


def test_no_per_class_stats_endpoint_exists(client):
    """DECISIONS.md 4.3 / 12.5: the thing that would feed a scoreboard is absent."""
    subject = make_class(client)
    assert client.get(f"/api/stats?class_id={subject['id']}").json().keys() == {
        "pages_today",
        "pages_all_time",
        "current_streak_days",
        "entry_count",
        "first_entry_date",
    }
    assert client.get("/api/stats/by-class").status_code == 404

    listed = client.get("/api/classes").json()[0]
    assert "entry_count" not in listed
    assert "pages" not in listed
