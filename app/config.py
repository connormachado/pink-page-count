"""Paths, port, and environment variable names. See DECISIONS.md sections 5 and 5.1."""

from __future__ import annotations

import os
from pathlib import Path

SCHEMA_VERSION = 1

# DECISIONS.md 5: binds to loopback only, never 0.0.0.0. Hard-coded, not configurable.
HOST = "127.0.0.1"
DEFAULT_PORT = 8420

PORT_ENV = "PAGECOUNT_PORT"
DATA_FILE_ENV = "PAGECOUNT_DATA_FILE"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = REPO_ROOT / "data" / "entries.json"


def data_file() -> Path:
    """Path to the JSON data file, overridable for tests via PAGECOUNT_DATA_FILE."""
    override = os.environ.get(DATA_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_DATA_FILE


def port() -> int:
    """Port to bind, overridable via PAGECOUNT_PORT."""
    raw = os.environ.get(PORT_ENV)
    if not raw:
        return DEFAULT_PORT
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{PORT_ENV} must be a number, got {raw!r}") from None
    if not (1 <= value <= 65535):
        raise SystemExit(f"{PORT_ENV} must be between 1 and 65535, got {value}")
    return value
