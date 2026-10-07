"""Start-up flow: create vs unlock, importing the old unencrypted database."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from mysafe.app import open_or_create_vault  # noqa: E402
from mysafe.db import Repository, open_database  # noqa: E402
from mysafe.demo import seed  # noqa: E402
from mysafe.vault import Vault  # noqa: E402


class FakeUI:
    def __init__(self, password: str | None = "Correct-horse-1") -> None:
        self.password = password
        self.setup_calls: list[bool] = []
        self.shown_keys: list[str] = []
        self.unlocked: list[Path] = []

    def choose_master_password(self, *, importing: bool) -> str | None:
        self.setup_calls.append(importing)
        return self.password

    def show_recovery_key(self, key: str) -> None:
        self.shown_keys.append(key)

    def unlock(self, path: Path) -> Vault | None:
        self.unlocked.append(path)
        return Vault.unlock(path, "Correct-horse-1")


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "vault.mysafe", tmp_path / "mysafe.db"


def test_first_start_creates_vault_and_shows_recovery_key(files: tuple[Path, Path]) -> None:
    vault_file, old_db = files
    ui = FakeUI()
    vault = open_or_create_vault(vault_file, old_db, ui)
    assert vault is not None and vault_file.exists()
    assert ui.setup_calls == [False]
    assert len(ui.shown_keys) == 1
    assert len(vault.repo.list_categories()) == 6  # default categories
    vault.lock()


def test_quitting_setup_creates_nothing(files: tuple[Path, Path]) -> None:
    vault_file, old_db = files
    assert open_or_create_vault(vault_file, old_db, FakeUI(password=None)) is None
    assert not vault_file.exists()


def test_old_unencrypted_data_is_imported_and_removed(files: tuple[Path, Path]) -> None:
    vault_file, old_db = files
    conn = open_database(old_db)
    added = seed(Repository(conn))
    conn.close()

    ui = FakeUI()
    vault = open_or_create_vault(vault_file, old_db, ui)
    assert vault is not None
    assert ui.setup_calls == [True]
    assert vault.repo.count_entries() == added
    assert len(vault.repo.list_categories()) == 6  # not duplicated
    assert not old_db.exists()  # plaintext copy is gone
    assert b"Demo-Passw0rd" not in vault_file.read_bytes()
    vault.lock()


def test_next_start_asks_to_unlock(files: tuple[Path, Path]) -> None:
    vault_file, old_db = files
    first = open_or_create_vault(vault_file, old_db, FakeUI())
    assert first is not None
    first.lock()

    ui = FakeUI()
    again = open_or_create_vault(vault_file, old_db, ui)
    assert ui.unlocked == [vault_file] and ui.setup_calls == []
    assert again is not None
    again.lock()


def test_leftover_plaintext_database_is_removed(files: tuple[Path, Path]) -> None:
    vault_file, old_db = files
    Vault.create(vault_file, "Correct-horse-1")[0].lock()
    old_db.write_bytes(b"SQLite format 3\x00 leftover plaintext")
    old_db.with_name("mysafe.db-wal").write_bytes(b"wal")
    vault = open_or_create_vault(vault_file, old_db, FakeUI())
    assert vault is not None
    assert not old_db.exists() and not old_db.with_name("mysafe.db-wal").exists()
    vault.lock()
