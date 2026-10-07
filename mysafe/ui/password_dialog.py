"""Password generator dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mysafe.services.password_generator import (
    DEFAULT_LENGTH,
    MAX_LENGTH,
    MIN_LENGTH,
    PasswordOptions,
    generate_password,
)
from mysafe.ui.clipboard import SecretClipboard
from mysafe.ui.widgets import icon_button, push_button


class PasswordGeneratorDialog(QDialog):
    """Generates passwords. With `use_button=True` it returns one via `password()`."""

    def __init__(
        self,
        clipboard: SecretClipboard | None = None,
        *,
        use_button: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Password generator")
        self.setMinimumWidth(460)
        self._clipboard = clipboard

        self.output = QLineEdit()
        self.output.setObjectName("passwordOutput")
        self.output.setReadOnly(True)
        regenerate = icon_button("refresh", "Generate another password", size=34)
        regenerate.clicked.connect(self.regenerate)
        self.copy_button = icon_button("copy", "Copy password", size=34)
        self.copy_button.clicked.connect(self._copy)
        self.copy_button.setVisible(clipboard is not None)
        top = QHBoxLayout()
        top.addWidget(self.output, 1)
        top.addWidget(regenerate)
        top.addWidget(self.copy_button)

        self.length = QSpinBox()
        self.length.setRange(MIN_LENGTH, MAX_LENGTH)
        self.length.setValue(DEFAULT_LENGTH)
        self.lowercase = QCheckBox("Lowercase (a-z)")
        self.uppercase = QCheckBox("Uppercase (A-Z)")
        self.digits = QCheckBox("Digits (0-9)")
        self.symbols = QCheckBox("Symbols (!@#…)")
        self.avoid_ambiguous = QCheckBox("Avoid look-alike characters (I l 1 O 0 o)")
        for box in (self.lowercase, self.uppercase, self.digits, self.symbols):
            box.setChecked(True)
        for widget in (
            self.lowercase,
            self.uppercase,
            self.digits,
            self.symbols,
            self.avoid_ambiguous,
        ):
            widget.toggled.connect(lambda _checked: self.regenerate())
        self.length.valueChanged.connect(lambda _value: self.regenerate())

        options = QFormLayout()
        options.addRow("Length:", self.length)
        options.addRow("", self.lowercase)
        options.addRow("", self.uppercase)
        options.addRow("", self.digits)
        options.addRow("", self.symbols)
        options.addRow("", self.avoid_ambiguous)

        self.error = QLabel()
        self.error.setObjectName("error")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._ok_button: QPushButton | None = None
        if use_button:
            cancel = push_button("Cancel")
            cancel.clicked.connect(self.reject)
            self._ok_button = push_button("Use this password", variant="primary")
            self._ok_button.setDefault(True)
            self._ok_button.clicked.connect(self.accept)
            buttons.addWidget(cancel)
            buttons.addWidget(self._ok_button)
        else:
            close = push_button("Close")
            close.clicked.connect(self.reject)
            buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addLayout(options)
        layout.addWidget(self.error)
        layout.addLayout(buttons)

        self.regenerate()

    def options(self) -> PasswordOptions:
        return PasswordOptions(
            length=self.length.value(),
            lowercase=self.lowercase.isChecked(),
            uppercase=self.uppercase.isChecked(),
            digits=self.digits.isChecked(),
            symbols=self.symbols.isChecked(),
            avoid_ambiguous=self.avoid_ambiguous.isChecked(),
        )

    def regenerate(self) -> None:
        try:
            self.output.setText(generate_password(self.options()))
            self.error.clear()
            ok = True
        except ValueError as exc:
            self.output.clear()
            self.error.setText(str(exc))
            ok = False
        self.copy_button.setEnabled(ok)
        if self._ok_button is not None:
            self._ok_button.setEnabled(ok)

    def password(self) -> str:
        return self.output.text()

    def _copy(self) -> None:
        if self._clipboard is not None and self.output.text():
            self._clipboard.copy(self.output.text(), secret=True)
            self.copy_button.setToolTip("Copied")
