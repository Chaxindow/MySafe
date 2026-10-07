"""Start-up screens: create a vault, show the recovery key, unlock (or recover) a vault.

The dialogs never touch files themselves: opening/recovering is done by callables passed
in by `app.py`, so the screens stay simple and testable.

Recovery is two steps: first the recovery key is checked (it opens the vault in memory);
only when it is right does the "choose a new master password" step appear.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mysafe import APP_NAME
from mysafe.resources import resource_path
from mysafe.services.crypto import VaultCryptoError, WrongPasswordError, recovery_key_problem
from mysafe.services.password_strength import estimate
from mysafe.ui.clipboard import SecretClipboard
from mysafe.ui.icons import icon
from mysafe.ui.palette import color
from mysafe.ui.widgets import push_button, repolish

UnlockFn = Callable[[str], Any]  # password -> opened vault (raises WrongPasswordError …)
CheckKeyFn = Callable[[str], Any]  # recovery key -> opened vault (raises WrongPasswordError …)
SetPasswordFn = Callable[[Any, str], Any]  # (vault opened by the key, new password) -> vault
DiscardFn = Callable[[Any], None]  # close a vault opened by the key but not used

# After this many wrong passwords / recovery keys in a row, the user has to wait a little
# before the next try (5 s, 10 s, … up to 30 s). Slows down guessing; harmless for typos.
FREE_ATTEMPTS = 5
MAX_WAIT_SECONDS = 30


def wait_seconds(failures: int) -> int:
    if failures < FREE_ATTEMPTS:
        return 0
    return min(MAX_WAIT_SECONDS, 5 * (failures - FREE_ATTEMPTS + 1))


# ------------------------------------------------------------------ helpers


class PasswordField(QLineEdit):
    """Password input with an eye button to show/hide what was typed."""

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setPlaceholderText(placeholder)
        self.setObjectName("bigInput")
        self._toggle = self.addAction(
            icon("eye", color("muted")), QLineEdit.ActionPosition.TrailingPosition
        )
        self._toggle.setToolTip("Show password")
        self._toggle.triggered.connect(self._flip)

    def _flip(self) -> None:
        hidden = self.echoMode() == QLineEdit.EchoMode.Password
        self.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self._toggle.setIcon(icon("eye-off" if hidden else "eye", color("muted")))
        self._toggle.setToolTip("Hide password" if hidden else "Show password")


class Banner(QFrame):
    """A colored box with an icon and a message; hidden while it has no text.

    kind="error": red, warning triangle (wrong password, invalid input).
    kind="ok": green, check mark (e.g. "Recovery key accepted").
    """

    def __init__(self, kind: str = "error", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("errorBanner" if kind == "error" else "okBanner")
        role = "danger" if kind == "error" else "success"
        badge = QLabel()
        badge.setPixmap(icon("alert" if kind == "error" else "check", color(role)).pixmap(20, 20))
        badge.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(badge)
        layout.addWidget(self._label, 1)
        self.setVisible(False)

    def setText(self, text: str) -> None:  # noqa: N802 (same name as QLabel.setText)
        self._label.setText(text)
        self.setVisible(bool(text))

    def text(self) -> str:
        return self._label.text()

    def clear(self) -> None:
        self.setText("")


def mark_invalid(field: QLineEdit, invalid: bool = True) -> None:
    """Red border + tint on a field; cleared automatically as soon as the user types."""
    if bool(field.property("invalid")) == invalid:
        return
    field.setProperty("invalid", invalid)
    repolish(field)


def _clear_mark_on_edit(*fields: QLineEdit) -> None:
    for field in fields:
        field.textEdited.connect(lambda _text, f=field: mark_invalid(f, False))


def shake(widget: QWidget) -> None:
    """A short horizontal shake of the window, the usual "no" of a lock screen."""
    window = widget.window()
    if not window.isVisible() or window.property("shaking"):
        return
    start = window.pos()
    animation = QPropertyAnimation(window, b"pos", window)
    animation.setDuration(380)
    animation.setEasingCurve(QEasingCurve.Type.Linear)
    offsets = (0, -12, 12, -9, 9, -5, 5, 0)
    for step, offset in enumerate(offsets):
        animation.setKeyValueAt(step / (len(offsets) - 1), start + QPoint(offset, 0))
    window.setProperty("shaking", True)
    animation.finished.connect(lambda: window.setProperty("shaking", False))
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def _logo(size: int = 64) -> QLabel:
    label = QLabel()
    pixmap = QPixmap(str(resource_path("icon-256.png")))
    pixmap.setDevicePixelRatio(256 / size)
    label.setPixmap(pixmap)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("screenTitle")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _text(text: str, *, name: str = "hint", center: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    if center:
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def master_password_problem(password: str, confirm: str) -> str | None:
    """Why this new master password can't be used yet, or None if it is fine."""
    strength = estimate(password)
    if not strength.acceptable:
        return strength.hint
    if password != confirm:
        return "The two passwords don't match."
    return None


def _show_new_password_problem(
    problem: str, banner: Banner, password: QLineEdit, confirm: QLineEdit
) -> None:
    banner.setText(problem)
    mark_invalid(confirm if "match" in problem else password)
    shake(banner)


class StrengthMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bar = QProgressBar()
        self.bar.setObjectName("strengthBar")
        self.bar.setRange(0, 4)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.label = QLabel(" ")
        self.label.setObjectName("hint")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.bar)
        layout.addWidget(self.label)

    def update_for(self, password: str) -> None:
        if not password:
            self.bar.setValue(0)
            self.label.setText(" ")
            return
        strength = estimate(password)
        self.bar.setValue(max(strength.score, 1) if strength.acceptable else 1)
        self.bar.setProperty("level", strength.score)
        repolish(self.bar)
        self.label.setText(f"{strength.label}. {strength.hint}".strip())


# ---------------------------------------------------------------- setup


class SetupDialog(QDialog):
    """First start: choose the master password."""

    def __init__(self, *, importing_old_data: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setMinimumWidth(460)

        intro = (
            "Your existing entries will be moved into the new encrypted vault."
            if importing_old_data
            else "Everything you save is encrypted with this password."
        )
        self.password = PasswordField("Master password")
        self.confirm = PasswordField("Repeat master password")
        self.meter = StrengthMeter()
        self.understand = QCheckBox(
            "I understand: if I forget this password and lose my recovery key,\n"
            "my data cannot be recovered by anyone."
        )
        self.understand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.error = Banner()
        self.create_button = push_button("Create vault", variant="primary")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._on_create)
        cancel = push_button("Quit")
        cancel.clicked.connect(self.reject)

        for field in (self.password, self.confirm):
            field.textChanged.connect(self._refresh)
        self.understand.toggled.connect(self._refresh)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 22)
        layout.setSpacing(12)
        layout.addWidget(_logo())
        layout.addWidget(_title("Create your master password"))
        layout.addWidget(_text(intro))
        layout.addSpacing(6)
        layout.addWidget(self.password)
        layout.addWidget(self.meter)
        layout.addWidget(self.confirm)
        layout.addWidget(self.understand)
        layout.addWidget(self.error)
        layout.addLayout(buttons)
        self._refresh()

    def chosen_password(self) -> str:
        return self.password.text()

    def problem(self) -> str | None:
        issue = master_password_problem(self.password.text(), self.confirm.text())
        if issue is None and not self.understand.isChecked():
            return "Please confirm that you understand the warning."
        return issue

    def _refresh(self, *_: object) -> None:
        self.meter.update_for(self.password.text())
        self.create_button.setEnabled(self.problem() is None)
        self.error.clear()

    def _on_create(self) -> None:
        issue = self.problem()
        if issue:
            self.error.setText(issue)
            return
        self.accept()


# -------------------------------------------------------------- recovery key


class RecoveryKeyDialog(QDialog):
    """Shows a recovery key once.

    * First start (replacing=False): the key is already in use, so the dialog can only be
      closed after confirming it was written down.
    * New key (replacing=True): nothing has changed yet. "Use the new key" makes it active;
      "Cancel — keep my old key" (or Esc / closing the window) leaves the old key working.
    """

    def __init__(
        self, recovery_key: str, *, replacing: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.replacing = replacing
        self.setWindowTitle("New recovery key" if replacing else "Your recovery key")
        self.setMinimumWidth(540)
        self._clipboard = SecretClipboard(clear_after_seconds=60, parent=self)

        self.key_label = QLabel(recovery_key)
        self.key_label.setObjectName("recoveryKey")
        self.key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = push_button("Copy", icon="copy", tooltip="Copied keys are cleared after 60 s")
        copy.clicked.connect(lambda: self._clipboard.copy(recovery_key, secret=True))

        self.written = QCheckBox("I have written down this recovery key and put it somewhere safe")
        self.written.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_button = push_button(
            "Use the new key" if replacing else "Continue", variant="primary"
        )
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.accept)
        self.written.toggled.connect(self.continue_button.setEnabled)
        self.cancel_button = push_button("Cancel — keep my old key")
        self.cancel_button.setVisible(replacing)
        self.cancel_button.clicked.connect(self.reject)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_label, 1)
        key_row.addWidget(copy)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.continue_button)

        if replacing:
            title = "Your new recovery key"
            intro = (
                "Nothing has changed yet: your old key keeps working until you press "
                "“Use the new key”. After that, only this new key works. The USB copy "
                "switches to it the next time you sync."
            )
            warning = "Write it down before you continue. It will not be shown again."
        else:
            title = "Write down your recovery key"
            intro = (
                "If you ever forget your master password, this key is the only way to open "
                "your vault. Write it on paper and keep it at home — not on this computer "
                "or the USB stick."
            )
            warning = "It will not be shown again."

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 22)
        layout.setSpacing(12)
        layout.addWidget(_title(title))
        layout.addWidget(_text(intro))
        layout.addSpacing(4)
        layout.addLayout(key_row)
        layout.addWidget(_text(warning, name="error"))
        layout.addSpacing(4)
        layout.addWidget(self.written)
        layout.addLayout(buttons)

    def reject(self) -> None:
        # A first-start key is already the only key: closing is allowed once written down.
        if self.replacing or self.written.isChecked():
            super().reject()

    def done(self, result: int) -> None:
        self._clipboard.flush()  # a copied recovery key must not stay on the clipboard
        super().done(result)


# ---------------------------------------------------------------- unlock

PASSWORD_PAGE, KEY_PAGE, NEW_PASSWORD_PAGE = 0, 1, 2


class UnlockDialog(QDialog):
    """Lock screen.

    Page 0: master password.  "Forgot password?" →
    Page 1: recovery key → "Check key" (nothing else is asked until the key is right) →
    Page 2: choose a new master password → the vault opens.
    """

    def __init__(
        self,
        unlock: UnlockFn,
        check_key: CheckKeyFn,
        set_password: SetPasswordFn,
        *,
        discard: DiscardFn | None = None,
        location: str = "",
        portable: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(460)
        self._unlock = unlock
        self._check_key = check_key
        self._set_password = set_password
        self._discard = discard
        self.vault: Any = None
        self.recovered: Any = None  # opened by the recovery key, waiting for a new password
        self.failures = 0  # wrong passwords / recovery keys in a row
        self.wait_left = 0
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(1000)
        self._wait_timer.timeout.connect(self._tick)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_password_page())
        self.pages.addWidget(self._build_key_page())
        self.pages.addWidget(self._build_new_password_page())

        where = _text(
            f"{'USB vault' if portable else 'Vault'}: {location}" if location else "",
            name="hint",
        )
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 18)
        layout.setSpacing(10)
        layout.addWidget(_logo())
        layout.addWidget(_title(APP_NAME))
        layout.addWidget(self.pages)
        layout.addWidget(where)
        self.show_page(PASSWORD_PAGE)

    # --- pages

    def _build_password_page(self) -> QWidget:
        page = QWidget()
        self.password = PasswordField("Master password")
        self.password.returnPressed.connect(self.try_unlock)
        _clear_mark_on_edit(self.password)
        self.error = Banner()
        self.unlock_button = push_button("Unlock", variant="primary")
        self.unlock_button.clicked.connect(self.try_unlock)
        forgot = push_button("Forgot password?", variant="ghost")
        forgot.clicked.connect(lambda: self.show_page(KEY_PAGE))

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(_text("Enter your master password to open your vault."))
        layout.addWidget(self.password)
        layout.addWidget(self.error)
        layout.addWidget(self.unlock_button)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(forgot)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_key_page(self) -> QWidget:
        page = QWidget()
        self.recovery_key = QLineEdit()
        self.recovery_key.setObjectName("bigInput")
        self.recovery_key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX")
        self.recovery_key.returnPressed.connect(self.try_check_key)
        _clear_mark_on_edit(self.recovery_key)
        self.recovery_error = Banner()
        self.check_button = push_button("Check key", variant="primary")
        self.check_button.clicked.connect(self.try_check_key)
        back = push_button("Back", variant="ghost")
        back.clicked.connect(lambda: self.show_page(PASSWORD_PAGE))

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            _text(
                "Forgot your master password? Type the recovery key you wrote down. "
                "If it is right, you can choose a new master password."
            )
        )
        layout.addWidget(self.recovery_key)
        layout.addWidget(self.recovery_error)
        buttons = QHBoxLayout()
        buttons.addWidget(back)
        buttons.addStretch(1)
        buttons.addWidget(self.check_button)
        layout.addLayout(buttons)
        return page

    def _build_new_password_page(self) -> QWidget:
        page = QWidget()
        self.key_ok = Banner("ok")
        self.key_ok.setText("Recovery key accepted. Now choose a new master password.")
        self.new_password = PasswordField("New master password")
        self.new_confirm = PasswordField("Repeat new master password")
        _clear_mark_on_edit(self.new_password, self.new_confirm)
        self.new_meter = StrengthMeter()
        self.new_password.textChanged.connect(self.new_meter.update_for)
        self.new_confirm.returnPressed.connect(self.try_set_password)
        self.new_error = Banner()
        self.set_button = push_button("Save password and open", variant="primary")
        self.set_button.clicked.connect(self.try_set_password)
        cancel = push_button("Cancel", variant="ghost")
        cancel.clicked.connect(self._cancel_recovery)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.key_ok)
        layout.addWidget(self.new_password)
        layout.addWidget(self.new_meter)
        layout.addWidget(self.new_confirm)
        layout.addWidget(self.new_error)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.set_button)
        layout.addLayout(buttons)
        return page

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.unlock_button.setDefault(index == PASSWORD_PAGE)
        self.check_button.setDefault(index == KEY_PAGE)
        self.set_button.setDefault(index == NEW_PASSWORD_PAGE)
        focus = {PASSWORD_PAGE: self.password, KEY_PAGE: self.recovery_key}
        focus.get(index, self.new_password).setFocus()

    # --- actions

    def try_unlock(self) -> None:
        if self.wait_left:
            return
        password = self.password.text()
        if not password:
            self._fail(self.error, self.password, "Enter your master password.", count=False)
            return
        self.vault = self._run(lambda: self._unlock(password), self.error, self.password)
        if self.vault is not None:
            self.accept()

    def try_check_key(self) -> None:
        """Step 1 of recovery: is this the right recovery key? Nothing else is asked yet."""
        if self.wait_left:
            return
        key = self.recovery_key.text()
        problem = recovery_key_problem(key)
        if problem:  # a typo in the format: not counted as a wrong attempt
            self._fail(self.recovery_error, self.recovery_key, problem, count=False)
            return
        vault = self._run(lambda: self._check_key(key), self.recovery_error, self.recovery_key)
        if vault is None:
            return
        self.recovered = vault
        self.new_password.clear()
        self.new_confirm.clear()
        self.new_error.clear()
        self.show_page(NEW_PASSWORD_PAGE)

    def try_set_password(self) -> None:
        """Step 2 of recovery: save the new master password and open the vault."""
        if self.recovered is None:
            self.show_page(KEY_PAGE)
            return
        problem = master_password_problem(self.new_password.text(), self.new_confirm.text())
        if problem:
            _show_new_password_problem(problem, self.new_error, self.new_password, self.new_confirm)
            return
        vault, new_password = self.recovered, self.new_password.text()
        self.vault = self._run(
            lambda: self._set_password(vault, new_password), self.new_error, None, count=False
        )
        if self.vault is not None:
            self.recovered = None
            self.accept()

    def reject(self) -> None:
        self._forget_recovered()
        super().reject()

    def _cancel_recovery(self) -> None:
        self._forget_recovered()
        self.recovery_key.clear()
        self.show_page(PASSWORD_PAGE)

    def _forget_recovered(self) -> None:
        if self.recovered is not None and self._discard is not None:
            self._discard(self.recovered)
        self.recovered = None

    # --- wrong attempts

    def _run(
        self,
        action: Callable[[], Any],
        banner: Banner,
        field: QLineEdit | None,
        *,
        count: bool = True,
    ) -> Any:
        banner.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = action()
        except WrongPasswordError as exc:
            message = (
                "Wrong recovery key — it does not belong to this vault."
                if getattr(exc, "what", "") == "recovery key"
                else "Wrong password — the vault did not open."
            )
            self._fail(banner, field, message, count=count)
        except VaultCryptoError as exc:
            message = f"{exc} A backup copy may exist next to the vault (.bak)."
            self._fail(banner, None, message, count=False)
        except OSError as exc:
            message = f"The vault file could not be read: {exc.strerror or exc}"
            self._fail(banner, None, message, count=False)
        else:
            self.failures = 0
            return result
        finally:
            QApplication.restoreOverrideCursor()
        return None

    def _fail(self, banner: Banner, field: QLineEdit | None, message: str, *, count: bool) -> None:
        if count:
            self.failures += 1
            message += f" (attempt {self.failures})"
            if self.failures >= 2:
                message += "\nCheck Caps Lock and your keyboard layout."
            wait = wait_seconds(self.failures)
            if wait:
                message += f"\nToo many wrong attempts: wait {wait} seconds before trying again."
                self._start_wait(wait)
        banner.setText(message)
        if field is not None:
            mark_invalid(field)
            field.setFocus()
            field.selectAll()
        shake(banner)

    def _start_wait(self, seconds: int) -> None:
        self.wait_left = seconds
        self._wait_timer.start()
        self._show_wait()

    def _tick(self) -> None:
        self.wait_left = max(0, self.wait_left - 1)
        if not self.wait_left:
            self._wait_timer.stop()
        self._show_wait()

    def _show_wait(self) -> None:
        waiting = self.wait_left > 0
        for button, text in ((self.unlock_button, "Unlock"), (self.check_button, "Check key")):
            button.setEnabled(not waiting)
            button.setText(f"Wait {self.wait_left} s…" if waiting else text)


# ------------------------------------------------------------ change password


class ChangePasswordDialog(QDialog):
    """Current password + new password (twice). `verify` checks the current one."""

    def __init__(self, verify: Callable[[str], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change master password")
        self.setMinimumWidth(440)
        self._verify = verify

        self.current = PasswordField("Current master password")
        self.new_password = PasswordField("New master password")
        self.new_confirm = PasswordField("Repeat new master password")
        _clear_mark_on_edit(self.current, self.new_password, self.new_confirm)
        self.meter = StrengthMeter()
        self.new_password.textChanged.connect(self.meter.update_for)
        self.error = Banner()
        save = push_button("Change password", variant="primary")
        save.setDefault(True)
        save.clicked.connect(self.try_save)
        cancel = push_button("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 18)
        layout.setSpacing(10)
        layout.addWidget(_title("Change master password"))
        layout.addWidget(
            _text(
                "Your recovery key keeps working. The USB copy switches to the new password "
                "the next time you sync."
            )
        )
        layout.addWidget(self.current)
        layout.addWidget(self.new_password)
        layout.addWidget(self.meter)
        layout.addWidget(self.new_confirm)
        layout.addWidget(self.error)
        layout.addLayout(buttons)

    def chosen_password(self) -> str:
        return self.new_password.text()

    def try_save(self) -> None:
        self.error.clear()
        problem = master_password_problem(self.new_password.text(), self.new_confirm.text())
        if problem:
            _show_new_password_problem(problem, self.error, self.new_password, self.new_confirm)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = self._verify(self.current.text())
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.error.setText("The current password is wrong.")
            mark_invalid(self.current)
            self.current.setFocus()
            self.current.selectAll()
            shake(self.error)
            return
        self.accept()


# ------------------------------------------------------------ other copy's password


class CopyPasswordDialog(QDialog):
    """Sync: the other copy's master password was changed there, so it is asked for once."""

    def __init__(
        self,
        location: str,
        other_name: str,
        error: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sync")
        self.setMinimumWidth(460)
        self.password = PasswordField(f"Master password of the {other_name} copy")
        self.password.returnPressed.connect(self._on_ok)
        self.error = Banner()
        self.error.setText(error)
        if error:
            mark_invalid(self.password)
        _clear_mark_on_edit(self.password)
        ok = push_button("Continue", variant="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        cancel = push_button("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 18)
        layout.setSpacing(10)
        layout.addWidget(_title("Password of the other copy"))
        layout.addWidget(
            _text(
                f"The master password of the {other_name} copy was changed there, so MySafe "
                "can't open it with your current one. Enter the password it opens with:"
            )
        )
        where = _text(location)
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(where)
        layout.addWidget(self.password)
        layout.addWidget(self.error)
        layout.addLayout(buttons)
        self.password.setFocus()

    def chosen_password(self) -> str:
        return self.password.text()

    def _on_ok(self) -> None:
        if not self.password.text():
            self.error.setText("Enter the password.")
            mark_invalid(self.password)
            return
        self.accept()
