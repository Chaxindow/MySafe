"""Left pane: app name, Favorites, All and the user's categories."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mysafe import APP_NAME
from mysafe.resources import resource_path
from mysafe.ui.controller import AppController
from mysafe.ui.delegates import ROLE_COUNT, ROLE_ICON, ROLE_KEY, SidebarDelegate
from mysafe.ui.icons import CATEGORY_FALLBACK, has_icon
from mysafe.ui.widgets import icon_button, push_button

# Special (non-category) keys
ALL = "__all__"
FAVORITES = "__favorites__"
SPECIAL_KEYS = (FAVORITES, ALL)


def is_category_key(key: str | None) -> bool:
    return key is not None and key not in SPECIAL_KEYS


class CategoryPanel(QFrame):
    selection_changed = Signal(str)  # key: ALL, FAVORITES or a category id
    add_requested = Signal()
    rename_requested = Signal(str)  # category id
    delete_requested = Signal(str)  # category id

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._controller = controller

        # Brand
        self._brand_icon = QLabel()
        self._brand_icon.setFixedSize(28, 28)
        self._brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_brand()
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(10, 4, 10, 8)
        brand_row.setSpacing(6)
        brand_row.addWidget(self._brand_icon)
        brand_row.addWidget(brand, 1)

        # List
        self.list = QListWidget()
        self.list.setObjectName("categoryList")
        self.list.setItemDelegate(SidebarDelegate(self.list))
        self.list.setMouseTracking(True)  # hover highlight
        self.list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)

        # Footer: new category + rename / delete for the selected category
        self.add_button = push_button(
            "New category", variant="ghost", icon="plus", tooltip="Add a category (Ctrl+Shift+N)"
        )
        self.add_button.clicked.connect(lambda: self.add_requested.emit())
        self.rename_button = icon_button("pencil", "Rename category")
        self.rename_button.clicked.connect(self._emit_rename)
        self.delete_button = icon_button("trash", "Delete category", role="danger")
        self.delete_button.clicked.connect(self._emit_delete)

        footer = QHBoxLayout()
        footer.setContentsMargins(4, 6, 8, 2)
        footer.setSpacing(2)
        footer.addWidget(self.add_button, 1)
        footer.addWidget(self.rename_button)
        footer.addWidget(self.delete_button)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: palette(mid);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 8)
        layout.setSpacing(0)
        layout.addLayout(brand_row)
        layout.addWidget(self.list, 1)
        layout.addWidget(separator)
        layout.addLayout(footer)

        controller.categories_changed.connect(self.reload)
        controller.entries_changed.connect(self.reload)  # counts change
        controller.settings_changed.connect(self._refresh_brand)
        self.reload()

    # ------------------------------------------------------------------ public

    def current_key(self) -> str:
        item = self.list.currentItem()
        return ALL if item is None else str(item.data(ROLE_KEY))

    def select_key(self, key: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(ROLE_KEY) == key:
                self.list.setCurrentItem(item)
                return

    def count_for(self, key: str) -> int | None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(ROLE_KEY) == key:
                return int(item.data(ROLE_COUNT))
        return None

    def reload(self) -> None:
        previous = self.current_key() if self.list.count() else ALL
        counts = self._controller.entry_counts()

        self.list.blockSignals(True)
        self.list.clear()
        self._add_item("Favorites", FAVORITES, "star", self._controller.favorite_count())
        self._add_item("All items", ALL, "grid", self._controller.total_entries())
        for category in self._controller.categories():
            icon_name = category.icon if has_icon(category.icon) else CATEGORY_FALLBACK
            self._add_item(category.name, category.id, str(icon_name), counts.get(category.id, 0))
        self.list.blockSignals(False)

        keys = [str(self.list.item(r).data(ROLE_KEY)) for r in range(self.list.count())]
        target = previous if previous in keys else ALL
        self.select_key(target)
        if target != previous:
            self.selection_changed.emit(target)
        self._update_buttons()

    # ---------------------------------------------------------------- private

    def _refresh_brand(self) -> None:
        pixmap = QPixmap(str(resource_path("icon-64.png")))
        pixmap.setDevicePixelRatio(64 / 24)  # crisp 24 px logo on any screen
        self._brand_icon.setPixmap(pixmap)

    def _add_item(self, label: str, key: str, icon_name: str, count: int) -> None:
        item = QListWidgetItem(label)
        item.setData(ROLE_KEY, key)
        item.setData(ROLE_ICON, icon_name)
        item.setData(ROLE_COUNT, count)
        item.setToolTip(label)
        self.list.addItem(item)

    def _update_buttons(self) -> None:
        editable = is_category_key(self.current_key())
        self.rename_button.setEnabled(editable)
        self.delete_button.setEnabled(editable)

    def _on_current_changed(self, *_: object) -> None:
        self._update_buttons()
        self.selection_changed.emit(self.current_key())

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        key = str(item.data(ROLE_KEY))
        if is_category_key(key):
            self.rename_requested.emit(key)

    def _emit_rename(self) -> None:
        key = self.current_key()
        if is_category_key(key):
            self.rename_requested.emit(key)

    def _emit_delete(self) -> None:
        key = self.current_key()
        if is_category_key(key):
            self.delete_requested.emit(key)
