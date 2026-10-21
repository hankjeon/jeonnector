"""색상 칸 표시: 글자색 선택과, 선택한 행에서도 색이 보이도록 그리는 위임자."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem


def readable_text_color(background: QColor) -> str:
    luminance = (
        0.299 * background.red()
        + 0.587 * background.green()
        + 0.114 * background.blue()
    )
    return "#ffffff" if luminance < 145 else "#0f172a"


class ColorCellDelegate(QStyledItemDelegate):
    """선택한 행에서도 칸의 배경색·글자색을 그대로 그리고, 선택 표시는 안쪽 테두리로 한다."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        plain = QStyleOptionViewItem(option)
        plain.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, plain, index)
        if not selected:
            return
        painter.save()
        rect = option.rect
        painter.setPen(QPen(option.palette.highlight().color(), 2))
        painter.drawRect(rect.adjusted(1, 1, -2, -2))
        # 선택색과 비슷한 칸 색에서도 테두리가 보이도록 안쪽에 흰 선을 한 줄 더 긋는다.
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.drawRect(rect.adjusted(3, 3, -4, -4))
        painter.restore()
