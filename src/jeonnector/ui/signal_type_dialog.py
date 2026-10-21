"""신호유형 관리 창 (제3.10절: 신호표와 같은 방식으로 표에서 바로 추가·이름 변경·색상 설정·삭제)."""

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
    QLineEdit,
    QMenu,
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
from jeonnector.ui.color_cell import ColorCellDelegate, readable_text_color


TYPE_NAME_RULE_MESSAGE = (
    "신호유형 이름은 영문자 또는 한글로 시작하고 영문 대문자·한글·숫자·언더스코어(_)만 사용할 수 있습니다(공백 불가, 32자 이하)."
)

COL_NAME = 0
COL_COLOR = 1
COL_ACTION = 2


def rename_signal_type(parent: QWidget, project: Project, old_name: str, raw: str) -> str:
    """신호유형 이름을 raw로 바꾸고 새 이름을 반환한다. 규칙 위반·중복이면 안내하고 빈 문자열."""
    if not is_valid_signal_type_name(raw):
        QMessageBox.warning(parent, "이름 규칙 오류", TYPE_NAME_RULE_MESSAGE)
        return ""
    norm = normalize_signal_type_name(raw)
    if not project.rename_signal_type(old_name, norm):
        QMessageBox.warning(
            parent, "이름 변경 불가", f"'{norm}' 신호유형이 이미 존재하거나 변경할 수 없습니다."
        )
        return ""
    return norm


def prompt_rename_signal_type(parent: QWidget, project: Project, old_name: str) -> str:
    """새 이름을 입력받아 신호유형 이름을 바꾸고 새 이름을 반환한다. 취소·실패 시 빈 문자열."""
    raw, ok = QInputDialog.getText(
        parent, "신호유형 이름 변경", f"'{old_name}'의 새 이름:", text=old_name
    )
    if not ok or not raw.strip():
        return ""
    return rename_signal_type(parent, project, old_name, raw)


def pick_signal_type_color(parent: QWidget, project: Project, type_name: str) -> bool:
    """색상 선택 창으로 신호유형 색상을 바꾼다. 바꾸었으면 True."""
    cur = project.signal_type_color(type_name)
    initial = QColor(cur) if cur else QColor("#3b82f6")
    chosen = QColorDialog.getColor(initial, parent, f"'{type_name}' 신호유형 색상 선택")
    if not chosen.isValid():
        return False
    project.set_signal_type_color(type_name, chosen.name())
    return True


def _paint_color_item(item: QTableWidgetItem, color_hex: str) -> None:
    item.setText(color_hex.upper() if color_hex else "없음")
    if color_hex:
        color = QColor(color_hex)
        item.setBackground(QBrush(color))
        item.setForeground(QBrush(QColor(readable_text_color(color))))


class SignalTypeDialog(QDialog):
    """프로젝트의 신호유형 목록을 신호표와 같은 방식으로 편집하는 대화상자 (제3.10절).

    이름 칸 더블클릭·F2로 이름 변경, 색상 칸 더블클릭·우클릭으로 색상 설정,
    마지막 입력 행에서 Enter로 추가, 행 헤더 우클릭으로 삭제한다.
    """

    signalTypesModified = Signal()

    def __init__(
        self, project: Project, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.project = project
        self._refreshing = False
        self._draft_name = ""
        self._draft_color = ""
        self.setWindowTitle("신호유형 관리")
        self.resize(520, 400)

        layout = QVBoxLayout(self)
        info = QLabel(
            "마지막 행에 입력 후 Enter로 추가 · 이름 더블클릭으로 변경 · 색상 더블클릭으로 선택 · "
            "행 헤더 우클릭으로 삭제\n"
            "• 이름을 바꾸면 해당 신호유형을 쓰던 신호가 바뀐 이름을 따라갑니다.\n"
            "• 삭제하면 해당 신호유형을 쓰던 신호는 '신호유형 없음'이 됩니다."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(info)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["신호유형", "색상", "입력"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_COLOR, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(COL_COLOR, 100)
        self.table.setColumnWidth(COL_ACTION, 130)
        v_header = self.table.verticalHeader()
        v_header.setDefaultSectionSize(28)
        v_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v_header.customContextMenuRequested.connect(self._on_vertical_header_context_menu)
        v_header.sectionClicked.connect(self.table.selectRow)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table.setItemDelegateForColumn(COL_COLOR, ColorCellDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = close_box.button(QDialogButtonBox.StandardButton.Close)
        close_button.setText("닫기")
        # 입력 행에서 Enter가 창을 닫지 않도록 기본 버튼으로 쓰지 않는다.
        close_button.setAutoDefault(False)
        close_box.rejected.connect(self.accept)
        layout.addWidget(close_box)

        self.refresh_table()

    def type_names(self) -> list[str]:
        return sorted(self.project.signal_types.keys(), key=natural_sort_key)

    def _type_at(self, row: int) -> str:
        names = self.type_names()
        return names[row] if 0 <= row < len(names) else ""

    def refresh_table(self, select_name: str = "") -> None:
        names = self.type_names()
        self._refreshing = True
        self.table.setRowCount(len(names) + 1)
        for row, name in enumerate(names):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            name_item.setData(Qt.ItemDataRole.UserRole, name)
            color_item = QTableWidgetItem()
            color_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            color_item.setToolTip("더블클릭: 색상 선택 · 우클릭: 메뉴")
            _paint_color_item(color_item, self.project.signal_types.get(name, ""))
            action_item = QTableWidgetItem("")
            action_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, COL_NAME, name_item)
            self.table.setItem(row, COL_COLOR, color_item)
            self.table.setItem(row, COL_ACTION, action_item)
        self._build_draft_row(len(names))
        self.table.setVerticalHeaderLabels([str(i + 1) for i in range(len(names))] + ["+"])
        self._refreshing = False
        if select_name in names:
            self.table.selectRow(names.index(select_name))
        else:
            self.table.clearSelection()

    def _build_draft_row(self, row: int) -> None:
        for col in (COL_NAME, COL_COLOR, COL_ACTION):
            placeholder = QTableWidgetItem("")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(row, col, placeholder)
        self.draft_name_edit = QLineEdit(self._draft_name)
        self.draft_name_edit.setPlaceholderText("새 신호유형 이름")
        self.draft_name_edit.textChanged.connect(self._set_draft_name)
        self.draft_name_edit.returnPressed.connect(self.add_draft_type)
        self.draft_color_button = QPushButton()
        self.draft_color_button.setAutoDefault(False)
        self.draft_color_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.draft_color_button.clicked.connect(self._pick_draft_color)
        self.draft_color_button.customContextMenuRequested.connect(self._draft_color_menu)
        self._update_draft_color_button()
        self.add_button = QPushButton("추가")
        self.reset_button = QPushButton("초기화")
        actions = QWidget()
        buttons = QHBoxLayout(actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(2)
        for button, slot in ((self.add_button, self.add_draft_type), (self.reset_button, self.reset_draft)):
            button.setAutoDefault(False)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        self.table.setCellWidget(row, COL_NAME, self.draft_name_edit)
        self.table.setCellWidget(row, COL_COLOR, self.draft_color_button)
        self.table.setCellWidget(row, COL_ACTION, actions)

    def _set_draft_name(self, text: str) -> None:
        self._draft_name = text

    def _update_draft_color_button(self) -> None:
        color = self._draft_color
        self.draft_color_button.setText(color.upper() if color else "없음")
        self.draft_color_button.setToolTip("클릭: 색상 선택 · 우클릭: 없음")
        self.draft_color_button.setStyleSheet(
            f"background-color: {color}; color: {readable_text_color(QColor(color))};"
            if color else ""
        )

    def _pick_draft_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._draft_color or "#3b82f6"), self, "새 신호유형 색상"
        )
        if chosen.isValid():
            self._draft_color = chosen.name()
            self._update_draft_color_button()

    def _draft_color_menu(self, pos) -> None:
        menu = QMenu(self)
        clear = menu.addAction("색상 없음")
        if menu.exec(self.draft_color_button.mapToGlobal(pos)) == clear:
            self._draft_color = ""
            self._update_draft_color_button()

    def reset_draft(self) -> None:
        self._draft_color = ""
        self.draft_name_edit.clear()
        self._update_draft_color_button()

    def add_draft_type(self) -> bool:
        """입력 행의 이름·색상으로 새 신호유형을 추가한다."""
        raw = self._draft_name.strip()
        if not raw:
            return False
        if not is_valid_signal_type_name(raw):
            QMessageBox.warning(self, "이름 규칙 오류", TYPE_NAME_RULE_MESSAGE)
            self.draft_name_edit.setFocus()
            return False
        norm = normalize_signal_type_name(raw)
        if norm in self.project.signal_types:
            QMessageBox.warning(self, "중복 이름", f"이미 존재하는 신호유형입니다: '{norm}'")
            self.draft_name_edit.setFocus()
            return False
        self.project.ensure_signal_type(norm, default_color=self._draft_color)
        self._draft_name, self._draft_color = "", ""
        self.refresh_table(select_name=norm)
        self.signalTypesModified.emit()
        self.draft_name_edit.setFocus()
        return True

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing or item.column() != COL_NAME:
            return
        old_name = item.data(Qt.ItemDataRole.UserRole)
        if not old_name:
            return
        raw = item.text().strip()
        if not raw or normalize_signal_type_name(raw) == old_name:
            self.refresh_table(select_name=old_name)
            return
        new_name = rename_signal_type(self, self.project, old_name, raw)
        self.refresh_table(select_name=new_name or old_name)
        if new_name:
            self.signalTypesModified.emit()

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        name = self._type_at(row)
        if col == COL_COLOR and name:
            self.pick_color(name)

    def pick_color(self, name: str) -> None:
        if pick_signal_type_color(self, self.project, name):
            self.refresh_table(select_name=name)
            self.signalTypesModified.emit()

    def clear_color(self, name: str) -> None:
        if self.project.set_signal_type_color(name, ""):
            self.refresh_table(select_name=name)
            self.signalTypesModified.emit()

    def build_cell_context_menu(self, row: int) -> QMenu | None:
        """이름·색상 칸 우클릭 메뉴: 이름 변경, 색상 선택, 색상 없음."""
        name = self._type_at(row)
        if not name:
            return None
        menu = QMenu(self)
        menu.addAction(f"'{name}' 이름 변경").triggered.connect(
            lambda: self.table.editItem(self.table.item(row, COL_NAME))
        )
        menu.addAction(f"'{name}' 색상 선택...").triggered.connect(lambda: self.pick_color(name))
        clear = menu.addAction(f"'{name}' 색상 없음")
        clear.setEnabled(bool(self.project.signal_type_color(name)))
        clear.triggered.connect(lambda: self.clear_color(name))
        return menu

    def _on_table_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        menu = self.build_cell_context_menu(index.row()) if index.isValid() else None
        if menu is not None:
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def build_row_header_menu(self, row: int) -> QMenu | None:
        name = self._type_at(row)
        if not name:
            return None
        menu = QMenu(self)
        menu.addAction(f"'{name}' 삭제").triggered.connect(lambda: self.delete_type(name))
        return menu

    def _on_vertical_header_context_menu(self, pos) -> None:
        row = self.table.verticalHeader().logicalIndexAt(pos)
        self.table.selectRow(row)
        menu = self.build_row_header_menu(row)
        if menu is not None:
            menu.exec(self.table.verticalHeader().mapToGlobal(pos))

    def delete_type(self, name: str) -> bool:
        """신호유형을 삭제한다. 쓰는 신호가 있으면 먼저 확인한다."""
        count = len(self.project.signals_with_type(name))
        if count:
            answer = QMessageBox.question(
                self,
                "신호유형 삭제 확인",
                f"'{name}' 신호유형을 쓰는 프로젝트 신호 {count}개가 '신호유형 없음'이 됩니다.\n"
                "삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        if not self.project.delete_signal_type(name):
            return False
        self.refresh_table()
        self.signalTypesModified.emit()
        return True
