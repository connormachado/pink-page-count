"""The two-base path split. See DECISIONS.md section 14.

RESOURCE_ROOT (read-only, ships with the app) and DATA_ROOT (writable, owned
by the user, survives a reinstall) must never overlap, and every env override
must resolve to an absolute path so a relative value can never silently
create a second file next to whatever the working directory happened to be.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config


# -- the two bases never overlap ----------------------------------------- #


def test_data_root_is_not_a_subpath_of_resource_root():
    assert not config.DATA_ROOT.is_relative_to(config.RESOURCE_ROOT)
    assert not config.RESOURCE_ROOT.is_relative_to(config.DATA_ROOT)


def test_data_root_is_application_support_pinkpagecount():
    assert config.DATA_ROOT == Path.home() / "Library" / "Application Support" / "PinkPageCount"
    # Exactly "PinkPageCount": no spaces, no apostrophes.
    assert config.DATA_ROOT.name == "PinkPageCount"
    assert " " not in config.DATA_ROOT.name
    assert "'" not in config.DATA_ROOT.name


def test_resource_root_is_the_repo_root_in_dev():
    """Unfrozen (every test run): identical to the pre-split REPO_ROOT."""
    assert config.RESOURCE_ROOT == Path(__file__).resolve().parent.parent
    assert (config.RESOURCE_ROOT / "app" / "config.py").is_file()


def test_bundled_resources_live_under_resource_root():
    assert config.DEFAULT_QUOTES_FILE.parent == config.RESOURCE_ROOT
    assert config.DEFAULT_DIST_DIR.is_relative_to(config.RESOURCE_ROOT)


def test_writable_files_live_under_data_root():
    assert config.DEFAULT_DATA_FILE.parent == config.DATA_ROOT
    assert config.DEFAULT_CLASSES_FILE.parent == config.DATA_ROOT
    assert config.DEFAULT_SETTINGS_FILE.parent == config.DATA_ROOT
    assert config.DEFAULT_USER_QUOTES_FILE.parent == config.DATA_ROOT
    assert config.user_quotes_file() == config.DEFAULT_USER_QUOTES_FILE


# -- env overrides always resolve absolutely ------------------------------ #

PATH_ENV_CASES = [
    (config.DATA_FILE_ENV, config.data_file),
    (config.CLASSES_FILE_ENV, config.classes_file),
    (config.SETTINGS_FILE_ENV, config.settings_file),
    (config.QUOTES_FILE_ENV, config.quotes_file),
    (config.DIST_DIR_ENV, config.dist_dir),
]


def test_relative_data_file_env_resolves_absolutely(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(config.DATA_FILE_ENV, "relative/entries.json")
    result = config.data_file()
    assert result.is_absolute()
    assert result == (tmp_path / "relative" / "entries.json").resolve()


@pytest.mark.parametrize("env_name,getter", PATH_ENV_CASES)
def test_every_path_env_override_resolves_absolutely(monkeypatch, tmp_path, env_name, getter):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(env_name, "relative/thing")
    result = getter()
    assert result.is_absolute()
    assert result == (tmp_path / "relative" / "thing").resolve()


@pytest.mark.parametrize("env_name,getter", PATH_ENV_CASES)
def test_env_override_still_expands_user(monkeypatch, env_name, getter):
    monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv(env_name, "~/pagecount-test-path")
    result = getter()
    assert result.is_absolute()
    assert str(result).startswith(str(Path.home()))
    assert "~" not in str(result)
