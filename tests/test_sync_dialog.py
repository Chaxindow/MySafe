"""Sync screen: rows, conflict cards, choices."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from mysafe.db import Repository, open_from_bytes, to_bytes  # noqa: E402
from mysafe.models import FieldInput, FieldKind  # noqa: E402
from mysafe.sync import Side, plan_sync  # noqa: E402
from mysafe.ui.sync_dialog import MASK, SyncDialog  # noqa: E402
from tests.conftest import FakeClock  # noqa: E402


def _plan(clock: FakeClock):  # type: ignore[no-untyped-def]
    local = Repository(open_from_bytes(), clock)
    local.ensure_default_categories()
    games = next(c.id for c in local.list_categories() if c.name == "Games")
    steam = local.create_entry(games, "Steam", [FieldInput("Password", "old", FieldKind.PASSWORD)])
    gone = local.create_entry(games, "Old game")
    remote = Repository(open_from_bytes(to_bytes(local.connection)), clock)
    clock.advance(10)
    remote.update_entry(
        steam.id,
        category_id=games,
        title="Steam",
        fields=[FieldInput("Password", "usb", FieldKind.PASSWORD)],
    )
    clock.advance(10)
    local.update_entry(
        steam.id,
        category_id=games,
        title="Steam",
        fields=[FieldInput("Password", "pc", FieldKind.PASSWORD)],
    )
    local.create_entry(games, "Riot")
    local.delete_entry(gone.id)
    return plan_sync(local, remote), steam.id, gone.id


def test_dialog_shows_everything_and_defaults(qtbot, clock: FakeClock) -> None:  # type: ignore[no-untyped-def]
    plan, steam, gone = _plan(clock)
    dialog = SyncDialog(plan, remote_location="E:\\MySafe-data\\vault.mysafe")
    qtbot.addWidget(dialog)
    assert len(dialog.cards) == 1 and list(dialog.delete_boxes) == [gone]
    choices = dialog.choices()
    assert choices.keep == {steam: Side.LOCAL}  # newer preselected
    assert choices.delete == {gone}  # ticked by default


def test_secrets_hidden_until_revealed_and_choice_changes(qtbot, clock: FakeClock) -> None:  # type: ignore[no-untyped-def]
    plan, steam, gone = _plan(clock)
    dialog = SyncDialog(plan)
    qtbot.addWidget(dialog)
    card = dialog.cards[0]
    texts = [c[0].text() for c in card._value_cells] + [c[1].text() for c in card._value_cells]
    assert MASK in texts and "pc" not in texts
    card.reveal_button.click()
    texts = [c[0].text() for c in card._value_cells] + [c[1].text() for c in card._value_cells]
    assert "pc" in texts and "usb" in texts

    card.keep_remote.click()
    dialog.delete_boxes[gone].setChecked(False)
    choices = dialog.choices()
    assert choices.keep == {steam: Side.REMOTE} and choices.delete == set()
    dialog.use_newest_for_all()
    assert dialog.choices().keep == {steam: Side.LOCAL}
