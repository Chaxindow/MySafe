"""Naming guide: an optional convention that makes entries quick to find with search."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from mysafe.ui.palette import current
from mysafe.ui.widgets import push_button

FORMULA = "Service – Account"

# (title, why) examples shown in the guide
TITLE_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("Steam", "Only one account: the service name is enough."),
    ("Gmail – Personal", "Two accounts on the same service? Add which one."),
    ("Gmail – Work", ""),
    ("Instagram – @mete", "Social accounts: the handle tells them apart."),
    ("Netflix – Family", "Shared accounts: say who uses it."),
)

FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("Email", "the address you sign in with"),
    ("Username", "only if the site uses one besides email"),
    ("Password", ""),
    ("Recovery code", "add the service if it has several: “Steam Guard recovery code”"),
    ("Security question", "write the question as the label: “Favorite color?”"),
)

TIPS: tuple[str, ...] = (
    "Start the title with the service name, exactly as the service writes it "
    "(“PlayStation”, not “PS”). Search matches titles, so the name is what you will type.",
    "Use the same separator every time: a space, an en dash and a space ( – ).",
    "Fill in the Website. Search also matches the web address, so “epicgames” finds "
    "Epic Games even if you named it differently.",
    "Several email accounts? One per service needs no suffix (“Gmail”, “Outlook”). Several on "
    "the same service: name them by use (“Gmail – Personal”, “Gmail – Work”, “Gmail – Games”) "
    "or by the start of the address (“Gmail – mete.k”).",
    "Keep categories broad (Games, Streaming, Email…). The title does the detailed work.",
)


def guide_html() -> str:
    t = current()
    rows = "".join(
        f"<tr><td style='padding:4px 18px 4px 0'><b>{title}</b></td>"
        f"<td style='padding:4px 0; color:{t.muted}'>{why}</td></tr>"
        for title, why in TITLE_EXAMPLES
    )
    labels = "".join(
        f"<tr><td style='padding:3px 18px 3px 0'><b>{label}</b></td>"
        f"<td style='padding:3px 0; color:{t.muted}'>{note}</td></tr>"
        for label, note in FIELD_LABELS
    )
    tips = "".join(f"<li style='margin-bottom:6px'>{tip}</li>" for tip in TIPS)
    return f"""
<p style='color:{t.muted}'>A suggestion, not a rule. Entries named the same way are
faster to find when you search.</p>

<h3 style='margin-bottom:4px'>Entry title</h3>
<p style='font-size:15pt; margin:8px 0 10px 0'>
  <span style='color:{t.accent}; font-weight:600'>Service</span>
  <span style='color:{t.muted}'> – </span>
  <span style='color:{t.accent}; font-weight:600'>Account</span>
  <span style='color:{t.muted}; font-size:10pt'>&nbsp;&nbsp;(second part only if needed)</span>
</p>
<table cellspacing='0'>{rows}</table>

<h3 style='margin-bottom:4px'>Field labels</h3>
<table cellspacing='0'>{labels}</table>

<h3 style='margin-bottom:4px'>Tips</h3>
<ul style='margin-left:-20px'>{tips}</ul>
"""


class NamingGuideDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Naming guide")
        self.resize(620, 640)

        self.body = QLabel(guide_html())
        self.body.setObjectName("guideBody")
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setContentsMargins(22, 14, 22, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.body)

        close = push_button("Got it", variant="primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(20, 0, 20, 16)
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
