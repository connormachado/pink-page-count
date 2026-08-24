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
QUOTES_FILE_ENV = "PAGECOUNT_QUOTES_FILE"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = REPO_ROOT / "data" / "entries.json"
# DECISIONS.md 10: quotes are source, not entry data, and live in their own file
# at the repo root where she can open them in any text editor.
DEFAULT_QUOTES_FILE = REPO_ROOT / "quotes.txt"


def data_file() -> Path:
    """Path to the JSON data file, overridable for tests via PAGECOUNT_DATA_FILE."""
    override = os.environ.get(DATA_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_DATA_FILE


def quotes_file() -> Path:
    """Path to the quote file, overridable for tests via PAGECOUNT_QUOTES_FILE.

    Separate from data_file() and always will be -- see DECISIONS.md 10.
    """
    override = os.environ.get(QUOTES_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_QUOTES_FILE


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
