"""AppController tests (needs PySide6 + pytest-qt)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from mysafe.db import Repository  # noqa: E402
from mysafe.models import FieldInput, FieldKind  # noqa: E402
from mysafe.ui.controller import (  # noqa: E402
    DEFAULT_CLIPBOARD_CLEAR_SECONDS,
    AppController,
    EntryData,
)


@pytest.fixture
def controller(qtbot, seeded_repo: Repository) -> AppController:  # type: ignore[no-untyped-def]
    return AppController(seeded_repo)


def _games(controller: AppController) -> str:
    return next(c.id for c in controller.categories() if c.name == "Games")


def test_create_category_emits_signal(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    with qtbot.waitSignal(controller.categories_changed, timeout=1000):
        category = controller.create_category("Banking")
    assert category is not None and category.name == "Banking"


def test_errors_are_reported_not_raised(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    with qtbot.waitSignal(controller.error_occurred, timeout=1000) as blocker:
        assert controller.create_category("Games") is None
    assert "already exists" in blocker.args[0]
    with qtbot.waitSignal(controller.error_occurred, timeout=1000):
        assert controller.create_entry(EntryData(category_id=_games(controller), title=" ")) is None


def test_entry_lifecycle(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    data = EntryData(
        category_id=_games(controller),
        title="Steam",
        fields=[FieldInput("Password", "pw", FieldKind.PASSWORD)],
    )
    with qtbot.waitSignal(controller.entries_changed, timeout=1000):
        entry = controller.create_entry(data)
    assert entry is not None

    data.title = "Steam 2"
    with qtbot.waitSignal(controller.entries_changed, timeout=1000):
        updated = controller.update_entry(entry.id, data)
    assert updated is not None and updated.title == "Steam 2"

    assert controller.set_favorite(entry.id, True)
    assert controller.favorite_count() == 1

    assert controller.delete_entry(entry.id)
    assert controller.entry(entry.id) is None  # missing entry -> None, no error


def test_delete_category_moves_entries(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    games = _games(controller)
    other = next(c.id for c in controller.categories() if c.name == "Other")
    controller.create_entry(EntryData(category_id=games, title="Steam"))

    with qtbot.waitSignals([controller.categories_changed, controller.entries_changed]):
        assert controller.delete_category(games, move_entries_to=other)
    assert controller.entry_counts() == {other: 1}


def test_delete_non_empty_category_without_target_fails(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    games = _games(controller)
    controller.create_entry(EntryData(category_id=games, title="Steam"))
    with qtbot.waitSignal(controller.error_occurred, timeout=1000):
        assert not controller.delete_category(games)
    assert controller.category(games) is not None


def test_settings(qtbot, controller: AppController) -> None:  # type: ignore[no-untyped-def]
    assert controller.theme() == "system"
    assert controller.clipboard_clear_seconds() == DEFAULT_CLIPBOARD_CLEAR_SECONDS
    with qtbot.waitSignal(controller.settings_changed, timeout=1000):
        controller.save_settings(theme="dark", clipboard_clear_seconds=5)
    assert controller.theme() == "dark"
    assert controller.clipboard_clear_seconds() == 5
    with pytest.raises(ValueError):
        controller.save_settings(theme="purple", clipboard_clear_seconds=5)
