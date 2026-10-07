"""A simple, explainable strength estimate for the master password."""

from __future__ import annotations

import string
from dataclasses import dataclass

MIN_MASTER_LENGTH = 10

_COMMON = frozenset(
    {
        "password",
        "password1",
        "12345678",
        "123456789",
        "1234567890",
        "qwertyuiop",
        "qwerty123",
        "11111111",
        "iloveyou",
        "sifre123",
        "parola123",
        "mysafe123",
    }
)


@dataclass(frozen=True, slots=True)
class Strength:
    score: int  # 0 (unusable) .. 4 (strong)
    label: str
    hint: str

    @property
    def acceptable(self) -> bool:
        return self.score >= 2


def _classes(password: str) -> int:
    groups = (
        string.ascii_lowercase,
        string.ascii_uppercase,
        string.digits,
    )
    count = sum(any(ch in group for ch in password) for group in groups)
    count += any(not ch.isalnum() for ch in password)  # symbols, spaces, Turkish letters …
    return count


def estimate(password: str) -> Strength:
    if len(password) < MIN_MASTER_LENGTH:
        return Strength(0, "Too short", f"Use at least {MIN_MASTER_LENGTH} characters.")
    if password.lower() in _COMMON or len(set(password)) <= 2:
        return Strength(0, "Too easy to guess", "Avoid common or repeated passwords.")
    score = 1
    if len(password) >= 12:
        score += 1
    if len(password) >= 16:
        score += 1
    if _classes(password) >= 3:
        score += 1
    score = min(score, 4)
    labels = {1: "Weak", 2: "Fair", 3: "Good", 4: "Strong"}
    hints = {
        1: "Make it 12+ characters, or mix letters, digits and symbols. "
        "A short sentence is easy to remember.",
        2: "Good start. A few more words or characters make it much stronger.",
        3: "",
        4: "",
    }
    return Strength(score, labels[score], hints[score])
