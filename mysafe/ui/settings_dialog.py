"""Settings: theme and clipboard clearing."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mysafe.ui.controller import THEMES
from mysafe.ui.widgets import push_button


class SettingsDialog(QDialog):
    def __init__(
        self,
        *,
        theme: str,
        clipboard_clear_seconds: int,
        auto_lock_minutes: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)

        self.theme = QComboBox()
        for value in THEMES:
            self.theme.addItem(value.capitalize(), value)
        self.theme.setCurrentIndex(max(self.theme.findData(theme), 0))

        self.clear_seconds = QSpinBox()
        self.clear_seconds.setRange(0, 600)
        self.clear_seconds.setSuffix(" s")
        self.clear_seconds.setSpecialValueText("Never")
        self.clear_seconds.setValue(clipboard_clear_seconds)

        hint = QLabel(
            "Copied passwords and codes are removed from the clipboard after this time. "
            "Lock any time with Ctrl+L."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)

        self.auto_lock = QSpinBox()
        self.auto_lock.setRange(0, 240)
        self.auto_lock.setSuffix(" min")
        self.auto_lock.setSpecialValueText("Off")
        self.auto_lock.setValue(auto_lock_minutes)
        self.auto_lock.setToolTip("Lock MySafe after this many minutes without using it")

        form = QFormLayout()
        form.addRow("Theme:", self.theme)
        form.addRow("Clear clipboard after:", self.clear_seconds)
        form.addRow("Lock when idle for:", self.auto_lock)

        cancel = push_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = push_button("Save", variant="primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(buttons)

    def selected_theme(self) -> str:
        return str(self.theme.currentData())

    def selected_clear_seconds(self) -> int:
        return self.clear_seconds.value()

    def selected_auto_lock_minutes(self) -> int:
        return self.auto_lock.value()
