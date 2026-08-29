"""Shared fixtures. No test ever touches the real data file (DECISIONS.md 3.7)."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.classes import ClassStore  # noqa: E402
from app.main import create_app  # noqa: E402
from app.quotes import QuoteSource  # noqa: E402
from app.settings import SettingsStore  # noqa: E402
from app.storage import Storage  # noqa: E402

TEST_TZ = "America/New_York"


@pytest.fixture(autouse=True)
def pinned_timezone():
    """Pin the system timezone so the 4am boundary is deterministic."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = TEST_TZ
    time.tzset()
    yield
    if previous is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "entries.json"


@pytest.fixture
def storage(data_file: Path) -> Storage:
    return Storage(data_file)


@pytest.fixture
def classes_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "classes.json"


@pytest.fixture
def class_store(classes_file: Path) -> ClassStore:
    return ClassStore(classes_file)


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    return tmp_path / "data" / "settings.json"


@pytest.fixture
def settings_store(settings_file: Path) -> SettingsStore:
    return SettingsStore(settings_file)


@pytest.fixture
def quotes_file(tmp_path: Path) -> Path:
    """A quote file under tmp_path. Deliberately NOT created -- a test that wants
    content writes it. No test ever reads the repo's real quotes.txt."""
    return tmp_path / "quotes.txt"


@pytest.fixture
def client(
    storage: Storage,
    quotes_file: Path,
    class_store: ClassStore,
    settings_store: SettingsStore,
) -> TestClient:
    return TestClient(
        create_app(
            storage,
            QuoteSource(quotes_file),
            classes=class_store,
            settings=settings_store,
        )
    )


def local(text: str) -> datetime:
    """Build an aware local datetime from 'YYYY-MM-DD HH:MM'."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").astimezone()
