"""Paths, port, and environment variable names. See DECISIONS.md sections 5 and 5.1."""

from __future__ import annotations

import os
import sys
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

# DECISIONS.md 14: two independent bases, not one.
#
# RESOURCE_ROOT is read-only and ships with the app: quotes.txt, web/dist. When
# frozen (sys.frozen and sys._MEIPASS, set by a PyInstaller onefile bundle) it is
# the bundle's extracted resource directory; the exact resolution for a onedir/
# .app build is not settled yet (AUDIT.md B6 -- next session's build machinery).
# In dev, unchanged from before this split: the repo root.
if getattr(sys, "frozen", False):
    _meipass = getattr(sys, "_MEIPASS", None)
    RESOURCE_ROOT = Path(_meipass) if _meipass else Path(sys.executable).resolve().parent
else:
    RESOURCE_ROOT = Path(__file__).resolve().parent.parent

# DATA_ROOT is writable and owned by the user: entries.json, classes.json,
# settings.json, my-quotes.txt. Always Application Support, identically in dev
# and frozen -- no branch, no special-casing of development. See DECISIONS.md 14
# for why: it is the one directory a reinstall, an app replacement, or deleting
# the repo checkout must never touch.
DATA_ROOT = Path.home() / "Library" / "Application Support" / "PinkPageCount"

DEFAULT_DATA_FILE = DATA_ROOT / "entries.json"
# DECISIONS.md 12.1: classes live beside the entry log, never inside it.
DEFAULT_CLASSES_FILE = DATA_ROOT / "classes.json"
# DECISIONS.md 13: settings are a third file, beside the other two, for the same
# reason classes are -- a feature about presentation has no business being able to
# rewrite the reading log.
DEFAULT_SETTINGS_FILE = DATA_ROOT / "settings.json"
# DECISIONS.md 10.1 (amended): the canonical, bundled quote list is a read-only
# resource, replaced on every update, not user-editable.
DEFAULT_QUOTES_FILE = RESOURCE_ROOT / "quotes.txt"
# DECISIONS.md 10.1 (amended): the user's own quotes, unioned with the bundled
# list at read time. Optional, user-owned, survives updates.
DEFAULT_USER_QUOTES_FILE = DATA_ROOT / "my-quotes.txt"
# DECISIONS.md 5: Phase 4 serves the built front end straight off disk.
DEFAULT_DIST_DIR = RESOURCE_ROOT / "web" / "dist"


def data_file() -> Path:
    """Path to the JSON data file, overridable for tests via PAGECOUNT_DATA_FILE."""
    override = os.environ.get(DATA_FILE_ENV)
    return Path(override).expanduser().resolve() if override else DEFAULT_DATA_FILE


def classes_file() -> Path:
    """Path to the class file, overridable for tests via PAGECOUNT_CLASSES_FILE.

    A separate file from data_file() and always will be -- see DECISIONS.md 12.1.
    """
    override = os.environ.get(CLASSES_FILE_ENV)
    return Path(override).expanduser().resolve() if override else DEFAULT_CLASSES_FILE


def settings_file() -> Path:
    """Path to the settings file, overridable for tests via PAGECOUNT_SETTINGS_FILE.

    A separate file from data_file() and classes_file(), and always will be -- see
    DECISIONS.md 13.
    """
    override = os.environ.get(SETTINGS_FILE_ENV)
    return Path(override).expanduser().resolve() if override else DEFAULT_SETTINGS_FILE


def quotes_file() -> Path:
    """Path to the canonical, bundled quote file, overridable for tests via
    PAGECOUNT_QUOTES_FILE.

    Separate from data_file() and always will be -- see DECISIONS.md 10.
    """
    override = os.environ.get(QUOTES_FILE_ENV)
    return Path(override).expanduser().resolve() if override else DEFAULT_QUOTES_FILE


def user_quotes_file() -> Path:
    """Path to the user's own, optional quote file -- DECISIONS.md 10.1 (amended).

    Always under DATA_ROOT. Not overridable via env: the only caller is
    create_app()'s own default (when no `quotes` is injected), and tests
    construct QuoteSource directly against tmp_path fixtures rather than going
    through config at all (see tests/conftest.py), the same way they already
    do for data_file().
    """
    return DEFAULT_USER_QUOTES_FILE


def dist_dir() -> Path:
    """Path to the built front end, overridable for tests via PAGECOUNT_DIST_DIR.

    This is the `web/dist` Vite produces -- see DECISIONS.md 5.
    """
    override = os.environ.get(DIST_DIR_ENV)
    return Path(override).expanduser().resolve() if override else DEFAULT_DIST_DIR


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
