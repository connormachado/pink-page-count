"""GET /api/export. See DECISIONS.md 4.4 -- a backup, not a feature."""

from __future__ import annotations

import re


def test_export_returns_entries_and_classes_from_the_live_data(client):
    class_created = client.post(
        "/api/classes", json={"title": "Bio 12", "color": "#E4557F"}
    ).json()
    client.post(
        "/api/entries",
        json={"page_start": 43, "page_end": 71, "class_id": class_created["id"]},
    )

    response = client.get("/api/export")

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["pages"] == 29
    assert body["entries"][0]["class_id"] == class_created["id"]
    assert len(body["classes"]) == 1
    assert body["classes"][0]["title"] == "Bio 12"


def test_export_names_a_dated_filename_for_download(client):
    response = client.get("/api/export")

    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    match = re.search(r'filename="(reading-log-\d{4}-\d{2}-\d{2}\.json)"', disposition)
    assert match is not None
