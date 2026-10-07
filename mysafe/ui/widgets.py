"""Shared widget helpers: consistent buttons with hover states and a pointing-hand cursor."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QToolButton, QWidget

from mysafe.ui.icons import bind_icon

ICON_SIZE = QSize(16, 16)


def _clickable(widget: QWidget) -> None:
    widget.setCursor(Qt.CursorShape.PointingHandCursor)


def tool_button(text: str, tooltip: str | None = None) -> QToolButton:
    """A plain text tool button (for small, text-only actions)."""
    button = QToolButton()
    button.setText(text)
    if tooltip:
        button.setToolTip(tooltip)
    _clickable(button)
    return button


def icon_button(
    icon: str,
    tooltip: str,
    *,
    role: str = "muted",
    checkable: bool = False,
    size: int = 30,
) -> QToolButton:
    """Square icon-only button. Its hover background shows it can be clicked."""
    button = QToolButton()
    bind_icon(button, icon, role)
    button.setIconSize(ICON_SIZE)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setCheckable(checkable)
    button.setFixedSize(size, size)
    _clickable(button)
    return button


def push_button(
    text: str,
    *,
    variant: str = "secondary",
    icon: str | None = None,
    tooltip: str | None = None,
) -> QPushButton:
    """Text button. variant: "primary" (brass), "secondary", "danger" or "ghost"."""
    button = QPushButton(text)
    button.setProperty("variant", variant)
    if icon:
        role = {"primary": "accent_text", "danger": "danger"}.get(variant, "muted")
        bind_icon(button, icon, role)
        button.setIconSize(ICON_SIZE)
    if tooltip:
        button.setToolTip(tooltip)
    _clickable(button)
    return button


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
