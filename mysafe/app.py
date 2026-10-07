"""Application start-up and the vault session — the composition root.

Start-up flow:
  * vault.mysafe exists      → lock screen (master password, or recovery key → new password)
  * no vault yet             → choose a master password → show the recovery key once
                               (an old unencrypted mysafe.db is imported, then removed)

While running, `Session` handles everything that touches the vault file: Lock (Ctrl+L) and
auto-lock, changing the master password, a new recovery key, "Create USB copy" and Sync.
All questions to the user go through a `SessionUI`, so the whole flow is testable.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QWidget

from mysafe import APP_NAME, __version__
from mysafe.paths import (
    PORTABLE_DIR_NAME,
    VAULT_FILENAME,
    computer_vault_path,
    db_path,
    is_portable,
    program_file,
    vault_path,
)
from mysafe.resources import resource_path
from mysafe.services.crypto import NeedsPasswordError, VaultCryptoError, WrongPasswordError
from mysafe.sync import Side, SyncChoices, SyncPlan, apply_sync, plan_sync
from mysafe.ui.controller import AppController
from mysafe.ui.dialogs import confirm
from mysafe.ui.main_window import MainWindow
from mysafe.ui.restore_dialog import BackupChoice, RestoreDialog
from mysafe.ui.sync_dialog import SyncDialog
from mysafe.ui.theme import apply_theme
from mysafe.ui.unlock import (
    ChangePasswordDialog,
    CopyPasswordDialog,
    RecoveryKeyDialog,
    SetupDialog,
    UnlockDialog,
)
from mysafe.vault import Backup, Vault

APP_USER_MODEL_ID = "MySafe.MySafe"
_ACTIVITY_EVENTS = {
    QEvent.Type.KeyPress,
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseMove,
    QEvent.Type.Wheel,
}


# ------------------------------------------------------------------ questions


class StartupUI(Protocol):
    """The questions start-up asks the user (real dialogs in the app, fakes in tests)."""

    def choose_master_password(self, *, importing: bool) -> str | None: ...

    def show_recovery_key(self, key: str) -> None: ...

    def unlock(self, path: Path) -> Vault | None: ...


class SessionUI(StartupUI, Protocol):
    used_recovery_key: bool

    def offer_new_recovery_key(self) -> bool: ...

    def confirm_new_recovery_key(self, parent: QWidget | None, key: str) -> bool: ...

    def new_master_password(self, parent: QWidget, vault: Vault) -> str | None: ...

    def choose_folder(self, parent: QWidget, title: str) -> Path | None: ...

    def review_sync(
        self, parent: QWidget, plan: SyncPlan, local_name: str, remote_name: str, location: str
    ) -> SyncChoices | None: ...

    def ask_copy_password(
        self, parent: QWidget, location: str, other_name: str, error: str
    ) -> str | None: ...

    def choose_backup(self, parent: QWidget, backups: list[Backup]) -> Backup | None: ...

    def ask(self, parent: QWidget, title: str, message: str, confirm_text: str) -> bool: ...

    def inform(self, parent: QWidget | None, title: str, message: str) -> None: ...

    def warn(self, parent: QWidget, title: str, message: str) -> None: ...


class DialogUI:
    """SessionUI implemented with the real dialogs."""

    def __init__(self) -> None:
        self.used_recovery_key = False

    def choose_master_password(self, *, importing: bool) -> str | None:
        dialog = SetupDialog(importing_old_data=importing)
        if dialog.exec() != SetupDialog.DialogCode.Accepted:
            return None
        return dialog.chosen_password()

    def show_recovery_key(self, key: str) -> None:
        RecoveryKeyDialog(key).exec()

    def unlock(self, path: Path) -> Vault | None:
        self.used_recovery_key = False

        def set_password(vault: Vault, new_password: str) -> Vault:
            vault.change_password(new_password)
            self.used_recovery_key = True
            return vault

        dialog = UnlockDialog(
            lambda password: Vault.unlock(path, password),
            lambda key: Vault.unlock_with_recovery_key(path, key),  # step 1: check the key
            set_password,  # step 2: only after the key was right
            discard=lambda vault: vault.lock(),
            location=str(path),
            portable=is_portable(),
        )
        if dialog.exec() != UnlockDialog.DialogCode.Accepted:
            return None
        vault = dialog.vault
        return vault if isinstance(vault, Vault) else None

    def offer_new_recovery_key(self) -> bool:
        return confirm(
            None,
            "New recovery key",
            "You opened MySafe with your recovery key. Create a new one?",
            "Create new key",
            details=[
                "Recommended if someone else may have seen the old key.",
                "You see the new key first; the old one works until you confirm it.",
            ],
            cancel_text="Keep the old key",
        )

    def confirm_new_recovery_key(self, parent: QWidget | None, key: str) -> bool:
        dialog = RecoveryKeyDialog(key, replacing=True, parent=parent)
        return dialog.exec() == RecoveryKeyDialog.DialogCode.Accepted

    def new_master_password(self, parent: QWidget, vault: Vault) -> str | None:
        dialog = ChangePasswordDialog(vault.verify_password, parent)
        if dialog.exec() != ChangePasswordDialog.DialogCode.Accepted:
            return None
        return dialog.chosen_password()

    def choose_folder(self, parent: QWidget, title: str) -> Path | None:
        folder = QFileDialog.getExistingDirectory(parent, title)
        return Path(folder) if folder else None

    def review_sync(
        self, parent: QWidget, plan: SyncPlan, local_name: str, remote_name: str, location: str
    ) -> SyncChoices | None:
        dialog = SyncDialog(
            plan,
            local_name=local_name,
            remote_name=remote_name,
            remote_location=location,
            parent=parent,
        )
        if dialog.exec() != SyncDialog.DialogCode.Accepted:
            return None
        return dialog.choices()

    def ask_copy_password(
        self, parent: QWidget, location: str, other_name: str, error: str
    ) -> str | None:
        dialog = CopyPasswordDialog(location, other_name, error, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.chosen_password()

    def choose_backup(self, parent: QWidget, backups: list[Backup]) -> Backup | None:
        choices = [
            BackupChoice(
                b.kind,
                f"{datetime.fromtimestamp(b.modified):%d %b %Y, %H:%M}  ·  "
                f"{b.entry_count} entr{'y' if b.entry_count == 1 else 'ies'}",
            )
            for b in backups
        ]
        dialog = RestoreDialog(choices, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        index = dialog.chosen_index()
        return backups[index] if index is not None else None

    def ask(self, parent: QWidget, title: str, message: str, confirm_text: str) -> bool:
        return confirm(parent, title, message, confirm_text)

    def inform(self, parent: QWidget | None, title: str, message: str) -> None:
        QMessageBox.information(parent, title, message)

    def warn(self, parent: QWidget, title: str, message: str) -> None:
        QMessageBox.warning(parent, title, message)


# ------------------------------------------------------------------ start-up


def _remove_plaintext_database(path: Path) -> None:
    """Delete the old unencrypted database after a successful import (overwrite first)."""
    for file in [path.with_name(path.name + suffix) for suffix in ("", "-journal", "-wal", "-shm")]:
        if not file.exists():
            continue
        try:
            size = file.stat().st_size
            with open(file, "r+b") as handle:  # best effort; SSDs may keep old copies
                handle.write(b"\0" * size)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            file.unlink(missing_ok=True)


def open_or_create_vault(vault_file: Path, old_database: Path, ui: StartupUI) -> Vault | None:
    """Return an unlocked vault, or None if the user quit."""
    if Vault.exists(vault_file):
        if old_database.exists():  # an import that was interrupted: finish the clean-up
            _remove_plaintext_database(old_database)
        return ui.unlock(vault_file)

    importing = old_database.exists()
    password = ui.choose_master_password(importing=importing)
    if password is None:
        return None
    vault, recovery_key = Vault.create(
        vault_file, password, import_from=old_database if importing else None
    )
    vault.repo.ensure_default_categories()
    if importing:
        _remove_plaintext_database(old_database)
    ui.show_recovery_key(recovery_key)
    return vault


def resolve_vault_location(folder: Path) -> Path:
    """The vault file for a chosen folder.

    <folder>/MySafe-data/vault.mysafe (a USB stick) or <folder>/vault.mysafe (a data folder).
    """
    if folder.suffix == ".mysafe":
        return folder
    portable = folder / PORTABLE_DIR_NAME / VAULT_FILENAME
    direct = folder / VAULT_FILENAME
    if folder.name == PORTABLE_DIR_NAME or (direct.exists() and not portable.exists()):
        return direct
    return portable


def copy_program_to(folder: Path) -> Path | None:
    """Put the packaged program next to a USB copy, so the stick works on any computer.

    Only for the packaged app (MySafe.exe); returns None when run from source or when the
    copy failed (e.g. the program on the stick is running right now).
    """
    program = program_file()
    if program is None:
        return None
    target = folder / program.name
    try:
        if target.exists() and target.resolve() == program:
            return target
        shutil.copy2(program, target)
    except OSError:
        return None
    return target


# -------------------------------------------------------------------- session


class Session(QObject):
    """One unlocked vault + its main window. Survives Lock → Unlock cycles."""

    def __init__(
        self,
        app: QApplication,
        ui: SessionUI,
        *,
        vault_file: Path | None = None,
        old_database: Path | None = None,
        portable: bool | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.ui = ui
        self.vault_file = vault_file or vault_path()
        self.old_database = old_database or db_path()
        self.portable = is_portable() if portable is None else portable
        self.vault: Vault | None = None
        self.controller: AppController | None = None
        self.window: MainWindow | None = None
        self._locking = False
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._on_idle)
        app.installEventFilter(self)

    # ------------------------------------------------------------- lifecycle

    def start(self) -> bool:
        vault = open_or_create_vault(self.vault_file, self.old_database, self.ui)
        if vault is None:
            return False
        self._open(vault)
        return True

    def _open(self, vault: Vault) -> None:
        self.vault = vault
        if vault.recovery_key_to_show is not None:  # vault upgraded to the safer format
            self.ui.inform(
                None,
                "Vault upgraded",
                "Your vault now uses MySafe's improved encryption. Because of that you get "
                "a new recovery key: write it down on the next screen. "
                "The old recovery key no longer works.",
            )
            self.ui.show_recovery_key(vault.recovery_key_to_show)
            vault.recovery_key_to_show = None
        elif self.ui.used_recovery_key and self.ui.offer_new_recovery_key():
            vault.new_recovery_key(lambda key: self.ui.confirm_new_recovery_key(None, key))
        self.ui.used_recovery_key = False  # ask only once
        controller = AppController(vault.repo)
        self.controller = controller
        apply_theme(self.app, controller.theme())
        controller.settings_changed.connect(self._on_settings_changed)
        window = MainWindow(
            controller,
            vault_location=str(vault.path),
            portable=self.portable,
            actions=self,
        )
        window.closing.connect(self._on_window_closing)
        self.window = window
        window.show()
        self._restart_idle_timer()

    def _close_window(self) -> None:
        if self.window is not None:
            self.window.clipboard.flush()  # don't leave a copied password behind
            self._locking = True
            self.window.close()
            self.window.deleteLater()
            self._locking = False
        self.window = None
        self.controller = None

    def shutdown(self) -> None:
        self.idle_timer.stop()
        if self.window is not None:
            self.window.clipboard.flush()
        if self.vault is not None:
            self.vault.lock()
            self.vault = None

    def _on_window_closing(self) -> None:
        if not self._locking:
            self.shutdown()
            self.app.quit()

    # ------------------------------------------------------------------ lock

    def lock(self) -> None:
        """Ctrl+L / auto-lock: close everything, wipe the key, show the lock screen."""
        QTimer.singleShot(0, self.lock_now)  # leave the menu/timer handler first

    def lock_now(self) -> None:
        if self.vault is None:
            return
        self.idle_timer.stop()
        self._close_window()
        self.vault.lock()
        self.vault = None
        reopened = self.ui.unlock(self.vault_file)
        if reopened is None:
            self.app.quit()
            return
        self._open(reopened)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in _ACTIVITY_EVENTS and self.idle_timer.isActive():
            self._restart_idle_timer()
        return False

    def _restart_idle_timer(self) -> None:
        minutes = self.controller.auto_lock_minutes() if self.controller else 0
        if minutes > 0 and self.vault is not None:
            self.idle_timer.start(minutes * 60_000)
        else:
            self.idle_timer.stop()

    def _on_idle(self) -> None:
        """Auto-lock: close any open dialog (unsaved edits are dropped), then lock."""
        for _ in range(20):
            dialog = QApplication.activeModalWidget()
            if dialog is None:
                break
            if isinstance(dialog, QDialog):
                dialog.reject()
            else:
                dialog.close()
            QApplication.processEvents()
        self.lock_now()

    def _on_settings_changed(self) -> None:
        if self.controller is not None:
            apply_theme(self.app, self.controller.theme())
        self._restart_idle_timer()

    # -------------------------------------------------------------- security

    def change_master_password(self, parent: QWidget) -> None:
        if self.vault is None:
            return
        new_password = self.ui.new_master_password(parent, self.vault)
        if new_password:
            self.vault.change_password(new_password)
            self.ui.inform(
                parent,
                "Master password changed",
                "Use the new password from now on. Your recovery key still works.\n\n"
                "Backups on this computer were re-encrypted, so the old password no longer "
                "opens them. A USB copy still opens with the old password until you sync it.",
            )

    def new_recovery_key(self, parent: QWidget) -> None:
        """Show a new key; it replaces the old one only if the user confirms it."""
        if self.vault is None:
            return
        self.vault.new_recovery_key(lambda key: self.ui.confirm_new_recovery_key(parent, key))

    # ------------------------------------------------------------------ USB

    @property
    def local_name(self) -> str:
        return "This USB" if self.portable else "This computer"

    @property
    def remote_name(self) -> str:
        return "Computer" if self.portable else "USB"

    def create_usb_copy(self, parent: QWidget) -> None:
        if self.vault is None or self.controller is None:
            return
        folder = self.ui.choose_folder(parent, "Choose the USB stick (or a folder) for the copy")
        if folder is None:
            return
        target = resolve_vault_location(folder)
        try:
            self.vault.copy_to(target)
        except FileExistsError:
            self.ui.warn(
                parent,
                "Create USB copy",
                f"There is already a MySafe vault at\n{target}\n\nUse Sync to update it.",
            )
            return
        except (ValueError, OSError) as exc:
            self.ui.warn(parent, "Create USB copy", f"The copy could not be created: {exc}")
            return
        copy = Vault.open_copy(target, self.vault.keys)
        copy.repo.set_setting("sync_target", str(self.vault.path))  # the copy syncs back here
        copy.lock()
        self.controller.set_sync_target(str(target))
        program = (
            copy_program_to(target.parent.parent)
            if target.parent.name == PORTABLE_DIR_NAME
            else None
        )
        start = (
            f"\n\nTo use it on another computer, open {program} on the stick."
            if program is not None
            else ""
        )
        self.ui.inform(
            parent,
            "USB copy created",
            f"An encrypted copy of your vault is now at\n{target}\n\n"
            "It opens with the same master password. Use File → Sync to keep both up to date."
            + start,
        )

    def _sync_target(self, parent: QWidget) -> Path | None:
        assert self.controller is not None
        remembered = self.controller.sync_target()
        if remembered and Path(remembered).exists():
            return Path(remembered)
        if self.portable and computer_vault_path().exists():
            return computer_vault_path()
        if remembered:
            self.ui.inform(
                parent,
                "Sync",
                f"The other vault was not found at\n{remembered}\n\n"
                "Plug in the USB stick, or choose where the other vault is.",
            )
        folder = self.ui.choose_folder(parent, "Where is the other MySafe vault?")
        return resolve_vault_location(folder) if folder else None

    def _open_other_copy(self, parent: QWidget, target: Path) -> tuple[Vault, bool] | None:
        """Open the other copy: with the keys we know, or with its own password if needed.

        Returns (vault, opened_with_its_password) or None if cancelled / impossible.
        """
        assert self.vault is not None
        try:
            return (
                Vault.open_copy(target, self.vault.keys, older_keys=self.vault.older_keys()),
                False,
            )
        except FileNotFoundError:
            self.ui.warn(parent, "Sync", f"No MySafe vault was found at\n{target}")
            return None
        except NeedsPasswordError:
            pass
        except (VaultCryptoError, OSError) as exc:
            self.ui.warn(parent, "Sync", str(exc))
            return None
        error = ""
        while True:
            password = self.ui.ask_copy_password(parent, str(target), self.remote_name, error)
            if password is None:
                return None
            try:
                other = Vault.open_copy_with_password(target, password)
            except WrongPasswordError:
                error = "Wrong password — that copy did not open."
                continue
            except (VaultCryptoError, OSError) as exc:
                self.ui.warn(parent, "Sync", str(exc))
                return None
            if other.keys.vault_id != self.vault.keys.vault_id:
                other.lock()
                self.ui.warn(parent, "Sync", "That vault is not a copy of yours.")
                return None
            return other, True

    def sync(self, parent: QWidget) -> None:
        if self.vault is None or self.controller is None:
            return
        target = self._sync_target(parent)
        if target is None:
            return
        if target.resolve() == self.vault.path.resolve():
            self.ui.warn(parent, "Sync", "That is this vault itself. Choose the other copy.")
            return
        opened = self._open_other_copy(parent, target)
        if opened is None:
            return
        remote, verified = opened
        try:
            plan = plan_sync(
                self.vault.repo,
                remote.repo,
                self.vault.keys,
                remote.keys,
                remote_verified=verified,
            )
            self.controller.set_sync_target(str(target))
            if plan.is_empty:
                self.ui.inform(parent, "Sync", "Everything is already in sync.")
                return
            choices = self.ui.review_sync(
                parent, plan, self.local_name, self.remote_name, str(target)
            )
            if choices is None:
                return
            self.vault.snapshot()
            remote.snapshot()
            result = apply_sync(self.vault.repo, remote.repo, plan, choices)
            self.vault.save()
            remote.save()
            if plan.keys_from is Side.REMOTE:
                self.vault.use_keys(remote.keys)
            elif plan.keys_from is Side.LOCAL:
                remote.use_keys(self.vault.keys)
            # Old keys must not open the backups either.
            self.vault.reseal_backups()
            remote.reseal_backups()
        finally:
            remote.lock()
        self.controller.refresh_all()
        self.ui.inform(parent, "Sync finished", "\n".join(result.summary(self.remote_name)))

    # --------------------------------------------------------------- restore

    def restore_backup(self, parent: QWidget) -> None:
        if self.vault is None:
            return
        backups = self.vault.backups()
        choice = self.ui.choose_backup(parent, backups)
        if choice is None:
            return
        try:
            self.vault.restore(choice.path)
        except (VaultCryptoError, OSError) as exc:
            self.ui.warn(parent, "Restore from backup", f"The backup could not be restored: {exc}")
            return
        vault = self.vault
        self._close_window()
        self._open(vault)  # reload everything from the restored contents
        self.ui.inform(
            self.window,
            "Restore from backup",
            "The backup was restored. What you had before is kept as the "
            "“Before restore” backup (File → Restore from backup…).",
        )


# ------------------------------------------------------------------------ main


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (32, 64, 256):
        icon.addFile(str(resource_path(f"icon-{size}.png")))
    return icon


def _use_own_taskbar_icon() -> None:
    """On Windows, show MySafe's icon in the taskbar instead of Python's."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def main() -> int:
    if "--self-check" in sys.argv:  # packaged-build smoke test, no window (see self_check.py)
        from mysafe import self_check

        index = sys.argv.index("--self-check")
        report = Path(sys.argv[index + 1]) if len(sys.argv) > index + 1 else None
        return self_check.run(report)
    _use_own_taskbar_icon()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # Lock closes the window without quitting
    apply_theme(app, "system")  # the saved theme lives inside the (still locked) vault

    session = Session(app, DialogUI())
    if not session.start():
        return 0
    try:
        return app.exec()
    finally:
        session.shutdown()
