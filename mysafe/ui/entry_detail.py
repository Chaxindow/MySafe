"""Right pane: one entry's details — header actions and a grouped list of fields."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mysafe.models import Entry, FieldKind
from mysafe.ui.clipboard import SecretClipboard
from mysafe.ui.controller import AppController
from mysafe.ui.icons import bind_icon
from mysafe.ui.widgets import icon_button, push_button

MASK = "●" * 10

CopyCallback = Callable[[str, str, bool], None]  # (label, value, secret)


def _is_link(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


class FieldValueRow(QFrame):
    """One field:  Label / value on the left, [show] [open] [copy] on the right."""

    def __init__(
        self,
        label: str,
        value: str,
        *,
        secret: bool,
        on_copy: CopyCallback,
        link: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("fieldRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)  # enables :hover styling
        self.value = value
        self.secret = secret

        name = QLabel(label)
        name.setObjectName("fieldLabel")
        self.value_label = QLabel()
        self.value_label.setObjectName("secretValue" if secret else "fieldValue")
        self.value_label.setWordWrap(True)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        actions = QHBoxLayout()
        actions.setSpacing(2)
        self.show_button: QToolButton | None = None
        if secret:
            self.show_button = icon_button("eye", f"Show {label}", checkable=True)
            self.show_button.toggled.connect(self._on_show_toggled)
            actions.addWidget(self.show_button)
        self.open_button: QToolButton | None = None
        if link:
            self.open_button = icon_button("external", "Open in your web browser")
            self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(value)))
            actions.addWidget(self.open_button)
        self.copy_button = icon_button("copy", f"Copy {label}")
        self.copy_button.clicked.connect(lambda: on_copy(label, value, secret))
        actions.addWidget(self.copy_button)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(self.value_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(12)
        layout.addLayout(text, 1)
        layout.addLayout(actions)
        self._render(revealed=False)

    def _on_show_toggled(self, checked: bool) -> None:
        self._render(revealed=checked)

    def _render(self, *, revealed: bool) -> None:
        masked = self.secret and not revealed
        self.value_label.setText(MASK if masked else self.value)
        if self.show_button is not None:
            bind_icon(self.show_button, "eye-off" if revealed else "eye")
            label = self.show_button.toolTip().split(" ", 1)[-1]
            self.show_button.setToolTip(f"{'Hide' if revealed else 'Show'} {label}")


class EntryDetailPanel(QFrame):
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    status_message = Signal(str)

    def __init__(
        self,
        controller: AppController,
        clipboard: SecretClipboard,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailPane")
        self._controller = controller
        self._clipboard = clipboard
        self._entry_id = ""
        self.rows: list[FieldValueRow] = []

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

        controller.entries_changed.connect(self.refresh)
        controller.categories_changed.connect(self.refresh)
        controller.settings_changed.connect(self.refresh)
        self.show_entry("")

    # ------------------------------------------------------------------ public

    @property
    def entry_id(self) -> str:
        return self._entry_id

    def refresh(self) -> None:
        self.show_entry(self._entry_id)

    def show_entry(self, entry_id: str) -> None:
        entry = self._controller.entry(entry_id) if entry_id else None
        self._entry_id = entry.id if entry else ""
        self.rows = []
        # A button on the old page may be the one that triggered this refresh, so delete
        # the old page later instead of immediately.
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        if entry is None:
            self._scroll.setWidget(self._placeholder("Select an entry to see its details."))
        else:
            self._scroll.setWidget(self._build(entry))

    # ---------------------------------------------------------------- private

    @staticmethod
    def _placeholder(text: str) -> QWidget:
        page = QWidget()
        page.setObjectName("detailPage")
        label = QLabel(text)
        label.setObjectName("placeholder")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(page)
        layout.addWidget(label)
        return page

    def _build(self, entry: Entry) -> QWidget:
        page = QWidget()
        page.setObjectName("detailPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        # Header: title + category on the left, actions on the right
        title = QLabel(entry.title)
        title.setObjectName("entryTitle")
        title.setWordWrap(True)
        category = self._controller.category(entry.category_id)
        chip = QLabel(category.name if category else "")
        chip.setObjectName("categoryChip")
        chip_row = QHBoxLayout()
        chip_row.addWidget(chip)
        chip_row.addStretch(1)
        heading = QVBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(title)
        heading.addLayout(chip_row)

        self.favorite_button = icon_button(
            "star",
            "Remove from favorites" if entry.favorite else "Add to favorites",
            role="accent" if entry.favorite else "muted",
            checkable=True,
            size=34,
        )
        bind_icon(
            self.favorite_button,
            "star",
            "accent" if entry.favorite else "muted",
            filled=entry.favorite,
        )
        self.favorite_button.setChecked(entry.favorite)
        self.favorite_button.toggled.connect(
            lambda checked: self._controller.set_favorite(entry.id, checked)
        )
        self.edit_button = push_button("Edit", icon="pencil", tooltip="Edit this entry (Ctrl+E)")
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(entry.id))
        self.delete_button = push_button(
            "Delete", variant="danger", icon="trash", tooltip="Delete this entry"
        )
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(entry.id))

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.favorite_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)

        header = QHBoxLayout()
        header.setSpacing(16)
        header.addLayout(heading, 1)
        header.addLayout(actions)
        header.setAlignment(actions, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        # Fields, grouped in one box with hairline dividers
        specs: list[tuple[str, str, bool, bool]] = []  # label, value, secret, link
        if entry.url:
            specs.append(("Website", entry.url, False, _is_link(entry.url)))
        for f in entry.fields:
            link = f.kind == FieldKind.URL and _is_link(f.value)
            specs.append((f.label, f.value, f.is_secret, link))

        if specs:
            group = QFrame()
            group.setObjectName("fieldGroup")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(0)
            for i, (label, value, secret, link) in enumerate(specs):
                row = FieldValueRow(label, value, secret=secret, on_copy=self._copy, link=link)
                row.setProperty("first", i == 0)
                row.setProperty("last", i == len(specs) - 1)
                group_layout.addWidget(row)
                self.rows.append(row)
            layout.addWidget(group)
        else:
            empty = QLabel("No fields yet. Click Edit to add an email, password or anything else.")
            empty.setObjectName("hint")
            empty.setWordWrap(True)
            layout.addWidget(empty)

        if entry.notes:
            notes_title = QLabel("Notes")
            notes_title.setObjectName("sectionTitle")
            notes = QLabel(entry.notes)
            notes.setObjectName("notes")
            notes.setWordWrap(True)
            notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            notes_box = QVBoxLayout()
            notes_box.setSpacing(6)
            notes_box.addWidget(notes_title)
            notes_box.addWidget(notes)
            layout.addLayout(notes_box)

        layout.addStretch(1)
        return page

    def _copy(self, label: str, value: str, secret: bool) -> None:
        will_clear = self._clipboard.copy(value, secret=secret)
        if will_clear:
            seconds = self._clipboard.clear_after_seconds
            self.status_message.emit(f"{label} copied. Clipboard will be cleared in {seconds} s.")
        else:
            self.status_message.emit(f"{label} copied.")
