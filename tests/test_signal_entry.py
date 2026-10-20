"""신호 입력 확정·미완료 입력 보호·즉시 정렬·좁은 핀맵 회귀 검증."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QPushButton,
)

from jeonnector.model import Project
from jeonnector.storage import PartLibrary, load_project, save_project
from jeonnector.ui.main_window import MainWindow
from jeonnector.ui.signal_table import (
    COL_COLOR,
    COL_PIN,
    COL_SIGNAL,
    COL_SIGNAL_TYPE,
    DEFAULT_COLUMN_WIDTHS,
)


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    # 사용자 창 배치와 최근 파일은 conftest.py의 임시 설정 파일로 격리된다.
    win =MainWindow(PartLibrary(storage_path=tmp_path / "parts.json"))
    def prepare_close(widget):
        widget.signal_table_panel.reset_draft()
        widget.mark_dirty(False)
        widget.stack.setCurrentIndex(0)

    qtbot.addWidget(win, before_close_func=prepare_close)
    win.add_connector("J1", win.part_library.list_parts()[0])
    yield win
    monkeypatch.setattr(win, "_ask_draft_action", lambda: "discard")
    monkeypatch.setattr(win, "_confirm_discard_or_save", lambda: True)
    win.signal_table_panel.reset_draft()
    win.mark_dirty(False)
    win.stack.setCurrentIndex(0)
    win.close()


def add(panel, name, pin="", signal_type=""):
    row = len(panel.connector.rows)
    panel.apply_cell_edit(row, COL_PIN, pin)
    panel.apply_cell_edit(row, COL_SIGNAL, name)
    if signal_type:
        panel.apply_cell_edit(row, COL_SIGNAL_TYPE, signal_type)
    assert panel.commit_draft()


def rows(window):
    return [(r.signal_name, r.pin_designator) for r in window.current_connector.rows]


def test_draft_controls_and_atomic_commit(window, qtbot):
    window.show()
    qtbot.waitUntil(window.isActiveWindow)
    panel = window.signal_table_panel
    connector = window.current_connector
    window.mark_dirty(False)
    panel.draft_pin_combo.setEditText("2")
    panel.draft_name_combo.setEditText("data_p")
    panel.draft_type_combo.setEditText("새유형")
    assert not connector.rows
    assert "새유형" not in window.project.signal_types
    assert not window.is_dirty
    assert window.project.to_dict()["connectors"][0]["signals"] == []
    panel.draft_name_combo.setFocus()
    qtbot.keyClick(panel.draft_name_combo, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: len(connector.rows) == 1)
    assert rows(window) == [("DATA_P", "2")]
    assert connector.get_signal("DATA_P").signal_type == "새유형"
    assert "새유형" in window.project.signal_types
    assert window.is_dirty
    assert not panel.has_draft()
    assert panel.table.rowCount() == 2
    assert window.commands.history_count == 2  # 연결기 추가 + 신호 추가


def test_draft_validation_reset_and_existing_properties(window, qtbot):
    panel = window.signal_table_panel
    panel.draft_pin_combo.setEditText("99999")
    panel.draft_name_combo.setEditText("NEW")
    panel.draft_type_combo.setEditText("새유형")
    assert not panel.commit_draft()
    assert panel.draft.pin == "99999"
    assert not window.current_connector.rows
    assert "새유형" not in window.project.signal_types
    qtbot.mouseClick(panel.reset_button, Qt.MouseButton.LeftButton)
    assert not panel.has_draft()
    add(panel, "GND", "1", "GROUND")
    window.current_connector.set_signal_color("GND", "#123456")
    panel.draft_pin_combo.setEditText("2")
    panel.draft_name_combo.setEditText("gnd")
    assert panel.draft_type_combo.currentText() == "GROUND"
    assert panel.draft.color == "#123456"
    assert not panel.draft_type_combo.isEnabled()
    assert not panel.draft_color_button.isEnabled()
    assert not panel.apply_cell_edit(1, COL_SIGNAL_TYPE, "POWER")
    assert panel.commit_draft()
    assert window.current_connector.pins_for_signal("GND") == {"1", "2"}
    assert window.current_connector.get_signal("GND").color == "#123456"


def test_pin_only_or_invalid_type_keeps_draft(window):
    panel = window.signal_table_panel
    panel.draft_pin_combo.setEditText("1")
    assert not panel.commit_draft()
    assert panel.draft.pin == "1"
    panel.draft_name_combo.setEditText("NEW")
    panel.draft_type_combo.setEditText("잘못된 유형")
    assert not panel.commit_draft()
    assert not window.current_connector.signals
    assert panel.draft.signal_type == "잘못된 유형"


def test_no_part_allows_unassigned_signal(window):
    window.add_connector("J2")
    panel = window.signal_table_panel
    assert not panel.draft_pin_combo.isEnabled()
    panel.draft_name_combo.setEditText("UNASSIGNED")
    assert panel.commit_draft()
    assert rows(window) == [("UNASSIGNED", "")]


@pytest.mark.parametrize("column", [COL_PIN, COL_SIGNAL, COL_SIGNAL_TYPE])
@pytest.mark.parametrize("descending", [False, True])
@pytest.mark.parametrize("source", ["canvas", "table"])
def test_unassign_resorts_and_preserves_draft(window, column, descending, source):
    panel = window.signal_table_panel
    add(panel, "A", "1", "GROUND")
    add(panel, "B", "2", "POWER")
    panel.sort_by_column(column, descending)
    panel.draft_pin_combo.setEditText("3")
    panel.draft_name_combo.setEditText("PENDING")
    if source == "canvas":
        window._on_pin_signal_assigned_from_canvas("1", "")
        assert not panel.table.selectedItems()
    else:
        index = window.current_connector.first_row_index_for_pin("1")
        assert panel.apply_cell_edit(index, COL_PIN, "미할당")
    assert rows(window) == [("B", "2"), ("A", "")]
    assert panel.draft.name == "PENDING"
    assert panel.draft.pin == "3"
    assert panel.table.cellWidget(2, COL_PIN) is panel.draft_pin_combo
    assert panel.table.horizontalHeader().sortIndicatorSection() == column
    assert panel._sort_descending is descending


def test_partial_unassign_replacement_and_selected_row_identity(window):
    panel = window.signal_table_panel
    add(panel, "A", "1")
    add(panel, "A", "2")
    add(panel, "B", "3")
    window._on_pin_signal_assigned_from_canvas("1", "")
    assert rows(window) == [("A", "2"), ("B", "3")]
    assert panel.apply_cell_edit(0, COL_PIN, "4")
    assert rows(window) == [("B", "3"), ("A", "4")]
    assert panel.table.currentRow() == 1
    assert window.pinmap_panel.canvas.selected_pin == "4"
    window._on_pin_signal_assigned_from_canvas("4", "B")
    assert rows(window) == [("B", "3"), ("B", "4"), ("A", "")]
    assert panel.table.currentRow() == 1


def test_duplicate_is_committed_and_warned(window):
    panel = window.signal_table_panel
    add(panel, "A", "1")
    panel.draft_pin_combo.setEditText("1")
    panel.draft_name_combo.setEditText("B")
    assert window.project.total_duplicate_pin_warnings() == 0
    assert panel.commit_draft()
    assert window.project.total_duplicate_pin_warnings() == 1
    assert "1건" in window.warning_status_label.text()


def test_keyboard_tab_enter_and_existing_cell_edit(window, qtbot):
    window.show()
    qtbot.waitUntil(window.isActiveWindow)
    panel = window.signal_table_panel
    panel.draft_pin_combo.setFocus()
    qtbot.keyClick(panel.draft_pin_combo, Qt.Key.Key_Tab)
    assert panel.draft_name_combo.hasFocus()
    # 핀 번호 칸에서 신호명 없이 Enter를 누르면 오류 없이 신호명 칸으로 이동한다.
    panel.draft_pin_combo.setFocus()
    qtbot.keyClicks(panel.draft_pin_combo.lineEdit(), "3")
    qtbot.keyClick(panel.draft_pin_combo.lineEdit(), Qt.Key.Key_Return)
    qtbot.waitUntil(panel.draft_name_combo.hasFocus)
    assert not window.current_connector.signals
    assert panel.draft_name_combo.styleSheet() == ""
    # 신호명이 있으면 Enter로 바로 추가하고 핀 번호 칸으로 돌아간다.
    qtbot.keyClicks(panel.draft_name_combo.lineEdit(), "first")
    qtbot.keyClick(panel.draft_name_combo.lineEdit(), Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: rows(window) == [("FIRST", "3")])
    qtbot.waitUntil(panel.draft_pin_combo.hasFocus)
    assert not panel.has_draft()
    add(panel, "SECOND", "2")
    row = next(i for i, r in enumerate(window.current_connector.rows) if r.signal_name == "FIRST")
    panel.table.setCurrentCell(row, COL_PIN)
    panel.table.editItem(panel.table.item(row, COL_PIN))
    editor = QApplication.focusWidget()
    if not isinstance(editor, QComboBox):
        editor = editor.parentWidget()
    assert isinstance(editor, QComboBox)
    editor.lineEdit().selectAll()
    qtbot.keyClicks(editor.lineEdit(), "1")
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: rows(window) == [("FIRST", "1"), ("SECOND", "2")])
    assert panel.table.item(0, COL_SIGNAL).text() == "FIRST"


def test_repeated_add_does_not_overlay_previous_rows(window, qtbot):
    window.show()
    qtbot.waitUntil(window.isActiveWindow)
    panel = window.signal_table_panel
    for pin in ("1", "2", "3"):
        add(panel, f"SIGNAL_{pin}", pin)
    visible_buttons = {b for b in panel.table.findChildren(QPushButton) if b.isVisible()}
    assert visible_buttons == {panel.draft_color_button, panel.add_button, panel.reset_button}


@pytest.mark.parametrize("action", ["add", "discard", "cancel"])
def test_pending_on_save(window, tmp_path, monkeypatch, action):
    panel = window.signal_table_panel
    panel.draft_pin_combo.setEditText("2")
    panel.draft_name_combo.setEditText("NEW")
    monkeypatch.setattr(window, "_ask_draft_action", lambda: action)
    path = tmp_path / "project.jnc"
    success = window.save_project_to_path(path)
    assert success is (action != "cancel")
    if action == "cancel":
        assert not path.exists()
        assert panel.draft.name == "NEW"
    else:
        saved = load_project(path)
        signals = saved.get_connector("J1").signals
        assert ("NEW" in signals) is (action == "add")
        assert not panel.has_draft()


def test_invalid_pending_add_prevents_save_and_transition(window, tmp_path, monkeypatch):
    panel = window.signal_table_panel
    panel.draft_pin_combo.setEditText("1")
    monkeypatch.setattr(window, "_ask_draft_action", lambda: "add")
    assert not window.save_project_to_path(tmp_path / "invalid.jnc")
    window.switch_to_editor_view()
    assert window.stack.currentIndex() == 0
    assert panel.draft.pin == "1"
    assert not window.current_connector.rows


@pytest.mark.parametrize("action", ["add", "discard", "cancel"])
def test_pending_connector_selection(window, monkeypatch, action):
    original = window.current_connector
    other = window.add_connector("J2", window.part_library.list_parts()[0])
    window.connector_list.setCurrentRow(0)
    panel = window.signal_table_panel
    panel.draft_name_combo.setEditText("FIRST_ONLY")
    monkeypatch.setattr(window, "_ask_draft_action", lambda: action)
    window.connector_list.setCurrentRow(1)
    assert window.current_connector is (original if action == "cancel" else other)
    assert ("FIRST_ONLY" in original.signals) is (action == "add")
    assert not other.signals
    assert panel.has_draft() is (action == "cancel")


def test_pending_part_change_and_close_cancel(window, monkeypatch):
    connector = window.current_connector
    part_uuid = connector.part_uuid
    panel = window.signal_table_panel
    panel.draft_name_combo.setEditText("PENDING")
    monkeypatch.setattr(window, "_ask_draft_action", lambda: "cancel")
    other = next(p for p in window.part_library.list_parts() if p.uuid != part_uuid)
    window._on_part_change_requested(other.uuid)
    assert connector.part_uuid == part_uuid
    window.show()
    assert not window.close()
    assert window.isVisible()
    assert panel.draft.name == "PENDING"


@pytest.mark.parametrize("transition", ["editor", "new", "load", "part"])
@pytest.mark.parametrize("action", ["add", "discard", "cancel"])
def test_pending_across_project_transitions(window, tmp_path, monkeypatch, transition, action):
    original_project = window.project
    original = window.current_connector
    panel = window.signal_table_panel
    panel.draft_name_combo.setEditText("PENDING")
    monkeypatch.setattr(window, "_ask_draft_action", lambda: action)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )
    if transition == "editor":
        window.switch_to_editor_view()
        assert window.stack.currentIndex() == (0 if action == "cancel" else 1)
    elif transition == "new":
        window.new_project()
        assert (window.project is original_project) is (action == "cancel")
    elif transition == "load":
        path = tmp_path / "other.jnc"
        save_project(Project(name="다른 프로젝트"), path)
        assert window.load_project_from_path(path) is (action != "cancel")
        assert (window.project is original_project) is (action == "cancel")
    else:
        part_uuid = original.part_uuid
        other = next(p for p in window.part_library.list_parts() if p.uuid != part_uuid)
        window._on_part_change_requested(other.uuid)
        assert original.part_uuid == (part_uuid if action == "cancel" else other.uuid)
    assert ("PENDING" in original.signals) is (action == "add")
    assert panel.has_draft() is (action == "cancel")


def test_narrow_pinmap_retains_controls(window, qtbot):
    window.show()
    qtbot.waitUntil(window.isVisible)
    panel = window.pinmap_panel
    assert panel.minimumSizeHint().width() <= 250
    # 창 너비는 글꼴·플랫폼에 따라 달라지므로 신호표를 최대한 넓혀 핀맵을 최소 너비 근처까지 줄인다.
    workspace = window.project_workspace
    workspace.resizeDocks([window.signal_dock], [workspace.width()], Qt.Orientation.Horizontal)
    qtbot.waitUntil(lambda: panel.width() <= panel.minimumSizeHint().width() + 20)
    for button in (panel.zoom_in_btn, panel.zoom_out_btn, panel.fit_btn, panel.flip_checkbox):
        assert button.isVisible()
        assert button.geometry().right() < panel.width()
    assert panel.connector_title_label.toolTip()
    panel.zoom_in_btn.click()
    panel.flip_checkbox.click()
    assert window.current_connector.flip_horizontal


def test_column_widths_adjustable_scroll_and_remembered(window, qtbot, tmp_path):
    panel = window.signal_table_panel
    header = panel.table.horizontalHeader()
    assert all(
        header.sectionResizeMode(col) == QHeaderView.ResizeMode.Interactive
        for col in range(panel.table.columnCount())
    )
    assert not header.stretchLastSection()
    assert panel.column_widths() == DEFAULT_COLUMN_WIDTHS

    # 열 너비 합계가 표보다 넓으면 가로 스크롤 바가 생긴다.
    window.show()
    qtbot.waitUntil(window.isVisible)
    panel.table.setColumnWidth(COL_SIGNAL, 3000)
    qtbot.waitUntil(lambda: panel.table.horizontalScrollBar().maximum() > 0)

    # 종료 시 저장한 열 너비를 다음 실행에서 복원하고, 배치 초기화로 기본값으로 되돌린다.
    panel.table.setColumnWidth(COL_SIGNAL, 260)
    widths = panel.column_widths()
    window._save_window_settings()
    other = MainWindow(PartLibrary(storage_path=tmp_path / "parts2.json"))
    qtbot.addWidget(other)
    assert other.signal_table_panel.column_widths() == widths
    other.reset_window_layout()
    assert other.signal_table_panel.column_widths() == DEFAULT_COLUMN_WIDTHS

    panel.set_column_widths([10, 20])  # 열 수가 다른 저장값은 무시한다.
    assert panel.column_widths() == widths


def menu_actions(menu):
    return {a.text(): a for a in menu.actions() if a.text()}


def test_signal_type_cell_menu_color_and_rename(window, monkeypatch):
    panel = window.signal_table_panel
    project = window.project
    add(panel, "PWR", "1", "POWER")
    add(panel, "VCC", "2", "POWER")
    add(panel, "NOTYPE", "3")
    connector = window.current_connector
    connector.set_signal_color("VCC", "#00ff00")
    row = [r.signal_name for r in connector.rows].index("PWR")

    # 신호유형 칸 외에는 기존 신호 개별 색상 메뉴, 입력 행에는 메뉴가 없다.
    assert list(menu_actions(panel.build_cell_context_menu(row, COL_SIGNAL))) == [
        "'PWR' 색상 선택...", "'PWR' 색상 없음 (신호유형 색상 사용)",
    ]
    assert panel.build_cell_context_menu(len(connector.rows), COL_SIGNAL_TYPE) is None
    no_type_row = [r.signal_name for r in connector.rows].index("NOTYPE")
    no_type = menu_actions(panel.build_cell_context_menu(no_type_row, COL_SIGNAL_TYPE))
    assert list(no_type) == ["신호유형 없음"] and not no_type["신호유형 없음"].isEnabled()

    # 유형 색상 변경: 영향 신호 수 표시, 개별 색상 신호 안내, 변경 표시
    actions = menu_actions(panel.build_cell_context_menu(row, COL_SIGNAL_TYPE))
    assert list(actions) == [
        "'POWER' 유형 색상 변경... (프로젝트 신호 2개)",
        "'POWER' 유형 색상 없음",
        "'POWER' 유형 이름 변경...",
    ]
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#123456"))
    messages = []
    panel.statusMessage.connect(messages.append)
    window.mark_dirty(False)
    actions["'POWER' 유형 색상 변경... (프로젝트 신호 2개)"].trigger()
    assert project.signal_type_color("POWER") == "#123456"
    assert window.is_dirty
    assert "신호 1개" in messages[-1]
    menu_actions(panel.build_cell_context_menu(row, COL_SIGNAL_TYPE))["'POWER' 유형 색상 없음"].trigger()
    assert project.signal_type_color("POWER") == ""

    # 유형 이름 변경: 모든 신호와 입력 중인 행이 새 이름을 따른다.
    panel.apply_cell_edit(len(connector.rows), COL_SIGNAL_TYPE, "POWER")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("main_power", True))
    menu_actions(panel.build_cell_context_menu(row, COL_SIGNAL_TYPE))["'POWER' 유형 이름 변경..."].trigger()
    assert "MAIN_POWER" in project.signal_types and "POWER" not in project.signal_types
    assert connector.get_signal("PWR").signal_type == "MAIN_POWER"
    assert connector.get_signal("VCC").signal_type == "MAIN_POWER"
    assert panel.draft.signal_type == "MAIN_POWER"


def test_color_column_shows_individual_type_or_none(window):
    panel = window.signal_table_panel
    window.project.set_signal_type_color("POWER", "#ef4444")
    add(panel, "PWR", "1", "POWER")
    add(panel, "PLAIN", "2")
    panel.draft_name_combo.setEditText("CUSTOM")
    panel.draft_pin_combo.setEditText("3")
    panel.draft.color = "#123456"
    assert panel.commit_draft()
    labels = {
        panel.table.item(r, COL_SIGNAL).text(): (
            panel.table.item(r, COL_COLOR).text(), panel.table.item(r, COL_COLOR).toolTip()
        )
        for r in range(len(window.current_connector.rows))
    }
    assert labels["PWR"] == ("유형", "유형 색상 #ef4444")
    assert labels["PLAIN"] == ("없음", "색상 없음")
    assert labels["CUSTOM"] == ("개별", "개별 색상 #123456")
    panel.draft_type_combo.setEditText("POWER")
    assert panel.draft_color_button.text() == "유형"
    panel.draft.color = "#00ff00"
    panel._update_draft_color_button()
    assert panel.draft_color_button.text() == "개별"


def test_sidebar_shows_identifier_and_context_menu(window):
    assert window.sidebar_dock.windowTitle() == "연결기 목록"
    assert not window.sidebar_dock.findChildren(QPushButton)
    item = window.connector_list.item(0)
    assert item.text() == "J1"
    assert item.toolTip() == ""
    empty_menu = [a.text() for a in window.build_connector_context_menu(None).actions()]
    assert empty_menu == ["연결기 추가..."]
    item_menu = [
        a.text() for a in window.build_connector_context_menu(item).actions() if a.text()
    ]
    assert item_menu == ["연결기 추가...", "식별자 변경...", "제거"]

    panel = window.signal_table_panel
    add(panel, "A", "3")
    add(panel, "B", "3")
    item = window.connector_list.item(0)
    assert item.text() == "⚠ J1"
    assert item.toolTip() == "신호 중복 1건"


def test_unassigned_pin_and_no_type_start_blank(window, qtbot):
    window.show()
    qtbot.waitUntil(window.isActiveWindow)
    panel = window.signal_table_panel
    for combo, placeholder in ((panel.draft_pin_combo, "미할당"), (panel.draft_type_combo, "없음")):
        assert combo.currentText() == ""
        assert combo.lineEdit().placeholderText() == placeholder
    qtbot.keyClicks(panel.draft_type_combo.lineEdit(), "POWER")
    assert panel.draft.signal_type == "POWER"
    panel.draft_type_combo.textActivated.emit("없음")
    assert panel.draft_type_combo.currentText() == "" and panel.draft.signal_type == ""

    add(panel, "SPARE")
    row = next(i for i, r in enumerate(window.current_connector.rows) if r.signal_name == "SPARE")
    assert panel.table.item(row, COL_PIN).text() == ""
    panel.table.setCurrentCell(row, COL_PIN)
    panel.table.editItem(panel.table.item(row, COL_PIN))
    editor = QApplication.focusWidget()
    if not isinstance(editor, QComboBox):
        editor = editor.parentWidget()
    assert editor.currentText() == "" and editor.lineEdit().placeholderText() == "미할당"
    qtbot.keyClicks(editor.lineEdit(), "4")
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: ("SPARE", "4") in rows(window))


def test_undo_redo_project_edits_and_focus(window, qtbot):
    window.show()
    qtbot.waitUntil(window.isActiveWindow)
    panel = window.signal_table_panel
    window.commands.mark_saved()
    window.mark_dirty(False)
    assert not window.undo_act.isEnabled() or window.commands.can_undo()

    add(panel, "GND", "1")
    assert window.undo_act.text() == "실행 취소: 신호 행 추가: GND"
    window.pinmap_panel.flip_checkbox.setChecked(True)
    window._on_pin_signal_assigned_from_canvas("2", "GND")
    assert window.current_connector.pins_for_signal("GND") == {"1", "2"}

    window.add_connector("J2", window.part_library.list_parts()[0])
    assert window.current_connector.designator == "J2"
    assert window.undo()  # 연결기 추가 취소
    assert window.project.get_connector("J2") is None
    assert window.undo()  # 핀맵 할당 취소, J1을 보여 준다
    assert window.current_connector.designator == "J1"
    assert window.current_connector.pins_for_signal("GND") == {"1"}
    assert window.undo()  # 좌우 반전 취소
    assert not window.pinmap_panel.flip_checkbox.isChecked()
    assert not window.current_connector.flip_horizontal
    assert window.undo()  # 신호 추가 취소 → 저장 시점으로 돌아옴
    assert not window.current_connector.signals
    assert not window.is_dirty and not window.windowTitle().endswith("*")
    assert window.redo()
    assert rows(window) == [("GND", "1")]
    assert window.is_dirty

    # 글자가 있는 입력 칸에서는 Ctrl+Z가 프로젝트 실행 취소로 넘어가지 않고, 빈 칸에서는 넘어간다.
    window._ask_draft_action = lambda: pytest.fail("입력 중 Ctrl+Z가 프로젝트 실행 취소로 넘어감")
    panel.draft_pin_combo.setFocus()
    qtbot.keyClicks(panel.draft_pin_combo.lineEdit(), "3")
    qtbot.keyClick(panel.draft_pin_combo, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert rows(window) == [("GND", "1")]
    del window._ask_draft_action
    panel.reset_draft()
    panel.draft_pin_combo.setFocus()
    qtbot.keyClick(panel.draft_pin_combo, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not window.current_connector.signals)

    window.switch_to_editor_view()
    assert not window.undo_act.isEnabled() and not window.redo_act.isEnabled()
    assert not window.redo()
    window.switch_to_project_view()
    assert window.redo_act.isEnabled()
