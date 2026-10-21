"""마크다운 교환 메뉴와 일괄 등록의 화면 통합 검증."""

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from jeonnector.storage import PartLibrary
from jeonnector.ui.main_window import MainWindow


def make_window(qtbot, tmp_path):
    window = MainWindow(PartLibrary(storage_path=tmp_path / 'parts.json'))

    def discard_test_edits(widget):
        widget.signal_table_panel.reset_draft()
        widget.mark_dirty(False)

    qtbot.addWidget(window, before_close_func=discard_test_edits)
    return window


def test_exchange_menus_and_enabled_state(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    assert window.import_markdown_file_act.text() == '파일 가져오기…'
    assert window.import_markdown_folder_act.text() == '폴더 가져오기…'
    assert not window.export_markdown_selected_act.isEnabled()
    assert not window.export_markdown_all_act.isEnabled()
    assert window.export_markdown_template_act.isEnabled()
    window.add_connector('J1')
    assert window.export_markdown_selected_act.isEnabled()
    assert window.export_markdown_all_act.isEnabled()
    assert window.undo()
    assert not window.export_markdown_selected_act.isEnabled()
    assert not window.export_markdown_all_act.isEnabled()


def test_template_export_does_not_modify_project(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    target = tmp_path / 'template.md'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    before = window.project.to_dict()
    window.export_markdown_template_act.trigger()
    assert target.exists()
    assert '| 핀 번호 | 신호명 | 신호유형 | 색상 |' in target.read_text()
    assert '- 식별자 :' in target.read_text()
    assert window.project.to_dict() == before
    assert not window.is_dirty


def test_preview_disables_invalid_files_and_allows_selection(qtbot, tmp_path):
    from types import SimpleNamespace
    from jeonnector.model import ConnectorInstance
    from jeonnector.ui.markdown_dialog import MarkdownImportDialog

    good = SimpleNamespace(path=tmp_path / 'good.md', connector=ConnectorInstance('J1'), error='', warnings=[])
    bad = SimpleNamespace(path=tmp_path / 'bad.md', connector=None, error='3행: 잘못된 색상', warnings=[])
    dialog = MarkdownImportDialog([good, bad])
    qtbot.addWidget(dialog)
    assert dialog.selected_items() == [good]
    from PySide6.QtCore import Qt
    assert not dialog.table.item(1, 0).flags() & Qt.ItemFlag.ItemIsEnabled
    assert '3행' in dialog.table.item(1, 4).text()
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.selected_items() == []


def test_import_batch_is_one_undo_and_cancel_is_unchanged(qtbot, tmp_path, monkeypatch):
    from jeonnector.ui.markdown_dialog import MarkdownImportDialog

    window = make_window(qtbot, tmp_path)
    source = tmp_path / 'input.md'
    text = '- 식별자 : J1\n\n| 핀 번호 | 신호명 | 신호유형 |\n| --- | --- | --- |\n| 17 | DATA+ | CUSTOM |\n'
    source.write_text(text)
    before = window.project.to_dict()
    monkeypatch.setattr(MarkdownImportDialog, 'exec', lambda self: QDialog.DialogCode.Rejected)
    assert not window.import_markdown_paths([source])
    assert window.project.to_dict() == before
    assert not window.commands.can_undo()
    monkeypatch.setattr(MarkdownImportDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    assert window.import_markdown_paths([source])
    assert source.read_text() == text
    assert window.current_connector.rows[0].pin_designator == '17'
    assert window.project.signal_types['CUSTOM'] == ''
    assert window.undo()
    assert window.project.to_dict() == before
    assert window.redo()
    assert window.current_connector.rows[0].signal_name == 'DATA+'


def test_first_part_selection_confirms_number_preservation(qtbot, tmp_path, monkeypatch):
    from jeonnector.model import SignalDefinition, SignalRow

    window = make_window(qtbot, tmp_path)
    conn = window.add_connector('J1')
    conn.signals['DATA'] = SignalDefinition('DATA')
    conn.rows.append(SignalRow(signal_name='DATA', pin_designator='17'))
    window._refresh_current_connector_views()
    messages = []

    def refuse(parent, title, message, *args):
        messages.append(message)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, 'question', refuse)
    window.pinmap_panel.part_combo.setCurrentIndex(1)
    assert len(messages) == 1
    assert '유지' in messages[0]
    assert '해제됩니다' not in messages[0]
    assert conn.part_uuid is None
    assert conn.rows[0].pin_designator == '17'


def test_export_overwrite_refusal_preserves_file(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    target = tmp_path / 'template.md'
    target.write_text('기존 설명과 표')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.No)
    window.export_markdown_dialog(template=True)
    assert target.read_text() == '기존 설명과 표'


def test_all_export_reports_failed_paths(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    window.add_connector('J1')
    window.add_connector('J2')
    original_write = window._write_markdown_file

    def write_with_failure(path, text):
        if path.name == 'J2.md':
            raise PermissionError('쓰기 금지')
        return original_write(path, text)

    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(window, '_write_markdown_file', write_with_failure)
    reports = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, message: reports.append(message))
    window.export_markdown_dialog(all_connectors=True)
    assert (tmp_path / 'J1.md').exists()
    assert not (tmp_path / 'J2.md').exists()
    assert len(reports) == 1
    assert '성공 1개 / 실패 1개' in reports[0]
    assert 'J2.md' in reports[0]


def test_exchange_draft_cancel_prevents_import_and_export(qtbot, tmp_path, monkeypatch):
    from jeonnector.ui.signal_table import COL_SIGNAL

    window = make_window(qtbot, tmp_path)
    window.add_connector('J1')
    window.signal_table_panel.apply_cell_edit(0, COL_SIGNAL, 'DATA+')
    monkeypatch.setattr(window, '_ask_draft_action', lambda: 'cancel')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (_ for _ in ()).throw(AssertionError('취소 후 저장 창')))
    assert not window.import_markdown_paths([tmp_path / 'missing.md'])
    window.export_markdown_dialog()
    assert window.signal_table_panel.has_draft()
    assert not window.current_connector.rows


def test_folder_import_uses_natural_file_order_without_recursion(qtbot, tmp_path, monkeypatch):
    from pathlib import Path
    from jeonnector.ui.markdown_dialog import MarkdownImportDialog

    window = make_window(qtbot, tmp_path)
    first = tmp_path / '10.md'
    second = tmp_path / '2.md'
    for path in (first, second):
        path.write_text('| 신호명 |\n| --- |\n| DATA |\n')
    subfolder = tmp_path / 'nested'
    subfolder.mkdir()
    (subfolder / '1.md').write_text('| 신호명 |\n| --- |\n| NESTED |\n')
    actual_iterdir = Path.iterdir
    monkeypatch.setattr(Path, 'iterdir', lambda path: iter([first, subfolder, second]) if path == tmp_path else actual_iterdir(path))
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a, **k: str(tmp_path))
    seen = []

    def reject_after_inspecting(dialog):
        seen.extend((entry.path.name, entry.connector.designator) for entry in dialog._items)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(MarkdownImportDialog, 'exec', reject_after_inspecting)
    window.import_markdown_dialog(folder=True)
    assert seen == [('2.md', 'J1'), ('10.md', 'J2')]
    assert not window.project.connectors


def test_partial_export_write_preserves_existing_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSaveFile

    window = make_window(qtbot, tmp_path)
    target = tmp_path / 'template.md'
    target.write_text('원본 문서')
    original_write = QSaveFile.write

    def partial_write(device, data):
        return original_write(device, data[:3])

    monkeypatch.setattr(QSaveFile, 'write', partial_write)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    reports = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, message: reports.append(message))
    window.export_markdown_dialog(template=True)
    assert target.read_text() == '원본 문서'
    assert '실패 1개' in reports[0]


def test_real_preview_registers_two_files_with_one_undo(qtbot, tmp_path):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    window = make_window(qtbot, tmp_path)
    paths = [tmp_path / name for name in ('first.md', 'second.md', 'invalid.md')]
    for path, name in zip(paths[:2], ('+5V', 'RESET#')):
        path.write_text(f'| 핀 번호 | 신호명 |\n| --- | --- |\n| 1 | `{name}` |\n')
    paths[2].write_text('| 신호명 | 색상 |\n| --- | --- |\n| DATA | RED |\n')
    observed = []

    def click_register():
        dialog = QApplication.activeModalWidget()
        observed.append(len(dialog.selected_items()))
        qtbot.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, click_register)
    assert window.import_markdown_paths(paths)
    assert observed == [2]
    assert window.project.connector_designators() == ['J1', 'J2']
    assert window.undo()
    assert not window.project.connectors
    assert not window.commands.can_undo()


def test_preview_shows_pin_only_warning_for_real_file(qtbot, tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import
    from jeonnector.model import Project
    from jeonnector.ui.markdown_dialog import MarkdownImportDialog

    path = tmp_path / 'pins.md'
    path.write_text('| 핀 번호 | 신호명 |\n| --- | --- |\n| 1 | VCC |\n| 2 | |\n', encoding='utf-8')
    dialog = MarkdownImportDialog(prepare_markdown_import([path], Project()))
    qtbot.addWidget(dialog)
    assert '신호명이 없는 핀 번호 1개' in dialog.table.item(0, 4).text()
    assert len(dialog.selected_items()) == 1
