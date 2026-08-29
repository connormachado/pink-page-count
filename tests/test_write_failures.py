"""A write that cannot land. See DECISIONS.md 3.5.1 and 4.5, and AUDIT.md B4.

The failure these cover is not hypothetical: with the data directory read-only, the
server starts, answers, and used to lose every save behind a plain-text 500 that the
front end read as "the app isn't running". What is asserted here is the *shape* of
the answer and the state of the file afterwards -- never the prose, which is copy and
may be reworded without breaking a test.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jsonfile
from app.jsonfile import DataWriteError, atomic_write_json

# Root ignores the permission bits these tests rely on, so the read-only cases would
# quietly pass by writing successfully. The simulated ones below cover the same
# handler without needing the filesystem to cooperate.
needs_unprivileged = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses directory permissions, so nothing would fail to write",
)


@pytest.fixture
def data_dir(tmp_path: Path, client: TestClient) -> Path:
    """The directory holding all three data files, with all three already created.

    Depends on `client` so the stores have finished their first writes (3.3) before
    anything here takes the write permission away.
    """
    return tmp_path / "data"


@pytest.fixture
def readonly_data_dir(data_dir: Path):
    """Exactly AUDIT.md B4's condition: the data directory cannot be written to."""
    os.chmod(data_dir, 0o500)
    try:
        yield data_dir
    finally:
        # Always, however the test ended -- otherwise pytest cannot clean tmp_path.
        os.chmod(data_dir, 0o700)


def error_body(response) -> str:
    """Assert DECISIONS.md 4.2's shape and hand back the message.

    The shape is the contract: one key, `error`, holding a non-empty string. A
    plain-text body -- which is what Starlette returns for an unhandled exception,
    and what B4 was -- fails at `response.json()`.
    """
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    assert isinstance(body["error"], str)
    assert body["error"].strip()
    return body["error"]


# --------------------------------------------------------------------------- #
# The read-only directory, end to end
# --------------------------------------------------------------------------- #


@needs_unprivileged
def test_failed_save_answers_with_the_json_error_shape(
    client: TestClient, readonly_data_dir: Path
):
    response = client.post("/api/entries", json={"page_start": 20, "page_end": 30})
    assert response.status_code == 500
    error_body(response)


@needs_unprivileged
def test_failed_save_leaves_entries_json_byte_identical(
    client: TestClient, readonly_data_dir: Path
):
    """The point of the whole exercise: nothing about the file changed."""
    entries_file = readonly_data_dir / "entries.json"
    before = entries_file.read_bytes()

    assert client.post("/api/entries", json={"page_start": 20, "page_end": 30}).status_code == 500

    assert entries_file.read_bytes() == before


@needs_unprivileged
def test_failed_save_leaves_the_served_log_unchanged(
    client: TestClient, readonly_data_dir: Path
):
    """Memory is rolled back to match the disk, so the next read is still the truth.

    Without this the in-memory list would carry an entry the file does not, and every
    number on screen would be one nobody could get back after a restart.
    """
    before = client.get("/api/entries").json()
    stats_before = client.get("/api/stats").json()

    assert client.post("/api/entries", json={"page_start": 20, "page_end": 30}).status_code == 500

    assert client.get("/api/entries").json() == before
    assert client.get("/api/stats").json() == stats_before


@needs_unprivileged
def test_failed_save_leaves_no_temp_file_beside_the_data(
    client: TestClient, readonly_data_dir: Path
):
    before = sorted(p.name for p in readonly_data_dir.iterdir())

    assert client.post("/api/entries", json={"page_start": 20, "page_end": 30}).status_code == 500

    assert sorted(p.name for p in readonly_data_dir.iterdir()) == before


@needs_unprivileged
@pytest.mark.parametrize(
    "method, path, payload",
    [
        ("post", "/api/entries", {"page_start": 20, "page_end": 30}),
        ("patch", "/api/entries/{entry_id}", {"page_end": 99}),
        ("delete", "/api/entries/{entry_id}", None),
        ("post", "/api/classes", {"title": "Bio 12"}),
        ("patch", "/api/settings", {"theme": "midnight"}),
    ],
)
def test_every_mutation_that_cannot_write_answers_the_same_way(
    client: TestClient, data_dir: Path, method: str, path: str, payload
):
    """One family, one shape. A failed delete is as much a lost write as a failed save."""
    seeded = client.post("/api/entries", json={"page_start": 1, "page_end": 5}).json()
    os.chmod(data_dir, 0o500)
    try:
        call = getattr(client, method)
        url = path.format(entry_id=seeded["id"])
        response = call(url) if payload is None else call(url, json=payload)
        assert response.status_code == 500
        error_body(response)
    finally:
        os.chmod(data_dir, 0o700)


@needs_unprivileged
def test_the_message_carries_nothing_she_cannot_act_on(
    client: TestClient, readonly_data_dir: Path
):
    """No errno, no path, no traceback -- DECISIONS.md 4.5.

    Deliberately not an assertion about the wording, which is copy. It is an
    assertion that the diagnosis did not leak into the copy.
    """
    response = client.post("/api/entries", json={"page_start": 20, "page_end": 30})
    message = error_body(response)

    assert "errno" not in message.lower()
    assert "Traceback" not in message
    assert str(readonly_data_dir) not in message
    assert "entries.json" not in message
    assert "/" not in message
    assert not any(character.isdigit() for character in message)


# --------------------------------------------------------------------------- #
# The rest of the family, which no chmod can produce
# --------------------------------------------------------------------------- #

# A read-only directory is one member. These are the others named in 3.5.1, each
# reached by making the syscall that would raise it raise it.
WRITE_FAILURES = [
    (errno.EACCES, "the directory belongs to somebody else"),
    (errno.EROFS, "the volume is mounted read-only"),
    (errno.ENOSPC, "the disk is full"),
    (errno.EDQUOT, "the quota is used up"),
    (errno.ENXIO, "the volume went away"),
    (errno.EIO, "the device answered with an error"),
]


@pytest.mark.parametrize("code, situation", WRITE_FAILURES)
def test_atomic_write_json_reports_every_kind_of_failure_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, situation: str
):
    target = tmp_path / "entries.json"
    atomic_write_json(target, {"schema_version": 2, "entries": []})
    before = target.read_bytes()

    def refuse(*args, **kwargs):
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(jsonfile.tempfile, "mkstemp", refuse)

    with pytest.raises(DataWriteError) as caught:
        atomic_write_json(target, {"schema_version": 2, "entries": [{"id": "x"}]})

    # The cause is carried, not replaced: the log needs it even though the screen
    # never sees it (3.5.1).
    assert caught.value.errno == code
    assert isinstance(caught.value.cause, OSError)
    assert caught.value.path == target
    assert target.read_bytes() == before, situation


def test_a_failure_after_the_temp_file_exists_still_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Disk-full lands on the write, not on the open. The temp file must not survive."""
    target = tmp_path / "entries.json"
    atomic_write_json(target, {"schema_version": 2, "entries": []})
    before = target.read_bytes()

    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(jsonfile.os, "replace", no_space)

    with pytest.raises(DataWriteError):
        atomic_write_json(target, {"schema_version": 2, "entries": [{"id": "x"}]})

    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["entries.json"]


def test_a_full_disk_answers_the_same_as_a_read_only_directory(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The route, not just the write path: ENOSPC through the whole stack."""

    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(jsonfile.os, "replace", no_space)

    response = client.post("/api/entries", json={"page_start": 20, "page_end": 30})
    assert response.status_code == 500
    error_body(response)
    assert client.get("/api/entries").json() == []


def test_the_cause_is_logged_in_full(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Not swallowed: whoever has to diagnose this gets the errno and the traceback.

    The screen gets one plain sentence; everything technical goes here instead of
    being thrown away (DECISIONS.md 4.5).
    """

    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(jsonfile.os, "replace", no_space)

    with caplog.at_level(logging.ERROR, logger="pinkpagecount"):
        assert client.post("/api/entries", json={"page_start": 1, "page_end": 5}).status_code == 500

    records = [r for r in caplog.records if r.name == "pinkpagecount"]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is not None  # the traceback, not just a one-liner
    logged = record.getMessage()
    assert "entries.json" in logged
    assert str(errno.ENOSPC) in logged
    assert "/api/entries" in logged
