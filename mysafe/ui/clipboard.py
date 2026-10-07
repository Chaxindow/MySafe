"""Copy to the clipboard and clear secrets again after a few seconds.

Secrets are also:
* kept out of Windows clipboard history (Win+V) and cloud clipboard, and marked as a
  password for KDE's clipboard manager;
* cleared when MySafe locks or quits (`flush`), if they are still on the clipboard.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QObject, QTimer
from PySide6.QtGui import QClipboard, QGuiApplication

_WINDOWS_FORMAT = 'application/x-qt-windows-mime;value="{}"'
_DWORD_ZERO = QByteArray(b"\x00\x00\x00\x00")


def secret_mime_data(text: str) -> QMimeData:
    """Clipboard data for a secret, with "don't keep this" hints for clipboard managers."""
    data = QMimeData()
    data.setText(text)
    data.setData(_WINDOWS_FORMAT.format("ExcludeClipboardContentFromMonitorProcessing"), b"")
    data.setData(_WINDOWS_FORMAT.format("CanIncludeInClipboardHistory"), _DWORD_ZERO)
    data.setData(_WINDOWS_FORMAT.format("CanUploadToCloudClipboard"), _DWORD_ZERO)
    data.setData("x-kde-passwordManagerHint", QByteArray(b"secret"))
    return data


class SecretClipboard(QObject):
    def __init__(self, clear_after_seconds: int = 20, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.clear_after_seconds = clear_after_seconds
        self._pending: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_if_unchanged)

    @staticmethod
    def _clipboard() -> QClipboard:
        return QGuiApplication.clipboard()

    def copy(self, text: str, *, secret: bool) -> bool:
        """Copy `text`. Returns True if it will be cleared automatically."""
        if not secret:
            self._clipboard().setText(text)
            self._pending = None
            self._timer.stop()
            return False
        self._clipboard().setMimeData(secret_mime_data(text))
        self._pending = text  # cleared on lock/quit even if auto-clear is off
        if self.clear_after_seconds > 0:
            self._timer.start(self.clear_after_seconds * 1000)
            return True
        self._timer.stop()
        return False

    def clear_if_unchanged(self) -> None:
        """Clear the clipboard, but only if it still holds the secret we put there."""
        self._timer.stop()
        clipboard = self._clipboard()
        if self._pending is not None and clipboard.text() == self._pending:
            clipboard.clear()
        self._pending = None

    def flush(self) -> None:
        """Lock / quit / dialog closed: remove a secret we copied, right now."""
        self.clear_if_unchanged()
