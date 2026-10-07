"""Middle pane: search box, "New" button and the entry list."""

from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mysafe.models import Entry
from mysafe.ui.category_panel import ALL, FAVORITES
from mysafe.ui.controller import AppController
from mysafe.ui.delegates import ROLE_FAVORITE, ROLE_KEY, ROLE_SUBTITLE, EntryDelegate
from mysafe.ui.search_box import SearchBox
from mysafe.ui.widgets import push_button


def _subtitle(entry: Entry, category_names: dict[str, str], show_category: bool) -> str:
    """Category name when the list mixes categories, otherwise the website's host."""
    if show_category:
        return category_names.get(entry.category_id, "")
    return urlparse(entry.url).netloc.removeprefix("www.") if entry.url else ""


class EntryListPanel(QFrame):
    entry_selected = Signal(str)  # entry id, "" when nothing is selected
    new_entry_requested = Signal()

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("listPane")
        self._controller = controller
        self._filter_key = ALL

        self.search_box = SearchBox()
        self.search_box.setPlaceholderText("Search  (Ctrl+F)")
        self.search_box.textChanged.connect(lambda _text: self.reload())

        self.new_button = push_button(
            "New", variant="primary", icon="plus", tooltip="Add a new account (Ctrl+N)"
        )
        self.new_button.clicked.connect(lambda: self.new_entry_requested.emit())

        top = QHBoxLayout()
        top.setContentsMargins(10, 0, 10, 0)
        top.setSpacing(8)
        top.addWidget(self.search_box, 1)
        top.addWidget(self.new_button)

        self.list = QListWidget()
        self.list.setObjectName("entryList")
        self.list.setItemDelegate(EntryDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._on_current_changed)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("placeholder")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 8)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty_label, 1)

        controller.entries_changed.connect(self.reload)
        controller.categories_changed.connect(self.reload)
        controller.settings_changed.connect(self._refresh_icons)
        self.reload()

    # ------------------------------------------------------------------ public

    def set_filter(self, key: str) -> None:
        self._filter_key = key
        self.reload()

    def current_entry_id(self) -> str:
        item = self.list.currentItem()
        return "" if item is None else str(item.data(ROLE_KEY))

    def select_entry(self, entry_id: str) -> bool:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(ROLE_KEY) == entry_id:
                self.list.setCurrentItem(item)
                return True
        return False

    def titles(self) -> list[str]:
        return [self.list.item(r).text() for r in range(self.list.count())]

    def reload(self) -> None:
        previous = self.current_entry_id()
        search = self.search_box.text().strip()
        entries = self._load(search)
        show_category = bool(search) or self._filter_key in (ALL, FAVORITES)
        names = {c.id: c.name for c in self._controller.categories()} if show_category else {}

        self.list.blockSignals(True)
        self.list.clear()
        for entry in entries:
            item = QListWidgetItem(entry.title)
            item.setData(ROLE_KEY, entry.id)
            item.setData(ROLE_FAVORITE, entry.favorite)
            item.setData(ROLE_SUBTITLE, _subtitle(entry, names, show_category))
            self.list.addItem(item)
        self.list.blockSignals(False)

        has_entries = self.list.count() > 0
        self.list.setVisible(has_entries)
        self.empty_label.setVisible(not has_entries)
        if search:
            self.empty_label.setText(f"Nothing matches “{search}”.")
        elif self._filter_key == FAVORITES:
            self.empty_label.setText("No favorites yet.\nUse the star on an entry to pin it here.")
        else:
            self.empty_label.setText("No entries here yet.\nClick “New” to add an account.")

        if not (previous and self.select_entry(previous)) and has_entries:
            self.list.setCurrentRow(0)
        if self.current_entry_id() != previous:
            self.entry_selected.emit(self.current_entry_id())

    # ---------------------------------------------------------------- private

    def _refresh_icons(self) -> None:
        self.search_box.refresh_icons()

    def _load(self, search: str) -> list[Entry]:
        if search:
            return self._controller.entries(search=search)  # search looks everywhere
        if self._filter_key == FAVORITES:
            return self._controller.entries(favorites_only=True)
        if self._filter_key == ALL:
            return self._controller.entries()
        return self._controller.entries(self._filter_key)

    def _on_current_changed(self, *_: object) -> None:
        self.entry_selected.emit(self.current_entry_id())
