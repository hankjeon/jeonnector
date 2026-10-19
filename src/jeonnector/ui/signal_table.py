"""우측 신호표(SignalTablePanel) 및 입력 가능한 콤보 박스 델리게이트 (제3.6절, 제3.8절, 제3.9절, 제3.10절)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jeonnector.commands import CommandDispatcher
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
COL_ACTION = 4


def color_cell_label(individual_color: str, type_color: str) -> tuple[str, str]:
    """색상 칸의 짧은 표시 문구와 색상 코드 툴팁을 반환한다 (제3.6절)."""
    if individual_color:
        return "개별", f"개별 색상 {individual_color}"
    if type_color:
        return "유형", f"유형 색상 {type_color}"
    return "없음", "색상 없음"


UNASSIGNED_TEXT = "미할당"
NO_TYPE_TEXT = "없음"


def use_blank_placeholder(combo: QComboBox, placeholder: str) -> None:
    """빈칸일 때 회색 안내 글자를 보이고, 드롭다운에서 안내 항목을 고르면 빈칸으로 둔다 (제3.9절)."""
    combo.lineEdit().setPlaceholderText(placeholder)
    combo.textActivated.connect(
        lambda text: combo.setEditText("") if text == placeholder else None
    )


def readable_text_color(background: QColor) -> str:
    luminance = (
        0.299 * background.red()
        + 0.587 * background.green()
        + 0.114 * background.blue()
    )
    return "#ffffff" if luminance < 145 else "#0f172a"


@dataclass
class SignalDraft:
    """프로젝트에 반영하기 전인 신호 입력값."""

    pin: str = ""
    name: str = ""
    signal_type: str = ""
    color: str = ""


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
            combo.addItem(UNASSIGNED_TEXT)
            use_blank_placeholder(combo, UNASSIGNED_TEXT)
            if part is not None:
                for pin_des in part.pin_designators():
                    combo.addItem(pin_des)
            # 새 입력 행에는 별도 콤보 박스를 사용한다.
            if conn is None or row >= len(conn.rows) or part is None:
                combo.setEnabled(False)
        elif col == COL_SIGNAL:
            if conn is not None:
                for sig_name in conn.signal_names():
                    combo.addItem(sig_name)
        elif col == COL_SIGNAL_TYPE:
            combo.addItem(NO_TYPE_TEXT)
            use_blank_placeholder(combo, NO_TYPE_TEXT)
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
            # 미할당 핀·신호유형 없음은 빈칸(회색 안내 글자)으로 시작해 입력이 이어 붙지 않게 한다.
            current_text = str(index.data(Qt.ItemDataRole.EditRole) or "")
            idx = editor.findText(current_text) if current_text else -1
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

    def __init__(
        self, parent: QWidget | None = None,
        commands: CommandDispatcher | None = None,
    ) -> None:
        super().__init__(parent)
        self.project: Project | None = None
        self.connector: ConnectorInstance | None = None
        self.part: ConnectorPart | None = None
        self._syncing = False
        self._sort_column: str = "pin"
        self._sort_descending: bool = False
        self.commands = commands
        self.draft = SignalDraft()
        self._draft_return_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.info_label = QLabel(
            "마지막 행에 입력 후 Enter로 추가 · 행 헤더 우클릭으로 삭제 · 열 헤더로 정렬"
        )
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.info_label.setStyleSheet("color: #475569; font-size: 11px;")
        layout.addWidget(self.info_label)

        self.table = SignalTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["핀 번호", "신호명", "신호유형", "색상", "입력"]
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
        self.table.setColumnWidth(COL_COLOR, 64)
        self.table.setColumnWidth(COL_ACTION, 140)

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
        self.add_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.add_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.add_shortcut.activated.connect(self.commit_draft)
        self.add_keypad_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), self)
        self.add_keypad_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.add_keypad_shortcut.activated.connect(self.commit_draft)

    def has_draft(self) -> bool:
        return any((self.draft.pin, self.draft.name, self.draft.signal_type, self.draft.color))

    def reset_draft(self) -> None:
        self.draft = SignalDraft()
        self.refresh_table(preserve_row_id="draft")

    def _make_draft_combo(self, items: list[str], value: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.addItems(items)
        combo.setEditText(value)
        return combo

    def _render_draft(self, row: int) -> None:
        # 실제 데이터에는 등록하지 않은 입력값을 갱신·정렬 사이에도 유지한다.
        self.draft_pin_combo = self._make_draft_combo(
            [UNASSIGNED_TEXT] + (self.part.pin_designators() if self.part else []),
            self.draft.pin,
        )
        use_blank_placeholder(self.draft_pin_combo, UNASSIGNED_TEXT)
        self.draft_pin_combo.setEnabled(self.part is not None)
        self.draft_name_combo = self._make_draft_combo(
            self.connector.signal_names(), self.draft.name,
        )
        self.draft_type_combo = self._make_draft_combo(
            [NO_TYPE_TEXT] + sorted(self.project.signal_types, key=natural_sort_key),
            self.draft.signal_type,
        )
        use_blank_placeholder(self.draft_type_combo, NO_TYPE_TEXT)
        self.draft_color_button = QPushButton()
        self.draft_color_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.draft_color_button.clicked.connect(self._pick_draft_color)
        self.draft_color_button.customContextMenuRequested.connect(self._draft_color_menu)
        self.add_button = QPushButton("추가")
        self.reset_button = QPushButton("초기화")
        self.add_button.clicked.connect(self.commit_draft)
        self.reset_button.clicked.connect(self.reset_draft)
        actions = QWidget()
        buttons = QHBoxLayout(actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(2)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.reset_button)
        for col, widget in enumerate((
            self.draft_pin_combo, self.draft_name_combo, self.draft_type_combo,
            self.draft_color_button, actions,
        )):
            self.table.setCellWidget(row, col, widget)
        self.draft_pin_combo.currentTextChanged.connect(
            lambda text: setattr(self.draft, "pin", "" if text == UNASSIGNED_TEXT else text)
        )
        self.draft_name_combo.currentTextChanged.connect(self._draft_name_changed)
        self.draft_type_combo.currentTextChanged.connect(self._draft_type_changed)
        for source, combo in (
            ("pin", self.draft_pin_combo),
            ("name", self.draft_name_combo),
            ("type", self.draft_type_combo),
        ):
            combo.lineEdit().returnPressed.connect(
                lambda source=source: self._on_draft_return(source)
            )
        self._update_draft_attributes()
        QWidget.setTabOrder(self.draft_pin_combo, self.draft_name_combo)
        QWidget.setTabOrder(self.draft_name_combo, self.draft_type_combo)
        QWidget.setTabOrder(self.draft_type_combo, self.draft_color_button)
        QWidget.setTabOrder(self.draft_color_button, self.add_button)
        QWidget.setTabOrder(self.add_button, self.reset_button)

    def _on_draft_return(self, source: str) -> None:
        # Ctrl+Enter는 단축키가 처리한다. 콤보 상자가 Enter를 줄 편집기에 다시 전달해
        # 한 번 누를 때 두 번 올 수 있으므로 한 번만 처리하고, 입력 위젯을 다시 만들기 전에 신호 처리를 끝낸다.
        if self._draft_return_pending or (
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            return
        self._draft_return_pending = True
        QTimer.singleShot(0, lambda: self._handle_draft_return(source))

    def _handle_draft_return(self, source: str) -> None:
        """입력 행의 Enter: 신호명이 없으면 핀 번호에서 신호명으로 이동하고, 있으면 추가한다 (제3.6.1절)."""
        self._draft_return_pending = False
        if self.connector is None:
            return
        if source == "pin" and not self.draft.name.strip():
            self.draft_name_combo.setFocus()
            return
        self.commit_draft()

    def _draft_type_changed(self, text: str) -> None:
        self.draft.signal_type = "" if text == NO_TYPE_TEXT else text
        self._update_draft_color_button()

    def _draft_name_changed(self, text: str) -> None:
        self.draft.name = text
        self._update_draft_attributes()

    def _update_draft_attributes(self) -> None:
        signal = self.connector.get_signal(self.draft.name) if self.connector else None
        if signal:
            self.draft.signal_type = signal.signal_type
            self.draft.color = signal.color
        self.draft_type_combo.blockSignals(True)
        self.draft_type_combo.setEditText(self.draft.signal_type)
        self.draft_type_combo.blockSignals(False)
        self.draft_type_combo.setEnabled(signal is None)
        self.draft_color_button.setEnabled(signal is None)
        self._update_draft_color_button()

    def _update_draft_color_button(self) -> None:
        type_color = (
            self.project.signal_type_color(self.draft.signal_type)
            if self.project and self.draft.signal_type
            else ""
        )
        text, tooltip = color_cell_label(self.draft.color, type_color)
        self.draft_color_button.setText(text)
        self.draft_color_button.setToolTip(f"{tooltip} · 클릭: 개별 색상 선택 · 우클릭: 없음")
        shown = self.draft.color or type_color
        self.draft_color_button.setStyleSheet(
            f"background-color: {shown}; color: {readable_text_color(QColor(shown))};"
            if shown else ""
        )

    def _pick_draft_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.draft.color or "#ffffff"), self, "새 신호 색상")
        if chosen.isValid():
            self.draft.color = chosen.name()
            self._update_draft_attributes()

    def _draft_color_menu(self, pos) -> None:
        menu = QMenu(self)
        clear = menu.addAction("색상 없음 (신호유형 색상 사용)")
        if menu.exec(self.draft_color_button.mapToGlobal(pos)) == clear:
            self.draft.color = ""
            self._update_draft_attributes()

    def _draft_error(self, message: str, widget: QWidget) -> bool:
        self.statusMessage.emit(message)
        widget.setToolTip(message)
        widget.setStyleSheet("border: 1px solid #dc2626;")
        widget.setFocus()
        return False

    def commit_draft(self) -> bool:
        if self.connector is None or self.project is None:
            return False
        if not is_valid_signal_name(self.draft.name):
            return self._draft_error(
                "신호명은 영문자로 시작하는 영문·숫자·밑줄 32자 이내로 입력하세요.",
                self.draft_name_combo,
            )
        if not self.connector.validate_pin_designator(self.draft.pin, self.part):
            return self._draft_error("현재 부품에 존재하는 핀 번호를 선택하세요.", self.draft_pin_combo)
        existing = self.connector.get_signal(self.draft.name)
        if (not existing and self.draft.signal_type
                and not is_valid_signal_type_name(self.draft.signal_type)):
            return self._draft_error("유효한 신호유형 이름을 입력하세요.", self.draft_type_combo)
        name = normalize_signal_name(self.draft.name)
        pin = self.draft.pin

        def add() -> bool:
            if not self.connector.add_signal_row(
                name, pin, self.part, self.draft.signal_type, self.draft.color,
            ):
                return False
            if not existing and self.draft.signal_type:
                self.project.ensure_signal_type(self.draft.signal_type)
            return True

        if self.commands:
            success = self.commands.execute(f"신호 행 추가: {name}", add)
        else:
            success = add()
        if not success:
            return False
        row_id = next((r.row_id for r in self.connector.rows
                       if r.signal_name == name and r.pin_designator == pin), "")
        self.draft = SignalDraft()
        self.refresh_table(preserve_row_id=row_id)
        self.dataChanged.emit()
        self._emit_current_row_pin_selection(self.table.currentRow())
        # 다음 신호를 이어서 입력하도록 입력 행의 첫 칸으로 돌아간다.
        if self.draft_pin_combo.isEnabled():
            self.draft_pin_combo.setFocus()
        else:
            self.draft_name_combo.setFocus()
        return True

    def set_context(
        self,
        project: Project | None,
        connector: ConnectorInstance | None,
        part: ConnectorPart | None,
    ) -> None:
        switching_connector = connector is not self.connector
        if switching_connector:
            self.draft = SignalDraft()
            self.table.clearContents()
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
        self.refresh_table()

    def _on_header_clicked(self, logical_index: int) -> None:
        if logical_index in (COL_PIN, COL_SIGNAL, COL_SIGNAL_TYPE):
            self.sort_by_column(logical_index)

    def refresh_table(
        self, preserve_row: int | None = None,
        preserve_row_id: str | None = None,
    ) -> None:
        """연결기의 신호 행 목록과 마지막 입력용 빈 행을 표에 렌더링한다."""
        self._syncing = True
        try:
            if self.connector is None or self.project is None:
                self.table.setRowCount(0)
                self.table.setEnabled(False)
                return

            if preserve_row_id is None:
                if preserve_row is not None and 0 <= preserve_row < len(self.connector.rows):
                    preserve_row_id = self.connector.rows[preserve_row].row_id
                else:
                    selected = (self.table.item(self.table.currentRow(), COL_SIGNAL)
                                if self.table.selectedItems() else None)
                    preserve_row_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
            self.connector.sort_rows(self._sort_column, self._sort_descending)
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

            # 이전 마지막 행의 입력 위젯이 데이터 행으로 남지 않도록 제거한다.
            for r_idx in range(total_rows):
                for col in range(self.table.columnCount()):
                    widget = self.table.cellWidget(r_idx, col)
                    if widget is not None:
                        widget.hide()
                        self.table.removeCellWidget(r_idx, col)

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
                sig_item.setData(Qt.ItemDataRole.UserRole, sig_row.row_id)
                self.table.setItem(r_idx, COL_SIGNAL, sig_item)

                # 2. 신호유형 셀
                type_item = QTableWidgetItem(s_type)
                if type_color:
                    t_bg = QColor(type_color)
                    t_bg.setAlpha(45)
                    type_item.setBackground(QBrush(t_bg))
                self.table.setItem(r_idx, COL_SIGNAL_TYPE, type_item)

                # 3. 색상 셀
                color_text, color_tip = color_cell_label(ind_color, type_color)
                color_item = QTableWidgetItem(color_text)
                color_item.setToolTip(color_tip)
                color_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                color_item.setFlags(
                    Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                )
                swatch = QColor(eff_color)
                color_item.setBackground(QBrush(swatch))
                color_item.setForeground(QBrush(QColor(readable_text_color(swatch))))
                self.table.setItem(r_idx, COL_COLOR, color_item)
                action_item = QTableWidgetItem("")
                action_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(r_idx, COL_ACTION, action_item)

            # 마지막 입력용 빈 행 설정 (제3.6절)
            blank_idx = len(rows)
            for col in range(self.table.columnCount()):
                blank_item = QTableWidgetItem("")
                blank_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                blank_item.setData(Qt.ItemDataRole.UserRole, "draft")
                self.table.setItem(blank_idx, col, blank_item)
            self._render_draft(blank_idx)
            target = next((i for i, r in enumerate(rows) if r.row_id == preserve_row_id), -1)
            if preserve_row_id == "draft":
                target = blank_idx
            self.table.clearSelection()
            self.table.setCurrentCell(target, COL_SIGNAL)
            if target >= 0:
                self.table.selectRow(target)
        finally:
            self._syncing = False

    def apply_cell_edit(self, row: int, col: int, text: str) -> bool:
        """콤보 박스 델리게이트 또는 외부 호출을 통해 셀 값을 검증·반영한다."""
        if self._syncing or self.connector is None or self.project is None:
            return False

        if row < 0 or row > len(self.connector.rows):
            return False
        is_blank_row = row == len(self.connector.rows)
        if is_blank_row:
            field = {
                COL_PIN: "pin", COL_SIGNAL: "name",
                COL_SIGNAL_TYPE: "signal_type", COL_COLOR: "color",
            }.get(col)
            if field is None:
                return False
            if col in (COL_SIGNAL_TYPE, COL_COLOR) and self.connector.get_signal(self.draft.name):
                return False
            value = "" if text in ("미할당", "없음") else text
            setattr(self.draft, field, value)
            self.refresh_table(preserve_row_id="draft")
            return True
        row_id = self.connector.rows[row].row_id

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
            self.refresh_table(preserve_row_id=row_id)
            self.dataChanged.emit()
            self._emit_current_row_pin_selection(self.table.currentRow())
            return True

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
            self.refresh_table(preserve_row_id=row_id)
            self.dataChanged.emit()
            self._emit_current_row_pin_selection(self.table.currentRow())
            return True

        if col == COL_SIGNAL_TYPE:
            cleaned = text.strip()
            sig_name = self.connector.rows[row].signal_name
            if cleaned in ("", "없음", "(없음)"):
                self.connector.set_signal_type(sig_name, "")
                self.refresh_table(preserve_row_id=row_id)
                self.dataChanged.emit()
                self._emit_current_row_pin_selection(self.table.currentRow())
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
            self.refresh_table(preserve_row_id=row_id)
            self.dataChanged.emit()
            self._emit_current_row_pin_selection(self.table.currentRow())
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
