"""All reads and writes for categories, entries and fields.

This is the only module that runs SQL against the app's data. Keeping every query here
means encryption can later be added in one place.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager

from mysafe.models import (
    DEFAULT_CATEGORIES,
    Category,
    DeletedItem,
    Entry,
    Field,
    FieldInput,
    FieldKind,
)

# Fields whose values are included in search (never secrets).
_SEARCHABLE_KINDS: tuple[str, ...] = (
    FieldKind.EMAIL.value,
    FieldKind.USERNAME.value,
    FieldKind.URL.value,
)

_META_SEEDED = "default_categories_seeded"


class RepositoryError(Exception):
    """Base class for expected, user-facing data errors."""


class NotFoundError(RepositoryError):
    pass


class DuplicateCategoryError(RepositoryError):
    pass


class CategoryNotEmptyError(RepositoryError):
    def __init__(self, category_id: str, entry_count: int) -> None:
        super().__init__(f"Category still contains {entry_count} entries")
        self.category_id = category_id
        self.entry_count = entry_count


def _new_id() -> str:
    return str(uuid.uuid4())


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean_name(name: str, what: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError(f"{what} cannot be empty")
    return cleaned


def _clean_optional(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    return cleaned or None


class Repository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], int] | None = None,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock or (lambda: int(time.time()))
        # Called after every successful write (the encrypted vault saves itself here).
        self._on_change = on_change
        self._suspended = 0
        self._pending_change = False

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        self._on_change = callback

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    @contextmanager
    def _write(self) -> Iterator[None]:
        """One transaction; on success, notify `on_change` (e.g. save the vault)."""
        with self._conn:
            yield
        if self._suspended:
            self._pending_change = True
        else:
            self._changed()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group many writes (e.g. a Sync) into a single save at the end."""
        self._suspended += 1
        try:
            yield
        finally:
            self._suspended -= 1
            if not self._suspended and self._pending_change:
                self._pending_change = False
                self._changed()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ setup

    def ensure_default_categories(self) -> bool:
        """Create the default categories the very first time the app runs.

        Returns True if they were created. Runs only once per database, so categories the
        user deletes later do not come back.
        """
        if self._get_meta(_META_SEEDED) == "1":
            return False
        with self._write():
            existing = int(self._conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0])
            if existing == 0:
                for order, (name, icon) in enumerate(DEFAULT_CATEGORIES):
                    self._insert_category(name, icon, order)
            self._set_meta(_META_SEEDED, "1")
        return existing == 0

    # ------------------------------------------------------------- categories

    def list_categories(self) -> list[Category]:
        rows = self._conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, name COLLATE NOCASE"
        ).fetchall()
        return [self._row_to_category(r) for r in rows]

    def get_category(self, category_id: str) -> Category:
        row = self._conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Category {category_id} not found")
        return self._row_to_category(row)

    def entry_counts(self) -> dict[str, int]:
        """Number of entries in each category (categories with no entries are omitted)."""
        rows = self._conn.execute(
            "SELECT category_id, COUNT(*) AS n FROM entries GROUP BY category_id"
        ).fetchall()
        return {r["category_id"]: r["n"] for r in rows}

    def create_category(self, name: str, icon: str | None = None) -> Category:
        name = _clean_name(name, "Category name")
        next_order = self._conn.execute(
            "SELECT COALESCE(MAX(sort_order) + 1, 0) FROM categories"
        ).fetchone()[0]
        with self._write():
            category_id = self._insert_category(name, icon, next_order)
        return self.get_category(category_id)

    def rename_category(self, category_id: str, new_name: str) -> Category:
        new_name = _clean_name(new_name, "Category name")
        self.get_category(category_id)
        try:
            with self._write():
                self._conn.execute(
                    "UPDATE categories SET name = ?, updated_at = ? WHERE id = ?",
                    (new_name, self._clock(), category_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateCategoryError(f"A category named '{new_name}' already exists") from exc
        return self.get_category(category_id)

    def set_category_icon(self, category_id: str, icon: str | None) -> Category:
        self.get_category(category_id)
        with self._write():
            self._conn.execute(
                "UPDATE categories SET icon = ?, updated_at = ? WHERE id = ?",
                (icon, self._clock(), category_id),
            )
        return self.get_category(category_id)

    def reorder_categories(self, ordered_ids: Sequence[str]) -> None:
        """Save a new category order. `ordered_ids` must contain every category exactly once."""
        current = {c.id for c in self.list_categories()}
        if set(ordered_ids) != current or len(ordered_ids) != len(current):
            raise ValueError("ordered_ids must contain every category exactly once")
        with self._write():
            self._conn.executemany(
                "UPDATE categories SET sort_order = ? WHERE id = ?",
                [(i, cid) for i, cid in enumerate(ordered_ids)],
            )

    def move_entries(self, from_category_id: str, to_category_id: str) -> int:
        """Move every entry from one category to another. Returns how many were moved."""
        self.get_category(from_category_id)
        self.get_category(to_category_id)
        with self._write():
            cur = self._conn.execute(
                "UPDATE entries SET category_id = ?, updated_at = ? WHERE category_id = ?",
                (to_category_id, self._clock(), from_category_id),
            )
        return cur.rowcount

    def delete_category(self, category_id: str) -> None:
        """Delete an empty category. Raises CategoryNotEmptyError if it still has entries."""
        self.get_category(category_id)
        count = self._conn.execute(
            "SELECT COUNT(*) FROM entries WHERE category_id = ?", (category_id,)
        ).fetchone()[0]
        if count:
            raise CategoryNotEmptyError(category_id, count)
        category = self.get_category(category_id)
        with self._write():
            self._conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            self._record_deletion(category_id, "category", category.name)

    # ---------------------------------------------------------------- entries

    def list_entries(
        self,
        category_id: str | None = None,
        *,
        favorites_only: bool = False,
        search: str | None = None,
    ) -> list[Entry]:
        """List entries (without their fields), sorted by title.

        `search` matches the title, the entry URL and email/username/url field values.
        Secret values are never searched.
        """
        where: list[str] = []
        params: list[object] = []
        if category_id is not None:
            where.append("e.category_id = ?")
            params.append(category_id)
        if favorites_only:
            where.append("e.favorite = 1")
        term = (search or "").strip()
        if term:
            like = f"%{_escape_like(term)}%"
            where.append(
                "(e.title LIKE ? ESCAPE '\\' OR e.url LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM fields f WHERE f.entry_id = e.id "
                "AND f.kind IN (?, ?, ?) AND f.value LIKE ? ESCAPE '\\'))"
            )
            params.extend([like, like, *_SEARCHABLE_KINDS, like])
        sql = "SELECT e.* FROM entries e"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.title COLLATE NOCASE, e.created_at"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_entry(self, entry_id: str) -> Entry:
        """Return an entry together with all of its fields."""
        row = self._conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Entry {entry_id} not found")
        entry = self._row_to_entry(row)
        entry.fields = self._fields_for(entry_id)
        return entry

    def create_entry(
        self,
        category_id: str,
        title: str,
        fields: Iterable[FieldInput] = (),
        *,
        url: str | None = None,
        notes: str | None = None,
        favorite: bool = False,
    ) -> Entry:
        title = _clean_name(title, "Title")
        self.get_category(category_id)
        entry_id = _new_id()
        now = self._clock()
        with self._write():
            self._conn.execute(
                "INSERT INTO entries (id, category_id, title, url, notes, favorite, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    category_id,
                    title,
                    _clean_optional(url),
                    notes or None,
                    int(favorite),
                    now,
                    now,
                ),
            )
            self._insert_fields(entry_id, fields)
        return self.get_entry(entry_id)

    def update_entry(
        self,
        entry_id: str,
        *,
        category_id: str,
        title: str,
        fields: Iterable[FieldInput],
        url: str | None = None,
        notes: str | None = None,
        favorite: bool = False,
    ) -> Entry:
        """Save an edited entry. The field list replaces the old one completely."""
        title = _clean_name(title, "Title")
        self.get_entry(entry_id)
        self.get_category(category_id)
        with self._write():
            self._conn.execute(
                "UPDATE entries SET category_id = ?, title = ?, url = ?, notes = ?, "
                "favorite = ?, updated_at = ? WHERE id = ?",
                (
                    category_id,
                    title,
                    _clean_optional(url),
                    notes or None,
                    int(favorite),
                    self._clock(),
                    entry_id,
                ),
            )
            self._conn.execute("DELETE FROM fields WHERE entry_id = ?", (entry_id,))
            self._insert_fields(entry_id, fields)
        return self.get_entry(entry_id)

    def set_favorite(self, entry_id: str, favorite: bool) -> None:
        with self._write():
            cur = self._conn.execute(
                "UPDATE entries SET favorite = ?, updated_at = ? WHERE id = ?",
                (int(favorite), self._clock(), entry_id),
            )
        if cur.rowcount == 0:
            raise NotFoundError(f"Entry {entry_id} not found")

    def delete_entry(self, entry_id: str) -> None:
        row = self._conn.execute("SELECT title FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Entry {entry_id} not found")
        with self._write():
            self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._record_deletion(entry_id, "entry", str(row["title"]))

    def list_deleted(self) -> list[DeletedItem]:
        """Deletions remembered for Sync, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM deleted_items ORDER BY deleted_at DESC, title COLLATE NOCASE"
        ).fetchall()
        return [DeletedItem(r["id"], r["kind"], r["title"], int(r["deleted_at"])) for r in rows]

    def _record_deletion(self, item_id: str, kind: str, title: str) -> None:
        self._conn.execute(
            "INSERT INTO deleted_items (id, kind, title, deleted_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET deleted_at = excluded.deleted_at, "
            "title = excluded.title",
            (item_id, kind, title, self._clock()),
        )

    def count_entries(self, *, favorites_only: bool = False) -> int:
        if favorites_only:
            row = self._conn.execute("SELECT COUNT(*) FROM entries WHERE favorite = 1").fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        return int(row[0])

    # ------------------------------------------------------------------- sync
    # Low-level copies used by Sync: ids and timestamps are kept exactly as given.

    def find_entry(self, entry_id: str) -> Entry | None:
        try:
            return self.get_entry(entry_id)
        except NotFoundError:
            return None

    def all_entries(self) -> list[Entry]:
        """Every entry including its fields."""
        return [self.get_entry(e.id) for e in self.list_entries()]

    def upsert_category(self, category: Category) -> None:
        with self._write():
            self._conn.execute(
                "INSERT INTO categories (id, name, icon, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
                "icon = excluded.icon, updated_at = excluded.updated_at",
                (
                    category.id,
                    category.name,
                    category.icon,
                    category.sort_order,
                    category.created_at,
                    category.updated_at,
                ),
            )
            self._conn.execute("DELETE FROM deleted_items WHERE id = ?", (category.id,))

    def upsert_entry(self, entry: Entry) -> None:
        """Insert or overwrite an entry (with its fields) exactly as given."""
        with self._write():
            self._conn.execute(
                "INSERT INTO entries (id, category_id, title, url, notes, favorite, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "category_id = excluded.category_id, title = excluded.title, url = excluded.url, "
                "notes = excluded.notes, favorite = excluded.favorite, "
                "created_at = excluded.created_at, updated_at = excluded.updated_at",
                (
                    entry.id,
                    entry.category_id,
                    entry.title,
                    entry.url,
                    entry.notes,
                    int(entry.favorite),
                    entry.created_at,
                    entry.updated_at,
                ),
            )
            self._conn.execute("DELETE FROM fields WHERE entry_id = ?", (entry.id,))
            self._conn.executemany(
                "INSERT INTO fields (id, entry_id, label, value, kind, is_secret, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (f.id, entry.id, f.label, f.value, f.kind.value, int(f.is_secret), i)
                    for i, f in enumerate(entry.fields)
                ],
            )
            self._conn.execute("DELETE FROM deleted_items WHERE id = ?", (entry.id,))

    def apply_deletion(self, item: DeletedItem) -> None:
        """Delete the entry/category if present and remember the deletion (keeping its time)."""
        with self._write():
            if item.kind == "entry":
                self._conn.execute("DELETE FROM entries WHERE id = ?", (item.id,))
            else:
                self._conn.execute("DELETE FROM categories WHERE id = ?", (item.id,))
            self._conn.execute(
                "INSERT INTO deleted_items (id, kind, title, deleted_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET deleted_at = MAX(deleted_at, excluded.deleted_at)",
                (item.id, item.kind, item.title, item.deleted_at),
            )

    def forget_deletion(self, item_id: str) -> None:
        with self._write():
            self._conn.execute("DELETE FROM deleted_items WHERE id = ?", (item_id,))

    # --------------------------------------------------------------- settings

    # ------------------------------------------------------------ key history

    def old_data_keys(self) -> list[bytes]:
        """Data keys this vault used before, newest first (to open older copies)."""
        rows = self._conn.execute(
            "SELECT data_key FROM key_history ORDER BY retired_at DESC"
        ).fetchall()
        return [bytes(row[0]) for row in rows]

    def remember_old_data_keys(self, keys: Iterable[bytes], retired_at: int | None = None) -> None:
        """Keep retired data keys (ignored if already known)."""
        when = self._clock() if retired_at is None else retired_at
        with self._write():
            self._conn.executemany(
                "INSERT OR IGNORE INTO key_history (data_key, retired_at) VALUES (?, ?)",
                [(bytes(key), when) for key in keys],
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Read an app setting (e.g. theme). Setting keys starting with '_' are reserved."""
        value = self._get_meta(f"setting.{key}")
        return default if value is None else value

    def set_setting(self, key: str, value: str) -> None:
        with self._write():
            self._set_meta(f"setting.{key}", value)

    # --------------------------------------------------------------- helpers

    def _insert_category(self, name: str, icon: str | None, sort_order: int) -> str:
        category_id = _new_id()
        now = self._clock()
        try:
            self._conn.execute(
                "INSERT INTO categories (id, name, icon, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (category_id, name, icon, sort_order, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateCategoryError(f"A category named '{name}' already exists") from exc
        return category_id

    def _insert_fields(self, entry_id: str, fields: Iterable[FieldInput]) -> None:
        rows = []
        for order, f in enumerate(fields):
            label = _clean_name(f.label, "Field label")
            kind = FieldKind(f.kind)
            rows.append(
                (_new_id(), entry_id, label, f.value, kind.value, int(f.resolved_secret()), order)
            )
        self._conn.executemany(
            "INSERT INTO fields (id, entry_id, label, value, kind, is_secret, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def _fields_for(self, entry_id: str) -> list[Field]:
        rows = self._conn.execute(
            "SELECT * FROM fields WHERE entry_id = ? ORDER BY sort_order", (entry_id,)
        ).fetchall()
        return [
            Field(
                id=r["id"],
                entry_id=r["entry_id"],
                label=r["label"],
                value=r["value"],
                kind=FieldKind(r["kind"]),
                is_secret=bool(r["is_secret"]),
                sort_order=r["sort_order"],
            )
            for r in rows
        ]

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @staticmethod
    def _row_to_category(row: sqlite3.Row) -> Category:
        return Category(
            id=row["id"],
            name=row["name"],
            icon=row["icon"],
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> Entry:
        return Entry(
            id=row["id"],
            category_id=row["category_id"],
            title=row["title"],
            url=row["url"],
            notes=row["notes"],
            favorite=bool(row["favorite"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
