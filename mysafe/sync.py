"""Two-way Sync between this vault and its copy (e.g. computer ⇄ USB).

Rules (agreed with the user):
* New entries (on one side only, never deleted on the other) are copied automatically.
* Entries that differ on both sides are *conflicts*: the user picks which version to keep
  (the newer one is preselected; "Use newest for all" picks the newer everywhere).
* An entry deleted on one side but still present on the other is shown as a *deletion*;
  "Delete on the other side too" is preselected.
* Categories follow automatically (new ones are copied, renames: newest wins).
* Deletion records are merged so later syncs know about them.
* Afterwards both sides open with the same master password / recovery key:
  - normally this vault's keys are written to the copy;
  - the copy's keys are taken over only if the user unlocked the copy with ITS password in
    this sync (`remote_verified`), they are newer, and not dated in the future. A file
    someone tampered with can therefore never change this vault's password.
* Data keys used before ("key history") are merged, so both sides can open older copies.

`plan_sync` only reads. `apply_sync` writes both sides, each in a single save.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum

from mysafe.db import Repository
from mysafe.models import Category, DeletedItem, Entry
from mysafe.services import crypto


class Side(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"

    @property
    def other(self) -> Side:
        return Side.REMOTE if self is Side.LOCAL else Side.LOCAL


@dataclass(frozen=True, slots=True)
class FieldDiff:
    label: str
    local: str | None  # None = not present on that side
    remote: str | None
    secret: bool

    @property
    def same(self) -> bool:
        return self.local == self.remote


@dataclass(slots=True)
class NewEntry:
    entry: Entry
    source: Side  # where it exists now; it will be copied to source.other
    category_name: str


@dataclass(slots=True)
class Conflict:
    local: Entry
    remote: Entry
    rows: list[FieldDiff]
    category_name: str

    @property
    def id(self) -> str:
        return self.local.id

    @property
    def newer(self) -> Side:
        return Side.REMOTE if self.remote.updated_at > self.local.updated_at else Side.LOCAL


@dataclass(slots=True)
class Deletion:
    item: DeletedItem
    deleted_on: Side
    existing: Entry  # still present on deleted_on.other
    category_name: str

    @property
    def edited_after_deletion(self) -> bool:
        return self.existing.updated_at > self.item.deleted_at


@dataclass(slots=True)
class SyncPlan:
    new_entries: list[NewEntry] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    deletions: list[Deletion] = field(default_factory=list)
    category_updates: int = 0  # automatic category changes (both directions)
    keys_from: Side | None = None  # both sides will use this side's password/recovery key

    @property
    def is_empty(self) -> bool:
        return not (
            self.new_entries
            or self.conflicts
            or self.deletions
            or self.category_updates
            or self.keys_from
        )


@dataclass(slots=True)
class SyncChoices:
    keep: dict[str, Side] = field(default_factory=dict)  # conflict id -> side to keep
    delete: set[str] = field(default_factory=set)  # deletion ids to apply on the other side

    @classmethod
    def defaults(cls, plan: SyncPlan) -> SyncChoices:
        return cls(
            keep={c.id: c.newer for c in plan.conflicts},
            delete={d.item.id for d in plan.deletions},
        )


@dataclass(slots=True)
class SyncResult:
    copied_to_local: int = 0
    copied_to_remote: int = 0
    conflicts_resolved: int = 0
    deleted_local: int = 0
    deleted_remote: int = 0
    kept_instead_of_deleting: int = 0
    password_updated_on: Side | None = None

    def summary(self, remote_name: str = "USB") -> list[str]:
        lines: list[str] = []
        if self.copied_to_remote:
            lines.append(f"{self.copied_to_remote} copied to {remote_name}")
        if self.copied_to_local:
            lines.append(f"{self.copied_to_local} copied to this computer")
        if self.conflicts_resolved:
            noun = "entry" if self.conflicts_resolved == 1 else "entries"
            lines.append(f"{self.conflicts_resolved} changed {noun} updated")
        if self.deleted_remote:
            lines.append(f"{self.deleted_remote} deleted on {remote_name}")
        if self.deleted_local:
            lines.append(f"{self.deleted_local} deleted on this computer")
        if self.kept_instead_of_deleting:
            lines.append(f"{self.kept_instead_of_deleting} kept (not deleted)")
        if self.password_updated_on is Side.REMOTE:
            lines.append(f"Master password on {remote_name} updated to match")
        elif self.password_updated_on is Side.LOCAL:
            lines.append("Master password here updated to match the newer one")
        return lines or ["Everything was already in sync."]


# ------------------------------------------------------------------- helpers


def _content(entry: Entry) -> tuple[object, ...]:
    return (
        entry.title,
        entry.url or None,
        entry.notes or None,
        entry.favorite,
        entry.category_id,
        tuple((f.label, f.value, f.kind.value, f.is_secret) for f in entry.fields),
    )


def _rows(
    local: Entry, remote: Entry, local_cats: dict[str, str], remote_cats: dict[str, str]
) -> list[FieldDiff]:
    rows = [
        FieldDiff("Title", local.title, remote.title, False),
        FieldDiff(
            "Category",
            local_cats.get(local.category_id, "?"),
            remote_cats.get(remote.category_id, "?"),
            False,
        ),
        FieldDiff("Website", local.url, remote.url, False),
    ]
    remote_by_label: dict[str, list[int]] = {}
    for i, f in enumerate(remote.fields):
        remote_by_label.setdefault(f.label, []).append(i)
    used: set[int] = set()
    for f in local.fields:
        match = next((i for i in remote_by_label.get(f.label, []) if i not in used), None)
        if match is None:
            rows.append(FieldDiff(f.label, f.value, None, f.is_secret))
        else:
            used.add(match)
            other = remote.fields[match]
            rows.append(FieldDiff(f.label, f.value, other.value, f.is_secret or other.is_secret))
    for i, f in enumerate(remote.fields):
        if i not in used:
            rows.append(FieldDiff(f.label, None, f.value, f.is_secret))
    rows.append(FieldDiff("Notes", local.notes, remote.notes, False))
    rows.append(
        FieldDiff(
            "Favorite", "Yes" if local.favorite else "No", "Yes" if remote.favorite else "No", False
        )
    )
    return [r for r in rows if not (r.local in (None, "") and r.remote in (None, ""))]


def _categories(repo: Repository) -> dict[str, Category]:
    return {c.id: c for c in repo.list_categories()}


def _category_mapping(source: dict[str, Category], target: dict[str, Category]) -> dict[str, str]:
    """Map source category ids to target ids; same-name categories with different ids merge."""
    by_name = {c.name.casefold(): c.id for c in target.values()}
    mapping: dict[str, str] = {}
    for cid, cat in source.items():
        if cid in target:
            mapping[cid] = cid
        elif cat.name.casefold() in by_name:
            mapping[cid] = by_name[cat.name.casefold()]
    return mapping


# ---------------------------------------------------------------------- plan


CLOCK_SKEW_SECONDS = 24 * 60 * 60  # "changed in the future" beyond this is not believed


def keys_source(
    local_keys: crypto.VaultKeys,
    remote_keys: crypto.VaultKeys,
    *,
    remote_verified: bool,
    now: int | None = None,
) -> Side | None:
    """Whose password/recovery key both sides should use after the sync (None: same already)."""
    same = crypto.same_data_key(local_keys, remote_keys) and all(
        local_keys.header.get(k) == remote_keys.header.get(k) for k in ("password", "recovery")
    )
    if same:
        return None
    if not remote_verified or remote_keys.version != crypto.FORMAT_VERSION:
        return Side.LOCAL
    current = int(time.time()) if now is None else now
    remote_at = crypto.keys_updated_at(remote_keys)
    if remote_at > current + CLOCK_SKEW_SECONDS:
        return Side.LOCAL  # a date in the future: wrong clock or a forged file
    try:
        remote_params = crypto.KdfParams.from_dict(remote_keys.header["kdf_params"])
        local_params = crypto.KdfParams.from_dict(local_keys.header["kdf_params"])
    except crypto.VaultCryptoError:
        return Side.LOCAL
    if not remote_params.at_least(local_params):
        return Side.LOCAL  # never switch to weaker key settings
    return Side.REMOTE if remote_at > crypto.keys_updated_at(local_keys) else Side.LOCAL


def plan_sync(
    local: Repository,
    remote: Repository,
    local_keys: crypto.VaultKeys | None = None,
    remote_keys: crypto.VaultKeys | None = None,
    *,
    remote_verified: bool = False,
) -> SyncPlan:
    plan = SyncPlan()
    local_cats, remote_cats = _categories(local), _categories(remote)
    local_names = {cid: c.name for cid, c in local_cats.items()}
    remote_names = {cid: c.name for cid, c in remote_cats.items()}
    to_remote = _category_mapping(local_cats, remote_cats)
    to_local = _category_mapping(remote_cats, local_cats)
    local_deleted = {d.id: d for d in local.list_deleted()}
    remote_deleted = {d.id: d for d in remote.list_deleted()}

    # Automatic category work: new categories and renames (newest wins).
    for cid, cat in local_cats.items():
        is_new = cid not in to_remote and cid not in remote_deleted
        renamed = cid in remote_cats and remote_cats[cid].name != cat.name
        if is_new or renamed:
            plan.category_updates += 1
    for cid in remote_cats:
        if cid not in to_local and cid not in local_deleted:
            plan.category_updates += 1

    local_entries = {e.id: e for e in local.all_entries()}
    remote_entries = {e.id: e for e in remote.all_entries()}

    for eid, entry in local_entries.items():
        name = local_names.get(entry.category_id, "")
        if eid in remote_entries:
            other = remote_entries[eid]
            mapped = replace(entry, category_id=to_remote.get(entry.category_id, entry.category_id))
            if _content(mapped) != _content(other):
                plan.conflicts.append(
                    Conflict(entry, other, _rows(entry, other, local_names, remote_names), name)
                )
        elif eid in remote_deleted:
            plan.deletions.append(Deletion(remote_deleted[eid], Side.REMOTE, entry, name))
        else:
            plan.new_entries.append(NewEntry(entry, Side.LOCAL, name))

    for eid, entry in remote_entries.items():
        if eid in local_entries:
            continue
        name = remote_names.get(entry.category_id, "")
        if eid in local_deleted:
            plan.deletions.append(Deletion(local_deleted[eid], Side.LOCAL, entry, name))
        else:
            plan.new_entries.append(NewEntry(entry, Side.REMOTE, name))

    if local_keys is not None and remote_keys is not None:
        plan.keys_from = keys_source(local_keys, remote_keys, remote_verified=remote_verified)

    plan.new_entries.sort(key=lambda n: n.entry.title.casefold())
    plan.conflicts.sort(key=lambda c: c.local.title.casefold())
    plan.deletions.sort(key=lambda d: d.item.title.casefold())
    return plan


# --------------------------------------------------------------------- apply


class _Sides:
    def __init__(self, local: Repository, remote: Repository) -> None:
        self.repo = {Side.LOCAL: local, Side.REMOTE: remote}
        self.cats = {Side.LOCAL: _categories(local), Side.REMOTE: _categories(remote)}

    def ensure_category(self, entry: Entry, source: Side) -> Entry:
        """Make sure the entry's category exists on the other side; return the mapped entry."""
        target = source.other
        source_cat = self.cats[source].get(entry.category_id)
        if entry.category_id in self.cats[target]:
            return entry
        by_name = {c.name.casefold(): c.id for c in self.cats[target].values()}
        if source_cat is not None and source_cat.name.casefold() in by_name:
            return replace(entry, category_id=by_name[source_cat.name.casefold()])
        if source_cat is None:  # should not happen; fall back to any category
            fallback = next(iter(self.cats[target]))
            return replace(entry, category_id=fallback)
        self.repo[target].upsert_category(source_cat)
        self.cats[target][source_cat.id] = source_cat
        return entry

    def copy(self, entry: Entry, source: Side) -> None:
        self.repo[source.other].upsert_entry(self.ensure_category(entry, source))


def _sync_categories(
    sides: _Sides, local_deleted: Iterable[DeletedItem], remote_deleted: Iterable[DeletedItem]
) -> None:
    deleted = {
        Side.LOCAL: {d.id for d in local_deleted},
        Side.REMOTE: {d.id for d in remote_deleted},
    }
    for source in (Side.LOCAL, Side.REMOTE):
        target = source.other
        target_names = {c.name.casefold() for c in sides.cats[target].values()}
        for cid, cat in list(sides.cats[source].items()):
            other = sides.cats[target].get(cid)
            if other is None:
                if cid in deleted[target] or cat.name.casefold() in target_names:
                    continue
                sides.repo[target].upsert_category(cat)
                sides.cats[target][cid] = cat
                target_names.add(cat.name.casefold())
            elif other.name != cat.name and cat.updated_at > other.updated_at:
                if (
                    cat.name.casefold() in target_names
                    and cat.name.casefold() != other.name.casefold()
                ):
                    continue  # the new name is taken on the other side; keep it as is
                sides.repo[target].upsert_category(cat)
                sides.cats[target][cid] = cat


def apply_sync(
    local: Repository,
    remote: Repository,
    plan: SyncPlan,
    choices: SyncChoices,
) -> SyncResult:
    """Apply the contents of the plan to both sides (keys are switched by the caller)."""
    result = SyncResult()
    local_deleted, remote_deleted = local.list_deleted(), remote.list_deleted()
    with local.batch(), remote.batch():
        sides = _Sides(local, remote)
        _sync_categories(sides, local_deleted, remote_deleted)

        for new in plan.new_entries:
            sides.copy(new.entry, new.source)
            if new.source is Side.LOCAL:
                result.copied_to_remote += 1
            else:
                result.copied_to_local += 1

        for conflict in plan.conflicts:
            keep = choices.keep.get(conflict.id, conflict.newer)
            sides.copy(conflict.local if keep is Side.LOCAL else conflict.remote, keep)
            result.conflicts_resolved += 1

        for deletion in plan.deletions:
            holder = deletion.deleted_on.other  # the side that still has the entry
            if deletion.item.id in choices.delete:
                sides.repo[holder].apply_deletion(deletion.item)
                if holder is Side.REMOTE:
                    result.deleted_remote += 1
                else:
                    result.deleted_local += 1
            else:  # keep it: bring it back where it was deleted
                sides.copy(deletion.existing, holder)
                result.kept_instead_of_deleting += 1

        # Merge the remaining deletion records (entries already gone on both sides etc.).
        shown = {d.item.id for d in plan.deletions}
        for source, records in ((Side.LOCAL, local_deleted), (Side.REMOTE, remote_deleted)):
            target_repo = sides.repo[source.other]
            known = {d.id for d in target_repo.list_deleted()}
            for record in records:
                if record.id in shown or record.id in known:
                    continue
                if record.kind == "category":
                    still_used = any(
                        e.category_id == record.id for e in target_repo.list_entries(record.id)
                    )
                    if still_used:
                        continue
                if record.kind == "entry" and target_repo.find_entry(record.id) is not None:
                    continue  # handled as a deletion choice above
                target_repo.apply_deletion(record)

        # Older data keys: both sides should be able to open any older copy.
        local_old, remote_old = set(local.old_data_keys()), set(remote.old_data_keys())
        if remote_old - local_old:
            local.remember_old_data_keys(remote_old - local_old)
        if local_old - remote_old:
            remote.remember_old_data_keys(local_old - remote_old)

    if plan.keys_from is not None:
        result.password_updated_on = plan.keys_from.other
    return result
