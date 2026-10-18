"""우측 신호표(SignalTablePanel) 및 입력 가능한 콤보 박스 델리게이트 (제3.6절, 제3.8절, 제3.9절, 제3.10절)."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jeonnector.model import (
    DUPLICATE_CELL_BG_COLOR,
    ConnectorInstance,
    ConnectorPart,
    Project,
    is_valid_signal_name,
    is_valid_signal_type_name,
    natural_sort_key,
    normalize_signal_name,
    normalize_signal_type_name,
)

COL_PIN = 0
COL_SIGNAL = 1
COL_SIGNAL_TYPE = 2
COL_CATEGORY = 2  # 하위 호환 별칭
COL_COLOR = 3


class EditableComboDelegate(QStyledItemDelegate):
    """핀 번호, 신호명, 신호유형 열을 위한 입력 가능한 콤보 박스(QComboBox) 델리게이트."""

    def __init__(self, table_panel: SignalTablePanel) -> None:
        super().__init__(table_panel.table)
        self.panel = table_panel

    def createEditor(self, parent: QWidget, option, index: QModelIndex) -> QWidget:  # noqa: N802
        col = index.column()
        row = index.row()
        conn = self.panel.connector
        project = self.panel.project
        part = self.panel.part

        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        if col == COL_PIN:
            # 제3.9절: 드롭다운 첫 항목에 '미할당'을 두고 핀 번호를 자연 정렬로 표시
            combo.addItem("미할당")
            if part is not None:
                for pin_des in part.pin_designators():
                    combo.addItem(pin_des)
            # 신호명 없이 핀 번호만 입력할 수 없으며, 부품이 없는 연결기에서도 입력 불가
            if conn is None or row >= len(conn.rows) or part is None:
                combo.setEnabled(False)
        elif col == COL_SIGNAL:
            if conn is not None:
                for sig_name in conn.signal_names():
                    combo.addItem(sig_name)
        elif col == COL_SIGNAL_TYPE:
            combo.addItem("없음")
            if project is not None:
                for type_name in sorted(
                    project.signal_types.keys(), key=natural_sort_key
                ):
                    combo.addItem(type_name)
            if conn is None or row >= len(conn.rows):
                combo.setEnabled(False)

        return combo

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:  # noqa: N802
        if isinstance(editor, QComboBox):
            current_text = str(index.data(Qt.ItemDataRole.EditRole) or "")
            if index.column() == COL_PIN and not current_text:
                current_text = "미할당"
            elif index.column() == COL_SIGNAL_TYPE and not current_text:
                current_text = "없음"
            idx = editor.findText(current_text)
            if idx >= 0:
                editor.setCurrentIndex(idx)
            editor.setEditText(current_text)

    def setModelData(self, editor: QWidget, model, index: QModelIndex) -> None:  # noqa: N802
        if not isinstance(editor, QComboBox):
            super().setModelData(editor, model, index)
            return
        text = editor.currentText()
        self.panel.apply_cell_edit(index.row(), index.column(), text)


class SignalTableWidget(QTableWidget):
    """Delete 키로 인한 실수 삭제를 차단하고 행 헤더 우클릭 삭제만 허용하는 신호표 위젯 (제3.6절)."""

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            event.ignore()
            return
        super().keyPressEvent(event)


class SignalTablePanel(QWidget):
    """선택한 연결기의 신호표 및 편집·정렬 기능을 제공하는 우측 패널."""

    dataChanged = Signal()
    pinSelectionChanged = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project: Project | None = None
        self.connector: ConnectorInstance | None = None
        self.part: ConnectorPart | None = None
        self._syncing = False
        self._sort_column: str = "pin"
        self._sort_descending: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.info_label = QLabel(
            "신호표 (마지막 빈 행에 신호명 입력 시 신호 생성 · 행 헤더 우클릭으로 삭제 · 열 헤더 클릭으로 정렬)"
        )
        self.info_label.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(self.info_label)

        self.table = SignalTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["핀 번호", "신호명", "신호유형", "색상"]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )

        h_header = self.table.horizontalHeader()
        h_header.setSectionsClickable(True)
        h_header.setSortIndicatorShown(True)
        h_header.setSortIndicator(COL_PIN, Qt.SortOrder.AscendingOrder)
        h_header.sectionClicked.connect(self._on_header_clicked)
        h_header.setSectionResizeMode(
            COL_PIN, QHeaderView.ResizeMode.Interactive
        )
        h_header.setSectionResizeMode(
            COL_SIGNAL, QHeaderView.ResizeMode.Stretch
        )
        h_header.setSectionResizeMode(
            COL_SIGNAL_TYPE, QHeaderView.ResizeMode.Interactive
        )
        h_header.setSectionResizeMode(
            COL_COLOR, QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(COL_PIN, 95)
        self.table.setColumnWidth(COL_SIGNAL_TYPE, 130)
        self.table.setColumnWidth(COL_COLOR, 110)

        # 행 헤더(제일 좌측 핸들 영역) 선택 및 우클릭 컨텍스트 메뉴 설정 (제3.6절)
        v_header = self.table.verticalHeader()
        v_header.setVisible(True)
        v_header.setDefaultSectionSize(28)
        v_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v_header.customContextMenuRequested.connect(
            self._on_vertical_header_context_menu
        )
        v_header.sectionClicked.connect(self.table.selectRow)

        # 셀 우클릭 시 색상 선택 / '없음' 설정 메뉴 제공
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            self._on_table_context_menu
        )

        self.delegate = EditableComboDelegate(self)
        self.table.setItemDelegateForColumn(COL_PIN, self.delegate)
        self.table.setItemDelegateForColumn(COL_SIGNAL, self.delegate)
        self.table.setItemDelegateForColumn(COL_SIGNAL_TYPE, self.delegate)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        layout.addWidget(self.table, 1)

    def set_context(
        self,
        project: Project | None,
        connector: ConnectorInstance | None,
        part: ConnectorPart | None,
    ) -> None:
        switching_connector = connector is not self.connector
        self.project = project
        self.connector = connector
        self.part = part
        if switching_connector and self.connector is not None:
            # 제3.6절: 처음 열 때는 핀 번호 오름차순이며 정렬 상태는 저장하지 않는다.
            self._sort_column = "pin"
            self._sort_descending = False
            self.table.horizontalHeader().setSortIndicator(
                COL_PIN, Qt.SortOrder.AscendingOrder
            )
            self.connector.sort_rows("pin", descending=False)
        self.refresh_table()

    def sort_by_column(self, col: int, descending: bool | None = None) -> None:
        """열 헤더 기준 정렬 수행 (제3.6절)."""
        if self.connector is None or col not in (
            COL_PIN,
            COL_SIGNAL,
            COL_SIGNAL_TYPE,
        ):
            return
        col_map = {
            COL_PIN: "pin",
            COL_SIGNAL: "signal",
            COL_SIGNAL_TYPE: "signal_type",
        }
        target_col = col_map[col]
        if descending is None:
            if self._sort_column == target_col:
                self._sort_descending = not self._sort_descending
            else:
                self._sort_column = target_col
                self._sort_descending = False
        else:
            self._sort_column = target_col
            self._sort_descending = descending

        order = (
            Qt.SortOrder.DescendingOrder
            if self._sort_descending
            else Qt.SortOrder.AscendingOrder
        )
        self.table.horizontalHeader().setSortIndicator(col, order)
        self.connector.sort_rows(
            self._sort_column, descending=self._sort_descending
        )
        self.refresh_table()

    def _on_header_clicked(self, logical_index: int) -> None:
        if logical_index in (COL_PIN, COL_SIGNAL, COL_SIGNAL_TYPE):
            self.sort_by_column(logical_index)

    def refresh_table(self, preserve_row: int | None = None) -> None:
        """연결기의 신호 행 목록과 마지막 입력용 빈 행을 표에 렌더링한다."""
        self._syncing = True
        try:
            if preserve_row is None:
                preserve_row = self.table.currentRow()

            if self.connector is None or self.project is None:
                self.table.setRowCount(0)
                self.table.setEnabled(False)
                return

            self.table.setEnabled(True)
            rows = self.connector.rows
            dup_rows = self.connector.duplicate_row_indices()
            total_rows = len(rows) + 1
            self.table.setRowCount(total_rows)

            header_labels: list[str] = [
                str(r_idx + 1) for r_idx in range(len(rows))
            ]
            header_labels.append("+")
            self.table.setVerticalHeaderLabels(header_labels)

            for r_idx, sig_row in enumerate(rows):
                sig_def = self.connector.get_signal(sig_row.signal_name)
                s_type = sig_def.signal_type if sig_def else ""
                ind_color = sig_def.color if sig_def else ""
                type_color = self.project.signal_type_color(s_type)
                eff_color = self.project.effective_signal_color(
                    self.connector, sig_row.signal_name
                )

                # 0. 핀 번호 셀
                pin_item = QTableWidgetItem(sig_row.pin_designator)
                pin_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if self.part is None:
                    pin_item.setToolTip(
                        "연결기 부품이 선택된 후 핀 번호를 할당할 수 있습니다."
                    )
                if r_idx in dup_rows:
                    pin_item.setBackground(
                        QBrush(QColor(DUPLICATE_CELL_BG_COLOR))
                    )
                    pin_item.setForeground(QBrush(QColor("#991b1b")))
                    font = pin_item.font()
                    font.setBold(True)
                    pin_item.setFont(font)
                    pin_item.setToolTip(
                        f"핀 번호 '{sig_row.pin_designator}' 신호 중복"
                    )
                self.table.setItem(r_idx, COL_PIN, pin_item)

                # 1. 신호명 셀
                sig_item = QTableWidgetItem(sig_row.signal_name)
                self.table.setItem(r_idx, COL_SIGNAL, sig_item)

                # 2. 신호유형 셀
                type_item = QTableWidgetItem(s_type)
                if type_color:
                    t_bg = QColor(type_color)
                    t_bg.setAlpha(45)
                    type_item.setBackground(QBrush(t_bg))
                self.table.setItem(r_idx, COL_SIGNAL_TYPE, type_item)

                # 3. 색상 셀
                if ind_color:
                    color_text = ind_color
                elif type_color:
                    color_text = f"유형색 ({type_color})"
                else:
                    color_text = "없음"
                color_item = QTableWidgetItem(color_text)
                color_item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                )
                swatch = QColor(eff_color)
                color_item.setBackground(QBrush(swatch))
                lum = (
                    0.299 * swatch.red()
                    + 0.587 * swatch.green()
                    + 0.114 * swatch.blue()
                )
                color_item.setForeground(
                    QBrush(QColor("#ffffff" if lum < 145 else "#0f172a"))
                )
                self.table.setItem(r_idx, COL_COLOR, color_item)

            # 마지막 입력용 빈 행 설정 (제3.6절)
            blank_idx = len(rows)
            for col in (COL_PIN, COL_SIGNAL, COL_SIGNAL_TYPE, COL_COLOR):
                blank_item = QTableWidgetItem("")
                if col == COL_SIGNAL:
                    blank_item.setToolTip(
                        "여기에 신호명을 입력하거나 선택하면 새 신호 행이 추가됩니다."
                    )
                else:
                    blank_item.setFlags(
                        Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                    )
                self.table.setItem(blank_idx, col, blank_item)

            if preserve_row is not None and 0 <= preserve_row < total_rows:
                self.table.selectRow(preserve_row)
        finally:
            self._syncing = False

    def apply_cell_edit(self, row: int, col: int, text: str) -> bool:
        """콤보 박스 델리게이트 또는 외부 호출을 통해 셀 값을 검증·반영한다."""
        if self._syncing or self.connector is None or self.project is None:
            return False

        is_blank_row = row >= len(self.connector.rows)

        if col == COL_SIGNAL:
            cleaned = text.strip()
            if not cleaned:
                self.refresh_table(preserve_row=row)
                return False
            if not is_valid_signal_name(cleaned):
                msg = (
                    "신호명은 영문자로 시작하고 영문 대문자·숫자·언더스코어(_)만 사용할 수 있습니다(공백·특수문자 불가, 32자 이하)."
                )
                self.statusMessage.emit(msg)
                QMessageBox.warning(self, "유효하지 않은 신호명", msg)
                self.refresh_table(preserve_row=row)
                return False

            norm_sig = normalize_signal_name(cleaned)
            self.connector.add_or_update_row_signal(row, norm_sig)
            sig = self.connector.get_signal(norm_sig)
            if sig and sig.signal_type:
                self.project.ensure_signal_type(sig.signal_type)
            next_row = min(row, max(len(self.connector.rows) - 1, 0))
            self.refresh_table(preserve_row=next_row)
            self.dataChanged.emit()
            self._emit_current_row_pin_selection(next_row)
            return True

        if is_blank_row:
            self.refresh_table(preserve_row=row)
            return False

        if col == COL_PIN:
            raw_pin = "" if text == "미할당" else text
            if not self.connector.validate_pin_designator(raw_pin, self.part):
                if self.part is None:
                    msg = "연결기 부품이 선택되지 않아 핀 번호를 입력할 수 없습니다."
                else:
                    msg = (
                        f"현재 부품({self.part.name})에 존재하지 않거나 형식이 잘못된 핀 번호입니다: '{text}'"
                    )
                self.statusMessage.emit(msg)
                QMessageBox.warning(self, "유효하지 않은 핀 번호", msg)
                self.refresh_table(preserve_row=row)
                return False

            self.connector.set_row_pin(row, raw_pin, self.part)
            next_row = min(row, max(len(self.connector.rows) - 1, 0))
            self.refresh_table(preserve_row=next_row)
            self.dataChanged.emit()
            self._emit_current_row_pin_selection(next_row)
            return True

        if col == COL_SIGNAL_TYPE:
            cleaned = text.strip()
            sig_name = self.connector.rows[row].signal_name
            if cleaned in ("", "없음", "(없음)"):
                self.connector.set_signal_type(sig_name, "")
                self.refresh_table(preserve_row=row)
                self.dataChanged.emit()
                self._emit_current_row_pin_selection(row)
                return True

            if not is_valid_signal_type_name(cleaned):
                msg = (
                    "신호유형 이름은 영문자 또는 한글로 시작하고 영문 대문자·한글·숫자·언더스코어(_)만 사용할 수 있습니다(공백 불가, 32자 이하)."
                )
                self.statusMessage.emit(msg)
                QMessageBox.warning(self, "유효하지 않은 신호유형 이름", msg)
                self.refresh_table(preserve_row=row)
                return False

            norm_type = self.project.ensure_signal_type(cleaned)
            self.connector.set_signal_type(sig_name, norm_type)
            self.refresh_table(preserve_row=row)
            self.dataChanged.emit()
            self._emit_current_row_pin_selection(row)
            return True

        return False

    def select_row_for_pin(self, pin_designator: str) -> None:
        """핀맵에서 핀을 선택했을 때 그 핀에 해당하는 행만 선택한다 (제3.8절).

        신호 중복 핀을 선택하면 현재 정렬 순서에서 그 핀이 할당된 첫 번째 행을 선택한다.
        미할당 핀을 선택하면 신호표 선택은 해제된다.
        """
        if self.connector is None:
            return
        self._syncing = True
        try:
            cleaned = pin_designator.strip()
            if not cleaned:
                self.table.clearSelection()
                return
            row_idx = self.connector.first_row_index_for_pin(cleaned)
            if row_idx is not None:
                self.table.selectRow(row_idx)
                item = self.table.item(row_idx, COL_PIN)
                if item is not None:
                    self.table.scrollToItem(item)
            else:
                self.table.clearSelection()
        finally:
            self._syncing = False

    def _on_selection_changed(self) -> None:
        if self._syncing or self.connector is None:
            return
        selected_items = self.table.selectedItems()
        if not selected_items:
            self.pinSelectionChanged.emit("")
            return
        row = self.table.currentRow()
        self._emit_current_row_pin_selection(row)

    def _emit_current_row_pin_selection(self, row: int) -> None:
        if self.connector is None or not (0 <= row < len(self.connector.rows)):
            self.pinSelectionChanged.emit("")
            return
        sig_row = self.connector.rows[row]
        # 제3.8절: 미할당 행을 선택하면 핀맵에는 강조 표시를 하지 않는다.
        if not sig_row.pin_designator:
            self.pinSelectionChanged.emit("")
        else:
            self.pinSelectionChanged.emit(sig_row.pin_designator)

    def _on_vertical_header_context_menu(self, pos) -> None:
        """행 헤더(제일 좌측 핸들 영역) 선택 후 우클릭 컨텍스트 메뉴로 삭제 (제3.6절)."""
        if self.connector is None:
            return
        v_header = self.table.verticalHeader()
        row = v_header.logicalIndexAt(pos)
        if not (0 <= row < len(self.connector.rows)):
            return

        self.table.selectRow(row)
        sig_row = self.connector.rows[row]
        usage = self.connector.row_usage_count(sig_row.signal_name)

        menu = QMenu(self)
        if usage <= 1:
            label = f"신호 행 삭제 ('{sig_row.signal_name}' 신호도 함께 삭제)"
        else:
            label = (
                f"신호 행 삭제 ('{sig_row.signal_name}' 다른 {usage - 1}개 행 유지)"
            )
        delete_action = menu.addAction(label)
        chosen = menu.exec(v_header.mapToGlobal(pos))
        if chosen == delete_action:
            self.delete_signal_row(row)

    def delete_signal_row(self, row_index: int) -> bool:
        """특정 행을 삭제하고 UI 및 핀맵을 갱신한다."""
        if self.connector is None:
            return False
        if not self.connector.delete_row(row_index):
            return False
        next_row = min(row_index, len(self.connector.rows))
        self.refresh_table(preserve_row=next_row)
        self.dataChanged.emit()
        self._emit_current_row_pin_selection(next_row)
        return True

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if self.connector is None or self.project is None:
            return
        if col == COL_COLOR and 0 <= row < len(self.connector.rows):
            self._pick_signal_color(row)

    def _on_table_context_menu(self, pos) -> None:
        if self.connector is None or self.project is None:
            return
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        if not (0 <= row < len(self.connector.rows)):
            return

        sig_name = self.connector.rows[row].signal_name
        sig = self.connector.get_signal(sig_name)
        menu = QMenu(self)
        pick_color_act = menu.addAction(f"'{sig_name}' 색상 선택...")
        clear_color_act = menu.addAction(
            f"'{sig_name}' 색상 없음 (신호유형 색상 사용)"
        )
        clear_color_act.setEnabled(bool(sig and sig.color))

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == pick_color_act:
            self._pick_signal_color(row)
        elif chosen == clear_color_act:
            self.connector.set_signal_color(sig_name, "")
            self.refresh_table(preserve_row=row)
            self.dataChanged.emit()

    def _pick_signal_color(self, row: int) -> None:
        if self.connector is None or self.project is None:
            return
        if not (0 <= row < len(self.connector.rows)):
            return
        sig_name = self.connector.rows[row].signal_name
        initial = QColor(
            self.project.effective_signal_color(self.connector, sig_name)
        )
        chosen = QColorDialog.getColor(
            initial, self, f"'{sig_name}' 신호 색상 선택"
        )
        if chosen.isValid():
            self.connector.set_signal_color(sig_name, chosen.name())
            self.refresh_table(preserve_row=row)
            self.dataChanged.emit()
