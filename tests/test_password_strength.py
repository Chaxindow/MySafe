from __future__ import annotations

import pytest

from mysafe.services.password_strength import MIN_MASTER_LENGTH, estimate


@pytest.mark.parametrize(
    ("password", "score"),
    [
        ("short", 0),
        ("password", 0),  # common
        ("aaaaaaaaaaaa", 0),  # repeated
        ("tahta kalem", 1),
        ("tahtakalem12", 2),
        ("Tahta-kalem-12", 3),
        ("Mavi bisiklet 1987 yazin!", 4),
    ],
)
def test_scores(password: str, score: int) -> None:
    assert estimate(password).score == score


def test_minimum_length() -> None:
    assert not estimate("x" * (MIN_MASTER_LENGTH - 1)).acceptable
    assert estimate("Correct horse").acceptable


@pytest.mark.parametrize("password", ["sunshine1", "abcdefghij", "tahta kalem"])
def test_weak_master_passwords_are_refused(password: str) -> None:
    assert not estimate(password).acceptable


@pytest.mark.parametrize("password", ["tahtakalem12", "Kalem-12ab", "Mavi bisiklet 1987"])
def test_reasonable_master_passwords_are_accepted(password: str) -> None:
    assert estimate(password).acceptable
