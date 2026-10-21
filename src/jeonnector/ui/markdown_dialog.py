"""마크다운 파일별 검사 결과와 선택 등록 대화상자."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

if TYPE_CHECKING:
    from jeonnector.markdown_exchange import MarkdownImportItem


class MarkdownImportDialog(QDialog):
    """원본이나 프로젝트를 수정하지 않고 등록할 정상 파일을 고른다."""

    def __init__(self, items: list[MarkdownImportItem], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("마크다운 가져오기 미리보기")
        self.resize(800, 400)
        self._items = items
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("정상 파일을 선택하여 새 연결기로 등록합니다. 원본 파일은 변경하지 않습니다."))
        self.table = QTableWidget(len(items), 5)
        self.table.setHorizontalHeaderLabels(["파일", "식별자", "신호 수", "행 수", "검사 결과"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for index, entry in enumerate(items):
            conn = entry.connector
            valid = conn is not None and not entry.error
            name = QTableWidgetItem(entry.path.name)
            name.setToolTip(str(entry.path))
            if valid:
                name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                name.setCheckState(Qt.CheckState.Checked)
            else:
                name.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(index, 0, name)
            values = [conn.designator if conn else "—", str(len(conn.signals)) if conn else "—",
                      str(len(conn.rows)) if conn else "—", entry.error or "\n".join(entry.warnings) or "정상"]
            for column, value in enumerate(values, 1):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(index, column, cell)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("선택 파일 등록")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.table.itemChanged.connect(self._update_accept)
        layout.addWidget(self.buttons)
        self._update_accept()

    def selected_items(self) -> list[MarkdownImportItem]:
        selected = []
        for index, entry in enumerate(self._items):
            cell = self.table.item(index, 0)
            if (entry.connector is not None and not entry.error and cell is not None
                    and cell.checkState() == Qt.CheckState.Checked):
                selected.append(entry)
        return selected

    def _update_accept(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.selected_items()))
