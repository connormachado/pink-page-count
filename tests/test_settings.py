"""Settings: the third data file, its validation, and its isolation from the other
two. See DECISIONS.md section 13, plus 3.1-3.4 (shared atomic write / corrupt halt).
"""

from __future__ import annotations

import json

import pytest

from app.jsonfile import CorruptDataFile
from app.settings import SettingsStore, load_settings_store_or_exit


# --------------------------------------------------------------------------- #
# Round-trip, defaults, and restart survival
# --------------------------------------------------------------------------- #


def test_a_missing_settings_file_is_created_with_defaults(settings_file):
    assert not settings_file.exists()
    SettingsStore(settings_file)
    document = json.loads(settings_file.read_text(encoding="utf-8"))
    assert document == {
        "schema_version": 1,
        "settings": {
            "theme": "pink",
            "custom_theme": None,
            "default_chip": "all_time",
        },
    }


def test_get_returns_the_documented_defaults(client):
    assert client.get("/api/settings").json() == {
        "theme": "pink",
        "custom_theme": None,
        "default_chip": "all_time",
    }


def test_patch_round_trips_and_persists(client, settings_file):
    response = client.patch(
        "/api/settings",
        json={"theme": "jewel", "default_chip": "today"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "theme": "jewel",
        "custom_theme": None,
        "default_chip": "today",
    }

    assert client.get("/api/settings").json()["theme"] == "jewel"

    document = json.loads(settings_file.read_text(encoding="utf-8"))
    assert document["settings"]["theme"] == "jewel"
    assert document["settings"]["default_chip"] == "today"


def test_custom_theme_round_trips(client):
    overrides = {"--pink-hot": "#123456", "--ink": "#abcdef"}
    response = client.patch("/api/settings", json={"theme": "custom", "custom_theme": overrides})
    assert response.status_code == 200
    assert response.json()["custom_theme"] == overrides
    assert client.get("/api/settings").json()["custom_theme"] == overrides


def test_custom_theme_null_clears_overrides(client):
    client.patch(
        "/api/settings",
        json={"theme": "custom", "custom_theme": {"--ink": "#000000"}},
    )
    response = client.patch("/api/settings", json={"custom_theme": None})
    assert response.status_code == 200
    assert response.json()["custom_theme"] is None


def test_an_omitted_field_on_patch_leaves_it_alone(client):
    client.patch("/api/settings", json={"default_chip": "streak"})
    response = client.patch("/api/settings", json={"theme": "cool"})
    assert response.json() == {
        "theme": "cool",
        "custom_theme": None,
        "default_chip": "streak",
    }


def test_settings_survive_a_restart(settings_file):
    first = SettingsStore(settings_file)
    first.update({"theme": "midnight", "default_chip": "today"})
    del first

    reloaded = SettingsStore(settings_file).get()
    assert reloaded == {
        "theme": "midnight",
        "custom_theme": None,
        "default_chip": "today",
    }


# --------------------------------------------------------------------------- #
# Validation (DECISIONS.md 4.1, 13)
# --------------------------------------------------------------------------- #


def test_an_unknown_top_level_key_is_a_422(client):
    response = client.patch("/api/settings", json={"nonsense": "x"})
    assert response.status_code == 422


def test_an_unknown_theme_id_is_a_422_and_names_it(client):
    response = client.patch("/api/settings", json={"theme": "nope"})
    assert response.status_code == 422
    assert "nope" in response.json()["error"]


@pytest.mark.parametrize("color", ["blue", "#12", "FF2E88", "#GGGGGG", "#1234567", ""])
def test_a_malformed_hex_in_custom_theme_is_a_422(client, color):
    response = client.patch(
        "/api/settings",
        json={"custom_theme": {"--pink-hot": color}},
    )
    assert response.status_code == 422
    assert "hex" in response.json()["error"]


def test_an_unrecognized_custom_theme_key_is_a_422(client):
    response = client.patch(
        "/api/settings",
        json={"custom_theme": {"--not-a-real-token": "#123456"}},
    )
    assert response.status_code == 422
    assert "--not-a-real-token" in response.json()["error"]


def test_an_invalid_default_chip_is_a_422(client):
    response = client.patch("/api/settings", json={"default_chip": "yesterday"})
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["theme", "default_chip"])
def test_theme_and_default_chip_reject_null(client, field):
    response = client.patch("/api/settings", json={field: None})
    assert response.status_code == 422


def test_custom_theme_id_is_accepted(client):
    response = client.patch("/api/settings", json={"theme": "custom"})
    assert response.status_code == 200
    assert response.json()["theme"] == "custom"


# --------------------------------------------------------------------------- #
# Corrupt file: refuse to start (DECISIONS.md 3.4)
# --------------------------------------------------------------------------- #

CORRUPT_SETTINGS_FILES = {
    "not_json": "nope",
    "empty": "",
    "top_level_list": "[]",
    "missing_settings": '{"schema_version": 1}',
    "settings_not_an_object": '{"schema_version": 1, "settings": []}',
    "missing_required_field": (
        '{"schema_version": 1, "settings": {"theme": "pink", '
        '"custom_theme": null}}'
    ),
    "unrecognized_settings_field": (
        '{"schema_version": 1, "settings": {"theme": "pink", "custom_theme": null, '
        '"default_chip": "all_time", "extra": 1}}'
    ),
    "future_schema_version": (
        '{"schema_version": 99, "settings": {"theme": "pink", "custom_theme": null, '
        '"default_chip": "all_time"}}'
    ),
    "bad_theme_id": (
        '{"schema_version": 1, "settings": {"theme": "nope", "custom_theme": null, '
        '"default_chip": "all_time"}}'
    ),
    "bad_custom_theme_hex": (
        '{"schema_version": 1, "settings": {"theme": "pink", '
        '"custom_theme": {"--ink": "blue"}, "default_chip": "all_time"}}'
    ),
    "bad_default_chip": (
        '{"schema_version": 1, "settings": {"theme": "pink", "custom_theme": null, '
        '"default_chip": "never"}}'
    ),
}


@pytest.mark.parametrize("name", sorted(CORRUPT_SETTINGS_FILES))
def test_a_corrupt_settings_file_halts_and_is_never_modified(settings_file, name):
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_bytes(CORRUPT_SETTINGS_FILES[name].encode("utf-8"))
    before = settings_file.read_bytes()

    with pytest.raises(CorruptDataFile):
        SettingsStore(settings_file)

    assert settings_file.read_bytes() == before
    assert __import__("os").listdir(settings_file.parent) == [settings_file.name]


def test_a_corrupt_settings_file_exits_non_zero_with_a_banner(settings_file, capsys):
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"schema_version": 1, "settings": [', encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        load_settings_store_or_exit(settings_file)

    assert exit_info.value.code != 0
    banner = capsys.readouterr().err
    assert str(settings_file) in banner
    assert "WILL NOT START" in banner


# --------------------------------------------------------------------------- #
# Structural guarantees: isolation from entries.json and classes.json
# --------------------------------------------------------------------------- #


def test_create_app_will_not_default_to_the_real_settings_file(storage, class_store):
    """DECISIONS.md 3.7: a forgotten argument must not reach real data."""
    from app.main import create_app

    with pytest.raises(TypeError):
        create_app(storage, classes=class_store)


def test_the_settings_store_cannot_reach_the_entry_log_or_classes():
    """Renaming a theme cannot touch the reading log or the class list, because there
    is no path from app/settings.py to either (DECISIONS.md 13, mirrors 12.1)."""
    import ast
    import inspect

    import app.settings as settings_module

    tree = ast.parse(inspect.getsource(settings_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert not any("storage" in name for name in imported), imported
    assert not any(name == "classes" or name.endswith(".classes") for name in imported), imported
    assert not hasattr(settings_module, "Storage")
    assert not hasattr(settings_module, "ClassStore")


def test_settings_changes_never_touch_entries_or_classes_files(
    client, data_file, classes_file
):
    client.post("/api/entries", json={"page_start": 1, "page_end": 10})
    client.post("/api/classes", json={"title": "Bio 12"})

    entries_before = data_file.read_bytes()
    classes_before = classes_file.read_bytes()

    for body in (
        {"theme": "jewel"},
        {"custom_theme": {"--pink-hot": "#123456"}},
        {"default_chip": "today"},
        {"theme": "custom", "custom_theme": None},
    ):
        assert client.patch("/api/settings", json=body).status_code == 200

    assert data_file.read_bytes() == entries_before
    assert classes_file.read_bytes() == classes_before
