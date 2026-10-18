"""신호 입력 확정·미완료 입력 보호·즉시 정렬·좁은 핀맵 회귀 검증."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QPushButton

from jeonnector.model import Project
from jeonnector.storage import PartLibrary, load_project, save_project
from jeonnector.ui.main_window import MainWindow
from jeonnector.ui.signal_table import COL_PIN, COL_SIGNAL, COL_SIGNAL_TYPE


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    # 사용자 창 배치와 최근 파일을 테스트에서 읽거나 덮어쓰지 않는다.
    monkeypatch.setattr(MainWindow, "_restore_window_settings", lambda self: None)
    monkeypatch.setattr(MainWindow, "_save_window_settings", lambda self: None)
    monkeypatch.setattr(MainWindow, "recent_files", lambda self: [])
    monkeypatch.setattr(MainWindow, "_add_recent_file", lambda self, path: None)
    win = MainWindow(PartLibrary(storage_path=tmp_path / "parts.json"))
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
    add(panel, "GND", "1", "접지")
    window.current_connector.set_signal_color("GND", "#123456")
    panel.draft_pin_combo.setEditText("2")
    panel.draft_name_combo.setEditText("gnd")
    assert panel.draft_type_combo.currentText() == "접지"
    assert panel.draft.color == "#123456"
    assert not panel.draft_type_combo.isEnabled()
    assert not panel.draft_color_button.isEnabled()
    assert not panel.apply_cell_edit(1, COL_SIGNAL_TYPE, "전원")
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
    add(panel, "A", "1", "접지")
    add(panel, "B", "2", "전원")
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
    qtbot.keyClicks(panel.draft_name_combo.lineEdit(), "first")
    qtbot.keyClick(panel.draft_name_combo, Qt.Key.Key_Return)
    assert not window.current_connector.signals  # Enter로 행을 추가하지 않는다.
    qtbot.mouseClick(panel.add_button, Qt.MouseButton.LeftButton)
    assert rows(window) == [("FIRST", "")]
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
    window.project_workspace.resizeDocks([window.signal_dock], [900], Qt.Orientation.Horizontal)
    qtbot.waitUntil(lambda: panel.width() <= 280)
    for button in (panel.zoom_in_btn, panel.zoom_out_btn, panel.fit_btn, panel.flip_checkbox):
        assert button.isVisible()
        assert button.geometry().right() < panel.width()
    assert panel.connector_title_label.toolTip()
    panel.zoom_in_btn.click()
    panel.flip_checkbox.click()
    assert window.current_connector.flip_horizontal
