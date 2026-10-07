from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from mysafe.db import Repository, open_database

# Run Qt without a visible window (CI / headless machines).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeClock:
    def __init__(self, start: int = 1_700_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int = 1) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo(clock: FakeClock) -> Iterator[Repository]:
    repository = Repository(open_database(":memory:"), clock=clock)
    yield repository
    repository.close()


@pytest.fixture
def seeded_repo(repo: Repository) -> Repository:
    repo.ensure_default_categories()
    return repo
