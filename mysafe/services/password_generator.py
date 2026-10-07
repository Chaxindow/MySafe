"""Random password generator (uses the `secrets` module, never `random`)."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

LOWERCASE = string.ascii_lowercase
UPPERCASE = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?"
# Characters that are easy to mix up when read by a human.
AMBIGUOUS = set("Il1O0o")

MIN_LENGTH = 4
MAX_LENGTH = 128
DEFAULT_LENGTH = 20


@dataclass(frozen=True, slots=True)
class PasswordOptions:
    length: int = DEFAULT_LENGTH
    lowercase: bool = True
    uppercase: bool = True
    digits: bool = True
    symbols: bool = True
    avoid_ambiguous: bool = False


def _pools(options: PasswordOptions) -> list[str]:
    pools = [
        chars
        for enabled, chars in (
            (options.lowercase, LOWERCASE),
            (options.uppercase, UPPERCASE),
            (options.digits, DIGITS),
            (options.symbols, SYMBOLS),
        )
        if enabled
    ]
    if options.avoid_ambiguous:
        pools = ["".join(c for c in pool if c not in AMBIGUOUS) for pool in pools]
    return pools


def generate_password(options: PasswordOptions | None = None) -> str:
    """Return a random password containing at least one character from every chosen set."""
    options = options or PasswordOptions()
    if not MIN_LENGTH <= options.length <= MAX_LENGTH:
        raise ValueError(f"Length must be between {MIN_LENGTH} and {MAX_LENGTH}")
    pools = _pools(options)
    if not pools:
        raise ValueError("Choose at least one character set")

    # One guaranteed character from each set, the rest from all sets combined.
    chars = [secrets.choice(pool) for pool in pools]
    alphabet = "".join(pools)
    chars += [secrets.choice(alphabet) for _ in range(options.length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
