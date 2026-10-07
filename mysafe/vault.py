"""The encrypted vault: ties the crypto service, the vault file and the database together.

    vault = Vault.create(path, "master password")   # -> also returns the recovery key
    vault = Vault.unlock(path, "master password")
    vault.repo.create_entry(...)                     # every change is saved automatically
    vault.lock()

The decrypted database exists only in memory. Every successful write re-encrypts the whole
database and replaces the file atomically (see services/vault_file.py).

Changing the master password or the recovery key switches to a new data key. The old data
key is kept inside the (encrypted) database so older copies — a USB stick that was not
synced yet, backups — can still be opened and brought up to date; backups next to the vault
are re-encrypted with the new key right away.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mysafe.db import Repository, RepositoryError, open_from_bytes, to_bytes
from mysafe.services import crypto
from mysafe.services.vault_file import (
    backup_path,
    discard_leftovers,
    read_vault,
    write_vault,
)

SYNC_BACKUP_SUFFIX = ".before-sync"
RESTORE_BACKUP_SUFFIX = ".before-restore"


class VaultLockedError(RuntimeError):
    pass


class VaultChangedElsewhereError(RepositoryError):
    """The file was changed by another MySafe window or by Sync since we opened it."""

    def __init__(self) -> None:
        super().__init__(
            "This vault was changed by another MySafe window (for example by Sync), so your "
            "last change was not saved. Lock MySafe (Ctrl+L) and open it again to continue."
        )


@dataclass(frozen=True, slots=True)
class Backup:
    path: Path
    kind: str  # "Before sync", "Before restore", "Previous save"
    modified: float  # file time (seconds since epoch)
    entry_count: int


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Vault:
    def __init__(
        self,
        path: Path,
        keys: crypto.VaultKeys,
        plaintext: bytes | None,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.path = path
        self._keys: crypto.VaultKeys | None = keys
        self._clock = clock
        # Fingerprint of the file as we last read/wrote it: never overwrite someone else's save.
        self._known_digest: str | None = None
        self._conn = open_from_bytes(plaintext)
        self._repo: Repository | None = Repository(self._conn, clock, on_change=self.save)
        # Set when MySafe had to make a new recovery key (old-format vault upgraded):
        # the caller must show it to the user once.
        self.recovery_key_to_show: str | None = None

    # ----------------------------------------------------------- constructors

    @staticmethod
    def exists(path: Path) -> bool:
        return path.is_file()

    @classmethod
    def create(
        cls,
        path: Path,
        password: str,
        *,
        import_from: Path | None = None,
        params: crypto.KdfParams = crypto.DEFAULT_KDF,
        clock: Callable[[], int] | None = None,
    ) -> tuple[Vault, str]:
        """Create a new vault (optionally importing an old unencrypted mysafe.db).

        Returns the vault and its recovery key, which must be shown to the user once.
        """
        if path.exists():
            raise FileExistsError(f"A vault already exists at {path}")
        keys, recovery_key = crypto.create_keys(password, params=params)
        plaintext = import_from.read_bytes() if import_from is not None else None
        vault = cls(path, keys, plaintext, clock=clock)
        vault.save()
        return vault, recovery_key

    @classmethod
    def unlock(cls, path: Path, password: str, *, clock: Callable[[], int] | None = None) -> Vault:
        discard_leftovers(path)
        blob = read_vault(path)
        plaintext, keys = crypto.open_with_password(blob, password)
        vault = cls._opened(path, keys, plaintext, blob, clock)
        if keys.version != crypto.FORMAT_VERSION:  # old format: upgrade now
            new_keys, recovery = crypto.upgraded(keys, password)
            vault._switch_keys(new_keys)
            vault.recovery_key_to_show = recovery
        return vault

    @classmethod
    def unlock_with_recovery_key(
        cls, path: Path, recovery_key: str, *, clock: Callable[[], int] | None = None
    ) -> Vault:
        """Open with the recovery key. The caller must then set a new password."""
        discard_leftovers(path)
        blob = read_vault(path)
        plaintext, keys = crypto.open_with_recovery_key(blob, recovery_key)
        return cls._opened(path, keys, plaintext, blob, clock)

    @classmethod
    def open_copy(
        cls,
        path: Path,
        keys: crypto.VaultKeys,
        *,
        older_keys: tuple[bytes, ...] = (),
        clock: Callable[[], int] | None = None,
    ) -> Vault:
        """Open a copy of an unlocked vault (e.g. the USB copy) without asking for a password.

        Raises NeedsPasswordError if it is a copy whose password was changed there.
        """
        discard_leftovers(path)
        blob = read_vault(path)
        try:
            plaintext, copy_keys = crypto.open_with_data_key(
                blob, keys.data_key, older_keys=older_keys
            )
        except crypto.OtherVaultError:
            if keys.vault_id and crypto.peek_vault_id(blob) == keys.vault_id:
                raise crypto.NeedsPasswordError(
                    "The password of this copy was changed there."
                ) from None
            raise
        return cls._opened(path, copy_keys, plaintext, blob, clock)

    @classmethod
    def open_copy_with_password(
        cls, path: Path, password: str, *, clock: Callable[[], int] | None = None
    ) -> Vault:
        """Open a copy with its own password (no format upgrade; Sync decides the keys)."""
        discard_leftovers(path)
        blob = read_vault(path)
        plaintext, keys = crypto.open_with_password(blob, password)
        return cls._opened(path, keys, plaintext, blob, clock)

    @classmethod
    def _opened(
        cls,
        path: Path,
        keys: crypto.VaultKeys,
        plaintext: bytes,
        blob: bytes,
        clock: Callable[[], int] | None,
    ) -> Vault:
        vault = cls(path, keys, plaintext, clock=clock)
        vault._known_digest = _digest(blob)
        return vault

    # ------------------------------------------------------------------ state

    @property
    def is_locked(self) -> bool:
        return self._keys is None

    @property
    def repo(self) -> Repository:
        if self._repo is None:
            raise VaultLockedError("The vault is locked")
        return self._repo

    @property
    def keys(self) -> crypto.VaultKeys:
        if self._keys is None:
            raise VaultLockedError("The vault is locked")
        return self._keys

    def older_keys(self) -> tuple[bytes, ...]:
        return tuple(self.repo.old_data_keys())

    # ---------------------------------------------------------------- actions

    def save(self) -> None:
        """Encrypt the in-memory database and write it to disk atomically.

        Refuses to overwrite the file if someone else saved it since we last read/wrote it.
        """
        if (
            self._known_digest is not None
            and self.path.exists()
            and _digest(read_vault(self.path)) != self._known_digest
        ):
            raise VaultChangedElsewhereError()
        blob = crypto.seal(to_bytes(self._conn), self.keys)
        write_vault(self.path, blob)
        self._known_digest = _digest(blob)

    def change_password(self, new_password: str) -> None:
        """New master password (and a new data key). The recovery key keeps working."""
        if self.keys.version != crypto.FORMAT_VERSION:  # old format opened with recovery key
            new_keys, recovery = crypto.upgraded(self.keys, new_password)
            self.recovery_key_to_show = recovery
        else:
            new_keys = crypto.with_new_password(self.keys, new_password)
        self._switch_keys(new_keys)

    def new_recovery_key(self, confirm: Callable[[str], bool] | None = None) -> str | None:
        """Replace the recovery key. Returns the new one, or None if `confirm` said no.

        `confirm(key)` is called with the new key BEFORE anything changes (it shows the key
        to the user). Only if it returns True does the new key replace the old one; until
        then the old key keeps working.
        """
        new_keys, recovery = crypto.with_new_recovery_key(self.keys)
        if confirm is not None and not confirm(recovery):
            new_keys.wipe()
            return None
        self._switch_keys(new_keys)
        return recovery

    def use_keys(self, keys: crypto.VaultKeys) -> bool:
        """Open with the same password/recovery key as `keys` from now on (used by Sync).

        Returns True if anything changed.
        """
        if crypto.same_data_key(self.keys, keys) and self.keys.header == keys.header:
            return False
        self._switch_keys(keys.copy())
        return True

    def _switch_keys(self, new_keys: crypto.VaultKeys) -> None:
        old_key = bytes(self.keys.data_key)
        with self.repo.batch():
            if old_key != bytes(new_keys.data_key):
                self.repo.remember_old_data_keys([old_key])
            self.keys.replace_with(new_keys)
            self.save()  # saved with the new keys even if no row changed
        new_keys.wipe()
        self.reseal_backups()

    def verify_password(self, password: str) -> bool:
        """True if `password` opens this vault's file (used before changing it)."""
        try:
            crypto.open_with_password(read_vault(self.path), password)
        except crypto.WrongPasswordError:
            return False
        return True

    # ---------------------------------------------------------------- backups

    def backup_files(self) -> list[tuple[Path, str]]:
        return [
            (self.path.with_name(self.path.name + SYNC_BACKUP_SUFFIX), "Before sync"),
            (self.path.with_name(self.path.name + RESTORE_BACKUP_SUFFIX), "Before restore"),
            (backup_path(self.path), "Previous save"),
        ]

    def _open_backup(self, path: Path) -> tuple[bytes, crypto.VaultKeys]:
        return crypto.open_with_data_key(
            read_vault(path), self.keys.data_key, older_keys=self.older_keys()
        )

    def reseal_backups(self) -> None:
        """Re-encrypt backups that still use older keys, so old passwords can't open them."""
        for path, _kind in self.backup_files():
            if not path.is_file():
                continue
            try:
                plaintext, keys = self._open_backup(path)
            except (crypto.VaultCryptoError, OSError):
                continue  # not ours / unreadable: leave it alone
            if crypto.same_data_key(keys, self.keys) and keys.header == self.keys.header:
                continue
            write_vault(path, crypto.seal(plaintext, self.keys), keep_backup=False)

    def backups(self) -> list[Backup]:
        """Backups next to the vault that this vault can open, newest first."""
        found: list[Backup] = []
        for path, kind in self.backup_files():
            if not path.is_file():
                continue
            try:
                plaintext, _keys = self._open_backup(path)
            except (crypto.VaultCryptoError, OSError):
                continue
            repo = Repository(open_from_bytes(plaintext))
            try:
                count = repo.count_entries()
            finally:
                repo.close()
            found.append(Backup(path, kind, path.stat().st_mtime, count))
        rank = {"Before restore": 2, "Before sync": 1, "Previous save": 0}
        # Newest first; files written in the same second: the more meaningful one first.
        found.sort(key=lambda b: (int(b.modified), rank.get(b.kind, 0)), reverse=True)
        return found

    def restore(self, backup: Path) -> None:
        """Replace the contents with a backup (keeps the current password and recovery key).

        The current contents are kept as a "Before restore" backup first, so a restore can
        itself be undone. Afterwards `repo` is a new object: callers must reload.
        """
        plaintext, _keys = self._open_backup(backup)
        older = self.older_keys()
        if backup != self.path.with_name(self.path.name + RESTORE_BACKUP_SUFFIX):
            self.snapshot(RESTORE_BACKUP_SUFFIX)
        else:  # undoing a restore: swap, so the undo can be undone too
            self.snapshot(RESTORE_BACKUP_SUFFIX + ".tmp")
        self._conn.close()
        self._conn = open_from_bytes(plaintext)
        self._repo = Repository(self._conn, self._clock, on_change=self.save)
        with self._repo.batch():
            self._repo.remember_old_data_keys(older)
            self.save()
        swap = self.path.with_name(self.path.name + RESTORE_BACKUP_SUFFIX + ".tmp")
        if swap.exists():
            swap.replace(self.path.with_name(self.path.name + RESTORE_BACKUP_SUFFIX))

    def copy_to(self, path: Path) -> None:
        """Write an encrypted copy of this vault to `path` (e.g. a USB stick)."""
        if path.exists():
            raise FileExistsError(f"A vault already exists at {path}")
        if path.resolve() == self.path.resolve():
            raise ValueError("The copy must go to a different place than this vault.")
        write_vault(path, crypto.seal(to_bytes(self._conn), self.keys), keep_backup=False)

    def snapshot(self, suffix: str = SYNC_BACKUP_SUFFIX) -> Path:
        """Copy the current vault file next to itself (encrypted), e.g. before a Sync."""
        target = self.path.with_name(self.path.name + suffix)
        write_vault(target, read_vault(self.path), keep_backup=False)
        return target

    def lock(self) -> None:
        """Close the in-memory database and wipe the key. The object can't be used after."""
        if self._keys is None:
            return
        self._repo = None
        self._conn.close()
        self._keys.wipe()
        self._keys = None
