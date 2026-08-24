"""Validation rejections and the {"error": ...} body shape (DECISIONS.md 4.1, 4.2)."""

from __future__ import annotations

import uuid

import pytest


def test_page_end_below_page_start_is_422_naming_both_values(client):
    response = client.post("/api/entries", json={"page_start": 40, "page_end": 12})
    assert response.status_code == 422
    message = response.json()["error"]
    assert "40" in message and "12" in message
    assert "page_start" in message and "page_end" in message


def test_negative_page_start_is_422(client):
    response = client.post("/api/entries", json={"page_start": -1, "page_end": 10})
    assert response.status_code == 422
    assert "error" in response.json()


@pytest.mark.parametrize(
    "bad", ["yesterday", "2026-13-45T99:99:99", "", "not-a-timestamp", "24/08/2026"]
)
def test_unparseable_read_at_is_422(client, bad):
    response = client.post(
        "/api/entries", json={"page_start": 1, "page_end": 2, "read_at": bad}
    )
    assert response.status_code == 422
    assert "error" in response.json()


def test_valid_read_at_is_accepted_and_normalized(client):
    response = client.post(
        "/api/entries",
        json={"page_start": 1, "page_end": 2, "read_at": "2026-08-20T21:30:00-04:00"},
    )
    assert response.status_code == 201
    assert response.json()["read_at"] == "2026-08-20T21:30:00-04:00"


def test_naive_read_at_gets_the_local_offset(client):
    """DECISIONS.md 2.2: naive input is interpreted as local time and stored with the
    local offset. August in America/New_York is -04:00."""
    response = client.post(
        "/api/entries",
        json={"page_start": 1, "page_end": 2, "read_at": "2026-08-20T21:30:00"},
    )
    assert response.status_code == 201
    assert response.json()["read_at"] == "2026-08-20T21:30:00-04:00"


def test_unknown_id_on_patch_is_404(client):
    response = client.patch(f"/api/entries/{uuid.uuid4()}", json={"page_end": 5})
    assert response.status_code == 404
    assert "error" in response.json()


def test_unknown_id_on_delete_is_404(client):
    response = client.delete(f"/api/entries/{uuid.uuid4()}")
    assert response.status_code == 404
    assert "error" in response.json()


def test_patch_validates_the_merged_result(client):
    """Patching only page_start to a value above the stored page_end must fail."""
    created = client.post(
        "/api/entries", json={"page_start": 10, "page_end": 20}
    ).json()
    response = client.patch(f"/api/entries/{created['id']}", json={"page_start": 50})
    assert response.status_code == 422
    message = response.json()["error"]
    assert "50" in message and "20" in message


def test_rejected_patch_does_not_change_stored_entry(client):
    created = client.post(
        "/api/entries", json={"page_start": 10, "page_end": 20}
    ).json()
    client.patch(f"/api/entries/{created['id']}", json={"page_start": 50})
    after = client.get("/api/entries").json()[0]
    assert after["page_start"] == 10
    assert after["page_end"] == 20


def test_limit_below_one_is_422(client):
    assert client.get("/api/entries", params={"limit": 0}).status_code == 422


def test_limit_returns_newest_first(client):
    for day in ("2026-08-01", "2026-08-03", "2026-08-02"):
        client.post(
            "/api/entries",
            json={"page_start": 1, "page_end": 2, "read_at": f"{day}T12:00:00-04:00"},
        )
    newest = client.get("/api/entries", params={"limit": 2}).json()
    assert [entry["read_at"][:10] for entry in newest] == ["2026-08-03", "2026-08-02"]


def test_delete_removes_the_entry(client):
    created = client.post("/api/entries", json={"page_start": 1, "page_end": 2}).json()
    assert client.delete(f"/api/entries/{created['id']}").status_code == 204
    assert client.get("/api/entries").json() == []


def test_note_defaults_to_null_and_can_be_set(client):
    created = client.post("/api/entries", json={"page_start": 1, "page_end": 2}).json()
    assert created["note"] is None
    patched = client.patch(f"/api/entries/{created['id']}", json={"note": "ch. 4"})
    assert patched.json()["note"] == "ch. 4"


def test_docs_routes_are_disabled_because_they_need_a_cdn(client):
    """DECISIONS.md 5: no route may depend on the internet."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 200
