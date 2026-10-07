"""Search field with a clearly clickable clear (✕) button."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import QLineEdit, QWidget

from mysafe.ui.icons import icon
from mysafe.ui.palette import color
from mysafe.ui.widgets import icon_button

_CLEAR_SIZE = 24


class SearchBox(QLineEdit):
    """Leading search icon; a round ✕ button appears while there is text. Esc also clears."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchBox")
        self._search_action = self.addAction(
            icon("search", color("muted")), QLineEdit.ActionPosition.LeadingPosition
        )

        self.clear_button = icon_button("x", "Clear search (Esc)", size=_CLEAR_SIZE)
        self.clear_button.setObjectName("clearButton")
        self.clear_button.setParent(self)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.clicked.connect(self.clear_search)
        self.clear_button.hide()
        self.setTextMargins(0, 0, _CLEAR_SIZE + 4, 0)

        self.textChanged.connect(self._on_text_changed)
        self.installEventFilter(self)

    def clear_search(self) -> None:
        self.clear()
        self.setFocus()

    def refresh_icons(self) -> None:
        self._search_action.setIcon(icon("search", color("muted")))

    # ---------------------------------------------------------------- events

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_clear_button()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and self.text()
        ):
            self.clear()
            return True
        return super().eventFilter(watched, event)

    def _on_text_changed(self, text: str) -> None:
        self.clear_button.setVisible(bool(text))
        self._place_clear_button()

    def _place_clear_button(self) -> None:
        x = self.width() - _CLEAR_SIZE - 6
        y = (self.height() - _CLEAR_SIZE) // 2
        self.clear_button.move(x, y)
