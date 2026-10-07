"""Fill the database with fake sample entries so the UI has something to show.

Usage:  python -m mysafe.demo
Only runs when the database has no entries yet. All data here is fake.
"""

from __future__ import annotations

import sys

from mysafe.db import Repository, open_database
from mysafe.models import FieldInput, FieldKind
from mysafe.paths import db_path, vault_path

_SAMPLES: list[tuple[str, str, str | None, list[FieldInput], bool]] = [
    (
        "Games",
        "Steam",
        "https://store.steampowered.com",
        [
            FieldInput("Username", "demo_gamer", FieldKind.USERNAME),
            FieldInput("Email", "demo.gamer@example.com", FieldKind.EMAIL),
            FieldInput("Password", "Demo-Passw0rd!", FieldKind.PASSWORD),
            FieldInput("Steam Guard recovery code", "R12345", FieldKind.RECOVERY_CODE),
        ],
        True,
    ),
    (
        "Games",
        "Epic Games",
        "https://store.epicgames.com",
        [
            FieldInput("Email", "demo.gamer@example.com", FieldKind.EMAIL),
            FieldInput("Password", "An0ther-Demo!", FieldKind.PASSWORD),
        ],
        False,
    ),
    (
        "Streaming",
        "Netflix",
        "https://www.netflix.com",
        [
            FieldInput("Email", "demo.family@example.com", FieldKind.EMAIL),
            FieldInput("Password", "Movie-Night-42", FieldKind.PASSWORD),
            FieldInput("Favorite color?", "Blue", FieldKind.SECURITY_QUESTION),
        ],
        False,
    ),
    (
        "Email",
        "Gmail",
        "https://mail.google.com",
        [
            FieldInput("Email", "demo.person@example.com", FieldKind.EMAIL),
            FieldInput("Password", "Mail-Demo-2026", FieldKind.PASSWORD),
            FieldInput("Recovery phone", "+00 000 000 0000", FieldKind.TEXT),
        ],
        True,
    ),
]


def seed(repo: Repository) -> int:
    """Add the sample entries. Returns how many were added (0 if the vault isn't empty)."""
    repo.ensure_default_categories()
    if repo.count_entries():
        return 0
    by_name = {c.name: c.id for c in repo.list_categories()}
    added = 0
    for category_name, title, url, fields, favorite in _SAMPLES:
        category_id = by_name.get(category_name)
        if category_id is None:
            category_id = repo.create_category(category_name).id
            by_name[category_name] = category_id
        repo.create_entry(category_id, title, fields, url=url, favorite=favorite)
        added += 1
    return added


def main() -> int:
    if vault_path().exists():
        print("An encrypted vault already exists; demo data is only added before setup.")
        return 0
    repo = Repository(open_database(db_path()))
    try:
        added = seed(repo)
    finally:
        repo.close()
    if added:
        print(f"Added {added} demo entries to {db_path()}")
    else:
        print("The database already has entries; nothing was added.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
