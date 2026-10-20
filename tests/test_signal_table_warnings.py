"""부품 없는 신호표 입력과 부품 불일치 경고 검증."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from jeonnector.default_parts import create_default_parts
from jeonnector.model import DUPLICATE_CELL_BG_COLOR, PinDefinition, Project
from jeonnector.ui.signal_table import COL_PIN, COL_SIGNAL, SignalTablePanel


@pytest.fixture
def panel(qtbot):
    project = Project()
    conn = project.add_connector("J1")
    widget = SignalTablePanel()
    qtbot.addWidget(widget)
    widget.set_context(project, conn, None)
    return widget


def add(panel, name, pin):
    panel.draft_pin_combo.setEditText(pin)
    panel.draft_name_combo.setEditText(name)
    assert panel.commit_draft()


def test_no_part_allows_draft_and_existing_pin_edit(panel):
    assert panel.draft_pin_combo.isEnabled()
    add(panel, "+5v", "A10")
    assert [(r.signal_name, r.pin_designator) for r in panel.connector.rows] == [("+5V", "A10")]
    index = panel.table.model().index(0, COL_PIN)
    editor = panel.delegate.createEditor(panel.table, None, index)
    assert editor.isEnabled()
    panel.delegate.setEditorData(editor, index)
    editor.setEditText("a1")
    panel.delegate.setModelData(editor, panel.table.model(), index)
    assert panel.connector.rows[0].pin_designator == "a1"
    item = panel.table.item(0, COL_PIN)
    assert item.background().style() == Qt.BrushStyle.NoBrush
    assert "선택된 후" not in item.toolTip()


def test_unknown_part_pin_is_committed_and_editable(panel):
    part = create_default_parts()[0]
    panel.project.change_connector_part("J1", part)
    panel.set_context(panel.project, panel.connector, part)
    add(panel, "DATA+", "999")
    assert panel.apply_cell_edit(0, COL_PIN, "a")
    assert panel.connector.rows[0].pin_designator == "a"
    assert panel.apply_cell_edit(0, COL_SIGNAL, "reset#")
    assert panel.connector.rows[0].signal_name == "RESET#"


def test_invalid_input_messages_describe_format_only(panel, monkeypatch):
    messages = []
    panel.statusMessage.connect(messages.append)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    panel.draft_name_combo.setEditText("+-")
    assert not panel.commit_draft()
    assert "영문자·숫자·+·-" in messages[-1]
    assert "_ + - # / ." in messages[-1]
    panel.draft_name_combo.setEditText("GOOD")
    panel.draft_pin_combo.setEditText("A 1")
    assert not panel.commit_draft()
    assert "공백" in messages[-1]
    assert "존재" not in messages[-1]
    assert panel.draft.pin == "A 1"
    panel.draft_pin_combo.setEditText("A1")
    assert panel.commit_draft()
    assert not panel.apply_cell_edit(0, COL_SIGNAL, "#BAD")
    assert "_ + - # / ." in messages[-1]
    assert not panel.apply_cell_edit(0, COL_PIN, " A")
    assert "공백" in messages[-1]
    assert "부품" not in messages[-1]


def test_mismatch_background_and_automatic_recovery(panel):
    add(panel, "GND", "1")
    add(panel, "GND", "a")
    part = create_default_parts()[0]
    panel.project.change_connector_part("J1", part)
    panel.set_context(panel.project, panel.connector, part)
    normal = panel.table.item(0, COL_PIN)
    assert normal.background().style() == Qt.BrushStyle.NoBrush
    warning = panel.table.item(1, COL_PIN)
    assert warning.background().color().name() == "#fed7aa"
    assert "부품 불일치" in warning.toolTip()
    assert "a" in warning.toolTip()
    assert "부품 불일치" not in panel.table.item(1, COL_SIGNAL).toolTip()
    assert panel.project.total_duplicate_pin_warnings() == 0
    assert panel.project.total_unassigned_signal_rows() == 0
    restored = part.clone()
    restored.pins.append(PinDefinition("a", 0, 0))
    panel.project.sync_part_definition(restored)
    panel.set_context(panel.project, panel.connector, panel.project.get_part_for_connector(panel.connector))
    recovered = panel.table.item(1, COL_PIN)
    assert recovered.background().style() == Qt.BrushStyle.NoBrush
    assert recovered.toolTip() == ""
    assert len(panel.connector.rows) == 2


def test_duplicate_has_priority_and_combines_tooltip(panel):
    add(panel, "DATA+", "a")
    add(panel, "DATA-", "a")
    for row in range(2):
        item = panel.table.item(row, COL_PIN)
        assert item.background().color().name() == DUPLICATE_CELL_BG_COLOR
        assert "신호 중복" in item.toolTip()
        assert "부품 불일치" not in item.toolTip()
    part = create_default_parts()[0]
    panel.project.change_connector_part("J1", part)
    panel.set_context(panel.project, panel.connector, part)
    for row in range(2):
        item = panel.table.item(row, COL_PIN)
        assert item.background().color().name() == DUPLICATE_CELL_BG_COLOR
        assert "신호 중복" in item.toolTip()
        assert "부품 불일치" in item.toolTip()
    assert panel.project.total_duplicate_pin_warnings() == 1
    assert panel.apply_cell_edit(0, COL_PIN, "1")
    warning = panel.table.item(1, COL_PIN)
    assert warning.background().color().name() == "#fed7aa"
    assert "신호 중복" not in warning.toolTip()
    assert panel.apply_cell_edit(1, COL_PIN, "2")
    assert panel.table.item(1, COL_PIN).background().style() == Qt.BrushStyle.NoBrush
    assert panel.table.item(1, COL_PIN).toolTip() == ""


@pytest.mark.parametrize("with_part,pin,expected", [
    (False, "1", ""), (True, "1", "1"), (True, "a", ""), (True, "", ""),
])
def test_selection_emits_only_existing_physical_pin(panel, with_part, pin, expected):
    part = create_default_parts()[0] if with_part else None
    panel.project.change_connector_part("J1", part)
    panel.set_context(panel.project, panel.connector, part)
    add(panel, "GND", pin)
    emitted = []
    panel.pinSelectionChanged.connect(emitted.append)
    panel.table.clearSelection()
    panel.table.setCurrentCell(0, COL_PIN)
    panel.table.selectRow(0)
    assert emitted[-1] == expected
