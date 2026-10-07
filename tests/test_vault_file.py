from __future__ import annotations

from pathlib import Path

from mysafe.services.vault_file import backup_path, discard_leftovers, read_vault, write_vault


def test_write_and_read(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "vault.mysafe"
    write_vault(path, b"one")
    assert read_vault(path) == b"one"
    assert not backup_path(path).exists()  # nothing to back up the first time


def test_previous_version_is_kept_as_backup(tmp_path: Path) -> None:
    path = tmp_path / "vault.mysafe"
    write_vault(path, b"one")
    write_vault(path, b"two")
    assert read_vault(path) == b"two"
    assert backup_path(path).read_bytes() == b"one"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vault.mysafe", "vault.mysafe.bak"]


def test_interrupted_save_leaves_old_file_intact(tmp_path: Path) -> None:
    path = tmp_path / "vault.mysafe"
    write_vault(path, b"good")
    # Simulate a crash after the temp file was written but before it replaced the vault.
    (tmp_path / "vault.mysafe.tmp").write_bytes(b"half-writ")
    assert read_vault(path) == b"good"
    discard_leftovers(path)
    assert not (tmp_path / "vault.mysafe.tmp").exists()
