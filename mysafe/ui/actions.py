"""What the main window can ask the app to do with the vault (implemented in app.py).

Keeping this as a small interface means the UI never handles files, keys or passwords itself.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QWidget


class VaultActions(Protocol):
    def lock(self) -> None: ...

    def change_master_password(self, parent: QWidget) -> None: ...

    def new_recovery_key(self, parent: QWidget) -> None: ...

    def create_usb_copy(self, parent: QWidget) -> None: ...

    def sync(self, parent: QWidget) -> None: ...

    def restore_backup(self, parent: QWidget) -> None: ...
