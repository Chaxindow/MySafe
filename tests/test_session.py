"""End-to-end: the same steps a user takes — USB copy, edits on both sides, Sync, Lock."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from mysafe.app import Session, resolve_vault_location  # noqa: E402
from mysafe.models import FieldInput, FieldKind  # noqa: E402
from mysafe.services.crypto import WrongPasswordError  # noqa: E402
from mysafe.sync import Side, SyncChoices, SyncPlan  # noqa: E402
from mysafe.vault import Backup, Vault  # noqa: E402

PASSWORD = "Correct-horse-1"


class FakeUI:
    def __init__(self, folder: Path | None = None) -> None:
        self.password = PASSWORD
        self.folder = folder
        self.used_recovery_key = False
        self.recovery_keys: list[str] = []
        self.unlocks = 0
        self.plans: list[SyncPlan] = []
        self.choices: SyncChoices | None = None  # None -> defaults
        self.messages: list[tuple[str, str]] = []
        self.answer = True
        self.next_password: str | None = None
        self.keep_new_key = True
        self.copy_passwords: list[str] = []  # answers for "password of the other copy"
        self.copy_password_errors: list[str] = []
        self.backup_choice: int | None = 0
        self.backup_kind: str | None = None  # choose by kind instead of position
        self.backups_offered: list[Backup] = []

    # start-up
    def choose_master_password(self, *, importing: bool) -> str | None:
        return self.password

    def show_recovery_key(self, key: str) -> None:
        self.recovery_keys.append(key)

    def unlock(self, path: Path) -> Vault | None:
        self.unlocks += 1
        return Vault.unlock(path, self.password)

    # session
    def offer_new_recovery_key(self) -> bool:
        return False

    def confirm_new_recovery_key(self, parent: QWidget | None, key: str) -> bool:
        self.recovery_keys.append(key)
        return self.keep_new_key

    def new_master_password(self, parent: QWidget, vault: Vault) -> str | None:
        assert vault.verify_password(self.password)
        return self.next_password

    def choose_folder(self, parent: QWidget, title: str) -> Path | None:
        return self.folder

    def review_sync(
        self, parent: QWidget, plan: SyncPlan, local_name: str, remote_name: str, location: str
    ) -> SyncChoices | None:
        self.plans.append(plan)
        return self.choices or SyncChoices.defaults(plan)

    def ask_copy_password(
        self, parent: QWidget, location: str, other_name: str, error: str
    ) -> str | None:
        self.copy_password_errors.append(error)
        return self.copy_passwords.pop(0) if self.copy_passwords else None

    def choose_backup(self, parent: QWidget, backups: list[Backup]) -> Backup | None:
        self.backups_offered = list(backups)
        if self.backup_kind is not None:
            return next(b for b in backups if b.kind == self.backup_kind)
        if self.backup_choice is None or not backups:
            return None
        return backups[self.backup_choice]

    def ask(self, parent: QWidget, title: str, message: str, confirm_text: str) -> bool:
        return self.answer

    def inform(self, parent: QWidget | None, title: str, message: str) -> None:
        self.messages.append((title, message))

    def warn(self, parent: QWidget, title: str, message: str) -> None:
        self.messages.append((f"WARN {title}", message))


@pytest.fixture
def app(qtbot) -> QApplication:  # type: ignore[no-untyped-def]
    instance = QApplication.instance()
    assert isinstance(instance, QApplication)
    return instance


def _session(app: QApplication, ui: FakeUI, vault_file: Path, *, portable: bool = False) -> Session:
    session = Session(
        app,
        ui,
        vault_file=vault_file,
        old_database=vault_file.with_name("none.db"),
        portable=portable,
    )
    assert session.start()
    return session


def _add(session: Session, title: str, category: str = "Games") -> str:
    assert session.vault is not None
    repo = session.vault.repo
    cid = next(c.id for c in repo.list_categories() if c.name == category)
    return repo.create_entry(
        cid, title, [FieldInput("Password", f"{title}-pw", FieldKind.PASSWORD)]
    ).id


def _titles(session: Session) -> list[str]:
    assert session.vault is not None
    return sorted(e.title for e in session.vault.repo.list_entries())


def test_resolve_vault_location(tmp_path: Path) -> None:
    assert resolve_vault_location(tmp_path / "E") == tmp_path / "E" / "MySafe-data" / "vault.mysafe"
    assert (
        resolve_vault_location(tmp_path / "MySafe-data")
        == tmp_path / "MySafe-data" / "vault.mysafe"
    )
    assert resolve_vault_location(tmp_path / "x.mysafe") == tmp_path / "x.mysafe"


def test_full_usb_round_trip(app: QApplication, tmp_path: Path) -> None:
    usb_folder = tmp_path / "USB"
    pc_ui = FakeUI(folder=usb_folder)
    pc = _session(app, pc_ui, tmp_path / "pc" / "vault.mysafe")
    for title in ("Steam", "Gmail – Personal", "Netflix – Family"):
        _add(pc, title)

    # 1) Create the USB copy.
    pc.create_usb_copy(pc.window)  # type: ignore[arg-type]
    usb_file = usb_folder / "MySafe-data" / "vault.mysafe"
    assert usb_file.exists()
    assert pc.controller is not None and pc.controller.sync_target() == str(usb_file)

    # 2) Edit on the USB (as if MySafe ran from the stick): add one, delete one.
    usb_ui = FakeUI()
    usb = _session(app, usb_ui, usb_file, portable=True)
    assert _titles(usb) == _titles(pc)
    _add(usb, "Discord", "Social Media")
    assert usb.vault is not None
    netflix = next(e.id for e in usb.vault.repo.list_entries() if e.title.startswith("Netflix"))
    usb.vault.repo.delete_entry(netflix)
    usb.shutdown()

    # 3) Edit on the computer: two new entries.
    _add(pc, "Spotify", "Streaming")
    _add(pc, "Epic Games")

    # 4) Sync from the computer.
    pc.sync(pc.window)  # type: ignore[arg-type]
    plan = pc_ui.plans[-1]
    assert sorted((n.entry.title, n.source) for n in plan.new_entries) == [
        ("Discord", Side.REMOTE),
        ("Epic Games", Side.LOCAL),
        ("Spotify", Side.LOCAL),
    ]
    assert [(d.item.title, d.deleted_on) for d in plan.deletions] == [
        ("Netflix – Family", Side.REMOTE)
    ]
    title, summary = pc_ui.messages[-1]
    assert title == "Sync finished" and "copied to USB" in summary
    expected = ["Discord", "Epic Games", "Gmail – Personal", "Spotify", "Steam"]
    assert _titles(pc) == expected
    assert usb_file.with_name("vault.mysafe.before-sync").exists()

    # 5) The USB now has exactly the same entries, and a second sync has nothing to do.
    usb = _session(app, FakeUI(), usb_file, portable=True)
    assert _titles(usb) == expected
    usb.shutdown()
    pc.sync(pc.window)  # type: ignore[arg-type]
    assert pc_ui.messages[-1] == ("Sync", "Everything is already in sync.")
    pc.shutdown()


def test_conflict_choice_is_respected(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI(folder=tmp_path / "USB")
    pc = _session(app, ui, tmp_path / "pc" / "vault.mysafe")
    steam = _add(pc, "Steam")
    pc.create_usb_copy(pc.window)  # type: ignore[arg-type]
    usb_file = tmp_path / "USB" / "MySafe-data" / "vault.mysafe"

    usb = _session(app, FakeUI(), usb_file, portable=True)
    assert usb.vault is not None
    usb.vault.repo.update_entry(
        steam,
        category_id=usb.vault.repo.get_entry(steam).category_id,
        title="Steam (USB)",
        fields=[],
    )
    usb.shutdown()
    assert pc.vault is not None
    pc.vault.repo.update_entry(
        steam, category_id=pc.vault.repo.get_entry(steam).category_id, title="Steam (PC)", fields=[]
    )

    ui.choices = SyncChoices(keep={steam: Side.REMOTE})
    pc.sync(pc.window)  # type: ignore[arg-type]
    assert len(ui.plans[-1].conflicts) == 1
    assert _titles(pc) == ["Steam (USB)"]
    pc.shutdown()


def test_password_change_reaches_the_usb(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI(folder=tmp_path / "USB")
    pc = _session(app, ui, tmp_path / "pc" / "vault.mysafe")
    pc.create_usb_copy(pc.window)  # type: ignore[arg-type]
    assert pc.vault is not None
    pc.vault.keys.header["keys_updated_at"] = 0  # pretend the copy was made earlier

    ui.next_password = "Brand-new-pass-2"
    pc.change_master_password(pc.window)  # type: ignore[arg-type]
    pc.sync(pc.window)  # type: ignore[arg-type]
    assert "Master password on USB updated to match" in ui.messages[-1][1]
    usb_file = tmp_path / "USB" / "MySafe-data" / "vault.mysafe"
    assert Vault.unlock(usb_file, "Brand-new-pass-2").repo.list_categories()
    pc.shutdown()


def test_lock_and_auto_lock(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI()
    session = _session(app, ui, tmp_path / "vault.mysafe")
    first_window = session.window
    session.lock_now()
    assert ui.unlocks == 1
    assert session.window is not None and session.window is not first_window
    assert session.vault is not None and not session.vault.is_locked

    assert not session.idle_timer.isActive()  # auto-lock is off by default
    assert session.controller is not None
    session.controller.save_settings(
        theme="system", clipboard_clear_seconds=20, auto_lock_minutes=5
    )
    assert session.idle_timer.isActive()
    assert session.idle_timer.interval() == 5 * 60_000
    session._on_idle()
    assert ui.unlocks == 2
    session.shutdown()


def test_sync_refuses_itself_and_other_vaults(app: QApplication, tmp_path: Path) -> None:
    own = tmp_path / "pc" / "vault.mysafe"
    ui = FakeUI(folder=own.parent)
    pc = _session(app, ui, own)
    pc.sync(pc.window)  # type: ignore[arg-type]
    assert ui.messages[-1][0] == "WARN Sync" and "this vault itself" in ui.messages[-1][1]

    other, _ = Vault.create(tmp_path / "other" / "vault.mysafe", PASSWORD)
    other.lock()
    assert pc.controller is not None
    pc.controller.set_sync_target(str(tmp_path / "other" / "vault.mysafe"))
    pc.sync(pc.window)  # type: ignore[arg-type]
    assert ui.messages[-1][0] == "WARN Sync" and "not a copy" in ui.messages[-1][1]
    pc.shutdown()


def test_new_recovery_key(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI()
    pc = _session(app, ui, tmp_path / "vault.mysafe")
    first = ui.recovery_keys[-1]
    pc.new_recovery_key(pc.window)  # type: ignore[arg-type]
    second = ui.recovery_keys[-1]
    assert second != first
    pc.shutdown()
    Vault.unlock_with_recovery_key(tmp_path / "vault.mysafe", second).lock()


def test_new_recovery_key_cancelled_keeps_old_key(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI()
    pc = _session(app, ui, tmp_path / "vault.mysafe")
    first = ui.recovery_keys[-1]
    ui.keep_new_key = False  # "Cancel — keep my old key"
    pc.new_recovery_key(pc.window)  # type: ignore[arg-type]
    shown = ui.recovery_keys[-1]
    assert shown != first
    pc.shutdown()
    Vault.unlock_with_recovery_key(tmp_path / "vault.mysafe", first).lock()
    with pytest.raises(WrongPasswordError):
        Vault.unlock_with_recovery_key(tmp_path / "vault.mysafe", shown)


def test_password_changed_on_the_usb_is_asked_for(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI(folder=tmp_path / "USB")
    pc = _session(app, ui, tmp_path / "pc" / "vault.mysafe")
    pc.create_usb_copy(pc.window)  # type: ignore[arg-type]
    usb_file = tmp_path / "USB" / "MySafe-data" / "vault.mysafe"

    usb_ui = FakeUI()
    usb = _session(app, usb_ui, usb_file, portable=True)
    usb_ui.next_password = "Usb-only-pass-7"
    usb.change_master_password(usb.window)  # type: ignore[arg-type]
    usb.shutdown()

    ui.copy_passwords = ["wrong guess", "Usb-only-pass-7"]
    pc.sync(pc.window)  # type: ignore[arg-type]
    assert ui.copy_password_errors == ["", "Wrong password — that copy did not open."]
    assert "Master password here updated to match the newer one" in ui.messages[-1][1]
    pc.shutdown()
    Vault.unlock(tmp_path / "pc" / "vault.mysafe", "Usb-only-pass-7").lock()


def test_sync_cancelled_at_the_password_question(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI(folder=tmp_path / "USB")
    pc = _session(app, ui, tmp_path / "pc" / "vault.mysafe")
    pc.create_usb_copy(pc.window)  # type: ignore[arg-type]
    usb_file = tmp_path / "USB" / "MySafe-data" / "vault.mysafe"
    usb = _session(app, FakeUI(), usb_file, portable=True)
    assert usb.vault is not None
    usb.vault.change_password("Usb-only-pass-7")
    usb.shutdown()
    pc.sync(pc.window)  # type: ignore[arg-type]  (no answer: cancelled)
    assert ui.plans == []
    pc.shutdown()
    Vault.unlock(tmp_path / "pc" / "vault.mysafe", PASSWORD).lock()  # unchanged


def test_restore_from_backup_can_be_undone(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI()
    pc = _session(app, ui, tmp_path / "vault.mysafe")
    _add(pc, "Steam")
    _add(pc, "Gmail")
    assert pc.vault is not None
    steam = next(e.id for e in pc.vault.repo.list_entries() if e.title == "Steam")
    pc.vault.repo.delete_entry(steam)  # oops
    ui.backup_choice = 0  # newest: the save just before the delete
    pc.restore_backup(pc.window)  # type: ignore[arg-type]
    assert [b.kind for b in ui.backups_offered] == ["Previous save"]
    assert _titles(pc) == ["Gmail", "Steam"]
    assert ui.messages[-1][0] == "Restore from backup"

    ui.backup_kind = "Before restore"  # undo the restore
    pc.restore_backup(pc.window)  # type: ignore[arg-type]
    assert "Before restore" in [b.kind for b in ui.backups_offered]
    assert _titles(pc) == ["Gmail"]
    pc.shutdown()
    Vault.unlock(tmp_path / "vault.mysafe", PASSWORD).lock()  # same password as before


def test_lock_clears_a_copied_password(app: QApplication, tmp_path: Path) -> None:
    session = _session(app, FakeUI(), tmp_path / "vault.mysafe")
    assert session.window is not None
    session.window.clipboard.copy("hunter2-secret", secret=True)
    assert QGuiApplication.clipboard().text() == "hunter2-secret"
    session.lock_now()
    assert QGuiApplication.clipboard().text() != "hunter2-secret"
    session.window.clipboard.copy("other-secret", secret=True)
    session.shutdown()
    assert QGuiApplication.clipboard().text() != "other-secret"


def test_auto_lock_closes_open_dialogs(app: QApplication, tmp_path: Path) -> None:
    ui = FakeUI()
    session = _session(app, ui, tmp_path / "vault.mysafe")
    dialog = QDialog(session.window)
    dialog.setModal(True)
    dialog.open()
    app.processEvents()
    session._on_idle()
    assert ui.unlocks == 1  # locked anyway
    assert not dialog.isVisible()
    session.shutdown()
