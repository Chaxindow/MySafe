"""Applies the light / dark / system theme: palette, stylesheet and icon colors."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from mysafe.ui.icons import refresh_bound_icons, svg_markup
from mysafe.ui.palette import DARK, LIGHT, Tokens, set_current

_SCHEMES = {
    "system": Qt.ColorScheme.Unknown,  # follow the operating system
    "light": Qt.ColorScheme.Light,
    "dark": Qt.ColorScheme.Dark,
}

MONO_FONTS = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo", monospace'

_system_hook_installed = False
_selected_theme = "system"


def resolve(app: QApplication, theme: str) -> Tokens:
    if theme == "light":
        return LIGHT
    if theme == "dark":
        return DARK
    return DARK if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT


def build_palette(t: Tokens) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.detail,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.input,
        QPalette.ColorRole.AlternateBase: t.hover,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.PlaceholderText: t.muted,
        QPalette.ColorRole.Button: t.surface,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.accent_text,
        QPalette.ColorRole.ToolTipBase: t.surface,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Midlight: t.hover,
        QPalette.ColorRole.Dark: t.pressed,
        QPalette.ColorRole.Light: t.surface,
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted))
    return p


def _arrow_files(t: Tokens) -> dict[str, str]:
    """Write small chevron SVGs for combo/spin boxes; QSS needs them as files."""
    folder = Path(tempfile.gettempdir()) / "mysafe-ui"
    folder.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for name in ("chevron-down", "chevron-up"):
        path = folder / f"{name}-{t.muted.lstrip('#')}.svg"
        if not path.exists():
            path.write_text(svg_markup(name, t.muted, stroke=2.5), encoding="utf-8")
        paths[name] = path.as_posix()
    return paths


def build_stylesheet(t: Tokens) -> str:
    arrows = _arrow_files(t)
    down, up = arrows["chevron-down"], arrows["chevron-up"]
    return f"""
* {{ font-size: 10pt; }}
QWidget {{ color: {t.text}; }}
QMainWindow, QDialog {{ background: {t.detail}; }}

/* ---- three panes, each with its own surface ---- */
#sidebar {{ background: {t.sidebar}; }}
#listPane {{ background: {t.list}; }}
#detailPane, #detailPage {{ background: {t.detail}; }}
QSplitter::handle {{ background: {t.border}; }}
QScrollArea {{ background: transparent; border: none; }}

#brand {{ font-size: 13pt; font-weight: 600; color: {t.text}; }}
#paneTitle {{ color: {t.muted}; font-size: 9pt; font-weight: 600; }}

QListView {{ background: transparent; border: none; outline: 0; }}

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background: {t.input}; border: 1px solid {t.border}; border-radius: 6px;
    padding: 6px 8px; selection-background-color: {t.accent};
    selection-color: {t.accent_text};
}}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover {{
    border-color: {t.muted};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {t.accent};
}}
#searchBox {{ padding: 7px 8px; }}
#clearButton {{
    background: {t.hover}; border: 1px solid {t.border}; border-radius: 12px; padding: 3px;
}}
#clearButton:hover {{ background: {t.accent_tint}; border-color: {t.accent}; }}
#clearButton:pressed {{ background: {t.pressed}; }}
#screenTitle {{ font-size: 16pt; font-weight: 600; }}
#bigInput {{ padding: 9px 10px; font-size: 11pt; }}
#recoveryKey {{
    font-family: {MONO_FONTS}; font-size: 14pt; letter-spacing: 1px; color: {t.accent};
    background: {t.surface}; border: 1px dashed {t.accent}; border-radius: 8px; padding: 14px;
}}
#strengthBar {{ background: {t.border}; border: none; border-radius: 3px; }}
#strengthBar::chunk {{ border-radius: 3px; background: {t.danger}; }}
#strengthBar[level="2"]::chunk {{ background: {t.accent}; }}
#strengthBar[level="3"]::chunk, #strengthBar[level="4"]::chunk {{ background: #3FB27F; }}
#syncRow {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 7px; }}
#syncCard {{ background: {t.surface}; border: 1px solid {t.accent}; border-radius: 8px; }}
#syncTitle {{ font-weight: 600; }}
#syncNote {{
    background: {t.accent_tint}; border: 1px solid {t.accent}; border-radius: 7px;
    padding: 8px 12px;
}}
#syncChip {{ border-radius: 5px; font-weight: 700; }}
#syncChip[kind="add"] {{ background: {t.success_tint}; color: {t.success}; }}
#syncChip[kind="change"] {{ background: {t.accent_tint}; color: {t.accent}; }}
#syncChip[kind="delete"] {{ background: {t.danger_tint}; color: {t.danger}; }}
#syncHead {{
    color: {t.muted}; font-size: 9pt; padding: 6px 12px; border-top: 1px solid {t.border};
}}
#syncHead[newer="true"] {{ color: {t.accent}; font-weight: 600; }}
#syncLabel {{ color: {t.muted}; padding: 6px 12px; border-top: 1px solid {t.border}; }}
#syncCell {{ padding: 6px 12px; border-top: 1px solid {t.border}; }}
#syncCell[state="keep"] {{ background: {t.success_tint}; color: {t.success}; }}
#syncCell[state="drop"] {{ background: {t.danger_tint}; color: {t.danger}; }}
QRadioButton {{ spacing: 8px; }}
QMessageBox QLabel#qt_msgbox_label {{ min-width: 340px; font-size: 11pt; font-weight: 600; }}
QMessageBox QLabel#qt_msgbox_informativelabel {{ min-width: 340px; color: {t.muted}; }}
QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 28px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 24px; border: none; background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t.hover}; }}
QSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {t.detail}; border: 1px solid {t.border};
    selection-background-color: {t.hover}; selection-color: {t.text};
}}

/* ---- buttons ---- */
QPushButton {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {t.hover}; border-color: {t.muted}; }}
QPushButton:pressed {{ background: {t.pressed}; }}
QPushButton:disabled {{ color: {t.muted}; background: transparent; }}
QPushButton:focus {{ border-color: {t.accent}; }}

QPushButton[variant="primary"] {{
    background: {t.accent}; color: {t.accent_text}; border: 1px solid {t.accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background: {t.accent_hover}; border-color: {t.accent_hover};
}}
QPushButton[variant="primary"]:pressed {{ background: {t.accent}; }}
QPushButton[variant="primary"]:disabled {{
    background: {t.surface}; color: {t.muted}; border-color: {t.border}; font-weight: 600;
}}

QPushButton[variant="danger"] {{
    background: transparent; color: {t.danger}; border: 1px solid {t.border};
}}
QPushButton[variant="danger"]:hover {{
    background: {t.danger_tint}; border-color: {t.danger};
}}

QPushButton[variant="ghost"] {{
    background: transparent; border: 1px solid transparent; color: {t.muted};
    text-align: left; padding: 7px 10px;
}}
QPushButton[variant="ghost"]:hover {{ background: {t.hover}; color: {t.text}; }}

/* icon-only buttons */
QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px;
}}
QToolButton:hover {{ background: {t.pressed}; border-color: {t.muted}; }}
QToolButton:pressed {{ background: {t.pressed}; }}
QToolButton:checked {{ background: {t.accent_tint}; border-color: {t.accent}; }}
QToolButton:disabled {{ background: transparent; border-color: transparent; }}
QToolButton:focus {{ border-color: {t.accent}; }}

/* ---- entry details ---- */
#entryTitle {{ font-size: 18pt; font-weight: 600; }}
#categoryChip {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px;
    padding: 2px 10px; color: {t.muted}; font-size: 9pt;
}}
#fieldGroup {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px;
}}
#fieldRow {{ background: transparent; border: none; border-top: 1px solid {t.border}; }}
#fieldRow[first="true"] {{ border-top: none; }}
#fieldRow:hover {{ background: {t.hover}; }}
#fieldRow[first="true"]:hover {{ border-top-left-radius: 8px; border-top-right-radius: 8px; }}
#fieldRow[last="true"]:hover {{
    border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;
}}
#fieldLabel {{ color: {t.muted}; font-size: 9pt; }}
#fieldValue {{ font-size: 11pt; }}
#secretValue {{ font-size: 11pt; font-family: {MONO_FONTS}; letter-spacing: 1px; }}
#sectionTitle {{ color: {t.muted}; font-size: 9pt; font-weight: 600; }}
#notes {{ font-size: 10pt; }}
#placeholder {{ color: {t.muted}; font-size: 11pt; }}
#hint {{ color: {t.muted}; font-size: 9pt; }}
#error {{ color: {t.danger}; }}
/* Wrong password / invalid input: impossible to miss. */
#errorBanner {{
    background: {t.danger_tint}; border: 1px solid {t.danger}; border-left: 4px solid {t.danger};
    border-radius: 7px;
}}
#errorBanner QLabel {{ color: {t.danger}; font-weight: 600; background: transparent; }}
#okBanner {{
    background: {t.success_tint}; border: 1px solid {t.success}; border-left: 4px solid {t.success};
    border-radius: 7px;
}}
#okBanner QLabel {{ color: {t.success}; font-weight: 600; background: transparent; }}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:hover, QLineEdit[invalid="true"]:focus {{
    border: 2px solid {t.danger}; background: {t.danger_tint};
}}
#passwordOutput {{ font-family: {MONO_FONTS}; font-size: 12pt; }}

QGroupBox {{
    border: 1px solid {t.border}; border-radius: 8px; margin-top: 14px; padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {t.muted};
}}
#editorFieldRow {{ background: transparent; }}

/* ---- chrome ---- */
QMenuBar {{ background: {t.sidebar}; border-bottom: 1px solid {t.border}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {t.hover}; border-radius: 4px; }}
QMenu {{ background: {t.detail}; border: 1px solid {t.border}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t.hover}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
QStatusBar {{ background: {t.sidebar}; color: {t.muted}; border-top: 1px solid {t.border}; }}
QToolTip {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 3px; min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QCheckBox {{ spacing: 8px; }}
"""


def apply_theme(app: QApplication, theme: str) -> Tokens:
    """Apply `theme` ("system", "light" or "dark") to the whole app. Returns the tokens used."""
    global _system_hook_installed, _selected_theme
    _selected_theme = theme
    app.setStyle("Fusion")  # same look on Windows and Linux; fully stylable
    app.styleHints().setColorScheme(_SCHEMES.get(theme, Qt.ColorScheme.Unknown))
    tokens = resolve(app, theme)
    set_current(tokens)
    app.setPalette(build_palette(tokens))
    app.setStyleSheet(build_stylesheet(tokens))
    refresh_bound_icons()

    if not _system_hook_installed:
        # Follow the OS when the user switches Windows/Linux between light and dark.
        def on_system_change(_scheme: Qt.ColorScheme) -> None:
            if _selected_theme == "system":
                apply_theme(app, "system")

        app.styleHints().colorSchemeChanged.connect(on_system_change)
        _system_hook_installed = True
    return tokens
