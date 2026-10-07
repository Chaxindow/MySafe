"""AppController — the only object in the UI that reads or changes data.

Panels never touch the Repository directly. They call the controller and refresh
themselves when it emits `categories_changed` / `entries_changed`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from PySide6.QtCore import QObject, Signal

from mysafe.db import Repository, RepositoryError
from mysafe.models import Category, Entry, FieldInput

T = TypeVar("T")

# Setting keys and defaults
THEME = "theme"  # "system" | "light" | "dark"
CLIPBOARD_CLEAR_SECONDS = "clipboard_clear_seconds"
AUTO_LOCK_MINUTES = "auto_lock_minutes"  # 0 = off (default)
SYNC_TARGET = "sync_target"  # path of the other vault (USB copy or computer)
THEMES = ("system", "light", "dark")
DEFAULT_THEME = "system"
DEFAULT_CLIPBOARD_CLEAR_SECONDS = 20


@dataclass(slots=True)
class EntryData:
    """Everything the entry editor produces."""

    category_id: str
    title: str
    url: str | None = None
    notes: str | None = None
    favorite: bool = False
    fields: list[FieldInput] = field(default_factory=list)


class AppController(QObject):
    categories_changed = Signal()
    entries_changed = Signal()
    settings_changed = Signal()
    error_occurred = Signal(str)

    def __init__(self, repo: Repository, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._repo = repo

    # ---------------------------------------------------------------- helpers

    def _attempt(self, action: Callable[[], T]) -> T | None:
        """Run a data change; turn expected errors into `error_occurred`."""
        try:
            return action()
        except (RepositoryError, ValueError) as exc:
            self.error_occurred.emit(str(exc))
            return None

    # ------------------------------------------------------------------ reads

    def categories(self) -> list[Category]:
        return self._repo.list_categories()

    def category(self, category_id: str) -> Category | None:
        return self._attempt(lambda: self._repo.get_category(category_id))

    def entry_counts(self) -> dict[str, int]:
        return self._repo.entry_counts()

    def total_entries(self) -> int:
        return self._repo.count_entries()

    def favorite_count(self) -> int:
        return self._repo.count_entries(favorites_only=True)

    def entries(
        self, category_id: str | None = None, *, favorites_only: bool = False, search: str = ""
    ) -> list[Entry]:
        return self._repo.list_entries(category_id, favorites_only=favorites_only, search=search)

    def entry(self, entry_id: str) -> Entry | None:
        """Return an entry with its fields, or None if it no longer exists (no error shown)."""
        try:
            return self._repo.get_entry(entry_id)
        except RepositoryError:
            return None

    # ------------------------------------------------------------- categories

    def create_category(self, name: str) -> Category | None:
        category = self._attempt(lambda: self._repo.create_category(name))
        if category is not None:
            self.categories_changed.emit()
        return category

    def rename_category(self, category_id: str, name: str) -> bool:
        ok = self._attempt(lambda: self._repo.rename_category(category_id, name)) is not None
        if ok:
            self.categories_changed.emit()
        return ok

    def reorder_categories(self, ordered_ids: Sequence[str]) -> bool:
        def run() -> bool:
            self._repo.reorder_categories(ordered_ids)
            return True

        ok = self._attempt(run) is not None
        if ok:
            self.categories_changed.emit()
        return ok

    def delete_category(self, category_id: str, move_entries_to: str | None = None) -> bool:
        """Delete a category. Its entries are first moved to `move_entries_to`, if given."""

        def run() -> bool:
            moved = 0
            if move_entries_to is not None:
                moved = self._repo.move_entries(category_id, move_entries_to)
            self._repo.delete_category(category_id)
            return moved > 0

        moved = self._attempt(run)
        if moved is None:
            return False
        self.categories_changed.emit()
        if moved:
            self.entries_changed.emit()
        return True

    # ---------------------------------------------------------------- entries

    def create_entry(self, data: EntryData) -> Entry | None:
        entry = self._attempt(
            lambda: self._repo.create_entry(
                data.category_id,
                data.title,
                data.fields,
                url=data.url,
                notes=data.notes,
                favorite=data.favorite,
            )
        )
        if entry is not None:
            self.entries_changed.emit()
        return entry

    def update_entry(self, entry_id: str, data: EntryData) -> Entry | None:
        entry = self._attempt(
            lambda: self._repo.update_entry(
                entry_id,
                category_id=data.category_id,
                title=data.title,
                fields=data.fields,
                url=data.url,
                notes=data.notes,
                favorite=data.favorite,
            )
        )
        if entry is not None:
            self.entries_changed.emit()
        return entry

    def set_favorite(self, entry_id: str, favorite: bool) -> bool:
        def run() -> bool:
            self._repo.set_favorite(entry_id, favorite)
            return True

        ok = self._attempt(run) is not None
        if ok:
            self.entries_changed.emit()
        return ok

    def delete_entry(self, entry_id: str) -> bool:
        def run() -> bool:
            self._repo.delete_entry(entry_id)
            return True

        ok = self._attempt(run) is not None
        if ok:
            self.entries_changed.emit()
        return ok

    # --------------------------------------------------------------- settings

    def theme(self) -> str:
        value = self._repo.get_setting(THEME, DEFAULT_THEME)
        return value if value in THEMES else DEFAULT_THEME

    def clipboard_clear_seconds(self) -> int:
        raw = self._repo.get_setting(CLIPBOARD_CLEAR_SECONDS)
        try:
            return max(0, int(raw)) if raw is not None else DEFAULT_CLIPBOARD_CLEAR_SECONDS
        except ValueError:
            return DEFAULT_CLIPBOARD_CLEAR_SECONDS

    def auto_lock_minutes(self) -> int:
        raw = self._repo.get_setting(AUTO_LOCK_MINUTES)
        try:
            return max(0, int(raw)) if raw is not None else 0
        except ValueError:
            return 0

    def save_settings(
        self, *, theme: str, clipboard_clear_seconds: int, auto_lock_minutes: int | None = None
    ) -> None:
        if theme not in THEMES:
            raise ValueError(f"Unknown theme: {theme}")
        with self._repo.batch():
            self._repo.set_setting(THEME, theme)
            self._repo.set_setting(CLIPBOARD_CLEAR_SECONDS, str(max(0, clipboard_clear_seconds)))
            if auto_lock_minutes is not None:
                self._repo.set_setting(AUTO_LOCK_MINUTES, str(max(0, auto_lock_minutes)))
        self.settings_changed.emit()

    def sync_target(self) -> str | None:
        return self._repo.get_setting(SYNC_TARGET)

    def set_sync_target(self, path: str) -> None:
        self._repo.set_setting(SYNC_TARGET, path)

    def refresh_all(self) -> None:
        """Tell every panel to reload (e.g. after a Sync changed many things at once)."""
        self.categories_changed.emit()
        self.entries_changed.emit()
