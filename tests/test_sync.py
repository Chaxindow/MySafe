"""Sync scenarios: computer (local) ⇄ USB copy (remote)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mysafe.db import Repository, open_from_bytes, to_bytes
from mysafe.models import FieldInput, FieldKind
from mysafe.services import crypto
from mysafe.services.crypto import (
    KdfParams,
    NeedsPasswordError,
    OtherVaultError,
    WrongPasswordError,
)
from mysafe.sync import Side, SyncChoices, apply_sync, keys_source, plan_sync
from mysafe.vault import Vault
from tests.conftest import FakeClock

FAST = KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)


@pytest.fixture
def pair(clock: FakeClock) -> tuple[Repository, Repository]:
    """A vault with 3 entries and an exact copy of it (like "Create USB copy")."""
    local = Repository(open_from_bytes(), clock)
    local.ensure_default_categories()
    games = _cat(local, "Games")
    for title in ("Steam", "Epic Games", "Riot"):
        local.create_entry(
            games,
            title,
            [
                FieldInput("Email", f"{title.lower()}@example.com", FieldKind.EMAIL),
                FieldInput("Password", f"{title}-pw", FieldKind.PASSWORD),
            ],
        )
    remote = Repository(open_from_bytes(to_bytes(local.connection)), clock)
    clock.advance(100)
    return local, remote


def _cat(repo: Repository, name: str) -> str:
    return next(c.id for c in repo.list_categories() if c.name == name)


def _titles(repo: Repository) -> list[str]:
    return [e.title for e in repo.list_entries()]


def _id(repo: Repository, title: str) -> str:
    return next(e.id for e in repo.list_entries() if e.title == title)


def _sync(local: Repository, remote: Repository, **choice_overrides: object):  # type: ignore[no-untyped-def]
    plan = plan_sync(local, remote)
    choices = SyncChoices.defaults(plan)
    for key, value in choice_overrides.items():
        setattr(choices, key, value)
    result = apply_sync(local, remote, plan, choices)
    return plan, result


def test_identical_copies_need_nothing(pair: tuple[Repository, Repository]) -> None:
    assert plan_sync(*pair).is_empty


def test_two_new_entries_on_computer_go_to_usb(pair: tuple[Repository, Repository]) -> None:
    local, remote = pair
    games = _cat(local, "Games")
    local.create_entry(games, "Battle.net")
    local.create_entry(_cat(local, "Streaming"), "Spotify")
    plan, result = _sync(local, remote)
    assert [(n.entry.title, n.source) for n in plan.new_entries] == [
        ("Battle.net", Side.LOCAL),
        ("Spotify", Side.LOCAL),
    ]
    assert result.copied_to_remote == 2
    assert sorted(_titles(remote)) == sorted(_titles(local))
    assert len(_titles(remote)) == 5
    assert plan_sync(local, remote).is_empty


def test_new_entry_on_usb_comes_to_computer(pair: tuple[Repository, Repository]) -> None:
    local, remote = pair
    remote.create_entry(
        _cat(remote, "Social Media"), "Discord", [FieldInput("Password", "d", FieldKind.PASSWORD)]
    )
    _, result = _sync(local, remote)
    assert result.copied_to_local == 1
    copied = local.get_entry(_id(local, "Discord"))
    assert copied.fields[0].value == "d"
    assert copied.id == _id(remote, "Discord")  # same identity on both sides


def test_changed_on_both_sides_is_a_conflict_with_a_diff(
    pair: tuple[Repository, Repository], clock: FakeClock
) -> None:
    local, remote = pair
    steam = _id(local, "Steam")
    remote_entry = remote.get_entry(steam)
    remote.update_entry(
        steam,
        category_id=remote_entry.category_id,
        title="Steam",
        fields=[
            FieldInput(f.label, "usb-pw" if f.label == "Password" else f.value, f.kind)
            for f in remote_entry.fields
        ],
    )
    clock.advance(10)
    local_entry = local.get_entry(steam)
    local.update_entry(
        steam,
        category_id=local_entry.category_id,
        title="Steam",
        fields=[
            FieldInput(f.label, "pc-pw" if f.label == "Password" else f.value, f.kind)
            for f in local_entry.fields
        ],
    )

    plan = plan_sync(local, remote)
    assert len(plan.conflicts) == 1
    conflict = plan.conflicts[0]
    assert conflict.newer is Side.LOCAL
    changed = [r for r in conflict.rows if not r.same]
    assert [(r.label, r.local, r.remote, r.secret) for r in changed] == [
        ("Password", "pc-pw", "usb-pw", True)
    ]

    # The user keeps the USB version even though the computer's is newer.
    apply_sync(local, remote, plan, SyncChoices(keep={steam: Side.REMOTE}))
    assert local.get_entry(steam).fields[1].value == "usb-pw"
    assert plan_sync(local, remote).is_empty


def test_use_newest_is_the_default(pair: tuple[Repository, Repository], clock: FakeClock) -> None:
    local, remote = pair
    riot = _id(local, "Riot")
    remote.set_favorite(riot, True)
    clock.advance(5)
    local.set_favorite(riot, False)  # same value as before but newer edit
    local.update_entry(riot, category_id=_cat(local, "Games"), title="Riot Games", fields=[])
    _sync(local, remote)
    assert remote.get_entry(riot).title == "Riot Games"


def test_deleted_on_computer_is_deleted_on_usb_by_default(
    pair: tuple[Repository, Repository],
) -> None:
    local, remote = pair
    epic = _id(local, "Epic Games")
    local.delete_entry(epic)
    plan, result = _sync(local, remote)
    assert [(d.item.title, d.deleted_on) for d in plan.deletions] == [("Epic Games", Side.LOCAL)]
    assert result.deleted_remote == 1
    assert remote.find_entry(epic) is None
    assert epic in {d.id for d in remote.list_deleted()}
    assert plan_sync(local, remote).is_empty


def test_unticking_delete_keeps_the_entry_everywhere(pair: tuple[Repository, Repository]) -> None:
    local, remote = pair
    epic = _id(local, "Epic Games")
    local.delete_entry(epic)
    _, result = _sync(local, remote, delete=set())
    assert result.kept_instead_of_deleting == 1
    assert local.find_entry(epic) is not None  # brought back
    assert epic not in {d.id for d in local.list_deleted()}
    assert plan_sync(local, remote).is_empty


def test_edited_after_deletion_is_flagged(
    pair: tuple[Repository, Repository], clock: FakeClock
) -> None:
    local, remote = pair
    riot = _id(local, "Riot")
    local.delete_entry(riot)
    clock.advance(60)
    remote.set_favorite(riot, True)
    deletion = plan_sync(local, remote).deletions[0]
    assert deletion.edited_after_deletion


def test_deleted_on_usb_is_deleted_on_computer(pair: tuple[Repository, Repository]) -> None:
    local, remote = pair
    steam = _id(remote, "Steam")
    remote.delete_entry(steam)
    _, result = _sync(local, remote)
    assert result.deleted_local == 1
    assert local.find_entry(steam) is None


def test_new_category_travels_with_its_entry(pair: tuple[Repository, Repository]) -> None:
    local, remote = pair
    banking = local.create_category("Banking")
    local.create_entry(banking.id, "My Bank")
    _sync(local, remote)
    assert "Banking" in [c.name for c in remote.list_categories()]
    assert remote.get_entry(_id(remote, "My Bank")).category_id == banking.id


def test_category_rename_newest_wins(pair: tuple[Repository, Repository], clock: FakeClock) -> None:
    local, remote = pair
    games = _cat(local, "Games")
    remote.rename_category(games, "Gaming")
    clock.advance(5)
    _sync(local, remote)
    assert "Gaming" in [c.name for c in local.list_categories()]


def test_independent_vaults_merge_categories_by_name(clock: FakeClock) -> None:
    a = Repository(open_from_bytes(), clock)
    b = Repository(open_from_bytes(), clock)
    a.ensure_default_categories()
    b.ensure_default_categories()  # same names, different ids
    b.create_entry(_cat(b, "Games"), "Steam")
    _sync(a, b)
    assert [c.name for c in a.list_categories()].count("Games") == 1
    assert a.get_entry(_id(a, "Steam")).category_id == _cat(a, "Games")


def test_sync_saves_each_side_once(pair: tuple[Repository, Repository]) -> None:
    local, remote = pair
    for i in range(5):
        local.create_entry(_cat(local, "Other"), f"Entry {i}")
    saves = {"local": 0, "remote": 0}
    local.set_on_change(lambda: saves.__setitem__("local", saves["local"] + 1))
    remote.set_on_change(lambda: saves.__setitem__("remote", saves["remote"] + 1))
    _sync(local, remote)
    assert saves["remote"] == 1


# ------------------------------------------------------------- whole vaults


def test_usb_copy_takes_over_the_new_password(tmp_path: Path) -> None:
    computer, _ = Vault.create(tmp_path / "pc" / "vault.mysafe", "old password", params=FAST)
    computer.repo.ensure_default_categories()
    usb_path = tmp_path / "usb" / "MySafe-data" / "vault.mysafe"
    computer.copy_to(usb_path)

    computer.change_password("new password")
    # The stale copy still opens: the old data key is kept (encrypted) in the history.
    usb = Vault.open_copy(usb_path, computer.keys, older_keys=computer.older_keys())
    plan = plan_sync(computer.repo, usb.repo, computer.keys, usb.keys)
    assert plan.keys_from is Side.LOCAL
    result = apply_sync(computer.repo, usb.repo, plan, SyncChoices.defaults(plan))
    usb.use_keys(computer.keys)
    assert result.password_updated_on is Side.REMOTE
    usb.lock()
    assert Vault.unlock(usb_path, "new password").repo.list_categories()
    with pytest.raises(WrongPasswordError):
        Vault.unlock(usb_path, "old password")


def test_copy_with_changed_password_needs_that_password(tmp_path: Path) -> None:
    computer, _ = Vault.create(tmp_path / "pc" / "vault.mysafe", "pc password", params=FAST)
    usb_path = tmp_path / "usb" / "vault.mysafe"
    computer.copy_to(usb_path)
    usb = Vault.open_copy(usb_path, computer.keys)
    usb.change_password("usb password")
    usb.lock()
    with pytest.raises(NeedsPasswordError):
        Vault.open_copy(usb_path, computer.keys, older_keys=computer.older_keys())
    usb = Vault.open_copy_with_password(usb_path, "usb password")
    plan = plan_sync(computer.repo, usb.repo, computer.keys, usb.keys, remote_verified=True)
    assert plan.keys_from is Side.REMOTE  # proven by its password, and newer
    computer.use_keys(usb.keys)
    usb.lock()
    computer.lock()
    Vault.unlock(tmp_path / "pc" / "vault.mysafe", "usb password").lock()


def test_tampered_copy_can_never_change_this_password(tmp_path: Path) -> None:
    """Someone who knew an OLD password (so an old data key) forges a "newer" USB vault."""
    computer, _ = Vault.create(tmp_path / "pc" / "vault.mysafe", "old password", params=FAST)
    old_keys = computer.keys.copy()
    computer.change_password("new password")

    forged_keys, _ = crypto.create_keys("attacker password", params=FAST)
    forged_keys.header["vault_id"] = computer.keys.vault_id
    forged_keys = crypto.with_new_password(forged_keys, "attacker password")
    forged_keys.data_key[:] = old_keys.data_key  # sealed with a key the computer still knows
    forged_keys.header["keys_updated_at"] = 2**40
    forged_path = tmp_path / "usb" / "vault.mysafe"
    forged_path.parent.mkdir()
    forged_path.write_bytes(crypto.seal(to_bytes(open_from_bytes()), forged_keys))

    forged = Vault.open_copy(forged_path, computer.keys, older_keys=computer.older_keys())
    plan = plan_sync(computer.repo, forged.repo, computer.keys, forged.keys)
    assert plan.keys_from is Side.LOCAL  # opened without its password: never adopted
    # Even if its password were typed, a date in the future is not believed.
    assert keys_source(computer.keys, forged.keys, remote_verified=True) is Side.LOCAL


def test_weaker_key_settings_are_never_adopted(tmp_path: Path) -> None:
    strong = crypto.KdfParams(16 * 1024, 2, 1)
    computer, _ = Vault.create(tmp_path / "pc.mysafe", "pc password", params=strong)
    weak_keys, _ = crypto.create_keys("usb password", params=FAST)
    weak_keys.header["vault_id"] = computer.keys.vault_id
    weak_keys.header["keys_updated_at"] = crypto.keys_updated_at(computer.keys) + 10
    assert keys_source(computer.keys, weak_keys, remote_verified=True) is Side.LOCAL


def test_key_history_is_merged(tmp_path: Path) -> None:
    computer, _ = Vault.create(tmp_path / "pc.mysafe", "pc password", params=FAST)
    usb_path = tmp_path / "usb.mysafe"
    computer.copy_to(usb_path)
    computer.change_password("pc password 2")
    usb = Vault.open_copy(usb_path, computer.keys, older_keys=computer.older_keys())
    plan = plan_sync(computer.repo, usb.repo, computer.keys, usb.keys)
    apply_sync(computer.repo, usb.repo, plan, SyncChoices.defaults(plan))
    assert set(usb.repo.old_data_keys()) == set(computer.repo.old_data_keys())


def test_a_different_vault_cannot_be_synced(tmp_path: Path) -> None:
    mine, _ = Vault.create(tmp_path / "a.mysafe", "pw", params=FAST)
    other, _ = Vault.create(tmp_path / "b.mysafe", "pw", params=FAST)
    other.lock()
    with pytest.raises(OtherVaultError):
        Vault.open_copy(tmp_path / "b.mysafe", mine.keys)
    with pytest.raises(FileExistsError):
        mine.copy_to(tmp_path / "b.mysafe")
    assert crypto.keys_updated_at(mine.keys) > 0
