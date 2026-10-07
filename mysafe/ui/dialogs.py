"""Confirmation dialogs for sensitive actions (replace, remove, save changes, delete)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from mysafe.ui.widgets import repolish

# confirm(parent, title, message, confirm_text, *, details, destructive) -> True if confirmed
ConfirmFn = Callable[..., bool]


def build_confirm_box(
    parent: QWidget | None,
    title: str,
    message: str,
    confirm_text: str,
    *,
    details: Sequence[str] = (),
    cancel_text: str = "Cancel",
    destructive: bool = False,
) -> tuple[QMessageBox, QPushButton]:
    """Create (but don't show) the confirmation box. Returns the box and its confirm button."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(message)
    if details:
        box.setInformativeText("\n".join(f"•  {line}" for line in details))

    ok = box.addButton(confirm_text, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
    ok.setProperty("variant", "danger" if destructive else "primary")
    for button in (ok, cancel):
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        repolish(button)  # the variant is set after the box styled its buttons
    # The safe choice is the default, so pressing Enter never confirms by accident.
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    return box, ok


def confirm(
    parent: QWidget | None,
    title: str,
    message: str,
    confirm_text: str,
    *,
    details: Sequence[str] = (),
    cancel_text: str = "Cancel",
    destructive: bool = False,
) -> bool:
    """Ask before doing something that changes or removes data. True if confirmed."""
    box, ok = build_confirm_box(
        parent,
        title,
        message,
        confirm_text,
        details=details,
        cancel_text=cancel_text,
        destructive=destructive,
    )
    box.exec()
    return box.clickedButton() is ok
