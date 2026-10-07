"""Render screenshots of the UI without showing any window (for design review).

Usage:  python tools/snapshot.py [output_dir]      (default: snapshots/)

Uses an in-memory database filled with the fake demo data — never your real data.
Windows are rendered with WA_DontShowOnScreen, so nothing appears on the desktop.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mysafe.db import Repository, open_database, open_from_bytes, to_bytes  # noqa: E402
from mysafe.demo import seed  # noqa: E402
from mysafe.models import FieldInput, FieldKind  # noqa: E402
from mysafe.services.crypto import WrongPasswordError  # noqa: E402
from mysafe.sync import plan_sync  # noqa: E402
from mysafe.ui.controller import AppController  # noqa: E402
from mysafe.ui.dialogs import build_confirm_box  # noqa: E402
from mysafe.ui.entry_editor import EntryEditorDialog  # noqa: E402
from mysafe.ui.main_window import MainWindow  # noqa: E402
from mysafe.ui.naming_guide import NamingGuideDialog  # noqa: E402
from mysafe.ui.password_dialog import PasswordGeneratorDialog  # noqa: E402
from mysafe.ui.restore_dialog import BackupChoice, RestoreDialog  # noqa: E402
from mysafe.ui.sync_dialog import SyncDialog  # noqa: E402
from mysafe.ui.theme import apply_theme  # noqa: E402
from mysafe.ui.unlock import (  # noqa: E402
    KEY_PAGE,
    CopyPasswordDialog,
    RecoveryKeyDialog,
    SetupDialog,
    UnlockDialog,
)
from mysafe.ui.widgets import repolish  # noqa: E402


def _settle() -> None:
    for _ in range(5):
        QCoreApplication.processEvents()


def _offscreen(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    _settle()


def _fake_hover(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    repolish(widget)


def _demo_plan():  # type: ignore[no-untyped-def]
    """A computer vault and an edited USB copy, for the Sync screen."""
    clock = iter(range(1_760_000_000, 1_760_100_000, 600))
    local = Repository(open_from_bytes(), lambda: next(clock))
    seed(local)
    remote = Repository(open_from_bytes(to_bytes(local.connection)), lambda: next(clock))
    games = next(c.id for c in local.list_categories() if c.name == "Games")
    social = next(c.id for c in remote.list_categories() if c.name == "Social Media")
    steam = next(e for e in local.list_entries() if e.title == "Steam")
    remote.create_entry(social, "Discord")
    remote_steam = remote.get_entry(steam.id)
    remote.update_entry(
        steam.id,
        category_id=games,
        title="Steam",
        fields=[
            FieldInput(f.label, "R-12345" if f.kind == FieldKind.RECOVERY_CODE else f.value, f.kind)
            for f in remote_steam.fields
        ],
    )
    local_steam = local.get_entry(steam.id)
    local.update_entry(
        steam.id,
        category_id=games,
        title="Steam",
        fields=[
            FieldInput(f.label, "R-7731" if f.kind == FieldKind.RECOVERY_CODE else f.value, f.kind)
            for f in local_steam.fields
        ],
    )
    local.create_entry(games, "Riot Games")
    local.create_entry(
        next(c.id for c in local.list_categories() if c.name == "Streaming"), "Spotify"
    )
    netflix = next(e for e in local.list_entries() if e.title == "Netflix")
    local.delete_entry(netflix.id)
    return plan_sync(local, remote)


def render(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)

    repo = Repository(open_database(":memory:"))
    seed(repo)
    controller = AppController(repo)
    steam = controller.entries(search="Steam")[0]
    saved: list[Path] = []

    for theme in ("dark", "light"):
        apply_theme(app, theme)
        window = MainWindow(controller)
        window.resize(1280, 780)
        _offscreen(window)
        window.entries.select_entry(steam.id)
        _settle()
        path = out_dir / f"main_{theme}.png"
        window.grab().save(str(path))
        saved.append(path)

        # Hover states: one field row, its copy button and the Edit button.
        row = window.detail.rows[2]
        _fake_hover(row)
        _fake_hover(row.copy_button)
        _fake_hover(window.detail.edit_button)
        _settle()
        path = out_dir / f"detail_hover_{theme}.png"
        window.detail.grab().save(str(path))
        saved.append(path)

        # Search with text: the clear button, hovered.
        window.entries.search_box.setText("st")
        _fake_hover(window.entries.search_box.clear_button)
        _settle()
        path = out_dir / f"search_{theme}.png"
        window.entries.grab().save(str(path))
        saved.append(path)
        window.entries.search_box.clear()

        editor = EntryEditorDialog(
            controller.categories(),
            entry=controller.entry(steam.id),
            password_provider=lambda _parent: None,
            confirm_fn=lambda *_a, **_k: True,
        )
        _offscreen(editor)
        path = out_dir / f"editor_{theme}.png"
        editor.grab().save(str(path))
        saved.append(path)

        # The "Save changes" confirmation with a list of changes.
        editor.rows[2].value.setText("changed")  # the password field
        box, _ok = build_confirm_box(
            editor,
            "Save changes",
            f"Save these changes to “{steam.title}”?",
            "Save changes",
            details=editor.changes() + ["Field removed: Steam Guard recovery code"],
            cancel_text="Keep editing",
        )
        _offscreen(box)
        path = out_dir / f"confirm_save_{theme}.png"
        box.grab().save(str(path))
        saved.append(path)
        box.close()

        box, _ok = build_confirm_box(
            editor,
            "Replace password",
            "Replace the current “Password”?",
            "Replace password",
            details=["The current password will be overwritten when you save this entry."],
            cancel_text="Keep current",
            destructive=True,
        )
        _offscreen(box)
        path = out_dir / f"confirm_replace_{theme}.png"
        box.grab().save(str(path))
        saved.append(path)
        box.close()
        editor.done(0)

        guide = NamingGuideDialog()
        _offscreen(guide)
        path = out_dir / f"naming_guide_{theme}.png"
        guide.grab().save(str(path))
        saved.append(path)
        guide.close()

        setup = SetupDialog(importing_old_data=True)
        setup.password.setText("Mavi bisiklet 1987")
        setup.confirm.setText("Mavi bisiklet 1987")
        setup.understand.setChecked(True)

        def wrong(_text: str) -> None:
            raise WrongPasswordError()

        def wrong_key(_text: str) -> None:
            raise WrongPasswordError("recovery key")

        def make_lock(check_key=wrong_key):  # type: ignore[no-untyped-def]
            return UnlockDialog(
                wrong,
                check_key,
                lambda _v, _p: None,
                location="E:\\MySafe\\MySafe-data\\vault.mysafe",
                portable=True,
            )

        lock = make_lock()
        lock.password.setText("not-my-password")
        lock.try_unlock()
        lock.try_unlock()
        key_page = make_lock()
        key_page.show_page(KEY_PAGE)
        key_page.recovery_key.setText("K7QX-M2PA-ZR4T-WN6E-BY3H-JD5L-QC7V")
        key_page.try_check_key()
        new_password_page = make_lock(lambda _k: object())
        new_password_page.show_page(KEY_PAGE)
        new_password_page.recovery_key.setText("K7QX-M2PA-ZR4T-WN6E-BY3H-JD5L-QC7V-SF2G")
        new_password_page.try_check_key()
        new_password_page.new_password.setText("Mavi bisiklet 1987")
        recovery = RecoveryKeyDialog("K7QX-M2PA-ZR4T-WN6E-BY3H-JD5L-QC7V-SF2G")
        replacing = RecoveryKeyDialog("M3PZ-QA7W-XR2T-KN6E-BY4H-JD5L-QC7V-SF2G", replacing=True)
        for name, dialog in (
            ("setup", setup),
            ("lock", lock),
            ("recover_key", key_page),
            ("recover_new_password", new_password_page),
            ("recovery_key", recovery),
            ("new_recovery_key", replacing),
        ):
            _offscreen(dialog)
            path = out_dir / f"{name}_{theme}.png"
            dialog.grab().save(str(path))
            saved.append(path)
            dialog.done(0)

        restore = RestoreDialog(
            [
                BackupChoice("Before restore", "07 Oct 2026, 11:52  ·  14 entries"),
                BackupChoice("Before sync", "06 Oct 2026, 21:40  ·  12 entries"),
                BackupChoice("Previous save", "06 Oct 2026, 21:38  ·  12 entries"),
            ]
        )
        copy_password = CopyPasswordDialog(
            "E:\\MySafe-data\\vault.mysafe", "USB", "Wrong password — that copy did not open."
        )
        for name, dialog in (("restore", restore), ("copy_password", copy_password)):
            _offscreen(dialog)
            path = out_dir / f"{name}_{theme}.png"
            dialog.grab().save(str(path))
            saved.append(path)
            dialog.done(0)

        sync = SyncDialog(_demo_plan(), remote_location="E:\\MySafe-data\\vault.mysafe")
        _offscreen(sync)
        path = out_dir / f"sync_{theme}.png"
        sync.grab().save(str(path))
        saved.append(path)
        sync.done(0)

        generator = PasswordGeneratorDialog(use_button=True)
        _offscreen(generator)
        path = out_dir / f"generator_{theme}.png"
        generator.grab().save(str(path))
        saved.append(path)
        generator.close()

        window.close()
        window.deleteLater()
        _settle()

    repo.close()
    return saved


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "snapshots"
    for p in render(target):
        print(f"saved {p}")
