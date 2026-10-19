"""전연결기(jeonnector) 메인 윈도우, 사이드바, 부품 동기화 및 화면 전환 관리 (제3.1~3.3절, 제3.10~3.12절, 제4.1절)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from jeonnector.commands import CommandDispatcher
from jeonnector.model import (
    ConnectorInstance,
    ConnectorPart,
    Project,
    ProjectFormatError,
    is_valid_signal_name,
    normalize_signal_name,
)
from jeonnector.storage import PartLibrary, load_project, save_project
from jeonnector.ui.connector_editor import ConnectorEditorWidget
from jeonnector.ui.pinmap_canvas import PinmapPanel
from jeonnector.ui.signal_table import SignalTablePanel
from jeonnector.ui.signal_type_dialog import SignalTypeDialog

MAX_RECENT_FILES = 8
EMPTY_CONNECTOR_LIST_HINT = "우클릭하여 연결기 추가"


class ConnectorListWidget(QListWidget):
    """연결기 목록. 비어 있으면 우클릭 추가 안내 문구를 표시한다 (제3.1절)."""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                EMPTY_CONNECTOR_LIST_HINT,
            )


class AddConnectorDialog(QDialog):
    """프로젝트에 새 연결기를 추가하는 대화상자 (제3.1절)."""

    def __init__(
        self,
        existing_designators: list[str],
        available_parts: list[ConnectorPart],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("연결기 추가")
        self.resize(400, 160)
        self._existing = {normalize_signal_name(d) for d in existing_designators}
        self._parts = available_parts

        layout = QVBoxLayout(self)
        form = QFormLayout()

        idx = 1
        while f"J{idx}" in self._existing:
            idx += 1
        self.designator_edit = QLineEdit(f"J{idx}")
        form.addRow("연결기 식별자 (예: J1, P1):", self.designator_edit)

        self.part_combo = QComboBox()
        self.part_combo.addItem("(나중에 선택 — 신호표 먼저 작성 가능)", "")
        for part in available_parts:
            self.part_combo.addItem(
                f"{part.name} ({part.pin_count}핀)", part.uuid
            )
        if available_parts:
            self.part_combo.setCurrentIndex(1)
        form.addRow("사용할 연결기 부품:", self.part_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        raw = self.designator_edit.text().strip()
        if not is_valid_signal_name(raw):
            QMessageBox.warning(
                self,
                "식별자 규칙 오류",
                "연결기 식별자는 영문자로 시작하고 영문 대문자·숫자·언더스코어(_)만 사용할 수 있습니다(32자 이하).",
            )
            return
        des = normalize_signal_name(raw)
        if des in self._existing:
            QMessageBox.warning(
                self,
                "식별자 중복",
                f"이미 프로젝트에 존재하는 연결기 식별자입니다: '{des}'",
            )
            return
        self.accept()

    def selected_designator(self) -> str:
        return normalize_signal_name(self.designator_edit.text())

    def selected_part(self) -> ConnectorPart | None:
        part_uuid = str(self.part_combo.currentData() or "")
        if not part_uuid:
            return None
        for p in self._parts:
            if p.uuid == part_uuid:
                return p
        return None


class MainWindow(QMainWindow):
    """전연결기(jeonnector) 메인 애플리케이션 윈도우."""

    def __init__(self, part_library: PartLibrary | None = None) -> None:
        super().__init__()
        self.part_library = part_library or PartLibrary()
        self.project = Project(name="새 프로젝트")
        self.commands = CommandDispatcher(lambda: self.project)
        self.current_file_path: Path | None = None
        self.is_dirty: bool = False
        self._syncing_sidebar = False
        self._editor_entry_part_snapshots: dict[str, ConnectorPart] = {}

        self.setWindowTitle("전연결기 (jeonnector) - 새 프로젝트")
        self.resize(1360, 820)

        self._build_menus_and_toolbar()
        self._build_stacked_views()
        self._build_status_bar()

        self._default_dock_state: QByteArray = (
            self.project_workspace.saveState()
        )
        self._restore_window_settings()

        self._refresh_available_parts()
        self._refresh_sidebar()
        self.update_status_bar()

    @property
    def current_connector(self) -> ConnectorInstance | None:
        item = self.connector_list.currentItem()
        if item is None:
            return None
        des = str(item.data(Qt.ItemDataRole.UserRole) or "")
        return self.project.get_connector(des)

    def _settings(self) -> QSettings:
        return QSettings("Jeonnector", "Jeonnector")

    def _build_menus_and_toolbar(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("파일(&F)")

        self.new_proj_act = QAction("새로 만들기(&N)", self)
        self.new_proj_act.setShortcut(QKeySequence.StandardKey.New)
        self.new_proj_act.triggered.connect(self.new_project)
        file_menu.addAction(self.new_proj_act)

        self.open_proj_act = QAction("열기(&O)...", self)
        self.open_proj_act.setShortcut(QKeySequence.StandardKey.Open)
        self.open_proj_act.triggered.connect(self.open_project_dialog)
        file_menu.addAction(self.open_proj_act)

        self.recent_menu = QMenu("최근 파일(&R)", self)
        file_menu.addMenu(self.recent_menu)
        self._update_recent_files_menu()

        self.save_proj_act = QAction("저장(&S)", self)
        self.save_proj_act.setShortcut(QKeySequence.StandardKey.Save)
        self.save_proj_act.triggered.connect(self.save_project_action)
        file_menu.addAction(self.save_proj_act)

        self.save_as_act = QAction("다른 이름으로 저장(&A)...", self)
        self.save_as_act.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_act.triggered.connect(self.save_project_as_dialog)
        file_menu.addAction(self.save_as_act)

        file_menu.addSeparator()
        exit_act = QAction("종료(&X)", self)
        exit_act.setShortcut(QKeySequence.StandardKey.Quit)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        project_menu = menubar.addMenu("프로젝트(&P)")
        self.signal_type_act = QAction("신호유형 관리(&T)...", self)
        self.signal_type_act.triggered.connect(self.open_signal_type_dialog)
        project_menu.addAction(self.signal_type_act)

        view_menu = menubar.addMenu("화면 및 창(&V)")
        self.show_project_view_act = QAction("메인 화면 (핀맵·신호표)", self)
        self.show_project_view_act.triggered.connect(
            lambda: self.switch_to_project_view()
        )
        view_menu.addAction(self.show_project_view_act)

        self.show_editor_view_act = QAction("연결기 부품 편집기", self)
        self.show_editor_view_act.triggered.connect(self.switch_to_editor_view)
        view_menu.addAction(self.show_editor_view_act)
        view_menu.addSeparator()

        self.reset_layout_act = QAction("배치 초기화(&R)", self)
        self.reset_layout_act.triggered.connect(self.reset_window_layout)
        view_menu.addAction(self.reset_layout_act)
        view_menu.addSeparator()

        self.main_toolbar = QToolBar("메인 도구 모음", self)
        self.main_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.main_toolbar)

        self.main_toolbar.addAction(self.new_proj_act)
        self.main_toolbar.addAction(self.open_proj_act)
        self.main_toolbar.addAction(self.save_proj_act)
        self.main_toolbar.addSeparator()
        self.main_toolbar.addAction(self.signal_type_act)
        self.main_toolbar.addSeparator()

        self.switch_editor_btn = QPushButton("연결기 부품 편집기 열기")
        self.switch_editor_btn.setStyleSheet(
            "font-weight: bold; padding: 4px 12px;"
        )
        self.switch_editor_btn.clicked.connect(self._toggle_screen_mode)
        self.main_toolbar.addWidget(self.switch_editor_btn)

        self._view_menu = view_menu

    def _build_stacked_views(self) -> None:
        """메인 화면과 연결기 부품 편집기 화면을 전체 전환 구조로 구성한다 (제4.1절, 제4.4절)."""
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)

        self.project_workspace = QMainWindow()
        self.project_workspace.setDockNestingEnabled(True)

        # 메인 화면 좌측(고정 영역): 핀맵 패널
        self.pinmap_panel = PinmapPanel(self.project_workspace)
        self.project_workspace.setCentralWidget(self.pinmap_panel)

        # 왼쪽 도킹 창: 사이드바
        self.sidebar_dock = QDockWidget("연결기 목록", self.project_workspace)
        self.sidebar_dock.setObjectName("SidebarDock")
        self.sidebar_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(6, 6, 6, 6)
        sidebar_layout.setSpacing(6)

        # 추가·식별자 변경·제거는 우클릭 메뉴로 처리한다 (제3.1절).
        self.connector_list = ConnectorListWidget()
        self.connector_list.currentItemChanged.connect(
            self._on_connector_selected
        )
        self.connector_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.connector_list.customContextMenuRequested.connect(
            self._show_connector_context_menu
        )
        sidebar_layout.addWidget(self.connector_list, 1)

        self.sidebar_dock.setWidget(sidebar_widget)
        self.project_workspace.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.sidebar_dock
        )

        # 우측 도킹 창: 신호표
        self.signal_dock = QDockWidget("신호표", self.project_workspace)
        self.signal_dock.setObjectName("SignalTableDock")
        self.signal_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.signal_table_panel = SignalTablePanel(
            self.project_workspace, commands=self.commands,
        )
        self.signal_dock.setWidget(self.signal_table_panel)
        self.project_workspace.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.signal_dock
        )

        self.project_workspace.resizeDocks(
            [self.sidebar_dock, self.signal_dock],
            [230, 520],
            Qt.Orientation.Horizontal,
        )

        self._view_menu.addAction(self.sidebar_dock.toggleViewAction())
        self._view_menu.addAction(self.signal_dock.toggleViewAction())

        # 화면 1: 연결기 부품 편집기 화면
        self.editor_widget = ConnectorEditorWidget(
            self.part_library, parent=self
        )
        self.editor_widget.backToProjectRequested.connect(
            self.switch_to_project_view
        )
        self.editor_widget.libraryUpdated.connect(
            self._refresh_available_parts
        )

        self.stack.addWidget(self.project_workspace)
        self.stack.addWidget(self.editor_widget)

        # 핀맵 ↔ 신호표 양방향 연동 시그널 연결
        self.pinmap_panel.partChangeRequested.connect(
            self._on_part_change_requested
        )
        self.pinmap_panel.flipToggled.connect(self._on_flip_toggled)
        self.pinmap_panel.pinSelected.connect(
            self.signal_table_panel.select_row_for_pin
        )
        self.pinmap_panel.pinSignalAssigned.connect(
            self._on_pin_signal_assigned_from_canvas
        )

        self.signal_table_panel.dataChanged.connect(
            self._on_signal_table_data_changed
        )
        self.signal_table_panel.pinSelectionChanged.connect(
            self._on_signal_table_pin_selected
        )
        self.signal_table_panel.statusMessage.connect(
            lambda msg: self.statusBar().showMessage(msg, 5000)
        )

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)

        self.warning_status_label = QLabel("경고: 신호 중복 0건")
        self.warning_status_label.setStyleSheet(
            "font-weight: bold; padding: 0 10px;"
        )
        status.addPermanentWidget(self.warning_status_label)

        self.info_status_label = QLabel("연결기 0개 · 미할당 신호 행 0개")
        self.info_status_label.setStyleSheet(
            "color: #475569; padding: 0 10px;"
        )
        status.addPermanentWidget(self.info_status_label)

    def reset_window_layout(self) -> None:
        """창 배치 초기화 (제4.1절)."""
        self.sidebar_dock.setFloating(False)
        self.signal_dock.setFloating(False)
        self.sidebar_dock.show()
        self.signal_dock.show()
        if not self._default_dock_state.isEmpty():
            self.project_workspace.restoreState(self._default_dock_state)
        self.project_workspace.resizeDocks(
            [self.sidebar_dock, self.signal_dock],
            [230, 520],
            Qt.Orientation.Horizontal,
        )

    def _restore_window_settings(self) -> None:
        settings = self._settings()
        geom = settings.value("main_geometry")
        if isinstance(geom, QByteArray) and not geom.isEmpty():
            self.restoreGeometry(geom)
        dock_state = settings.value("workspace_dock_state")
        if isinstance(dock_state, QByteArray) and not dock_state.isEmpty():
            self.project_workspace.restoreState(dock_state)

    def _save_window_settings(self) -> None:
        settings = self._settings()
        settings.setValue("main_geometry", self.saveGeometry())
        settings.setValue(
            "workspace_dock_state", self.project_workspace.saveState()
        )

    def recent_files(self) -> list[str]:
        settings = self._settings()
        raw = settings.value("recent_files", [])
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, list):
            return [str(x) for x in raw if x]
        return []

    def _add_recent_file(self, path: Path) -> None:
        resolved = str(path.resolve())
        items = [p for p in self.recent_files() if p != resolved]
        items.insert(0, resolved)
        self._settings().setValue("recent_files", items[:MAX_RECENT_FILES])
        self._update_recent_files_menu()

    def _update_recent_files_menu(self) -> None:
        self.recent_menu.clear()
        files = self.recent_files()
        if not files:
            empty_act = self.recent_menu.addAction("(최근 파일 없음)")
            empty_act.setEnabled(False)
            return
        for f_str in files:
            act = self.recent_menu.addAction(f_str)
            act.triggered.connect(
                lambda checked=False, p=f_str: self._open_recent_file(p)
            )

    def _open_recent_file(self, path_str: str) -> None:
        if not self._confirm_discard_or_save():
            return
        target = Path(path_str)
        if not target.exists():
            QMessageBox.warning(
                self, "파일 없음", f"파일을 찾을 수 없습니다:\n{target}"
            )
            return
        self.load_project_from_path(target, prompt_library_sync=True)

    def mark_dirty(self, dirty: bool = True) -> None:
        self.is_dirty = dirty
        self._update_window_title()
        self.update_status_bar()

    def _update_window_title(self) -> None:
        file_label = (
            self.current_file_path.name
            if self.current_file_path
            else self.project.name
        )
        star = " *" if self.is_dirty else ""
        self.setWindowTitle(f"전연결기 (jeonnector) - {file_label}{star}")

    def update_status_bar(self) -> None:
        """상태바에 프로젝트 전체의 신호 중복 경고 수(중복 핀 1개 = 경고 1건)를 표시한다 (제3.12절)."""
        dup_pin_warnings = self.project.total_duplicate_pin_warnings()
        unassigned_rows = self.project.total_unassigned_signal_rows()
        conn_count = len(self.project.connectors)

        if dup_pin_warnings > 0:
            self.warning_status_label.setText(
                f"⚠ 경고: 신호 중복 {dup_pin_warnings}건"
            )
            self.warning_status_label.setStyleSheet(
                "color: #dc2626; font-weight: bold; padding: 0 10px;"
            )
        else:
            self.warning_status_label.setText("✓ 경고: 신호 중복 0건")
            self.warning_status_label.setStyleSheet(
                "color: #16a34a; font-weight: bold; padding: 0 10px;"
            )

        self.info_status_label.setText(
            f"연결기 {conn_count}개 · 미할당 신호 행 {unassigned_rows}개"
        )

    def _toggle_screen_mode(self) -> None:
        if self.stack.currentIndex() == 0:
            self.switch_to_editor_view()
        else:
            self.switch_to_project_view()

    def switch_to_editor_view(self) -> None:
        """미완료 신호 입력을 먼저 처리한 뒤 부품 편집기로 전환한다."""
        if not self._resolve_signal_draft():
            return
        self._editor_entry_part_snapshots = {
            p_uuid: part.clone() for p_uuid, part in self.project.parts.items()
        }
        self.editor_widget.refresh_part_list()
        self.stack.setCurrentIndex(1)
        self.switch_editor_btn.setText("← 메인 화면으로 돌아가기")

    def _sync_edited_library_parts_to_project(
        self, confirm_unassign: Callable[[list[tuple[str, str, str]]], bool] | None = None
    ) -> bool:
        """편집기에서 변경한 부품을 부품 데이터베이스에 저장하고 현재 열린 프로젝트에 자동 반영한다 (제3.3절).

        - 핀 이동·추가 등 할당이 유지되는 변경은 상태바에 알린다.
        - 핀이 삭제되어 할당이 해제되는 경우에는 영향받는 연결기와 신호를 확인 창으로 보여준다.
          취소하면 저장·반영·전환(또는 종료)을 하지 않고 편집기에 남는다.
        """
        if self.editor_widget.current_part is not None:
            # 먼저 핀 삭제 영향이 있는지 확인
            edited_Candidates: dict[str, ConnectorPart] = {}
            for p_uuid, proj_part in self.project.parts.items():
                lib_part = self.part_library.get_part(p_uuid)
                if (
                    self.editor_widget.current_part.uuid == p_uuid
                ):
                    lib_part = self.editor_widget.current_part
                if lib_part is not None and not proj_part.is_definition_equal(
                    lib_part
                ):
                    edited_Candidates[p_uuid] = lib_part

            all_impacts: list[tuple[str, str, str]] = []
            for lib_part in edited_Candidates.values():
                all_impacts.extend(
                    self.project.preview_part_sync_impact(lib_part)
                )

            if all_impacts:
                if confirm_unassign is not None:
                    approved = confirm_unassign(all_impacts)
                else:
                    lines = [
                        f"• 연결기 {c_id}: 핀 {pin_d} (신호 {sig_n})"
                        for c_id, pin_d, sig_n in all_impacts
                    ]
                    ans = QMessageBox.question(
                        self,
                        "부품 핀 삭제에 따른 할당 해제 확인",
                        "부품에서 삭제된 핀에 할당된 다음 신호의 할당이 해제됩니다:\n\n"
                        + "\n".join(lines[:15])
                        + "\n\n저장하고 프로젝트에 반영하시겠습니까?",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    approved = ans == QMessageBox.StandardButton.Yes

                if not approved:
                    # 취소 시 부품 데이터베이스도 편집기 진입 시점 상태로 유지하고 편집기에 남음
                    for p_uuid, snap in self._editor_entry_part_snapshots.items():
                        self.part_library.upsert_part(snap, save_now=True)
                    return False

            self.editor_widget.save_current_part_to_library()
            for lib_part in edited_Candidates.values():
                self.project.sync_part_definition(lib_part)
            if edited_Candidates:
                self.mark_dirty(True)
                self.statusBar().showMessage(
                    f"연결기 부품 변경사항({len(edited_Candidates)}종)이 현재 프로젝트에 반영되었습니다.",
                    5000,
                )
        return True

    def switch_to_project_view(
        self,
        confirm_unassign: Callable[[list[tuple[str, str, str]]], bool] | None = None,
    ) -> bool:
        """연결기 부품 편집기에서 메인 화면으로 전환한다 (제3.2절, 제3.3절)."""
        if self.stack.currentIndex() == 1:
            if not self._sync_edited_library_parts_to_project(
                confirm_unassign=confirm_unassign
            ):
                return False

        self.stack.setCurrentIndex(0)
        self.switch_editor_btn.setText("연결기 부품 편집기 열기")
        self._refresh_available_parts()
        self._refresh_sidebar()
        self._refresh_current_connector_views(reset_canvas_view=False)
        return True

    def _refresh_available_parts(self) -> None:
        parts = self.part_library.list_parts()
        self.pinmap_panel.update_available_parts(parts)

    def _refresh_sidebar(
        self, select_designator: str | None = None
    ) -> None:
        """사이드바에 연결기를 식별자의 자연 정렬 순서로 표시하고 신호 중복 경고 아이콘을 표시한다 (제3.1절)."""
        self._syncing_sidebar = True
        try:
            current_des = select_designator or (
                self.current_connector.designator
                if self.current_connector
                else None
            )
            self.connector_list.clear()
            selected_row = -1
            sorted_conns = self.project.sorted_connectors()
            for idx, conn in enumerate(sorted_conns):
                dup_cnt = conn.duplicate_pin_count()
                prefix = "⚠ " if dup_cnt > 0 else ""
                item = QListWidgetItem(f"{prefix}{conn.designator}")
                item.setData(Qt.ItemDataRole.UserRole, conn.designator)
                if dup_cnt > 0:
                    item.setForeground(Qt.GlobalColor.red)
                    item.setToolTip(f"신호 중복 {dup_cnt}건")
                self.connector_list.addItem(item)
                if current_des and conn.designator == normalize_signal_name(
                    current_des
                ):
                    selected_row = idx

            if self.connector_list.count() > 0:
                if selected_row < 0:
                    selected_row = 0
                self.connector_list.setCurrentRow(selected_row)
        finally:
            self._syncing_sidebar = False

        self._refresh_current_connector_views(reset_canvas_view=False)
        self.update_status_bar()

    def build_connector_context_menu(
        self, item: QListWidgetItem | None
    ) -> QMenu:
        """빈 공간은 추가, 연결기는 추가·식별자 변경·제거 메뉴를 만든다 (제3.1절)."""
        menu = QMenu(self.connector_list)
        menu.addAction("연결기 추가...", self.open_add_connector_dialog)
        if item is not None:
            menu.addSeparator()
            menu.addAction("식별자 변경...", self.rename_selected_connector)
            menu.addAction("제거", self.remove_selected_connector)
        return menu

    def _show_connector_context_menu(self, pos) -> None:
        item = self.connector_list.itemAt(pos)
        if item is not None and item is not self.connector_list.currentItem():
            target = item.data(Qt.ItemDataRole.UserRole)
            self.connector_list.setCurrentItem(item)
            # 미완료 입력 처리에서 취소하면 선택이 바뀌지 않으므로 메뉴를 열지 않는다.
            # 처리 과정에서 목록을 다시 만들 수 있어 현재 항목을 다시 읽는다.
            item = self.connector_list.currentItem()
            if item is None or item.data(Qt.ItemDataRole.UserRole) != target:
                return
        menu = self.build_connector_context_menu(item)
        menu.exec(self.connector_list.viewport().mapToGlobal(pos))

    def _on_connector_selected(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if self._syncing_sidebar:
            return
        target = str(current.data(Qt.ItemDataRole.UserRole)) if current else None
        old_connector = self.signal_table_panel.connector
        if old_connector is not None and self.signal_table_panel.has_draft():
            # 추가 확정의 데이터 변경 신호가 다른 연결기에 적용되지 않도록
            # 기존 연결기를 선택한 상태에서 미완료 입력부터 처리한다.
            self._syncing_sidebar = True
            for i in range(self.connector_list.count()):
                item = self.connector_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == old_connector.designator:
                    self.connector_list.setCurrentItem(item)
                    break
            self._syncing_sidebar = False
            if not self._resolve_signal_draft():
                return
            self._refresh_sidebar(select_designator=target)
        self._refresh_current_connector_views(reset_canvas_view=True)

    def _refresh_current_connector_views(
        self, reset_canvas_view: bool = False
    ) -> None:
        conn = self.current_connector
        part = (
            self.project.get_part_for_connector(conn)
            if conn is not None
            else None
        )
        self.pinmap_panel.set_context(
            self.project, conn, part, reset_view=reset_canvas_view
        )
        self.signal_table_panel.set_context(self.project, conn, part)

    def add_connector(
        self,
        designator: str,
        part: ConnectorPart | None = None,
    ) -> ConnectorInstance | None:
        """프로젝트에 연결기를 추가하고 사이드바에서 선택한다."""
        if not self._resolve_signal_draft():
            return None
        self.commands.add_connector(designator, part)
        conn = self.project.get_connector(designator)
        assert conn is not None
        self.mark_dirty(True)
        self._refresh_sidebar(select_designator=conn.designator)
        self._refresh_current_connector_views(reset_canvas_view=True)
        return conn

    def open_add_connector_dialog(self) -> None:
        dlg = AddConnectorDialog(
            existing_designators=self.project.connector_designators(),
            available_parts=self.part_library.list_parts(),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.add_connector(
                dlg.selected_designator(), dlg.selected_part()
            )

    def rename_selected_connector(self) -> None:
        """선택한 연결기의 식별자를 변경한다 (제3.1절)."""
        conn = self.current_connector
        if conn is None:
            return
        raw, ok = QInputDialog.getText(
            self,
            "연결기 식별자 변경",
            f"'{conn.designator}'의 새 연결기 식별자 (영문자 시작, 영문 대문자·숫자·_):",
            text=conn.designator,
        )
        if not ok or not raw.strip():
            return
        if not is_valid_signal_name(raw):
            QMessageBox.warning(
                self,
                "식별자 규칙 오류",
                "연결기 식별자는 영문자로 시작하고 영문 대문자·숫자·언더스코어(_)만 사용할 수 있습니다(32자 이하).",
            )
            return
        norm_new = normalize_signal_name(raw)
        if not self.commands.rename_connector(conn.designator, norm_new):
            QMessageBox.warning(
                self,
                "식별자 중복",
                f"이미 존재하는 연결기 식별자입니다: '{norm_new}'",
            )
            return
        self.mark_dirty(True)
        self._refresh_sidebar(select_designator=norm_new)

    def remove_selected_connector(self) -> None:
        """선택한 연결기를 확인 창 후 제거한다 (제3.1절)."""
        conn = self.current_connector
        if conn is None:
            return
        if not self._resolve_signal_draft():
            return
        ans = QMessageBox.question(
            self,
            "연결기 제거 확인",
            f"프로젝트에서 연결기 '{conn.designator}'을(를) 제거하시겠습니까?\n"
            "(연결기 부품 데이터베이스의 원본 부품은 유지됩니다.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.commands.remove_connector(conn.designator)
            self.mark_dirty(True)
            self._refresh_sidebar()
            self._refresh_current_connector_views(reset_canvas_view=True)

    def open_signal_type_dialog(self) -> None:
        """신호유형 관리 창을 연다 (제3.10절)."""
        dlg = SignalTypeDialog(self.project, self)
        dlg.signalTypesModified.connect(self._on_signal_types_modified)
        dlg.exec()

    def _on_signal_types_modified(self) -> None:
        self.mark_dirty(True)
        self.pinmap_panel.canvas.redraw()
        self.signal_table_panel.refresh_table()

    def _on_part_change_requested(self, new_part_uuid: str) -> None:
        conn = self.current_connector
        if conn is None:
            return
        if not self._resolve_signal_draft():
            self._refresh_current_connector_views()
            return
        new_part = (
            self.part_library.get_part(new_part_uuid)
            if new_part_uuid
            else None
        )
        self.commands.change_connector_part(conn.designator, new_part)
        self.mark_dirty(True)
        self._refresh_sidebar(select_designator=conn.designator)
        self._refresh_current_connector_views(reset_canvas_view=True)

    def _on_flip_toggled(self, checked: bool) -> None:
        conn = self.current_connector
        if conn is None:
            return
        conn.flip_horizontal = checked
        self.mark_dirty(True)
        self.pinmap_panel.canvas.redraw()

    def _on_pin_signal_assigned_from_canvas(
        self, pin_designator: str, signal_name: str
    ) -> None:
        conn = self.current_connector
        if conn is None:
            return
        part = self.project.get_part_for_connector(conn)
        if conn.assign_signal_from_pinmap(
            pin_designator, signal_name or None, part
        ):
            self.mark_dirty(True)
            self.signal_table_panel.refresh_table()
            self.signal_table_panel.select_row_for_pin(pin_designator)
            self.pinmap_panel.canvas.redraw()
            self._refresh_sidebar(select_designator=conn.designator)

    def _on_signal_table_data_changed(self) -> None:
        conn = self.current_connector
        self.mark_dirty(True)
        self.pinmap_panel.canvas.redraw()
        if conn is not None:
            self._refresh_sidebar(select_designator=conn.designator)

    def _on_signal_table_pin_selected(self, pin_designator: str) -> None:
        self.pinmap_panel.canvas.select_pin(
            pin_designator, emit_signal=False
        )

    def new_project(self) -> None:
        if not self._confirm_discard_or_save():
            return
        self.project = Project(name="새 프로젝트")
        self.commands.clear()
        self.current_file_path = None
        self.mark_dirty(False)
        self._refresh_sidebar()
        self._refresh_current_connector_views(reset_canvas_view=True)

    def open_project_dialog(self) -> None:
        if not self._confirm_discard_or_save():
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "전연결기 프로젝트 열기 (.jnc)",
            "",
            "전연결기 프로젝트 (*.jnc *.json);;모든 파일 (*.*)",
        )
        if not file_path:
            return
        self.load_project_from_path(
            Path(file_path), prompt_library_sync=True
        )

    def load_project_from_path(
        self,
        path: str | Path,
        prompt_library_sync: bool = False,
        library_sync_decision: Callable[[ list[ConnectorPart]], bool] | None = None,
    ) -> bool:
        """프로젝트 파일을 불러온다 (제3.2절, 제3.3절).

        - 손상된 파일이나 상위 schema_version 파일은 오류 메시지를 표시하고 열지 않는다.
        - 프로젝트의 부품 사본이 부품 데이터베이스의 같은 UUID 부품과 다르면 자동으로 바꾸지 않고 알린다.
          사용자가 '갱신'을 선택한 경우에만 제3.3절 규칙대로 반영한다.
        """
        if not self._resolve_signal_draft():
            return False
        target = Path(path)
        try:
            loaded = load_project(target)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "프로젝트 열기 오류",
                f"프로젝트 파일을 열 수 없습니다:\n{exc}",
            )
            return False

        # 제3.3절: 프로젝트의 부품 사본과 부품 데이터베이스의 같은 UUID 부품 비교
        differing_parts: list[ConnectorPart] = []
        for p_uuid, proj_part in loaded.parts.items():
            lib_part = self.part_library.get_part(p_uuid)
            if lib_part is not None and not proj_part.is_definition_equal(
                lib_part
            ):
                differing_parts.append(lib_part)

        did_sync = False
        if differing_parts:
            should_update = False
            if library_sync_decision is not None:
                should_update = library_sync_decision(differing_parts)
            elif prompt_library_sync:
                names = ", ".join(p.name for p in differing_parts)
                ans = QMessageBox.question(
                    self,
                    "연결기 부품 정의 차이 알림",
                    f"프로젝트의 부품 사본({names})이 현재 연결기 부품 데이터베이스의 정의와 다릅니다.\n"
                    "부품 데이터베이스의 최신 정의로 갱신하시겠습니까?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                should_update = ans == QMessageBox.StandardButton.Yes

            if should_update:
                for lib_part in differing_parts:
                    loaded.sync_part_definition(lib_part)
                did_sync = True

        self.project = loaded
        self.commands.clear()
        self.current_file_path = target
        self._add_recent_file(target)
        self.mark_dirty(did_sync)
        self._refresh_available_parts()
        self._refresh_sidebar()
        self._refresh_current_connector_views(reset_canvas_view=True)
        return True

    def save_project_action(self) -> bool:
        if self.current_file_path is None:
            return self.save_project_as_dialog()
        return self.save_project_to_path(self.current_file_path)

    def save_project_as_dialog(self) -> bool:
        if not self._resolve_signal_draft():
            return False
        default_name = (
            str(self.current_file_path)
            if self.current_file_path
            else "project.jnc"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "전연결기 프로젝트 저장 (.jnc)",
            default_name,
            "전연결기 프로젝트 (*.jnc);;JSON 파일 (*.json)",
        )
        if not file_path:
            return False
        target = Path(file_path)
        if target.suffix.lower() not in (".jnc", ".json"):
            target = target.with_suffix(".jnc")
        return self.save_project_to_path(target)

    def save_project_to_path(self, path: str | Path) -> bool:
        if not self._resolve_signal_draft():
            return False
        target = Path(path)
        try:
            save_project(self.project, target)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "프로젝트 저장 오류",
                f"프로젝트 파일을 저장할 수 없습니다:\n{exc}",
            )
            return False

        self.current_file_path = target
        self.project.name = target.stem
        self._add_recent_file(target)
        self.mark_dirty(False)
        self.statusBar().showMessage(
            f"프로젝트 저장 완료: {target.name}", 4000
        )
        return True

    def _confirm_discard_or_save(self) -> bool:
        """변경사항이 있는 상태에서 종료·새로 만들기·열기 시 저장 여부를 묻는다 (제3.2절)."""
        if not self._resolve_signal_draft():
            return False
        if not self.is_dirty:
            return True
        ans = QMessageBox.question(
            self,
            "변경사항 저장 확인",
            "현재 프로젝트에 저장하지 않은 변경사항이 있습니다.\n저장하시겠습니까?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if ans == QMessageBox.StandardButton.Save:
            return self.save_project_action()
        if ans == QMessageBox.StandardButton.Discard:
            return True
        return False

    def _ask_draft_action(self) -> str:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("입력 중인 신호")
        dialog.setText("신호표에 입력 중인 값이 있습니다. 먼저 처리 방법을 선택하세요.")
        add = dialog.addButton("추가", QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton("버리기", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() == add:
            return "add"
        if dialog.clickedButton() == discard:
            return "discard"
        return "cancel"

    def _resolve_signal_draft(self) -> bool:
        panel = self.signal_table_panel
        if not panel.has_draft():
            return True
        action = self._ask_draft_action()
        if action == "add":
            return panel.commit_draft()
        if action == "discard":
            panel.reset_draft()
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.stack.currentIndex() == 1:
            if not self._sync_edited_library_parts_to_project():
                event.ignore()
                return
        if self._confirm_discard_or_save():
            self._save_window_settings()
            event.accept()
        else:
            event.ignore()
