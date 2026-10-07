"""Where MySafe keeps its files on disk.

Order of precedence for the data folder:
1. The MYSAFE_DATA_DIR environment variable (development and tests).
2. Portable mode: a "MySafe-data" folder next to MySafe.exe (e.g. on a USB stick).
3. The normal per-user folder: %APPDATA%\\MySafe on Windows, ~/.local/share/MySafe on Linux.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_data_dir

from mysafe import APP_NAME

DB_FILENAME = "mysafe.db"  # old, unencrypted format (imported once, then removed)
VAULT_FILENAME = "vault.mysafe"
DATA_DIR_ENV = "MYSAFE_DATA_DIR"
PORTABLE_DIR_NAME = "MySafe-data"


def app_dir() -> Path | None:
    """Folder that contains the packaged MySafe executable, or None when run from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def program_file() -> Path | None:
    """The packaged MySafe executable (MySafe.exe), or None when run from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def portable_dir() -> Path | None:
    """The portable data folder next to the executable, if it exists."""
    base = app_dir()
    if base is None:
        return None
    candidate = base / PORTABLE_DIR_NAME
    return candidate if candidate.is_dir() else None


PORTABLE_ENV = "MYSAFE_PORTABLE"  # "1": treat the data folder as a USB copy (testing)


def is_portable() -> bool:
    if os.environ.get(PORTABLE_ENV) == "1":
        return True
    return os.environ.get(DATA_DIR_ENV) is None and portable_dir() is not None


def data_dir() -> Path:
    """Return the data folder (see module docstring), creating it if needed."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        path = Path(override)
    else:
        path = portable_dir() or Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def db_path() -> Path:
    """Return the full path of the database file."""
    return data_dir() / DB_FILENAME


def vault_path() -> Path:
    """Full path of the encrypted vault file."""
    return data_dir() / VAULT_FILENAME


def computer_vault_path() -> Path:
    """The vault in the normal per-user folder (used by the USB copy to sync back)."""
    return Path(user_data_dir(APP_NAME, appauthor=False, roaming=True)) / VAULT_FILENAME
