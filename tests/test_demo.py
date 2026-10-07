from __future__ import annotations

from mysafe.db import Repository
from mysafe.demo import seed


def test_seed_adds_entries_only_once(repo: Repository) -> None:
    added = seed(repo)
    assert added > 0
    assert repo.count_entries() == added
    assert seed(repo) == 0
