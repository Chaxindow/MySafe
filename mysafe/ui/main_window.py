"""Main window: puts the three panels together and handles menus, shortcuts and dialogs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QWidget,
)

from mysafe import APP_NAME, __version__
from mysafe.paths import data_dir, is_portable
from mysafe.ui.actions import VaultActions
from mysafe.ui.category_panel import CategoryPanel, is_category_key
from mysafe.ui.clipboard import SecretClipboard
from mysafe.ui.controller import AppController
from mysafe.ui.dialogs import ConfirmFn, confirm
from mysafe.ui.entry_detail import EntryDetailPanel
from mysafe.ui.entry_editor import EntryEditorDialog
from mysafe.ui.entry_list import EntryListPanel
from mysafe.ui.naming_guide import NamingGuideDialog
from mysafe.ui.password_dialog import PasswordGeneratorDialog
from mysafe.ui.settings_dialog import SettingsDialog

STATUS_TIMEOUT_MS = 6000
ENCRYPTION_NOTE = "Your vault is encrypted with AES-256. Only your master password opens it."


class MainWindow(QMainWindow):
    closing = Signal()  # the user closed the window (not emitted for Lock)

    def __init__(
        self,
        controller: AppController,
        parent: QWidget | None = None,
        *,
        confirm_fn: ConfirmFn = confirm,
        vault_location: str = "",
        portable: bool = False,
        actions: VaultActions | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.vault_actions = actions  # (not `actions`: QWidget.actions() exists)
        self._confirm = confirm_fn
        self.clipboard = SecretClipboard(controller.clipboard_clear_seconds(), self)
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 740)
        self.setMinimumSize(900, 560)

        self.categories = CategoryPanel(controller)
        self.entries = EntryListPanel(controller)
        self.detail = EntryDetailPanel(controller, self.clipboard)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.categories)
        splitter.addWidget(self.entries)
        splitter.addWidget(self.detail)
        splitter.setSizes([240, 320, 640])
        splitter.setHandleWidth(1)  # a hairline divider between the three panes
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(2, 1)
        self.categories.setMinimumWidth(190)
        self.entries.setMinimumWidth(240)
        self.setCentralWidget(splitter)

        # Wiring between panels
        self.categories.selection_changed.connect(self.entries.set_filter)
        self.categories.add_requested.connect(self.new_category)
        self.categories.rename_requested.connect(self.rename_category)
        self.categories.delete_requested.connect(self.delete_category)
        self.entries.entry_selected.connect(self.detail.show_entry)
        self.entries.new_entry_requested.connect(self.new_entry)
        self.detail.edit_requested.connect(self.edit_entry)
        self.detail.delete_requested.connect(self.delete_entry)
        self.detail.status_message.connect(self.show_status)

        controller.error_occurred.connect(self._show_error)
        controller.settings_changed.connect(self._apply_settings)

        self._build_menus()
        self._vault_status = (
            f"Encrypted {'USB ' if portable else ''}vault: {vault_location}"
            if vault_location
            else ""
        )
        self.vault_label = QLabel(self._vault_status)
        self.vault_label.setObjectName("hint")
        self.statusBar().addPermanentWidget(self.vault_label)  # stays while messages come and go
        self.detail.show_entry(self.entries.current_entry_id())

    # ------------------------------------------------------------------ menus

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "&New entry", self.new_entry, QKeySequence.StandardKey.New)
        self._action(file_menu, "New &category", self.new_category, "Ctrl+Shift+N")
        file_menu.addSeparator()
        self._action(file_menu, "&Password generator…", self.open_password_generator, "Ctrl+G")
        file_menu.addSeparator()
        self.sync_action = self._action(file_menu, "S&ync…", self._sync, "Ctrl+Shift+S")
        self.usb_copy_action = self._action(file_menu, "Create &USB copy…", self._create_usb_copy)
        self.restore_action = self._action(file_menu, "&Restore from backup…", self._restore_backup)
        file_menu.addSeparator()
        self._action(file_menu, "&Settings…", self.open_settings, "Ctrl+,")
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.close, QKeySequence.StandardKey.Quit)

        entry_menu = self.menuBar().addMenu("&Entry")
        self._action(entry_menu, "&Edit", self._edit_current, "Ctrl+E")
        self._action(entry_menu, "&Delete", self._delete_current)
        entry_menu.addSeparator()
        self._action(entry_menu, "&Find", self.focus_search, QKeySequence.StandardKey.Find)

        security_menu = self.menuBar().addMenu("&Security")
        self.lock_action = self._action(security_menu, "&Lock now", self._lock, "Ctrl+L")
        security_menu.addSeparator()
        self.change_password_action = self._action(
            security_menu, "&Change master password…", self._change_password
        )
        self.recovery_action = self._action(
            security_menu, "New &recovery key…", self._new_recovery_key
        )
        for action in (
            self.sync_action,
            self.usb_copy_action,
            self.restore_action,
            self.lock_action,
            self.change_password_action,
            self.recovery_action,
        ):
            action.setEnabled(self.vault_actions is not None)

        help_menu = self.menuBar().addMenu("&Help")
        self.naming_action = self._action(
            help_menu,
            "&Naming guide…",
            self.open_naming_guide,
            QKeySequence.StandardKey.HelpContents,
        )
        help_menu.addSeparator()
        self._action(help_menu, f"&About {APP_NAME}", self._about)

        # Delete key only when the entry list has focus (so it never fires while typing).
        delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.entries.list)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_current)

    def _action(
        self,
        menu: QMenu,
        text: str,
        slot: Callable[[], object],
        shortcut: QKeySequence.StandardKey | str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    # ---------------------------------------------------------------- entries

    def _password_from_dialog(self, parent: QWidget) -> str | None:
        dialog = PasswordGeneratorDialog(use_button=True, parent=parent)
        if dialog.exec() == PasswordGeneratorDialog.DialogCode.Accepted:
            return dialog.password()
        return None

    def new_entry(self) -> None:
        categories = self.controller.categories()
        if not categories:
            self._show_error("Create a category first.")
            return
        key = self.categories.current_key()
        dialog = EntryEditorDialog(
            categories,
            default_category_id=key if is_category_key(key) else None,
            password_provider=self._password_from_dialog,
            confirm_fn=self._confirm,
            parent=self,
        )
        if dialog.exec() != EntryEditorDialog.DialogCode.Accepted:
            return
        entry = self.controller.create_entry(dialog.result_data())
        if entry is not None:
            self._reveal_entry(entry.id, entry.category_id)
            self.show_status(f"“{entry.title}” added.")

    def edit_entry(self, entry_id: str) -> None:
        entry = self.controller.entry(entry_id)
        if entry is None:
            return
        dialog = EntryEditorDialog(
            self.controller.categories(),
            entry=entry,
            password_provider=self._password_from_dialog,
            confirm_fn=self._confirm,
            parent=self,
        )
        if dialog.exec() != EntryEditorDialog.DialogCode.Accepted:
            return
        updated = self.controller.update_entry(entry_id, dialog.result_data())
        if updated is not None:
            self._reveal_entry(updated.id, updated.category_id)
            self.show_status(f"“{updated.title}” saved.")

    def delete_entry(self, entry_id: str) -> None:
        entry = self.controller.entry(entry_id)
        if entry is None:
            return
        if self._confirm(
            self,
            "Delete entry",
            f"Delete “{entry.title}”?",
            "Delete entry",
            details=["All of its fields will be removed. This cannot be undone."],
            destructive=True,
        ) and self.controller.delete_entry(entry_id):
            self.show_status(f"“{entry.title}” deleted.")

    def _edit_current(self) -> None:
        if self.detail.entry_id:
            self.edit_entry(self.detail.entry_id)

    def _delete_current(self) -> None:
        if self.detail.entry_id:
            self.delete_entry(self.detail.entry_id)

    def _reveal_entry(self, entry_id: str, category_id: str) -> None:
        """Make sure an entry is visible in the list and selected."""
        self.entries.search_box.clear()
        if not self.entries.select_entry(entry_id):
            self.categories.select_key(category_id)
            self.entries.select_entry(entry_id)

    def focus_search(self) -> None:
        self.entries.search_box.setFocus()
        self.entries.search_box.selectAll()

    # ------------------------------------------------------------- categories

    def new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "New category", "Category name:")
        if ok and name.strip():
            category = self.controller.create_category(name)
            if category is not None:
                self.categories.select_key(category.id)

    def rename_category(self, category_id: str) -> None:
        category = self.controller.category(category_id)
        if category is None:
            return
        name, ok = QInputDialog.getText(self, "Rename category", "New name:", text=category.name)
        if ok and name.strip() and name.strip() != category.name:
            self.controller.rename_category(category_id, name)

    def delete_category(self, category_id: str) -> None:
        category = self.controller.category(category_id)
        if category is None:
            return
        count = self.controller.entry_counts().get(category_id, 0)
        if count == 0:
            if self._confirm(
                self,
                "Delete category",
                f"Delete the category “{category.name}”?",
                "Delete category",
                destructive=True,
            ):
                self.controller.delete_category(category_id)
            return

        others = [c for c in self.controller.categories() if c.id != category_id]
        if not others:
            self._show_error(
                f"“{category.name}” still has {count} entries and there is no other "
                "category to move them to."
            )
            return
        names = [c.name for c in others]
        target, ok = QInputDialog.getItem(
            self,
            "Delete category",
            f"“{category.name}” has {count} entries.\nMove them to:",
            names,
            0,
            False,
        )
        if ok:
            target_id = others[names.index(target)].id
            if self.controller.delete_category(category_id, move_entries_to=target_id):
                self.show_status(f"Moved {count} entries to “{target}”.")

    # ------------------------------------------------------------ vault actions

    def _lock(self) -> None:
        if self.vault_actions is not None:
            self.vault_actions.lock()

    def _change_password(self) -> None:
        if self.vault_actions is not None:
            self.vault_actions.change_master_password(self)

    def _new_recovery_key(self) -> None:
        if self.vault_actions is not None:
            self.vault_actions.new_recovery_key(self)

    def _create_usb_copy(self) -> None:
        if self.vault_actions is not None:
            self.vault_actions.create_usb_copy(self)

    def _sync(self) -> None:
        if self.vault_actions is not None:
            self.vault_actions.sync(self)

    def _restore_backup(self) -> None:
        if self.vault_actions is not None:
            self.vault_actions.restore_backup(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing.emit()
        super().closeEvent(event)

    # ----------------------------------------------------------------- dialogs

    def open_naming_guide(self) -> None:
        NamingGuideDialog(self).exec()

    def open_password_generator(self) -> None:
        PasswordGeneratorDialog(self.clipboard, parent=self).exec()

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            theme=self.controller.theme(),
            clipboard_clear_seconds=self.controller.clipboard_clear_seconds(),
            auto_lock_minutes=self.controller.auto_lock_minutes(),
            parent=self,
        )
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.controller.save_settings(
                theme=dialog.selected_theme(),
                clipboard_clear_seconds=dialog.selected_clear_seconds(),
                auto_lock_minutes=dialog.selected_auto_lock_minutes(),
            )

    def _apply_settings(self) -> None:
        self.clipboard.clear_after_seconds = self.controller.clipboard_clear_seconds()

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {__version__}<br><br>"
            "Keep all your account details in one place.<br><br>"
            f"Data folder{' (portable)' if is_portable() else ''}:<br>"
            f"<code>{data_dir()}</code><br><br>"
            f"<i>{ENCRYPTION_NOTE}</i>",
        )

    # ------------------------------------------------------------------ status

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, message)
