"""User-interface tests (needs PySide6 + pytest-qt). Modal dialogs are never opened here."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from mysafe.db import Repository  # noqa: E402
from mysafe.demo import seed  # noqa: E402
from mysafe.models import FieldInput, FieldKind  # noqa: E402
from mysafe.ui.category_panel import ALL, FAVORITES  # noqa: E402
from mysafe.ui.clipboard import SecretClipboard  # noqa: E402
from mysafe.ui.controller import AppController, EntryData  # noqa: E402
from mysafe.ui.entry_detail import MASK  # noqa: E402
from mysafe.ui.entry_editor import EntryEditorDialog  # noqa: E402
from mysafe.ui.main_window import MainWindow  # noqa: E402
from mysafe.ui.password_dialog import PasswordGeneratorDialog  # noqa: E402


class Confirm:
    """Stand-in for the confirmation dialog: records questions, returns a fixed answer."""

    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def __call__(self, parent, title, message, confirm_text, **kwargs) -> bool:  # type: ignore[no-untyped-def]
        self.calls.append({"title": title, "message": message, **kwargs})
        return self.answer


@pytest.fixture
def controller(qtbot, repo: Repository) -> AppController:  # type: ignore[no-untyped-def]
    seed(repo)
    return AppController(repo)


@pytest.fixture
def window(qtbot, controller: AppController) -> MainWindow:  # type: ignore[no-untyped-def]
    win = MainWindow(controller, confirm_fn=Confirm(True))
    qtbot.addWidget(win)
    return win


def _category_id(controller: AppController, name: str) -> str:
    return next(c.id for c in controller.categories() if c.name == name)


def _select_entry(window: MainWindow, title: str) -> None:
    window.entries.search_box.setText(title)
    assert window.entries.titles(), f"{title} not found"


# ------------------------------------------------------------------ main window


def test_window_shows_categories_and_entries(window: MainWindow, controller: AppController) -> None:
    assert window.categories.list.count() == 2 + len(controller.categories())
    assert window.categories.current_key() == ALL
    assert len(window.entries.titles()) == controller.total_entries()
    assert window.detail.entry_id  # first entry is shown


def test_selecting_category_filters_entries(window: MainWindow, controller: AppController) -> None:
    window.categories.select_key(_category_id(controller, "Games"))
    titles = window.entries.titles()
    assert len(titles) == 2 and all(t.split()[0] in ("Steam", "Epic") for t in titles)

    window.categories.select_key(FAVORITES)
    assert len(window.entries.titles()) == controller.favorite_count()


def test_search(window: MainWindow) -> None:
    window.entries.search_box.setText("netflix")
    assert window.entries.titles() == ["Netflix"]
    window.entries.search_box.setText("zzz")
    assert window.entries.titles() == []
    assert window.detail.entry_id == ""


def test_rename_delete_only_enabled_for_real_categories(
    window: MainWindow, controller: AppController
) -> None:
    window.categories.select_key(ALL)
    assert not window.categories.rename_button.isEnabled()
    window.categories.select_key(_category_id(controller, "Games"))
    assert window.categories.rename_button.isEnabled()
    assert window.categories.delete_button.isEnabled()


def test_counts_update_after_changes(window: MainWindow, controller: AppController) -> None:
    other = _category_id(controller, "Other")
    controller.create_entry(EntryData(category_id=other, title="Spotify"))
    assert window.categories.count_for(other) == 1
    assert window.categories.count_for(ALL) == controller.total_entries()


# ----------------------------------------------------------------- entry detail


def test_secrets_masked_and_can_be_revealed(window: MainWindow) -> None:
    _select_entry(window, "Steam")
    password_row = next(r for r in window.detail.rows if r.value == "Demo-Passw0rd!")
    assert password_row.value_label.text() == MASK
    assert password_row.show_button is not None
    password_row.show_button.click()
    assert password_row.value_label.text() == "Demo-Passw0rd!"
    password_row.show_button.click()
    assert password_row.value_label.text() == MASK

    email_row = next(r for r in window.detail.rows if r.value == "demo.gamer@example.com")
    assert email_row.show_button is None
    assert email_row.value_label.text() == "demo.gamer@example.com"


def test_copy_secret_and_clear(window: MainWindow) -> None:
    _select_entry(window, "Steam")
    password_row = next(r for r in window.detail.rows if r.value == "Demo-Passw0rd!")
    password_row.copy_button.click()
    clipboard = QGuiApplication.clipboard()
    assert clipboard.text() == "Demo-Passw0rd!"
    assert "cleared" in window.statusBar().currentMessage()

    window.clipboard.clear_if_unchanged()
    assert clipboard.text() == ""


def test_clipboard_not_cleared_if_user_copied_something_else(qtbot) -> None:  # type: ignore[no-untyped-def]
    clip = SecretClipboard(clear_after_seconds=20)
    clip.copy("secret", secret=True)
    QGuiApplication.clipboard().setText("something else")
    clip.clear_if_unchanged()
    assert QGuiApplication.clipboard().text() == "something else"


def test_clipboard_clears_after_timeout(qtbot) -> None:  # type: ignore[no-untyped-def]
    clip = SecretClipboard(clear_after_seconds=1)
    assert clip.copy("secret", secret=True)
    qtbot.waitUntil(lambda: QGuiApplication.clipboard().text() == "", timeout=3000)


def test_favorite_toggle(window: MainWindow, controller: AppController) -> None:
    _select_entry(window, "Netflix")
    before = controller.favorite_count()
    window.detail.favorite_button.click()
    assert controller.favorite_count() == before + 1
    assert window.detail.entry_id  # still showing the entry after refresh


def test_deleted_entry_disappears(window: MainWindow, controller: AppController) -> None:
    _select_entry(window, "Netflix")
    entry_id = window.detail.entry_id
    controller.delete_entry(entry_id)
    assert window.entries.titles() == []
    assert window.detail.entry_id == ""


# ----------------------------------------------------------------- entry editor


def test_new_entry_editor_defaults(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    games = _category_id(controller, "Games")
    dialog = EntryEditorDialog(
        controller.categories(), confirm_fn=Confirm(True), default_category_id=games
    )
    qtbot.addWidget(dialog)
    assert [r.current_kind() for r in dialog.rows] == [FieldKind.EMAIL, FieldKind.PASSWORD]
    assert dialog.rows[1].value.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.category.currentData() == games
    assert dialog.collect() == "Please enter a title."


def test_editor_collects_data(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    dialog = EntryEditorDialog(controller.categories(), confirm_fn=Confirm(True))
    qtbot.addWidget(dialog)
    dialog.title.setText("  Steam ")
    dialog.rows[0].value.setText("me@example.com")
    dialog.rows[1].value.setText("pw")
    extra = dialog.add_field(FieldInput("", "", FieldKind.TEXT))
    extra.kind.setCurrentIndex(extra.kind.findData(FieldKind.RECOVERY_CODE.value))
    assert extra.label.text() == "Recovery code"  # label follows the kind
    extra.value.setText("R-1")
    dialog.add_field(FieldInput("", "", FieldKind.TEXT))  # blank -> dropped

    data = dialog.collect()
    assert not isinstance(data, str)
    assert data.title == "Steam"
    assert [(f.label, f.value, f.kind) for f in data.fields] == [
        ("Email", "me@example.com", FieldKind.EMAIL),
        ("Password", "pw", FieldKind.PASSWORD),
        ("Recovery code", "R-1", FieldKind.RECOVERY_CODE),
    ]


def test_editor_requires_labels(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    dialog = EntryEditorDialog(controller.categories(), confirm_fn=Confirm(True))
    qtbot.addWidget(dialog)
    dialog.title.setText("Steam")
    dialog.rows[0].label.setText("")
    dialog.rows[0].value.setText("value without label")
    assert dialog.collect() == "Every field needs a label."


def test_editor_reorder_and_remove(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    dialog = EntryEditorDialog(controller.categories(), confirm_fn=Confirm(True))
    qtbot.addWidget(dialog)
    dialog.title.setText("X")
    first, second = dialog.rows
    first.value.setText("a")
    second.value.setText("b")
    second.move_up.emit(second)
    assert dialog.rows == [second, first]
    dialog.rows[0].remove.emit(dialog.rows[0])
    data = dialog.collect()
    assert not isinstance(data, str)
    assert [f.label for f in data.fields] == ["Email"]


def test_editor_prefills_existing_entry(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    steam_id = controller.entries(search="Steam")[0].id
    entry = controller.entry(steam_id)
    assert entry is not None
    dialog = EntryEditorDialog(controller.categories(), confirm_fn=Confirm(True), entry=entry)
    qtbot.addWidget(dialog)
    assert dialog.title.text() == "Steam"
    assert dialog.favorite.isChecked()
    assert len(dialog.rows) == len(entry.fields)


def test_generate_button_uses_password_provider(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    dialog = EntryEditorDialog(
        controller.categories(), confirm_fn=Confirm(True), password_provider=lambda _parent: "Gen!1"
    )
    qtbot.addWidget(dialog)
    password_row = dialog.rows[1]
    password_row.generate_button.click()
    assert password_row.value.text() == "Gen!1"


# ------------------------------------------------------------ password dialog


def test_password_dialog(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = PasswordGeneratorDialog(use_button=True)
    qtbot.addWidget(dialog)
    assert len(dialog.password()) == 20
    dialog.length.setValue(32)
    assert len(dialog.password()) == 32
    for box in (dialog.lowercase, dialog.uppercase, dialog.digits, dialog.symbols):
        box.setChecked(False)
    assert dialog.password() == ""
    assert dialog.error.text()


# ------------------------------------------------------------------- look & feel


def test_buttons_show_they_are_clickable(window: MainWindow) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QLineEdit

    _select_entry(window, "Steam")
    buttons = [
        b
        for b in window.findChildren(QAbstractButton)
        if b.isVisibleTo(window)
        and not isinstance(b.parent(), QLineEdit)  # built-in line-edit icons
        and not b.objectName().startswith("qt_")  # Qt's own helpers (menu-bar overflow »)
    ]
    assert buttons
    for button in buttons:
        assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor, button.toolTip()
    for row in window.detail.rows:
        assert row.testAttribute(Qt.WidgetAttribute.WA_Hover)  # row hover highlight
        assert row.copy_button.toolTip().startswith("Copy")


def test_link_rows_have_open_button(window: MainWindow) -> None:
    _select_entry(window, "Steam")
    website = window.detail.rows[0]
    assert website.value.startswith("https://")
    assert website.open_button is not None


def test_both_themes_apply_and_render(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    from mysafe.ui.palette import DARK, LIGHT, current
    from mysafe.ui.theme import apply_theme

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    for theme, expected in (("dark", DARK), ("light", LIGHT)):
        assert apply_theme(app, theme) is expected
        assert current() is expected
        image = window.grab()
        assert not image.isNull()


def test_icons_render(qtbot) -> None:  # type: ignore[no-untyped-def]
    from mysafe.ui.icons import _PATHS, icon

    for name in _PATHS:
        assert not icon(name, "#808080").pixmap(16, 16).isNull(), name


# ------------------------------------------------------------- safety prompts


def _steam(controller: AppController):  # type: ignore[no-untyped-def]
    entry = controller.entry(controller.entries(search="Steam")[0].id)
    assert entry is not None
    return entry


def _password_row(dialog: EntryEditorDialog):  # type: ignore[no-untyped-def]
    return next(r for r in dialog.rows if r.current_kind() == FieldKind.PASSWORD)


def test_generate_asks_before_replacing_existing_password(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    dialog = EntryEditorDialog(
        controller.categories(),
        entry=_steam(controller),
        password_provider=lambda _p: "New-Pass-1",
        confirm_fn=ask,
    )
    qtbot.addWidget(dialog)
    row = _password_row(dialog)
    row.generate_button.click()
    assert ask.calls and ask.calls[0]["title"] == "Replace password"
    assert row.value.text() == "Demo-Passw0rd!"  # declined -> unchanged

    ask.answer = True
    row.generate_button.click()
    assert row.value.text() == "New-Pass-1"


def test_generate_on_empty_password_does_not_ask(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    dialog = EntryEditorDialog(
        controller.categories(), password_provider=lambda _p: "Fresh-1", confirm_fn=ask
    )
    qtbot.addWidget(dialog)
    _password_row(dialog).generate_button.click()
    assert _password_row(dialog).value.text() == "Fresh-1"
    assert ask.calls == []


def test_unchanged_edit_saves_nothing_and_asks_nothing(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(True)
    dialog = EntryEditorDialog(controller.categories(), entry=_steam(controller), confirm_fn=ask)
    qtbot.addWidget(dialog)
    assert dialog.changes() == []
    dialog.save_button.click()
    assert ask.calls == []
    assert dialog.closing
    assert dialog.result() == EntryEditorDialog.DialogCode.Rejected  # nothing saved


def test_edit_lists_changes_and_asks_before_saving(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    dialog = EntryEditorDialog(controller.categories(), entry=_steam(controller), confirm_fn=ask)
    qtbot.addWidget(dialog)
    _password_row(dialog).value.setText("changed")
    recovery = next(r for r in dialog.rows if r.current_kind() == FieldKind.RECOVERY_CODE)
    recovery.remove.emit(recovery)
    assert recovery not in dialog.rows

    changes = dialog.changes()
    assert "Password changed" in changes
    assert "Field removed: Steam Guard recovery code" in changes

    ask.answer = False  # "Keep editing"
    ask.calls.clear()
    dialog.save_button.click()
    assert ask.calls[0]["title"] == "Save changes"
    assert ask.calls[0]["details"] == changes
    assert not dialog.closing

    ask.answer = True
    dialog.save_button.click()
    assert dialog.result() == EntryEditorDialog.DialogCode.Accepted


def test_removing_a_field_does_not_ask(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    dialog = EntryEditorDialog(controller.categories(), entry=_steam(controller), confirm_fn=ask)
    qtbot.addWidget(dialog)
    first = dialog.rows[0]
    first.remove.emit(first)
    assert first not in dialog.rows
    assert ask.calls == []  # the removal is listed in "Save changes" instead
    assert f"Field removed: {first.original.label}" in dialog.changes()  # type: ignore[union-attr]


def test_cancel_with_changes_asks_to_discard(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    dialog = EntryEditorDialog(controller.categories(), entry=_steam(controller), confirm_fn=ask)
    qtbot.addWidget(dialog)
    dialog.title.setText("Steam (old)")
    dialog.reject()
    assert ask.calls[0]["title"] == "Discard changes"
    assert not dialog.closing  # "Keep editing"
    ask.answer = True
    dialog.reject()
    assert dialog.closing


def test_new_entry_saves_without_question(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    dialog = EntryEditorDialog(controller.categories(), confirm_fn=ask)
    qtbot.addWidget(dialog)
    dialog.title.setText("Spotify")
    dialog.save_button.click()
    assert ask.calls == []
    assert dialog.result() == EntryEditorDialog.DialogCode.Accepted


def test_delete_entry_respects_answer(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    ask = Confirm(False)
    win = MainWindow(controller, confirm_fn=ask)
    qtbot.addWidget(win)
    steam_id = _steam(controller).id
    win.delete_entry(steam_id)
    assert controller.entry(steam_id) is not None
    ask.answer = True
    win.delete_entry(steam_id)
    assert controller.entry(steam_id) is None


# ------------------------------------------------------------------ search box


def test_search_clear_button(window: MainWindow) -> None:
    from PySide6.QtCore import Qt

    box = window.entries.search_box
    assert box.clear_button.isHidden()
    box.setText("steam")
    assert not box.clear_button.isHidden()
    assert box.clear_button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert box.clear_button.toolTip().startswith("Clear search")
    box.clear_button.click()
    assert box.text() == ""
    assert box.clear_button.isHidden()


def test_escape_clears_search(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    box = window.entries.search_box
    box.setText("netflix")
    qtbot.keyClick(box, Qt.Key.Key_Escape)
    assert box.text() == ""


# ---------------------------------------------------------------- naming guide


def test_naming_guide(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from mysafe.ui.naming_guide import FORMULA, NamingGuideDialog

    assert window.naming_action.text().replace("&", "").startswith("Naming guide")
    dialog = NamingGuideDialog()
    qtbot.addWidget(dialog)
    text = dialog.body.text()
    assert "Service" in text and "Account" in text and "Gmail – Work" in text
    assert FORMULA == "Service – Account"


def test_editor_offers_naming_tips(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    dialog = EntryEditorDialog(controller.categories(), confirm_fn=Confirm(True))
    qtbot.addWidget(dialog)
    assert dialog.naming_button.isVisibleTo(dialog)
    assert "Service – Account" in dialog.title.placeholderText()


def test_app_icon_resources_exist() -> None:
    from mysafe.resources import resource_path

    for name in ("icon.svg", "icon-32.png", "icon-64.png", "icon-256.png", "mysafe.ico"):
        assert resource_path(name).is_file(), name
