"""Color tokens for the light and dark themes.

Identity: a vault — cool steel surfaces with a single brass accent. Each of the three
panes has its own surface tone so the layout reads as three distinct areas.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class Tokens:
    sidebar: str  # left pane (categories)
    list: str  # middle pane (entries)
    detail: str  # right pane, dialogs
    surface: str  # grouped field box, secondary buttons
    input: str  # text inputs
    border: str  # dividers, outlines
    hover: str  # hover background
    pressed: str  # pressed background
    text: str
    muted: str  # labels, secondary text, icons
    accent: str  # brass: primary actions, selection, favorites
    accent_hover: str
    accent_text: str  # text on top of the accent
    accent_tint: str  # selected rows (accent at low opacity)
    danger: str
    danger_tint: str
    success: str  # "added" in Sync
    success_tint: str


DARK = Tokens(
    sidebar="#121820",
    list="#171E27",
    detail="#1C2430",
    surface="#222C39",
    input="#151C25",
    border="#2C3746",
    hover="#2A3545",
    pressed="#334052",
    text="#E7EBF0",
    muted="#8D99A8",
    accent="#D4A73C",
    accent_hover="#E3BA57",
    accent_text="#1B1405",
    accent_tint="#3A3424",
    danger="#EF7268",
    danger_tint="#3D2427",
    success="#5BD08A",
    success_tint="#1F3A2B",
)

LIGHT = Tokens(
    sidebar="#E6EBF0",
    list="#F1F4F7",
    detail="#FFFFFF",
    surface="#F6F8FA",
    input="#FFFFFF",
    border="#D3DBE3",
    hover="#E3E9EF",
    pressed="#D6DEE7",
    text="#18212C",
    muted="#5B6776",
    accent="#8A6410",
    accent_hover="#74540C",
    accent_text="#FFFFFF",
    accent_tint="#F1E7CF",
    danger="#C0362D",
    danger_tint="#FBE6E4",
    success="#1E7F4F",
    success_tint="#DDF3E6",
)

ROLES = frozenset(f.name for f in fields(Tokens))

_current: Tokens = DARK


def current() -> Tokens:
    return _current


def set_current(tokens: Tokens) -> None:
    global _current
    _current = tokens


def color(role: str) -> str:
    """Hex color for a token role of the current theme, e.g. color("muted")."""
    if role not in ROLES:
        raise KeyError(f"Unknown color role: {role}")
    return str(getattr(_current, role))


def is_dark() -> bool:
    return _current is DARK
