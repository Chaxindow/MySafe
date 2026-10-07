from __future__ import annotations

import json
import os
import stat
import struct
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mysafe.db import open_database, to_bytes
from mysafe.models import FieldInput, FieldKind
from mysafe.services import crypto
from mysafe.services.crypto import KdfParams, WrongPasswordError
from mysafe.vault import Vault, VaultLockedError

FAST = KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "MySafe-data" / "vault.mysafe"


def _new(path: Path) -> tuple[Vault, str]:
    vault, recovery = Vault.create(path, "master pw", params=FAST)
    vault.repo.ensure_default_categories()
    return vault, recovery


def _games(vault: Vault) -> str:
    return next(c.id for c in vault.repo.list_categories() if c.name == "Games")


def test_create_saves_encrypted_file(path: Path) -> None:
    vault, recovery = _new(path)
    vault.repo.create_entry(
        _games(vault), "Steam", [FieldInput("Password", "Hunter2-secret", FieldKind.PASSWORD)]
    )
    raw = path.read_bytes()
    assert raw.startswith(b"MYSAFE")
    assert b"Hunter2-secret" not in raw and b"Steam" not in raw
    assert recovery.count("-") == 7
    with pytest.raises(FileExistsError):
        Vault.create(path, "x", params=FAST)


def test_changes_survive_reopen(path: Path) -> None:
    vault, _ = _new(path)
    entry = vault.repo.create_entry(_games(vault), "Steam")
    vault.repo.set_favorite(entry.id, True)
    vault.lock()

    again = Vault.unlock(path, "master pw")
    assert [e.title for e in again.repo.list_entries(favorites_only=True)] == ["Steam"]


def test_every_change_is_saved_immediately(path: Path) -> None:
    vault, _ = _new(path)
    before = path.read_bytes()
    vault.repo.create_category("Banking")
    assert path.read_bytes() != before


def test_wrong_password_and_recovery_key(path: Path) -> None:
    vault, recovery = _new(path)
    vault.repo.create_entry(_games(vault), "Steam")
    vault.lock()
    with pytest.raises(WrongPasswordError):
        Vault.unlock(path, "nope")

    rescued = Vault.unlock_with_recovery_key(path, recovery)
    rescued.change_password("brand new")
    rescued.lock()
    assert Vault.unlock(path, "brand new").repo.count_entries() == 1


def test_lock_blocks_access(path: Path) -> None:
    vault, _ = _new(path)
    vault.lock()
    assert vault.is_locked
    with pytest.raises(VaultLockedError):
        _ = vault.repo
    vault.lock()  # locking twice is harmless


def test_import_old_unencrypted_database(path: Path, tmp_path: Path) -> None:
    old = tmp_path / "mysafe.db"
    conn = open_database(old)
    from mysafe.db import Repository

    repo = Repository(conn)
    repo.ensure_default_categories()
    games = next(c.id for c in repo.list_categories() if c.name == "Games")
    repo.create_entry(games, "Old entry", [FieldInput("Password", "pw", FieldKind.PASSWORD)])
    conn.close()

    vault, _ = Vault.create(path, "master pw", import_from=old, params=FAST)
    entries = vault.repo.list_entries()
    assert [e.title for e in entries] == ["Old entry"]
    assert vault.repo.get_entry(entries[0].id).fields[0].value == "pw"
    vault.lock()
    assert Vault.unlock(path, "master pw").repo.count_entries() == 1


def test_backup_file_is_encrypted_too(path: Path) -> None:
    vault, _ = _new(path)
    vault.repo.create_entry(_games(vault), "Visible-Title-XYZ")
    vault.repo.create_category("Another change")
    backup = path.with_name(path.name + ".bak").read_bytes()
    assert backup.startswith(b"MYSAFE") and b"Visible-Title-XYZ" not in backup


def test_never_overwrites_a_change_made_elsewhere(path: Path) -> None:
    """E.g. the USB window is open while the computer window syncs into the USB file."""
    from mysafe.vault import VaultChangedElsewhereError

    vault, _ = _new(path)
    vault.lock()
    usb_window = Vault.unlock(path, "master pw")
    sync_side = Vault.unlock(path, "master pw")
    sync_side.repo.create_category("Added by sync")  # saves the file

    before = path.read_bytes()
    with pytest.raises(VaultChangedElsewhereError):
        usb_window.repo.create_category("Stale window change")
    assert path.read_bytes() == before  # the synced file was not overwritten
    assert "Added by sync" in [
        c.name for c in Vault.unlock(path, "master pw").repo.list_categories()
    ]


def test_own_saves_keep_working(path: Path) -> None:
    vault, _ = _new(path)
    for name in ("A", "B", "C"):
        vault.repo.create_category(name)  # each save updates the fingerprint
    vault.lock()
    assert {"A", "B", "C"} <= {
        c.name for c in Vault.unlock(path, "master pw").repo.list_categories()
    }


def test_new_recovery_key_only_after_confirmation(path: Path) -> None:
    vault, old = Vault.create(path, "master pw", params=FAST)
    shown: list[str] = []
    assert vault.new_recovery_key(lambda key: shown.append(key) is not None) is None
    Vault.unlock_with_recovery_key(path, old).lock()  # refused: the old key still works
    new = vault.new_recovery_key(lambda key: True)
    assert new is not None and new != old
    vault.lock()
    Vault.unlock_with_recovery_key(path, new).lock()
    with pytest.raises(WrongPasswordError):
        Vault.unlock_with_recovery_key(path, old)


def test_old_password_opens_nothing_after_a_change(path: Path) -> None:
    """Backups are re-encrypted: the old password must not unlock any file next to the vault."""
    vault, _ = _new(path)
    vault.repo.create_entry(_games(vault), "Steam")
    vault.snapshot()  # like a sync
    vault.change_password("new master pw")
    vault.repo.create_entry(_games(vault), "Epic")
    files = [path, path.with_name(path.name + ".bak"), path.with_name(path.name + ".before-sync")]
    assert all(f.exists() for f in files)
    for file in files:
        with pytest.raises(WrongPasswordError):
            crypto.open_with_password(file.read_bytes(), "master pw")
        crypto.open_with_password(file.read_bytes(), "new master pw")
    assert len(vault.older_keys()) == 1


def test_backups_list_and_restore(path: Path) -> None:
    vault, _ = _new(path)
    vault.repo.create_entry(_games(vault), "Steam")
    vault.repo.create_entry(_games(vault), "Epic")
    vault.repo.delete_entry(next(e.id for e in vault.repo.list_entries() if e.title == "Steam"))
    backups = vault.backups()
    assert [(b.kind, b.entry_count) for b in backups] == [("Previous save", 2)]
    vault.restore(backups[0].path)
    assert sorted(e.title for e in vault.repo.list_entries()) == ["Epic", "Steam"]
    before = path.with_name(path.name + ".before-restore")
    vault.restore(before)  # undo
    assert [e.title for e in vault.repo.list_entries()] == ["Epic"]
    vault.restore(before)  # redo
    assert len(vault.repo.list_entries()) == 2
    vault.lock()
    assert Vault.unlock(path, "master pw").repo.count_entries() == 2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_vault_files_are_private(path: Path) -> None:
    old_umask = os.umask(0o022)
    try:
        vault, _ = _new(path)
        vault.repo.create_entry(_games(vault), "Steam")
    finally:
        os.umask(old_umask)
    for file in (path, path.with_name(path.name + ".bak")):
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_old_format_vault_is_upgraded_on_unlock(path: Path) -> None:
    vault, _ = _new(path)
    vault.repo.create_entry(_games(vault), "Steam")
    plaintext = to_bytes(vault.repo.connection)
    vault.lock()
    # Rewrite the file in format 1 (symmetric key slots), as MySafe 0.1 previews did.
    data_key = os.urandom(32)

    def slot(secret: bytes, aad: bytes) -> dict[str, str]:
        salt, nonce = os.urandom(16), os.urandom(12)
        wrapped = AESGCM(crypto._derive(secret, salt, FAST)).encrypt(nonce, data_key, aad)
        return {"salt": crypto._b64(salt), "nonce": crypto._b64(nonce), "key": crypto._b64(wrapped)}

    old_recovery = crypto.new_recovery_key()
    header = {
        "version": 1,
        "cipher": "AES-256-GCM",
        "kdf": "argon2id",
        "kdf_params": FAST.to_dict(),
        "password": slot(b"master pw", crypto._AAD_PASSWORD),
        "recovery": slot(crypto.normalize_recovery_key(old_recovery), crypto._AAD_RECOVERY),
        "keys_updated_at": 1_700_000_000,
    }
    raw = json.dumps(header).encode()
    nonce = os.urandom(12)
    body = AESGCM(data_key).encrypt(nonce, plaintext, crypto.MAGIC + raw)
    path.write_bytes(crypto.MAGIC + struct.pack(">I", len(raw)) + raw + nonce + body)

    upgraded = Vault.unlock(path, "master pw")
    new_recovery = upgraded.recovery_key_to_show
    assert new_recovery is not None and upgraded.keys.version == crypto.FORMAT_VERSION
    assert [e.title for e in upgraded.repo.list_entries()] == ["Steam"]
    upgraded.lock()
    Vault.unlock_with_recovery_key(path, new_recovery).lock()
    reopened = Vault.unlock(path, "master pw")
    assert reopened.recovery_key_to_show is None
    reopened.lock()
