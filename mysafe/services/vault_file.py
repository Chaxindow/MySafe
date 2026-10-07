"""Reading and safely writing the vault file.

Writes are atomic: the new contents go to a temporary file in the same folder, are flushed
to disk, and only then replace the vault. The previous version is kept as ``<name>.bak``.
If the USB stick is pulled out mid-save, either the old or the new vault survives intact.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

BACKUP_SUFFIX = ".bak"
_TMP_SUFFIX = ".tmp"
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
_BINARY = getattr(os, "O_BINARY", 0)  # Windows: no newline translation


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def read_vault(path: Path) -> bytes:
    return path.read_bytes()


def _fsync_dir(folder: Path) -> None:
    if sys.platform == "win32":
        return  # not supported on Windows; os.replace is still atomic there
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def make_private_dir(folder: Path) -> None:
    """Create a folder only the current user can open (on Linux; Windows uses its ACLs)."""
    folder.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    if os.name == "posix":
        with contextlib.suppress(OSError):  # e.g. a FAT USB stick has no permissions
            os.chmod(folder, PRIVATE_DIR_MODE)


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if os.name == "posix":
        with contextlib.suppress(OSError):
            os.chmod(path, PRIVATE_FILE_MODE)  # also if the file already existed


def write_vault(path: Path, data: bytes, *, keep_backup: bool = True) -> None:
    """Atomically replace `path` with `data`, keeping the previous file as a backup.

    Files are created readable by the current user only (Linux: mode 600).
    """
    make_private_dir(path.parent)
    tmp = path.with_name(path.name + _TMP_SUFFIX)
    _write_private(tmp, data)
    if keep_backup and path.exists():
        bak = backup_path(path)
        bak_tmp = bak.with_name(bak.name + _TMP_SUFFIX)
        _write_private(bak_tmp, path.read_bytes())
        os.replace(bak_tmp, bak)
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def discard_leftovers(path: Path) -> None:
    """Remove temporary files left by an interrupted save."""
    for leftover in (
        path.with_name(path.name + _TMP_SUFFIX),
        backup_path(path).with_name(backup_path(path).name + _TMP_SUFFIX),
    ):
        leftover.unlink(missing_ok=True)
