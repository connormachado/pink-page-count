"""Settings: theme choice, custom theme overrides, default chip. See DECISIONS.md 13.

Shaped like `app/classes.py`, but the payload is a single object rather than a list,
so it cannot reuse `jsonfile.envelope_list` unchanged -- that helper assumes a list
value. This module validates the `{schema_version, settings: {...}}` wrapper by hand
instead, while still reusing the same atomic write path and corrupt-file halt
(DECISIONS.md 3.1, 3.4).

**This module never opens entries.json or classes.json.** A feature about how the
page looks has no business being able to touch the reading log or the class list --
the same structural separation section 10 gives the quote file and section 12.1 gives
classes.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from .config import SETTINGS_SCHEMA_VERSION
from .jsonfile import CorruptDataFile, atomic_write_json, read_json_document
from .models import ValidationProblem, validate_color

# The preset ids the server recognizes. The server has no colors for these -- it only
# knows their ids, so a request naming an unknown one is a 422. The colors themselves
# live in web/src/theme.ts and nowhere else, mirroring how classes.py has no palette
# (DECISIONS.md 12.2). Keep this set identical to PRESETS' ids there.
THEME_IDS = frozenset({"pink", "jewel", "neutral", "cool", "contrast", "midnight"})
CUSTOM_THEME_ID = "custom"

# The semantic tokens a custom theme may override, spelled as the literal CSS
# custom-property names from web/src/tokens.css (DECISIONS.md 9, 13) -- not a
# snake_case shadow encoding. An unrecognized key is a 422: strict on purpose, the
# same reasoning storage.py gives for entry fields -- a typo'd key would otherwise be
# silently discarded the next time the file is written.
SEMANTIC_TOKENS = frozenset(
    {
        "--pink-hot",
        "--pink-wash",
        "--pink-surface",
        "--pink-edge",
        "--ink",
        "--rose-muted",
    }
)

DEFAULT_THEME = "pink"
DEFAULT_CHIP = "all_time"
CHIP_VALUES = frozenset({"all_time", "today", "streak"})

SETTINGS_FIELDS = ("theme", "custom_theme", "default_chip")


# --------------------------------------------------------------------------- #
# Per-field validation, shared by on-disk validation and the API (DECISIONS.md 4.1)
# --------------------------------------------------------------------------- #


def validate_theme(value: Any) -> str:
    if not isinstance(value, str) or (
        value != CUSTOM_THEME_ID and value not in THEME_IDS
    ):
        raise ValidationProblem(f"Unknown theme id {value!r}")
    return value


def validate_custom_theme(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationProblem("custom_theme must be an object or null")
    unknown = [key for key in value if key not in SEMANTIC_TOKENS]
    if unknown:
        raise ValidationProblem(
            f"custom_theme has unrecognized key(s): {', '.join(sorted(unknown))}"
        )
    return {key: validate_color(color) for key, color in value.items()}


def validate_default_chip(value: Any) -> str:
    if value not in CHIP_VALUES:
        raise ValidationProblem(
            f"default_chip must be one of {sorted(CHIP_VALUES)}, got {value!r}"
        )
    return value


# --------------------------------------------------------------------------- #
# Validation of what is already on disk (DECISIONS.md 3.4)
# --------------------------------------------------------------------------- #


def _validate_settings_document(document: Any, path: Path) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise CorruptDataFile(
            path, f"top level must be a JSON object, found {type(document).__name__}"
        )

    version = document.get("schema_version")
    if version is None:
        raise CorruptDataFile(path, "top level is missing 'schema_version'")
    if not isinstance(version, int) or isinstance(version, bool):
        raise CorruptDataFile(
            path, f"'schema_version' must be a whole number, got {version!r}"
        )
    if version > SETTINGS_SCHEMA_VERSION:
        raise CorruptDataFile(
            path,
            f"file uses schema_version {version}, but this code understands only "
            f"{SETTINGS_SCHEMA_VERSION}. It was written by a newer version of this app.",
        )

    settings = document.get("settings")
    if settings is None:
        raise CorruptDataFile(path, "top level is missing 'settings'")
    if not isinstance(settings, dict):
        raise CorruptDataFile(
            path, f"'settings' must be an object, found {type(settings).__name__}"
        )

    missing = [field for field in SETTINGS_FIELDS if field not in settings]
    if missing:
        raise CorruptDataFile(
            path, f"settings is missing required field(s): {', '.join(missing)}"
        )
    unknown = [key for key in settings if key not in SETTINGS_FIELDS]
    if unknown:
        raise CorruptDataFile(
            path,
            f"settings has unrecognized field(s): {', '.join(sorted(unknown))}. "
            f"Recognized fields are: {', '.join(SETTINGS_FIELDS)}",
        )

    try:
        return {
            "theme": validate_theme(settings["theme"]),
            "custom_theme": validate_custom_theme(settings["custom_theme"]),
            "default_chip": validate_default_chip(settings["default_chip"]),
        }
    except ValidationProblem as exc:
        raise CorruptDataFile(path, str(exc)) from None


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


class SettingsStore:
    """The settings object, held in memory and written through on every mutation."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._settings: dict[str, Any] = {}
        self._load()

    # -- loading ---------------------------------------------------------- #

    def _load(self) -> None:
        if not self.path.exists():
            # DECISIONS.md 3.3: missing file is not an error. It is created at the
            # current version, with the documented defaults -- a first write, not a
            # migration.
            self._settings = {
                "theme": DEFAULT_THEME,
                "custom_theme": None,
                "default_chip": DEFAULT_CHIP,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, self._document())
            return
        self._settings = _validate_settings_document(
            read_json_document(self.path), self.path
        )

    def _document(self) -> dict[str, Any]:
        return {"schema_version": SETTINGS_SCHEMA_VERSION, "settings": self._settings}

    def _persist(self) -> None:
        atomic_write_json(self.path, self._document())

    # -- reads ------------------------------------------------------------ #

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    # -- mutations -------------------------------------------------------- #

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply only the provided keys, re-validating each, and persist.

        `custom_theme` is replaced wholesale, not deep-merged -- the same "a field
        that was sent is the new value in full" rule every other field in this API
        already follows (DECISIONS.md 13).
        """
        with self._lock:
            merged = dict(self._settings)
            if "theme" in changes:
                merged["theme"] = validate_theme(changes["theme"])
            if "custom_theme" in changes:
                merged["custom_theme"] = validate_custom_theme(changes["custom_theme"])
            if "default_chip" in changes:
                merged["default_chip"] = validate_default_chip(changes["default_chip"])

            previous = self._settings
            self._settings = merged
            try:
                self._persist()
            except BaseException:
                self._settings = previous  # keep memory consistent with disk
                raise
            return dict(merged)


def load_settings_store_or_exit(path: Path | str) -> SettingsStore:
    """Open the settings file, or print the banner and halt (DECISIONS.md 3.4)."""
    try:
        return SettingsStore(path)
    except CorruptDataFile as exc:
        print(exc.banner(), file=sys.stderr, flush=True)
        raise SystemExit(2) from None
