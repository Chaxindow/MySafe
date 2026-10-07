from __future__ import annotations

import pytest

from mysafe.db import (
    CategoryNotEmptyError,
    DuplicateCategoryError,
    NotFoundError,
    Repository,
)
from mysafe.models import DEFAULT_CATEGORIES, FieldInput, FieldKind, default_fields
from tests.conftest import FakeClock


def _category_id(repo: Repository, name: str) -> str:
    return next(c.id for c in repo.list_categories() if c.name == name)


# ----------------------------------------------------------------- categories


def test_default_categories_created_once(repo: Repository) -> None:
    assert repo.ensure_default_categories() is True
    names = [c.name for c in repo.list_categories()]
    assert names == [name for name, _ in DEFAULT_CATEGORIES]

    # Deleted defaults must not come back on the next start.
    repo.delete_category(_category_id(repo, "Shopping"))
    assert repo.ensure_default_categories() is False
    assert "Shopping" not in [c.name for c in repo.list_categories()]


def test_create_category_trims_and_appends(seeded_repo: Repository) -> None:
    category = seeded_repo.create_category("  Banking  ", icon="bank")
    assert category.name == "Banking"
    assert category.icon == "bank"
    assert seeded_repo.list_categories()[-1].id == category.id


def test_create_category_rejects_empty_name(repo: Repository) -> None:
    with pytest.raises(ValueError):
        repo.create_category("   ")


def test_duplicate_category_names_rejected_case_insensitive(seeded_repo: Repository) -> None:
    with pytest.raises(DuplicateCategoryError):
        seeded_repo.create_category("games")
    other = seeded_repo.create_category("Work")
    with pytest.raises(DuplicateCategoryError):
        seeded_repo.rename_category(other.id, "EMAIL")


def test_rename_category(seeded_repo: Repository, clock: FakeClock) -> None:
    cid = _category_id(seeded_repo, "Games")
    clock.advance(10)
    renamed = seeded_repo.rename_category(cid, "Gaming")
    assert renamed.name == "Gaming"
    assert renamed.updated_at > renamed.created_at


def test_reorder_categories(seeded_repo: Repository) -> None:
    ids = [c.id for c in seeded_repo.list_categories()]
    seeded_repo.reorder_categories(list(reversed(ids)))
    assert [c.id for c in seeded_repo.list_categories()] == list(reversed(ids))
    with pytest.raises(ValueError):
        seeded_repo.reorder_categories(ids[:-1])


def test_cannot_delete_category_with_entries(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    other = _category_id(seeded_repo, "Other")
    seeded_repo.create_entry(games, "Steam")

    with pytest.raises(CategoryNotEmptyError) as info:
        seeded_repo.delete_category(games)
    assert info.value.entry_count == 1

    assert seeded_repo.move_entries(games, other) == 1
    seeded_repo.delete_category(games)
    assert seeded_repo.entry_counts() == {other: 1}


def test_unknown_category_raises(repo: Repository) -> None:
    with pytest.raises(NotFoundError):
        repo.get_category("missing")
    with pytest.raises(NotFoundError):
        repo.create_entry("missing", "Steam")


# -------------------------------------------------------------------- entries


def test_create_entry_with_custom_fields(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    entry = seeded_repo.create_entry(
        games,
        "Steam",
        [
            FieldInput("Email", "a@example.com", FieldKind.EMAIL),
            FieldInput("Password", "hunter2", FieldKind.PASSWORD),
            FieldInput("Recovery code", "R-123", FieldKind.RECOVERY_CODE),
            FieldInput("Favorite color?", "Blue", FieldKind.SECURITY_QUESTION),
            FieldInput("Public note", "x", FieldKind.TEXT, is_secret=True),
        ],
        url=" https://store.steampowered.com ",
        favorite=True,
    )
    assert entry.title == "Steam"
    assert entry.url == "https://store.steampowered.com"
    assert entry.favorite is True
    assert [f.label for f in entry.fields] == [
        "Email",
        "Password",
        "Recovery code",
        "Favorite color?",
        "Public note",
    ]
    assert [f.is_secret for f in entry.fields] == [False, True, True, True, True]


def test_new_entry_defaults_to_email_and_password() -> None:
    fields = default_fields()
    assert [f.kind for f in fields] == [FieldKind.EMAIL, FieldKind.PASSWORD]


def test_entry_requires_title_and_field_labels(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    with pytest.raises(ValueError):
        seeded_repo.create_entry(games, "  ")
    with pytest.raises(ValueError):
        seeded_repo.create_entry(games, "Steam", [FieldInput("", "value")])
    assert seeded_repo.count_entries() == 0  # nothing half-saved


def test_update_entry_replaces_fields(seeded_repo: Repository, clock: FakeClock) -> None:
    games = _category_id(seeded_repo, "Games")
    other = _category_id(seeded_repo, "Other")
    entry = seeded_repo.create_entry(games, "Steam", default_fields())
    clock.advance(5)

    updated = seeded_repo.update_entry(
        entry.id,
        category_id=other,
        title="Steam (old)",
        fields=[FieldInput("Username", "gamer", FieldKind.USERNAME)],
        notes="moved",
    )
    assert updated.category_id == other
    assert updated.title == "Steam (old)"
    assert updated.notes == "moved"
    assert [(f.label, f.value) for f in updated.fields] == [("Username", "gamer")]
    assert updated.updated_at == entry.created_at + 5
    count = seeded_repo.connection.execute("SELECT COUNT(*) FROM fields").fetchone()[0]
    assert count == 1


def test_failed_update_changes_nothing(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    entry = seeded_repo.create_entry(games, "Steam", default_fields())
    with pytest.raises(ValueError):
        seeded_repo.update_entry(
            entry.id, category_id=games, title="New", fields=[FieldInput(" ", "x")]
        )
    again = seeded_repo.get_entry(entry.id)
    assert again.title == "Steam"
    assert len(again.fields) == 2


def test_delete_entry_removes_fields(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    entry = seeded_repo.create_entry(games, "Steam", default_fields())
    seeded_repo.delete_entry(entry.id)
    with pytest.raises(NotFoundError):
        seeded_repo.get_entry(entry.id)
    assert seeded_repo.connection.execute("SELECT COUNT(*) FROM fields").fetchone()[0] == 0
    with pytest.raises(NotFoundError):
        seeded_repo.delete_entry(entry.id)


def test_favorites(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    a = seeded_repo.create_entry(games, "Steam")
    seeded_repo.create_entry(games, "Epic")
    seeded_repo.set_favorite(a.id, True)
    assert [e.title for e in seeded_repo.list_entries(favorites_only=True)] == ["Steam"]
    assert seeded_repo.count_entries(favorites_only=True) == 1
    with pytest.raises(NotFoundError):
        seeded_repo.set_favorite("missing", True)


def test_list_entries_by_category_sorted_by_title(seeded_repo: Repository) -> None:
    games = _category_id(seeded_repo, "Games")
    mail = _category_id(seeded_repo, "Email")
    seeded_repo.create_entry(games, "steam")
    seeded_repo.create_entry(games, "Epic")
    seeded_repo.create_entry(mail, "Gmail")
    assert [e.title for e in seeded_repo.list_entries(games)] == ["Epic", "steam"]
    assert len(seeded_repo.list_entries()) == 3
    assert seeded_repo.list_entries(games)[0].fields == []  # list view has no fields


# --------------------------------------------------------------------- search


@pytest.fixture
def search_repo(seeded_repo: Repository) -> Repository:
    games = _category_id(seeded_repo, "Games")
    mail = _category_id(seeded_repo, "Email")
    seeded_repo.create_entry(
        games,
        "Steam",
        [
            FieldInput("Username", "gamer_tr", FieldKind.USERNAME),
            FieldInput("Password", "supersecret", FieldKind.PASSWORD),
        ],
        url="https://store.steampowered.com",
    )
    seeded_repo.create_entry(
        mail, "Gmail", [FieldInput("Email", "someone@gmail.com", FieldKind.EMAIL)]
    )
    seeded_repo.create_entry(mail, "100% Mail")
    return seeded_repo


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("steam", ["Steam"]),  # title, case-insensitive
        ("steampowered", ["Steam"]),  # url
        ("gamer", ["Steam"]),  # username field
        ("@gmail", ["Gmail"]),  # email field
        ("supersecret", []),  # secrets are never searched
        ("%", ["100% Mail"]),  # wildcards are literal
        ("_tr", ["Steam"]),
        ("   ", ["100% Mail", "Gmail", "Steam"]),  # blank search = everything
    ],
)
def test_search(search_repo: Repository, term: str, expected: list[str]) -> None:
    assert [e.title for e in search_repo.list_entries(search=term)] == expected


def test_search_within_category(search_repo: Repository) -> None:
    games = _category_id(search_repo, "Games")
    assert search_repo.list_entries(games, search="gmail") == []


def test_repr_does_not_leak_values(search_repo: Repository) -> None:
    entry_id = search_repo.list_entries(search="steam")[0].id
    entry = search_repo.get_entry(entry_id)
    assert "supersecret" not in repr(entry)
    assert all("supersecret" not in repr(f) for f in entry.fields)


def test_settings_roundtrip(repo: Repository) -> None:
    assert repo.get_setting("theme") is None
    assert repo.get_setting("theme", "system") == "system"
    repo.set_setting("theme", "dark")
    repo.set_setting("theme", "light")
    assert repo.get_setting("theme") == "light"


def test_deletions_are_remembered_for_sync(seeded_repo: Repository, clock: FakeClock) -> None:
    games = _category_id(seeded_repo, "Games")
    entry = seeded_repo.create_entry(games, "Steam")
    clock.advance(30)
    seeded_repo.delete_entry(entry.id)
    shopping = _category_id(seeded_repo, "Shopping")
    seeded_repo.delete_category(shopping)

    deleted = {d.id: d for d in seeded_repo.list_deleted()}
    assert deleted[entry.id].kind == "entry"
    assert deleted[entry.id].title == "Steam"
    assert deleted[entry.id].deleted_at == clock.now
    assert deleted[shopping].kind == "category"


def test_on_change_called_after_each_write_only(repo: Repository) -> None:
    calls: list[int] = []
    repo.set_on_change(lambda: calls.append(1))
    repo.ensure_default_categories()
    assert len(calls) == 1
    games = _category_id(repo, "Games")
    repo.create_entry(games, "Steam")
    repo.list_entries()  # reads do not save
    assert len(calls) == 2
    with pytest.raises(ValueError):
        repo.create_entry(games, "  ")  # failed writes do not save
    assert len(calls) == 2
