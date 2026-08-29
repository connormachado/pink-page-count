"""Paths, port, and environment variable names. See DECISIONS.md sections 5 and 5.1."""

from __future__ import annotations

import os
from pathlib import Path

# DECISIONS.md 1.2: each data file carries its own version, and each is bumped only
# when that file's on-disk shape changes incompatibly. entries.json went to 2 when
# class_id was added (1.4).
ENTRIES_SCHEMA_VERSION = 2
CLASSES_SCHEMA_VERSION = 1
SETTINGS_SCHEMA_VERSION = 1

# The entry log is the file this project exists to protect, so its version is the one
# an unqualified SCHEMA_VERSION means.
SCHEMA_VERSION = ENTRIES_SCHEMA_VERSION

# DECISIONS.md 5: binds to loopback only, never 0.0.0.0. Hard-coded, not configurable.
HOST = "127.0.0.1"
DEFAULT_PORT = 8420

PORT_ENV = "PAGECOUNT_PORT"
DATA_FILE_ENV = "PAGECOUNT_DATA_FILE"
CLASSES_FILE_ENV = "PAGECOUNT_CLASSES_FILE"
SETTINGS_FILE_ENV = "PAGECOUNT_SETTINGS_FILE"
QUOTES_FILE_ENV = "PAGECOUNT_QUOTES_FILE"
DIST_DIR_ENV = "PAGECOUNT_DIST_DIR"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = REPO_ROOT / "data" / "entries.json"
# DECISIONS.md 12.1: classes live beside the entry log, never inside it.
DEFAULT_CLASSES_FILE = REPO_ROOT / "data" / "classes.json"
# DECISIONS.md 13: settings are a third file, beside the other two, for the same
# reason classes are -- a feature about presentation has no business being able to
# rewrite the reading log.
DEFAULT_SETTINGS_FILE = REPO_ROOT / "data" / "settings.json"
# DECISIONS.md 10: quotes are source, not entry data, and live in their own file
# at the repo root where she can open them in any text editor.
DEFAULT_QUOTES_FILE = REPO_ROOT / "quotes.txt"
# DECISIONS.md 5: Phase 4 serves the built front end straight off disk.
DEFAULT_DIST_DIR = REPO_ROOT / "web" / "dist"


def data_file() -> Path:
    """Path to the JSON data file, overridable for tests via PAGECOUNT_DATA_FILE."""
    override = os.environ.get(DATA_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_DATA_FILE


def classes_file() -> Path:
    """Path to the class file, overridable for tests via PAGECOUNT_CLASSES_FILE.

    A separate file from data_file() and always will be -- see DECISIONS.md 12.1.
    """
    override = os.environ.get(CLASSES_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_CLASSES_FILE


def settings_file() -> Path:
    """Path to the settings file, overridable for tests via PAGECOUNT_SETTINGS_FILE.

    A separate file from data_file() and classes_file(), and always will be -- see
    DECISIONS.md 13.
    """
    override = os.environ.get(SETTINGS_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_SETTINGS_FILE


def quotes_file() -> Path:
    """Path to the quote file, overridable for tests via PAGECOUNT_QUOTES_FILE.

    Separate from data_file() and always will be -- see DECISIONS.md 10.
    """
    override = os.environ.get(QUOTES_FILE_ENV)
    return Path(override).expanduser() if override else DEFAULT_QUOTES_FILE


def dist_dir() -> Path:
    """Path to the built front end, overridable for tests via PAGECOUNT_DIST_DIR.

    This is the `web/dist` Vite produces -- see DECISIONS.md 5.
    """
    override = os.environ.get(DIST_DIR_ENV)
    return Path(override).expanduser() if override else DEFAULT_DIST_DIR


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
