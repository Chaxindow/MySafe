"""Sync screen: what will change on each side, GitHub-diff style.

* New entries (green +) are copied automatically — listed for information.
* Conflicts show both versions side by side; the user picks which one to keep.
* Deletions (red −) have a "Delete on … too" checkbox, ticked by default.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mysafe.sync import Conflict, Deletion, NewEntry, Side, SyncChoices, SyncPlan
from mysafe.ui.widgets import icon_button, push_button, repolish

MASK = "●" * 8


def _when(timestamp: int) -> str:
    moment = datetime.fromtimestamp(timestamp)
    return f"{moment.day} {moment:%b %H:%M}"


def _chip(symbol: str, kind: str) -> QLabel:
    chip = QLabel(symbol)
    chip.setObjectName("syncChip")
    chip.setProperty("kind", kind)  # add / change / delete
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setFixedSize(24, 24)
    return chip


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    return label


class ConflictCard(QFrame):
    """Both versions of one entry side by side, with "keep" radio buttons."""

    def __init__(self, conflict: Conflict, local_name: str, remote_name: str) -> None:
        super().__init__()
        self.setObjectName("syncCard")
        self.conflict = conflict
        self._revealed = False
        self._value_cells: list[tuple[QLabel, QLabel, str | None, str | None, bool, bool]] = []

        header = QHBoxLayout()
        header.addWidget(_chip("~", "change"))
        title = QLabel(conflict.local.title)
        title.setObjectName("syncTitle")
        header.addWidget(title)
        category = QLabel(conflict.category_name)
        category.setObjectName("hint")
        header.addWidget(category)
        header.addStretch(1)
        has_secret = any(r.secret and not r.same for r in conflict.rows)
        self.reveal_button = icon_button("eye", "Show hidden values", checkable=True)
        self.reveal_button.setVisible(has_secret)
        self.reveal_button.toggled.connect(self._on_reveal)
        header.addWidget(self.reveal_button)

        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        newer = conflict.newer
        for col, (side, name, entry) in enumerate(
            ((Side.LOCAL, local_name, conflict.local), (Side.REMOTE, remote_name, conflict.remote)),
            start=1,
        ):
            text = f"{name} · edited {_when(entry.updated_at)}"
            head = QLabel(f"{text}  ★ newer" if side is newer else text)
            head.setObjectName("syncHead")
            head.setProperty("newer", side is newer)
            grid.addWidget(head, 0, col)
        for row, diff in enumerate(conflict.rows, start=1):
            label = QLabel(diff.label)
            label.setObjectName("syncLabel")
            left, right = QLabel(), QLabel()
            for cell in (left, right):
                cell.setObjectName("syncCell")
                cell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                cell.setWordWrap(True)
            grid.addWidget(label, row, 0)
            grid.addWidget(left, row, 1)
            grid.addWidget(right, row, 2)
            self._value_cells.append((left, right, diff.local, diff.remote, diff.secret, diff.same))

        self.keep_local = QRadioButton(f"Keep {local_name.lower()}'s version")
        self.keep_remote = QRadioButton(f"Keep {remote_name}'s version")
        self.group = QButtonGroup(self)
        for button in (self.keep_local, self.keep_remote):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(button)
            button.toggled.connect(self._paint)
        (self.keep_local if newer is Side.LOCAL else self.keep_remote).setChecked(True)
        picks = QHBoxLayout()
        picks.setContentsMargins(12, 8, 12, 10)
        picks.addWidget(self.keep_local, 1)
        picks.addWidget(self.keep_remote, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header_box = QWidget()
        header_box.setLayout(header)
        header.setContentsMargins(12, 8, 8, 8)
        layout.addWidget(header_box)
        layout.addLayout(grid)
        layout.addLayout(picks)
        self._paint()

    def kept_side(self) -> Side:
        return Side.LOCAL if self.keep_local.isChecked() else Side.REMOTE

    def choose(self, side: Side) -> None:
        (self.keep_local if side is Side.LOCAL else self.keep_remote).setChecked(True)

    def _on_reveal(self, checked: bool) -> None:
        self._revealed = checked
        self.reveal_button.setToolTip("Hide values" if checked else "Show hidden values")
        self._paint()

    def _paint(self, *_: object) -> None:
        keep = self.kept_side()
        for left, right, local, remote, secret, same in self._value_cells:
            for cell, value, side in ((left, local, Side.LOCAL), (right, remote, Side.REMOTE)):
                if value is None:
                    text = "—"
                elif secret and not self._revealed:
                    text = MASK
                else:
                    text = value or "—"
                cell.setText(text)
                state = "same" if same else ("keep" if side is keep else "drop")
                cell.setProperty("state", state)
                repolish(cell)


class SyncDialog(QDialog):
    def __init__(
        self,
        plan: SyncPlan,
        *,
        local_name: str = "This computer",
        remote_name: str = "USB",
        remote_location: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sync")
        self.resize(900, 680)
        self.plan = plan
        self.cards: list[ConflictCard] = []
        self.delete_boxes: dict[str, QCheckBox] = {}

        title = QLabel("Sync")
        title.setObjectName("screenTitle")
        sides = QLabel(f"{local_name}  ⇄  {remote_name}  {remote_location}")
        sides.setObjectName("hint")
        top = QHBoxLayout()
        top.setContentsMargins(22, 16, 22, 12)
        top.addWidget(title)
        top.addSpacing(12)
        top.addWidget(sides, 1)

        body = QWidget()
        body.setObjectName("detailPage")
        content = QVBoxLayout(body)
        content.setContentsMargins(22, 6, 22, 16)
        content.setSpacing(8)

        if plan.keys_from is not None:
            where = local_name if plan.keys_from is Side.LOCAL else remote_name
            other = remote_name if plan.keys_from is Side.LOCAL else local_name.lower()
            note = QLabel(
                f"The master password / recovery key was changed on {where}. "
                f"{other[0].upper() + other[1:]} will use the same one after this sync."
            )
            note.setObjectName("syncNote")
            note.setWordWrap(True)
            content.addWidget(note)

        if plan.new_entries:
            content.addWidget(_section("New entries — copied automatically"))
            for new in plan.new_entries:
                content.addWidget(self._new_row(new, local_name, remote_name))
        if plan.conflicts:
            content.addSpacing(6)
            content.addWidget(_section("Changed on both sides — choose which version to keep"))
            for conflict in plan.conflicts:
                card = ConflictCard(conflict, local_name, remote_name)
                self.cards.append(card)
                content.addWidget(card)
        if plan.deletions:
            content.addSpacing(6)
            content.addWidget(_section("Deleted on one side"))
            for deletion in plan.deletions:
                content.addWidget(self._deletion_row(deletion, local_name, remote_name))
        if plan.category_updates:
            content.addSpacing(6)
            count = plan.category_updates
            content.addWidget(
                _section(
                    f"{count} category change{'s' if count != 1 else ''} applied automatically"
                )
            )
        content.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)

        self.newest_button = push_button(
            "Use newest for all",
            variant="ghost",
            tooltip="Keep the newer version of every conflict",
        )
        self.newest_button.setVisible(bool(plan.conflicts))
        self.newest_button.clicked.connect(self.use_newest_for_all)
        backups = QLabel("Backups of both vaults are made first.")
        backups.setObjectName("hint")
        cancel = push_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.sync_button = push_button("Sync", variant="primary")
        self.sync_button.setDefault(True)
        self.sync_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.setContentsMargins(22, 12, 22, 14)
        footer.addWidget(self.newest_button)
        footer.addStretch(1)
        footer.addWidget(backups)
        footer.addSpacing(10)
        footer.addWidget(cancel)
        footer.addWidget(self.sync_button)

        divider_top, divider_bottom = QFrame(), QFrame()
        for divider in (divider_top, divider_bottom):
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setStyleSheet("color: palette(mid);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(divider_top)
        layout.addWidget(scroll, 1)
        layout.addWidget(divider_bottom)
        layout.addLayout(footer)

    # ------------------------------------------------------------------ rows

    @staticmethod
    def _row_frame() -> tuple[QFrame, QHBoxLayout]:
        frame = QFrame()
        frame.setObjectName("syncRow")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(10)
        return frame, row

    def _new_row(self, new: NewEntry, local_name: str, remote_name: str) -> QFrame:
        frame, row = self._row_frame()
        row.addWidget(_chip("+", "add"))
        title = QLabel(new.entry.title)
        title.setObjectName("syncTitle")
        row.addWidget(title)
        category = QLabel(new.category_name)
        category.setObjectName("hint")
        row.addWidget(category)
        row.addStretch(1)
        source, target = (
            (local_name, remote_name) if new.source is Side.LOCAL else (remote_name, local_name)
        )
        direction = QLabel(f"{source} → {target}")
        direction.setObjectName("hint")
        row.addWidget(direction)
        return frame

    def _deletion_row(self, deletion: Deletion, local_name: str, remote_name: str) -> QFrame:
        frame, row = self._row_frame()
        row.addWidget(_chip("−", "delete"))
        title = QLabel(deletion.item.title)
        title.setObjectName("syncTitle")
        row.addWidget(title)
        where = local_name.lower() if deletion.deleted_on is Side.LOCAL else remote_name
        holder = remote_name if deletion.deleted_on is Side.LOCAL else local_name.lower()
        detail = f"deleted on {where} · {_when(deletion.item.deleted_at)}"
        if deletion.edited_after_deletion:
            detail += f" · edited on {holder} after that"
        info = QLabel(detail)
        info.setObjectName("hint")
        row.addWidget(info)
        row.addStretch(1)
        box = QCheckBox(f"Delete on {holder} too")
        box.setChecked(True)
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_boxes[deletion.item.id] = box
        row.addWidget(box)
        return frame

    # --------------------------------------------------------------- results

    def use_newest_for_all(self) -> None:
        for card in self.cards:
            card.choose(card.conflict.newer)

    def choices(self) -> SyncChoices:
        return SyncChoices(
            keep={card.conflict.id: card.kept_side() for card in self.cards},
            delete={item_id for item_id, box in self.delete_boxes.items() if box.isChecked()},
        )
