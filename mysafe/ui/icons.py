"""Small line icons drawn from inline SVG, tinted with the current theme colors."""

from __future__ import annotations

import weakref
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton

from mysafe.ui.palette import color

# 24x24 stroke icons (simple geometric shapes).
_PATHS: dict[str, str] = {
    "alert": '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0'
    '-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/>'
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>'
    '<circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 6.1A10 10 0 0 1 12 6c6.5 0 10 6 10 6'
    'a17 17 0 0 1-3 3.6"/><path d="M6.6 6.6C3.9 8.3 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 '
    '5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "external": '<path d="M14 3h7v7"/><path d="M10 14L21 3"/>'
    '<path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>',
    "star": '<path d="M12 2l3.1 6.3 6.9 1-5 4.8 1.2 6.9-6.2-3.2-6.2 3.2 1.2-6.9-5-4.8 6.9-1z"/>',
    "pencil": '<path d="M17 3a2.8 2.8 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
    '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/>',
    "arrow-up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "arrow-down": '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    "x": '<path d="M18 6L6 18M6 6l12 12"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M18 15l-6-6-6 6"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="M21 2l-9.6 9.6"/>'
    '<path d="M15.5 7.5l3 3L22 7l-3-3"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/>'
    '<rect x="14" y="3" width="7" height="7" rx="1.5"/>'
    '<rect x="14" y="14" width="7" height="7" rx="1.5"/>'
    '<rect x="3" y="14" width="7" height="7" rx="1.5"/>',
    # category icons
    "gamepad": '<rect x="2" y="6" width="20" height="12" rx="6"/><path d="M6 12h4M8 10v4"/>'
    '<path d="M15 11h.01M18 13h.01"/>',
    "tv": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M17 2l-5 5-5-5"/>',
    "film": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M17 2l-5 5-5-5"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 6L2 7"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
    '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>'
    '<path d="M2 2h2l2.7 12.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L22 7H5.1"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9L9.6 3.9'
    'A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"/>',
}

CATEGORY_FALLBACK = "folder"
_RENDER_PX = 64  # rendered large, Qt scales it down crisply


def has_icon(name: str | None) -> bool:
    return name is not None and name in _PATHS


def svg_markup(name: str, tint: str, *, filled: bool = False, stroke: float = 2) -> str:
    body = _PATHS.get(name, _PATHS[CATEGORY_FALLBACK])
    fill = tint if filled else "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" '
        f'stroke="{tint}" stroke-width="{stroke}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


@lru_cache(maxsize=512)
def icon(name: str, tint: str, *, filled: bool = False) -> QIcon:
    """Return the named icon in `tint` (a hex color). Unknown names fall back to a folder."""
    svg = svg_markup(name, tint, filled=filled)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(_RENDER_PX, _RENDER_PX)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------- theme binding
# Buttons register which icon/color role they use, so a theme switch can re-tint them.

_bound: weakref.WeakKeyDictionary[QAbstractButton, tuple[str, str, bool]] = (
    weakref.WeakKeyDictionary()
)


def bind_icon(
    button: QAbstractButton, name: str, role: str = "muted", *, filled: bool = False
) -> None:
    """Give `button` an icon colored by theme `role` and keep it in sync with the theme."""
    _bound[button] = (name, role, filled)
    button.setIcon(icon(name, color(role), filled=filled))


def refresh_bound_icons() -> None:
    for button, (name, role, filled) in list(_bound.items()):
        try:
            button.setIcon(icon(name, color(role), filled=filled))
        except RuntimeError:  # the C++ widget is already gone
            _bound.pop(button, None)
