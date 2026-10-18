"""신호유형 관리 창 (제3.10절: 신호유형 표 조회·추가·이름 변경·색상 설정·삭제)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jeonnector.model import (
    Project,
    is_valid_signal_type_name,
    natural_sort_key,
    normalize_signal_type_name,
)


class SignalTypeDialog(QDialog):
    """프로젝트의 신호유형 목록을 표로 관리하는 대화상자 (제3.10절)."""

    signalTypesModified = Signal()

    def __init__(
        self, project: Project, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("신호유형 관리")
        self.resize(480, 380)

        layout = QVBoxLayout(self)
        info = QLabel(
            "프로젝트의 신호유형과 색상을 관리합니다.\n"
            "• 이름을 바꾸면 해당 신호유형을 쓰던 신호가 바뀐 이름을 따라갑니다.\n"
            "• 삭제하면 해당 신호유형을 쓰던 신호는 '신호유형 없음'이 됩니다."
        )
        info.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(info)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["신호유형", "색상"])
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 140)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("추가")
        self.rename_btn = QPushButton("이름 변경")
        self.color_btn = QPushButton("색상 선택")
        self.clear_color_btn = QPushButton("색상 없음")
        self.delete_btn = QPushButton("삭제")

        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.rename_btn)
        btn_row.addWidget(self.color_btn)
        btn_row.addWidget(self.clear_color_btn)
        btn_row.addWidget(self.delete_btn)
        layout.addLayout(btn_row)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.accept)
        close_box.accepted.connect(self.accept)
        layout.addWidget(close_box)

        self.add_btn.clicked.connect(self._on_add_clicked)
        self.rename_btn.clicked.connect(self._on_rename_clicked)
        self.color_btn.clicked.connect(self._on_color_clicked)
        self.clear_color_btn.clicked.connect(self._on_clear_color_clicked)
        self.delete_btn.clicked.connect(self._on_delete_clicked)

        self.refresh_table()

    def selected_type_name(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return item.text().strip() if item else ""

    def refresh_table(self, select_name: str = "") -> None:
        names = sorted(self.project.signal_types.keys(), key=natural_sort_key)
        self.table.setRowCount(len(names))
        selected_row = 0
        for idx, t_name in enumerate(names):
            color_hex = self.project.signal_types.get(t_name, "")
            name_item = QTableWidgetItem(t_name)
            color_item = QTableWidgetItem(color_hex if color_hex else "없음")
            color_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color_hex:
                c = QColor(color_hex)
                color_item.setBackground(QBrush(c))
                lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                color_item.setForeground(
                    QBrush(QColor("#ffffff" if lum < 145 else "#0f172a"))
                )
            self.table.setItem(idx, 0, name_item)
            self.table.setItem(idx, 1, color_item)
            if select_name and t_name == select_name:
                selected_row = idx
        if names:
            self.table.selectRow(selected_row)

    def _on_add_clicked(self) -> None:
        raw, ok = QInputDialog.getText(
            self,
            "신호유형 추가",
            "새 신호유형 이름 (한글·영문 대문자·숫자·_, 공백 불가, 32자 이하):",
        )
        if not ok or not raw.strip():
            return
        if not is_valid_signal_type_name(raw):
            QMessageBox.warning(
                self,
                "이름 규칙 오류",
                "신호유형 이름은 영문자 또는 한글로 시작하고 영문 대문자·한글·숫자·언더스코어(_)만 사용할 수 있습니다(공백 불가, 32자 이하).",
            )
            return
        norm = normalize_signal_type_name(raw)
        if norm in self.project.signal_types:
            QMessageBox.warning(
                self, "중복 이름", f"이미 존재하는 신호유형입니다: '{norm}'"
            )
            return
        self.project.ensure_signal_type(norm, default_color="")
        self.refresh_table(select_name=norm)
        self.signalTypesModified.emit()

    def _on_rename_clicked(self) -> None:
        old_name = self.selected_type_name()
        if not old_name:
            return
        raw, ok = QInputDialog.getText(
            self,
            "신호유형 이름 변경",
            f"'{old_name}'의 새 이름:",
            text=old_name,
        )
        if not ok or not raw.strip():
            return
        if not is_valid_signal_type_name(raw):
            QMessageBox.warning(
                self,
                "이름 규칙 오류",
                "신호유형 이름은 영문자 또는 한글로 시작하고 영문 대문자·한글·숫자·언더스코어(_)만 사용할 수 있습니다(공백 불가, 32자 이하).",
            )
            return
        norm = normalize_signal_type_name(raw)
        if not self.project.rename_signal_type(old_name, norm):
            QMessageBox.warning(
                self,
                "이름 변경 불가",
                f"'{norm}' 신호유형이 이미 존재하거나 변경할 수 없습니다.",
            )
            return
        self.refresh_table(select_name=norm)
        self.signalTypesModified.emit()

    def _on_color_clicked(self) -> None:
        t_name = self.selected_type_name()
        if not t_name:
            return
        cur = self.project.signal_type_color(t_name)
        initial = QColor(cur) if cur else QColor("#3b82f6")
        chosen = QColorDialog.getColor(
            initial, self, f"'{t_name}' 신호유형 색상 선택"
        )
        if chosen.isValid():
            self.project.set_signal_type_color(t_name, chosen.name())
            self.refresh_table(select_name=t_name)
            self.signalTypesModified.emit()

    def _on_clear_color_clicked(self) -> None:
        t_name = self.selected_type_name()
        if not t_name:
            return
        self.project.set_signal_type_color(t_name, "")
        self.refresh_table(select_name=t_name)
        self.signalTypesModified.emit()

    def _on_delete_clicked(self) -> None:
        t_name = self.selected_type_name()
        if not t_name:
            return
        if self.project.delete_signal_type(t_name):
            self.refresh_table()
            self.signalTypesModified.emit()
