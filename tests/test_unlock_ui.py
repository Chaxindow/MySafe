"""Setup, recovery-key and lock screens (no real files, no modal exec)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from mysafe.services.crypto import (  # noqa: E402
    CorruptVaultError,
    WrongPasswordError,
    normalize_recovery_key,
)
from mysafe.ui.unlock import (  # noqa: E402
    KEY_PAGE,
    NEW_PASSWORD_PAGE,
    PASSWORD_PAGE,
    ChangePasswordDialog,
    RecoveryKeyDialog,
    SetupDialog,
    UnlockDialog,
    master_password_problem,
    wait_seconds,
)

GOOD_KEY = "ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ23-4567"
OTHER_KEY = "ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX-YZ23-4567"


def _never(*_args: object) -> object:
    raise AssertionError("should not be called")


def test_master_password_rules() -> None:
    assert master_password_problem("short", "short")
    assert (
        master_password_problem("Correct-horse-1", "different") == "The two passwords don't match."
    )
    assert master_password_problem("Correct-horse-1", "Correct-horse-1") is None


def test_setup_needs_valid_password_and_confirmation(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SetupDialog(importing_old_data=True)
    qtbot.addWidget(dialog)
    assert not dialog.create_button.isEnabled()
    dialog.password.setText("Correct-horse-1")
    dialog.confirm.setText("Correct-horse-1")
    assert not dialog.create_button.isEnabled()  # warning not confirmed yet
    dialog.understand.setChecked(True)
    assert dialog.create_button.isEnabled()
    assert dialog.meter.label.text() in ("Good.", "Strong.")
    dialog.create_button.click()
    assert dialog.result() == SetupDialog.DialogCode.Accepted
    assert dialog.chosen_password() == "Correct-horse-1"


def test_recovery_key_dialog_cannot_be_skipped(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = RecoveryKeyDialog("ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ23-4567")
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.key_label.text().startswith("ABCD-")
    assert not dialog.continue_button.isEnabled()
    dialog.reject()  # Esc / close is ignored
    assert dialog.isVisible()
    dialog.written.setChecked(True)
    dialog.continue_button.click()
    assert dialog.result() == RecoveryKeyDialog.DialogCode.Accepted


def test_new_key_dialog_can_be_cancelled(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = RecoveryKeyDialog(GOOD_KEY, replacing=True)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.cancel_button.isVisible()
    assert dialog.continue_button.text() == "Use the new key"
    assert not dialog.continue_button.isEnabled()
    dialog.cancel_button.click()  # clicked by mistake -> nothing changes
    assert dialog.result() == RecoveryKeyDialog.DialogCode.Rejected
    assert not dialog.isVisible()


def test_first_recovery_key_has_no_cancel(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = RecoveryKeyDialog(GOOD_KEY)
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.cancel_button.isVisible()


def test_unlock_wrong_then_right(qtbot) -> None:  # type: ignore[no-untyped-def]
    attempts: list[str] = []

    def unlock(password: str) -> object:
        attempts.append(password)
        if password != "right":
            raise WrongPasswordError()
        return "VAULT"

    dialog = UnlockDialog(unlock, _never, _never, location="E:/MySafe-data/vault.mysafe")
    qtbot.addWidget(dialog)
    dialog.password.setText("wrong")
    dialog.try_unlock()
    assert dialog.error.text().startswith("Wrong password")
    assert "(attempt 1)" in dialog.error.text()
    assert not dialog.error.isHidden()
    assert dialog.password.property("invalid") is True
    assert dialog.vault is None
    dialog.try_unlock()
    assert "(attempt 2)" in dialog.error.text() and "Caps Lock" in dialog.error.text()
    dialog.password.textEdited.emit("r")  # typing clears the red field
    assert dialog.password.property("invalid") is False
    dialog.password.setText("right")
    dialog.unlock_button.click()
    assert dialog.vault == "VAULT"
    assert dialog.failures == 0
    assert attempts == ["wrong", "wrong", "right"]


def test_empty_password_is_not_an_attempt(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = UnlockDialog(_never, _never, _never)
    qtbot.addWidget(dialog)
    dialog.try_unlock()
    assert dialog.error.text() == "Enter your master password."
    assert dialog.failures == 0


def test_many_wrong_attempts_wait(qtbot) -> None:  # type: ignore[no-untyped-def]
    def unlock(_password: str) -> object:
        raise WrongPasswordError()

    assert [wait_seconds(n) for n in (1, 4, 5, 6, 20)] == [0, 0, 5, 10, 30]
    dialog = UnlockDialog(unlock, _never, _never)
    qtbot.addWidget(dialog)
    dialog.password.setText("guess")
    for _ in range(5):
        dialog.try_unlock()
    assert "wait 5 seconds" in dialog.error.text()
    assert not dialog.unlock_button.isEnabled()
    assert dialog.unlock_button.text() == "Wait 5 s…"
    dialog.try_unlock()  # ignored while waiting
    assert dialog.failures == 5
    for _ in range(5):
        dialog._tick()
    assert dialog.unlock_button.isEnabled() and dialog.unlock_button.text() == "Unlock"


def test_damaged_vault_mentions_backup(qtbot) -> None:  # type: ignore[no-untyped-def]
    def unlock(_password: str) -> object:
        raise CorruptVaultError("The vault file is damaged or was modified.")

    dialog = UnlockDialog(unlock, _never, _never)
    qtbot.addWidget(dialog)
    dialog.password.setText("x")
    dialog.try_unlock()
    assert ".bak" in dialog.error.text()
    assert dialog.failures == 0


def test_recovery_checks_the_key_first(qtbot) -> None:  # type: ignore[no-untyped-def]
    checked: list[str] = []
    saved: list[tuple[object, str]] = []
    discarded: list[object] = []

    def check_key(key: str) -> object:
        checked.append(key)
        if normalize_recovery_key(key) != normalize_recovery_key(GOOD_KEY):
            raise WrongPasswordError("recovery key")
        return "OPENED"

    def set_password(vault: object, new_password: str) -> object:
        saved.append((vault, new_password))
        return "VAULT"

    dialog = UnlockDialog(_never, check_key, set_password, discard=discarded.append)
    qtbot.addWidget(dialog)
    dialog.show_page(KEY_PAGE)

    # Not a recovery key at all: explained, not counted, nothing checked.
    dialog.recovery_key.setText("ABCD-EFGH")
    dialog.try_check_key()
    assert "32 characters" in dialog.recovery_error.text() and "you typed 8" in (
        dialog.recovery_error.text()
    )
    assert dialog.recovery_key.property("invalid") is True
    assert checked == [] and dialog.failures == 0

    # A well-formed but wrong key: a clear error, still on the key page.
    dialog.recovery_key.setText(OTHER_KEY)
    dialog.try_check_key()
    assert dialog.recovery_error.text().startswith("Wrong recovery key")
    assert "(attempt 1)" in dialog.recovery_error.text()
    assert dialog.pages.currentIndex() == KEY_PAGE

    # The right key (any case, spaces instead of dashes): on to the new password.
    dialog.recovery_key.setText(GOOD_KEY.lower().replace("-", " "))
    dialog.check_button.click()
    assert dialog.pages.currentIndex() == NEW_PASSWORD_PAGE
    assert dialog.recovered == "OPENED" and saved == []

    dialog.new_password.setText("New-password-9")
    dialog.new_confirm.setText("typo")
    dialog.try_set_password()
    assert "match" in dialog.new_error.text() and saved == []
    assert dialog.new_confirm.property("invalid") is True

    dialog.new_confirm.setText("New-password-9")
    dialog.set_button.click()
    assert saved == [("OPENED", "New-password-9")]
    assert dialog.vault == "VAULT"
    assert discarded == []


def test_cancel_after_key_closes_vault(qtbot) -> None:  # type: ignore[no-untyped-def]
    discarded: list[object] = []
    dialog = UnlockDialog(_never, lambda _k: "OPENED", _never, discard=discarded.append)
    qtbot.addWidget(dialog)
    dialog.show_page(KEY_PAGE)
    dialog.recovery_key.setText(GOOD_KEY)
    dialog.try_check_key()
    assert dialog.pages.currentIndex() == NEW_PASSWORD_PAGE
    dialog._cancel_recovery()
    assert discarded == ["OPENED"]
    assert dialog.pages.currentIndex() == PASSWORD_PAGE

    dialog.show_page(KEY_PAGE)
    dialog.recovery_key.setText(GOOD_KEY)
    dialog.try_check_key()
    dialog.reject()  # closing the window
    assert discarded == ["OPENED", "OPENED"]


def test_change_password_wrong_current(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ChangePasswordDialog(lambda _p: False)
    qtbot.addWidget(dialog)
    dialog.current.setText("nope")
    dialog.new_password.setText("New-password-9")
    dialog.new_confirm.setText("New-password-9")
    dialog.try_save()
    assert dialog.error.text() == "The current password is wrong."
    assert dialog.current.property("invalid") is True
