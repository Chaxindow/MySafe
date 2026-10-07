"""Custom painting for the category and entry lists (icon, counts, hover, selection)."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from mysafe.ui.icons import icon
from mysafe.ui.palette import current

ROLE_KEY = Qt.ItemDataRole.UserRole
ROLE_COUNT = Qt.ItemDataRole.UserRole + 1
ROLE_ICON = Qt.ItemDataRole.UserRole + 2
ROLE_SUBTITLE = Qt.ItemDataRole.UserRole + 3
ROLE_FAVORITE = Qt.ItemDataRole.UserRole + 4

Index = QModelIndex | QPersistentModelIndex


def _paint_background(painter: QPainter, option: QStyleOptionViewItem, rect: QRect) -> None:
    t = current()
    selected = bool(option.state & QStyle.StateFlag.State_Selected)
    hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
    painter.setPen(Qt.PenStyle.NoPen)
    if selected:
        painter.setBrush(QColor(t.accent_tint))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setBrush(QColor(t.accent))
        painter.drawRoundedRect(QRect(rect.left(), rect.top() + 6, 3, rect.height() - 12), 1.5, 1.5)
    elif hovered:
        painter.setBrush(QColor(t.hover))
        painter.drawRoundedRect(rect, 6, 6)


class SidebarDelegate(QStyledItemDelegate):
    """[icon] Name ............ count"""

    HEIGHT = 36

    def sizeHint(self, option: QStyleOptionViewItem, index: Index) -> QSize:
        return QSize(120, self.HEIGHT)  # width follows the view

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: Index) -> None:
        t = current()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(8, 2, -8, -2)
        _paint_background(painter, option, rect)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        icon_name = str(index.data(ROLE_ICON) or "folder")
        icon_color = t.accent if selected else t.muted
        icon_rect = QRect(rect.left() + 12, rect.center().y() - 8, 16, 16)
        icon(icon_name, icon_color).paint(painter, icon_rect)

        count = index.data(ROLE_COUNT)
        count_text = "" if count is None else str(count)
        font = QFont(option.font)
        painter.setFont(font)
        count_width = painter.fontMetrics().horizontalAdvance(count_text) + 4
        count_rect = QRect(rect.right() - 12 - count_width, rect.top(), count_width, rect.height())
        painter.setPen(QColor(t.muted))
        painter.drawText(
            count_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count_text
        )

        if selected:
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
        name_rect = QRect(
            icon_rect.right() + 10,
            rect.top(),
            count_rect.left() - icon_rect.right() - 16,
            rect.height(),
        )
        name = painter.fontMetrics().elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole)),
            Qt.TextElideMode.ElideRight,
            name_rect.width(),
        )
        painter.setPen(QColor(t.text))
        painter.drawText(
            name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name
        )
        painter.restore()


class EntryDelegate(QStyledItemDelegate):
    """Title (bold) over a muted subtitle, with a brass star for favorites."""

    HEIGHT = 54

    def sizeHint(self, option: QStyleOptionViewItem, index: Index) -> QSize:
        return QSize(120, self.HEIGHT)  # width follows the view

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: Index) -> None:
        t = current()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(8, 2, -8, -2)
        _paint_background(painter, option, rect)

        favorite = bool(index.data(ROLE_FAVORITE))
        right = rect.right() - 12
        if favorite:
            star_rect = QRect(right - 14, rect.center().y() - 7, 14, 14)
            icon("star", t.accent, filled=True).paint(painter, star_rect)
            right = star_rect.left() - 8

        text_left = rect.left() + 14
        width = right - text_left
        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(option.font.pointSizeF() - 1, 7))

        title = str(index.data(Qt.ItemDataRole.DisplayRole))
        subtitle = str(index.data(ROLE_SUBTITLE) or "")
        mid = rect.center().y()

        painter.setFont(title_font)
        painter.setPen(QColor(t.text))
        title = painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, width)
        title_rect = QRect(text_left, rect.top() + 6, width, mid - rect.top() - 4)
        if subtitle:
            painter.drawText(
                title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title
            )
            painter.setFont(sub_font)
            painter.setPen(QColor(t.muted))
            subtitle = painter.fontMetrics().elidedText(
                subtitle, Qt.TextElideMode.ElideRight, width
            )
            sub_rect = QRect(text_left, mid + 2, width, rect.bottom() - mid - 6)
            painter.drawText(
                sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, subtitle
            )
        else:
            painter.drawText(
                QRect(text_left, rect.top(), width, rect.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                title,
            )
        painter.restore()
