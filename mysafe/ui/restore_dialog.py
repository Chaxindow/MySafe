"""File → Restore from backup…: pick one of the backups MySafe keeps next to the vault."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mysafe.ui.widgets import push_button


@dataclass(frozen=True, slots=True)
class BackupChoice:
    title: str  # e.g. "Before sync"
    detail: str  # e.g. "7 Oct 11:52 · 12 entries"


class RestoreDialog(QDialog):
    def __init__(self, backups: Sequence[BackupChoice], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restore from backup")
        self.setMinimumWidth(520)

        title = QLabel("Restore from backup")
        title.setObjectName("screenTitle")
        intro = QLabel(
            "MySafe keeps a few encrypted backups next to your vault. Restoring one replaces "
            "everything in MySafe with that backup. Your master password and recovery key "
            "stay the same, and what you have now is kept as a “Before restore” backup, so "
            "you can undo this."
        )
        intro.setObjectName("hint")
        intro.setWordWrap(True)

        self.list = QListWidget()
        self.list.setObjectName("backupList")
        for backup in backups:
            item = QListWidgetItem(f"{backup.title}\n{backup.detail}")
            self.list.addItem(item)
        if backups:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())

        empty = QLabel("There are no backups yet. They are made when you sync or save.")
        empty.setObjectName("hint")
        empty.setVisible(not backups)

        cancel = push_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.restore_button = push_button("Restore", variant="danger")
        self.restore_button.setEnabled(bool(backups))
        self.restore_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.restore_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 18)
        layout.setSpacing(10)
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(intro)
        layout.addWidget(self.list, 1)
        layout.addWidget(empty)
        layout.addLayout(buttons)

    def chosen_index(self) -> int | None:
        row = self.list.currentRow()
        return row if row >= 0 else None
