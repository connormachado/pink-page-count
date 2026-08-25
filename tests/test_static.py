"""Serving the built front end from FastAPI. See DECISIONS.md section 5.

Each test builds its own app with a tmp_path-based dist_dir, the same way
test_persistence.py builds its own Storage -- no test here touches web/dist.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.classes import ClassStore
from app.main import create_app
from app.quotes import QuoteSource
from app.storage import Storage


def _app(data_file: Path, classes_file: Path, quotes_file: Path, dist_dir: Path):
    return create_app(
        Storage(data_file),
        QuoteSource(quotes_file),
        classes=ClassStore(classes_file),
        dist_dir=dist_dir,
    )


def test_api_routes_are_not_shadowed_by_the_static_section(
    data_file, classes_file, quotes_file, tmp_path
):
    """/api/stats must still answer as JSON, not fall through to index.html."""
    with TestClient(
        _app(data_file, classes_file, quotes_file, tmp_path / "dist")
    ) as client:
        response = client.get("/api/stats")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_index_html_is_served_with_cache_control_no_store(
    data_file, classes_file, quotes_file, tmp_path
):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html>hi</html>", encoding="utf-8")

    with TestClient(
        _app(data_file, classes_file, quotes_file, dist_dir)
    ) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.text == "<html>hi</html>"
    assert response.headers["cache-control"] == "no-store"


def test_missing_dist_returns_a_friendly_200_not_a_500(
    data_file, classes_file, quotes_file, tmp_path
):
    """A front end that hasn't been built yet must never crash startup or the
    request -- it is a setup step, not a server error."""
    with TestClient(
        _app(data_file, classes_file, quotes_file, tmp_path / "does-not-exist")
    ) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "npm run build" in response.text


def test_a_real_asset_is_served_at_its_mounted_path(
    data_file, classes_file, quotes_file, tmp_path
):
    dist_dir = tmp_path / "dist"
    (dist_dir / "assets").mkdir(parents=True)
    (dist_dir / "assets" / "index-abc123.js").write_text(
        "console.log('hi');", encoding="utf-8"
    )

    with TestClient(
        _app(data_file, classes_file, quotes_file, dist_dir)
    ) as client:
        response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == "console.log('hi');"
