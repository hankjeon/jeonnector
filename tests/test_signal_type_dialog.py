"""신호유형 관리 창의 표 안 편집과 선택한 행의 색상 칸 표시 검증."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QColorDialog, QDialogButtonBox, QMessageBox, QPushButton

from jeonnector.model import ConnectorInstance, Project, SignalDefinition, SignalRow
from jeonnector.ui.signal_type_dialog import COL_COLOR, COL_NAME, SignalTypeDialog


def make_dialog(qtbot, project=None):
    project = project or Project()
    dialog = SignalTypeDialog(project)
    qtbot.addWidget(dialog)
    changes = []
    dialog.signalTypesModified.connect(lambda: changes.append(True))
    return dialog, project, changes


def row_of(dialog, name):
    return dialog.type_names().index(name)


def project_with_power_signal():
    project = Project()
    project.connectors.append(ConnectorInstance(
        "J1", signals={"VCC": SignalDefinition("VCC", "POWER")}, rows=[SignalRow("VCC", "1")]))
    return project


def test_layout_has_draft_row_and_korean_close_without_old_buttons(qtbot):
    dialog, project, _ = make_dialog(qtbot)
    table = dialog.table
    assert table.rowCount() == len(project.signal_types) + 1
    assert table.verticalHeaderItem(table.rowCount() - 1).text() == "+"
    assert table.cellWidget(table.rowCount() - 1, COL_NAME) is dialog.draft_name_edit
    texts = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "닫기" in texts and not texts & {"이름 변경", "색상 선택", "삭제", "Close"}
    close = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Close)
    assert not close.autoDefault()


def test_selected_row_keeps_color_visible(qtbot):
    dialog, project, _ = make_dialog(qtbot)
    dialog.show()
    row = row_of(dialog, "POWER")
    dialog.table.selectRow(row)
    rect = dialog.table.visualRect(dialog.table.model().index(row, COL_COLOR))
    image = dialog.table.viewport().grab().toImage()
    sample = image.pixelColor(rect.left() + 8, rect.center().y())
    assert sample.name() == project.signal_types["POWER"]


def test_signal_table_selected_row_keeps_color_visible(qtbot):
    from jeonnector.ui.signal_table import COL_COLOR as TABLE_COL_COLOR, SignalTablePanel

    project = project_with_power_signal()
    panel = SignalTablePanel()
    qtbot.addWidget(panel)
    panel.set_context(project, project.connectors[0], None)
    panel.resize(700, 300)
    panel.show()
    panel.table.selectRow(0)
    rect = panel.table.visualRect(panel.table.model().index(0, TABLE_COL_COLOR))
    sample = panel.table.viewport().grab().toImage().pixelColor(rect.left() + 8, rect.center().y())
    assert sample.name() == project.signal_types["POWER"]


def test_inline_rename_follows_signals_and_rejects_invalid(qtbot, monkeypatch):
    project = project_with_power_signal()
    dialog, _, changes = make_dialog(qtbot, project)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    dialog.table.item(row_of(dialog, "POWER"), COL_NAME).setText("main_power")
    assert "MAIN_POWER" in project.signal_types and "POWER" not in project.signal_types
    assert project.connectors[0].signals["VCC"].signal_type == "MAIN_POWER"
    assert changes == [True]
    selected = dialog.table.currentRow()
    assert dialog.table.item(selected, COL_NAME).text() == "MAIN_POWER"

    dialog.table.item(row_of(dialog, "GROUND"), COL_NAME).setText("BAD NAME")
    assert len(warnings) == 1 and "GROUND" in project.signal_types
    assert dialog.table.item(row_of(dialog, "GROUND"), COL_NAME).text() == "GROUND"
    dialog.table.item(row_of(dialog, "GROUND"), COL_NAME).setText("ANALOG")
    assert len(warnings) == 2 and "GROUND" in project.signal_types
    assert changes == [True]


def test_enter_in_draft_row_adds_type_without_closing(qtbot, monkeypatch):
    dialog, project, changes = make_dialog(qtbot)
    dialog.show()
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#123456"))
    dialog.draft_color_button.click()
    dialog.draft_name_edit.setText("신호_A")
    QTest.keyClick(dialog.draft_name_edit, Qt.Key.Key_Return)
    assert dialog.isVisible()
    assert project.signal_types["신호_A"] == "#123456"
    assert changes == [True]
    assert dialog.draft_name_edit.text() == "" and dialog.draft_color_button.text() == "없음"
    assert dialog.table.item(dialog.table.currentRow(), COL_NAME).text() == "신호_A"

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    dialog.draft_name_edit.setText("power")
    QTest.keyClick(dialog.draft_name_edit, Qt.Key.Key_Return)
    assert len(warnings) == 1 and dialog.draft_name_edit.text() == "power"
    assert changes == [True]


def test_color_double_click_and_context_menu(qtbot, monkeypatch):
    dialog, project, changes = make_dialog(qtbot)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#abcdef"))
    dialog._on_cell_double_clicked(row_of(dialog, "ANALOG"), COL_COLOR)
    assert project.signal_types["ANALOG"] == "#abcdef"
    menu = dialog.build_cell_context_menu(row_of(dialog, "ANALOG"))
    labels = [action.text() for action in menu.actions()]
    assert labels == ["'ANALOG' 이름 변경", "'ANALOG' 색상 선택...", "'ANALOG' 색상 없음"]
    menu.actions()[2].trigger()
    assert project.signal_types["ANALOG"] == ""
    assert not dialog.build_cell_context_menu(row_of(dialog, "ANALOG")).actions()[2].isEnabled()
    assert dialog.build_cell_context_menu(dialog.table.rowCount() - 1) is None
    assert changes == [True, True]


def test_delete_confirms_only_when_used(qtbot, monkeypatch):
    project = project_with_power_signal()
    dialog, _, changes = make_dialog(qtbot, project)
    answers = []

    def answer(choice):
        def ask(*args, **kwargs):
            answers.append(args[2])
            return choice
        return ask

    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.No))
    dialog.build_row_header_menu(row_of(dialog, "POWER")).actions()[0].trigger()
    assert "POWER" in project.signal_types and "신호 1개" in answers[0]
    monkeypatch.setattr(QMessageBox, "question", answer(QMessageBox.StandardButton.Yes))
    assert dialog.delete_type("POWER")
    assert "POWER" not in project.signal_types
    assert project.connectors[0].signals["VCC"].signal_type == ""
    assert dialog.delete_type("ANALOG") and len(answers) == 2  # 쓰지 않는 유형은 묻지 않음
    assert dialog.build_row_header_menu(dialog.table.rowCount() - 1) is None
    assert changes == [True, True]


def test_rename_through_real_cell_editor(qtbot):
    from PySide6.QtWidgets import QLineEdit

    dialog, project, changes = make_dialog(qtbot, project_with_power_signal())
    dialog.show()
    item = dialog.table.item(row_of(dialog, "POWER"), COL_NAME)
    dialog.table.setCurrentItem(item)
    dialog.table.editItem(item)
    editor = dialog.table.indexWidget(dialog.table.indexFromItem(item))
    assert isinstance(editor, QLineEdit)
    editor.setText("전원")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    qtbot.wait(20)  # 위임자는 Enter 확정을 다음 이벤트 처리 때 반영한다
    assert dialog.isVisible()
    assert "전원" in project.signal_types and "POWER" not in project.signal_types
    assert project.connectors[0].signals["VCC"].signal_type == "전원"
    assert changes == [True]
