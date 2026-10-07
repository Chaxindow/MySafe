"""Dialog for creating or editing an entry and its custom fields."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mysafe.models import Category, Entry, FieldInput, FieldKind, default_fields
from mysafe.ui.controller import EntryData
from mysafe.ui.dialogs import ConfirmFn, confirm
from mysafe.ui.icons import bind_icon
from mysafe.ui.naming_guide import NamingGuideDialog
from mysafe.ui.widgets import icon_button, push_button

PasswordProvider = Callable[[QWidget], str | None]


class FieldRow(QWidget):
    """One editable field: [kind ▾] [label] [value] [show] [generate] [↑] [↓] [✕]"""

    move_up = Signal(object)
    move_down = Signal(object)
    remove = Signal(object)

    def __init__(
        self,
        field: FieldInput,
        password_provider: PasswordProvider | None = None,
        *,
        original: FieldInput | None = None,
        confirm_fn: ConfirmFn = confirm,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("editorFieldRow")
        self._password_provider = password_provider
        self._confirm = confirm_fn
        # The saved field this row started from (None for rows added in this dialog).
        self.original = original

        self.kind = QComboBox()
        for kind in FieldKind:
            self.kind.addItem(kind.display_name, kind.value)
        self.kind.setCurrentIndex(self.kind.findData(FieldKind(field.kind).value))
        self.kind.setToolTip("Field type — passwords and codes are hidden by default")

        self.label = QLineEdit(field.label)
        self.label.setPlaceholderText("Label (e.g. Recovery code)")
        self.value = QLineEdit(field.value)
        self.value.setPlaceholderText("Value")

        self.show_button = icon_button("eye", "Show value", checkable=True)
        self.show_button.toggled.connect(self._apply_echo)
        self.generate_button = icon_button("key", "Generate a strong password", role="accent")
        self.generate_button.clicked.connect(self._generate)
        up = icon_button("arrow-up", "Move up")
        up.clicked.connect(lambda: self.move_up.emit(self))
        down = icon_button("arrow-down", "Move down")
        down.clicked.connect(lambda: self.move_down.emit(self))
        delete = icon_button("x", "Remove this field", role="danger")
        delete.clicked.connect(lambda: self.remove.emit(self))
        for button in (self.show_button, self.generate_button):
            policy = button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)  # keeps every row's columns aligned
            button.setSizePolicy(policy)
        self.kind.setMinimumWidth(150)
        self.kind.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.kind)
        layout.addWidget(self.label, 3)
        layout.addWidget(self.value, 4)
        layout.addWidget(self.show_button)
        layout.addWidget(self.generate_button)
        layout.addWidget(up)
        layout.addWidget(down)
        layout.addWidget(delete)

        self._previous_kind = self.current_kind()
        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        self._apply_kind()

    def current_kind(self) -> FieldKind:
        return FieldKind(self.kind.currentData())

    def to_input(self) -> FieldInput:
        return FieldInput(
            label=self.label.text().strip(), value=self.value.text(), kind=self.current_kind()
        )

    def is_blank(self) -> bool:
        return not self.label.text().strip() and not self.value.text()

    # ---------------------------------------------------------------- private

    def _on_kind_changed(self, _index: int) -> None:
        new_kind = self.current_kind()
        # Keep the label in sync while the user hasn't typed a custom one.
        if self.label.text().strip() in ("", self._previous_kind.display_name):
            self.label.setText(new_kind.display_name)
        self._previous_kind = new_kind
        self._apply_kind()

    def _apply_kind(self) -> None:
        secret = self.current_kind().is_secret_by_default
        self.show_button.setVisible(secret)
        self.show_button.setChecked(False)
        self.generate_button.setVisible(
            self.current_kind() == FieldKind.PASSWORD and self._password_provider is not None
        )
        self._apply_echo(False)

    def _apply_echo(self, revealed: bool) -> None:
        secret = self.current_kind().is_secret_by_default
        hidden = secret and not revealed
        self.value.setEchoMode(QLineEdit.EchoMode.Password if hidden else QLineEdit.EchoMode.Normal)
        bind_icon(self.show_button, "eye-off" if revealed else "eye")
        self.show_button.setToolTip("Hide value" if revealed else "Show value")

    def _generate(self) -> None:
        if self._password_provider is None:
            return
        password = self._password_provider(self)
        if not password:
            return
        if self.value.text() and not self._confirm(
            self,
            "Replace password",
            f"Replace the current “{self.label.text().strip() or 'Password'}”?",
            "Replace password",
            details=["The current password will be overwritten when you save this entry."],
            cancel_text="Keep current",
            destructive=True,
        ):
            return
        self.value.setText(password)


class EntryEditorDialog(QDialog):
    def __init__(
        self,
        categories: list[Category],
        *,
        entry: Entry | None = None,
        default_category_id: str | None = None,
        password_provider: PasswordProvider | None = None,
        confirm_fn: ConfirmFn = confirm,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit entry" if entry else "New entry")
        self._entry = entry
        self._confirm = confirm_fn
        self._closing = False
        self.resize(920, 620)
        self._password_provider = password_provider
        self.rows: list[FieldRow] = []

        # --- basics
        self.title = QLineEdit(entry.title if entry else "")
        self.title.setPlaceholderText("Service – Account   e.g. Steam, Gmail – Work")
        self.naming_button = push_button(
            "Naming tips",
            variant="ghost",
            icon="search",
            tooltip="How to name entries so search finds them",
        )
        self.naming_button.clicked.connect(lambda: NamingGuideDialog(self).exec())
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(self.title, 1)
        title_row.addWidget(self.naming_button)
        self.category = QComboBox()
        for category in categories:
            self.category.addItem(category.name, category.id)
        wanted = entry.category_id if entry else default_category_id
        index = self.category.findData(wanted) if wanted else -1
        self.category.setCurrentIndex(max(index, 0))
        self.url = QLineEdit(entry.url or "" if entry else "")
        self.url.setPlaceholderText("https://… (optional)")
        self.favorite = QCheckBox("Add to favorites")
        self.favorite.setCursor(Qt.CursorShape.PointingHandCursor)
        self.favorite.setChecked(entry.favorite if entry else False)

        basics = QFormLayout()
        basics.setHorizontalSpacing(14)
        basics.setVerticalSpacing(10)
        basics.addRow("Title:", title_row)
        basics.addRow("Category:", self.category)
        basics.addRow("Website:", self.url)
        basics.addRow("", self.favorite)

        # --- fields
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 4, 4, 4)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._rows_container)

        add_field = push_button("Add field", icon="plus")
        add_field.clicked.connect(self._add_blank_field)
        hint = QLabel("Add a username, recovery code, security question or anything else.")
        hint.setObjectName("hint")
        add_row = QHBoxLayout()
        add_row.addWidget(add_field)
        add_row.addWidget(hint, 1)

        fields_box = QGroupBox("Fields")
        fields_layout = QVBoxLayout(fields_box)
        fields_layout.addWidget(scroll, 1)
        fields_layout.addLayout(add_row)

        self._saved_fields: list[FieldInput] = []
        if entry:
            for f in entry.fields:
                saved = FieldInput(f.label, f.value, f.kind, f.is_secret)
                self._saved_fields.append(saved)
                self.add_field(saved, original=saved)
        else:
            for field in default_fields():
                self.add_field(field)

        # --- notes
        self.notes = QPlainTextEdit(entry.notes or "" if entry else "")
        self.notes.setPlaceholderText("Notes (optional)")
        self.notes.setFixedHeight(80)

        # --- buttons
        self.error = QLabel()
        self.error.setObjectName("error")
        self.save_button = push_button("Save", variant="primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        cancel = push_button("Cancel")
        cancel.clicked.connect(self.reject)  # asks first if something was changed
        buttons = QHBoxLayout()
        buttons.addWidget(self.error, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addLayout(basics)
        layout.addWidget(fields_box, 1)
        layout.addWidget(self.notes)
        layout.addLayout(buttons)

        self.title.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------ public

    def add_field(self, field: FieldInput, *, original: FieldInput | None = None) -> FieldRow:
        row = FieldRow(field, self._password_provider, original=original, confirm_fn=self._confirm)
        row.move_up.connect(lambda r: self._move(r, -1))
        row.move_down.connect(lambda r: self._move(r, +1))
        row.remove.connect(self._remove)
        self.rows.append(row)
        self._rows_layout.insertWidget(len(self.rows) - 1, row)
        return row

    def collect(self) -> EntryData | str:
        """Return the entered data, or an error message to show the user."""
        title = self.title.text().strip()
        if not title:
            return "Please enter a title."
        if self.category.currentIndex() < 0:
            return "Please create a category first."
        fields: list[FieldInput] = []
        for row in self.rows:
            if row.is_blank():
                continue  # silently drop completely empty rows
            data = row.to_input()
            if not data.label:
                return "Every field needs a label."
            fields.append(data)
        return EntryData(
            category_id=str(self.category.currentData()),
            title=title,
            url=self.url.text().strip() or None,
            notes=self.notes.toPlainText().strip() or None,
            favorite=self.favorite.isChecked(),
            fields=fields,
        )

    @property
    def closing(self) -> bool:
        """True once the dialog has decided to close (saved, discarded or nothing to save)."""
        return self._closing

    @property
    def is_editing(self) -> bool:
        return self._entry is not None

    def changes(self) -> list[str]:
        """Human-readable list of what differs from the saved entry (edit mode only)."""
        entry = self._entry
        if entry is None:
            return []
        out: list[str] = []
        if self.title.text().strip() != entry.title:
            out.append("Title changed")
        if self.category.currentData() != entry.category_id:
            out.append(f"Moved to “{self.category.currentText()}”")
        if (self.url.text().strip() or None) != entry.url:
            out.append("Website changed")
        if self.favorite.isChecked() != entry.favorite:
            out.append(
                "Added to favorites" if self.favorite.isChecked() else "Removed from favorites"
            )
        if (self.notes.toPlainText().strip() or None) != (entry.notes or None):
            out.append("Notes changed")

        kept = [r for r in self.rows if r.original is not None and not r.is_blank()]
        kept_ids = {id(r.original) for r in kept}
        for row in kept:
            original = row.original
            assert original is not None
            name = original.label
            if row.value.text() != original.value:
                out.append(f"{name} changed")
            if row.label.text().strip() != original.label:
                out.append(f"“{name}” renamed to “{row.label.text().strip()}”")
            if row.current_kind() != FieldKind(original.kind):
                out.append(f"{name} type changed to {row.current_kind().display_name}")
        for row in self.rows:
            if row.original is None and not row.is_blank():
                out.append(f"Field added: {row.label.text().strip() or 'unnamed'}")
        originals = self._saved_fields
        for original in originals:
            if id(original) not in kept_ids:
                out.append(f"Field removed: {original.label}")
        current_order = [id(r.original) for r in kept]
        saved_order = [id(o) for o in originals if id(o) in kept_ids]
        if current_order != saved_order:
            out.append("Field order changed")
        return out

    def has_unsaved_input(self) -> bool:
        if self.is_editing:
            return bool(self.changes())
        return bool(
            self.title.text().strip()
            or self.url.text().strip()
            or self.notes.toPlainText().strip()
            or any(r.value.text() for r in self.rows)
        )

    def result_data(self) -> EntryData:
        data = self.collect()
        if isinstance(data, str):
            raise ValueError(data)
        return data

    # ---------------------------------------------------------------- private

    def _add_blank_field(self) -> None:
        row = self.add_field(FieldInput(label="", value="", kind=FieldKind.TEXT))
        row.label.setFocus()

    def _remove(self, row: FieldRow) -> None:
        # No question here: removals are listed in the "Save changes" confirmation.
        self.rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()

    def _move(self, row: FieldRow, step: int) -> None:
        index = self.rows.index(row)
        target = index + step
        if not 0 <= target < len(self.rows):
            return
        self.rows.insert(target, self.rows.pop(index))
        self._rows_layout.removeWidget(row)
        self._rows_layout.insertWidget(target, row)

    def _on_save(self) -> None:
        data = self.collect()
        if isinstance(data, str):
            self.error.setText(data)
            return
        if self.is_editing:
            changes = self.changes()
            if not changes:
                self._close(accepted=False)  # nothing changed, nothing to save
                return
            assert self._entry is not None
            if not self._confirm(
                self,
                "Save changes",
                f"Save these changes to “{self._entry.title}”?",
                "Save changes",
                details=changes,
                cancel_text="Keep editing",
            ):
                return
        self._close(accepted=True)

    def reject(self) -> None:
        """Cancel / Esc / window close: ask before throwing away typed changes."""
        if (
            not self._closing
            and self.has_unsaved_input()
            and not self._confirm(
                self,
                "Discard changes",
                "Close without saving?",
                "Discard changes",
                details=self.changes() if self.is_editing else [],
                cancel_text="Keep editing",
                destructive=True,
            )
        ):
            return
        self._close(accepted=False)

    def _close(self, *, accepted: bool) -> None:
        self._closing = True
        if accepted:
            super().accept()
        else:
            super().reject()
