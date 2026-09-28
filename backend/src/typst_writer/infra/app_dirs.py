"""Per-user directories for local state and caches (never inside the workspace)."""

import os
import sys
from pathlib import Path

HOME_ENV_VAR = "TYPST_WRITER_HOME"  # overrides both directories (tests, portable installs)
APP_NAME = "typst-writer"


def config_dir() -> Path:
    if override := os.environ.get(HOME_ENV_VAR):
        return Path(override) / "config"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def cache_dir() -> Path:
    if override := os.environ.get(HOME_ENV_VAR):
        return Path(override) / "cache"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME
