"""Page counting is INCLUSIVE (DECISIONS.md 1.1)."""

from __future__ import annotations

import json

from app.models import compute_pages


def test_43_to_71_is_29_pages():
    assert compute_pages(43, 71) == 29


def test_43_to_43_is_1_page():
    assert compute_pages(43, 43) == 1


def test_api_returns_29_for_43_to_71(client):
    response = client.post("/api/entries", json={"page_start": 43, "page_end": 71})
    assert response.status_code == 201
    assert response.json()["pages"] == 29


def test_api_returns_1_for_a_single_page(client):
    response = client.post("/api/entries", json={"page_start": 43, "page_end": 43})
    assert response.status_code == 201
    assert response.json()["pages"] == 1


def test_pages_is_never_written_to_disk(client, data_file):
    client.post("/api/entries", json={"page_start": 43, "page_end": 71})
    document = json.loads(data_file.read_text(encoding="utf-8"))
    assert "pages" not in document["entries"][0]


def test_client_supplied_pages_is_ignored(client, data_file):
    response = client.post(
        "/api/entries", json={"page_start": 43, "page_end": 71, "pages": 9999}
    )
    assert response.json()["pages"] == 29
    document = json.loads(data_file.read_text(encoding="utf-8"))
    assert "pages" not in document["entries"][0]


def test_pages_is_recomputed_after_a_patch(client):
    created = client.post(
        "/api/entries", json={"page_start": 43, "page_end": 71}
    ).json()
    patched = client.patch(f"/api/entries/{created['id']}", json={"page_end": 43})
    assert patched.status_code == 200
    assert patched.json()["pages"] == 1
