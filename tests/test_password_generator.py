from __future__ import annotations

import pytest

from mysafe.services.password_generator import (
    AMBIGUOUS,
    DIGITS,
    LOWERCASE,
    SYMBOLS,
    UPPERCASE,
    PasswordOptions,
    generate_password,
)


def test_default_password_has_every_character_set() -> None:
    for _ in range(200):
        pw = generate_password()
        assert len(pw) == 20
        assert any(c in LOWERCASE for c in pw)
        assert any(c in UPPERCASE for c in pw)
        assert any(c in DIGITS for c in pw)
        assert any(c in SYMBOLS for c in pw)


def test_only_selected_sets_are_used() -> None:
    pw = generate_password(PasswordOptions(length=50, uppercase=False, symbols=False))
    assert set(pw) <= set(LOWERCASE + DIGITS)


def test_avoid_ambiguous() -> None:
    for _ in range(100):
        pw = generate_password(PasswordOptions(length=64, avoid_ambiguous=True))
        assert not set(pw) & AMBIGUOUS


def test_passwords_are_not_repeated() -> None:
    assert len({generate_password() for _ in range(500)}) == 500


@pytest.mark.parametrize("length", [3, 129])
def test_invalid_length(length: int) -> None:
    with pytest.raises(ValueError):
        generate_password(PasswordOptions(length=length))


def test_no_character_set() -> None:
    with pytest.raises(ValueError):
        generate_password(
            PasswordOptions(lowercase=False, uppercase=False, digits=False, symbols=False)
        )
