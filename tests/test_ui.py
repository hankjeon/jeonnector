"""전연결기(jeonnector) UI 통합 테스트 (핀맵, 신호표, 신호유형 관리, 연결기 부품 편집기, 메인 윈도우)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDockWidget

from jeonnector.model import (
    DUPLICATE_CELL_BG_COLOR,
    EMPTY_PART_MESSAGE,
)
from jeonnector.storage import PartLibrary
from jeonnector.ui.connector_editor import MODE_ADD_PIN, MODE_SELECT
from jeonnector.ui.main_window import MainWindow
from jeonnector.ui.pinmap_canvas import AURA_ALPHA, SELECTED_PIN_BORDER_WIDTH
from jeonnector.ui.signal_table import (
    COL_PIN,
    COL_SIGNAL,
    COL_SIGNAL_TYPE,
)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_layout_and_workflow(
    qapp: QApplication, tmp_path: Path
) -> None:
    """메인 화면 레이아웃, 부품 미선택 표시, 신호표·핀맵 양방향 연동, 좌우 반전, 부품 동기화 통합 검증."""
    lib = PartLibrary(storage_path=tmp_path / "test_lib.json")
    win = MainWindow(part_library=lib)
    win.show()
    qapp.processEvents()

    # 1. 사이드바와 신호표 도킹/플로팅 가능 여부 확인 (제4.1절)
    dock_features = win.sidebar_dock.features()
    assert bool(dock_features & QDockWidget.DockWidgetFeature.DockWidgetMovable)
    assert bool(
        dock_features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    sig_features = win.signal_dock.features()
    assert bool(sig_features & QDockWidget.DockWidgetFeature.DockWidgetMovable)
    assert bool(
        sig_features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )

    # 2. 부품이 없는 연결기 추가 시 핀맵 안내 문구 및 버튼 비활성화 확인 (제3.4절, 제4.1절)
    conn_no_part = win.add_connector("J_NONE", None)
    assert win.current_connector is conn_no_part
    assert win.pinmap_panel.part_action_label.text() == "부품 선택:"
    assert not win.pinmap_panel.flip_checkbox.isEnabled()
    assert not win.pinmap_panel.fit_btn.isEnabled()
    empty_texts = [
        item.toPlainText()
        for item in win.pinmap_panel.canvas.scene().items()
        if hasattr(item, "toPlainText")
    ]
    assert any(EMPTY_PART_MESSAGE in t for t in empty_texts)
    win.commands.remove_connector("J_NONE")

    # 3. 부품이 있는 연결기 추가 및 기본 빈 행 확인 (제3.6절)
    part_9p = lib.list_parts()[0]
    conn = win.add_connector("J1", part_9p)
    assert win.current_connector is conn
    assert win.pinmap_panel.part_action_label.text() == "부품 변경:"
    assert win.pinmap_panel.face_badge_label.text() == "정면"
    assert win.signal_table_panel.table.rowCount() == 1

    # 4. 핀 번호부터 입력하고 추가 버튼 동작으로 함께 확정
    assert win.signal_table_panel.apply_cell_edit(0, COL_PIN, "1")
    assert win.signal_table_panel.apply_cell_edit(0, COL_SIGNAL, "gnd")
    assert not conn.rows
    assert win.signal_table_panel.commit_draft()
    assert len(conn.rows) == 1
    assert conn.rows[0].signal_name == "GND"
    assert win.signal_table_panel.table.rowCount() == 2

    # 두 번째 행에 GND 추가 후 2번 핀 할당, 세 번째 행에 VCC_5V 추가 후 2번 핀 중복 할당
    assert win.signal_table_panel.apply_cell_edit(1, COL_SIGNAL, "GND")
    assert win.signal_table_panel.apply_cell_edit(1, COL_PIN, "2")
    assert win.signal_table_panel.commit_draft()
    assert win.signal_table_panel.apply_cell_edit(2, COL_SIGNAL, "VCC_5V")
    assert win.signal_table_panel.apply_cell_edit(2, COL_PIN, "2")
    assert win.signal_table_panel.commit_draft()
    assert len(conn.rows) == 3
    assert win.signal_table_panel.table.rowCount() == 4

    # 5. 신호유형 설정 및 새 신호유형 직접 입력 추가 확인 (제3.10절)
    assert win.signal_table_panel.apply_cell_edit(0, COL_SIGNAL_TYPE, "접지")
    assert win.signal_table_panel.apply_cell_edit(
        2, COL_SIGNAL_TYPE, "사용자전원유형"
    )
    assert "사용자전원유형" in win.project.signal_types
    # 새로 만든 신호유형의 초기 색상은 '없음'("")이어야 함
    assert win.project.signal_type_color("사용자전원유형") == ""
    # 같은 신호(GND)의 다른 행에도 신호유형이 즉시 공유 반영되어야 함
    assert (
        win.signal_table_panel.table.item(1, COL_SIGNAL_TYPE).text() == "접지"
    )

    # 6. 신호 중복 표시 및 상태바 경고 집계 확인 (제3.4절, 제3.9절, 제3.12절)
    assert win.project.total_duplicate_pin_warnings() == 1
    assert "1건" in win.warning_status_label.text()

    bg1 = (
        win.signal_table_panel.table.item(1, COL_PIN)
        .background()
        .color()
        .name()
        .lower()
    )
    bg2 = (
        win.signal_table_panel.table.item(2, COL_PIN)
        .background()
        .color()
        .name()
        .lower()
    )
    assert bg1 == DUPLICATE_CELL_BG_COLOR.lower()
    assert bg2 == DUPLICATE_CELL_BG_COLOR.lower()

    # 핀맵에서 신호 중복 핀("2") 선택 시 현재 정렬 순서에서 첫 번째 행(row 1)이 선택되는지 확인 (제3.8절)
    win.pinmap_panel.canvas.select_pin("2", emit_signal=True)
    assert win.signal_table_panel.table.currentRow() == 1

    # 중복 해소: 2번 행(VCC_5V)의 핀 번호를 "3"으로 변경
    assert win.signal_table_panel.apply_cell_edit(2, COL_PIN, "3")
    assert win.project.total_duplicate_pin_warnings() == 0

    # 7. 핀 선택 시 동일 신호 굵은 외곽선, 같은 신호유형 주변 영역(Aura), 축소 시 생략 검증 (제3.4절, 제3.8절)
    win.pinmap_panel.canvas.zoom_by(2.5)
    win.pinmap_panel.canvas.select_pin("1", emit_signal=True)
    assert win.signal_table_panel.table.currentRow() == 0

    bold_items = [
        item
        for item in win.pinmap_panel.canvas.scene().items()
        if hasattr(item, "pen")
        and abs(item.pen().widthF() - SELECTED_PIN_BORDER_WIDTH) < 0.01
    ]
    # GND가 할당된 1번 핀, 2번 핀 총 2개가 굵은 외곽선을 가져야 함
    assert len(bold_items) == 2

    aura_items_zoomed_in = [
        item
        for item in win.pinmap_panel.canvas.scene().items()
        if hasattr(item, "brush")
        and item.brush().color().alpha() == AURA_ALPHA
    ]
    assert len(aura_items_zoomed_in) == 2

    # 축소해서 핀 사이 공간이 좁아지면 주변 영역(Aura)이 생략되는지 확인
    win.pinmap_panel.canvas.zoom_by(
        0.25 / win.pinmap_panel.canvas.current_zoom_scale
    )
    assert not win.pinmap_panel.canvas.should_show_category_aura(
        part_9p.min_pin_distance()
    )

    # 모든 선 굵기가 확대/축소 비율에 비례하지 않는 cosmetic 펜인지 확인 (제3.4절)
    for item in win.pinmap_panel.canvas.scene().items():
        if hasattr(item, "pen"):
            pen = item.pen()
            if pen.style() != Qt.PenStyle.NoPen:
                assert pen.isCosmetic()

    # 8. 충분히 확대했을 때 신호명이 표시되는지 확인 (제3.4절)
    win.pinmap_panel.canvas.zoom_by(
        2.5 / win.pinmap_panel.canvas.current_zoom_scale
    )
    assert win.pinmap_panel.canvas.should_show_signal_labels()
    scene_texts = [
        item.text()
        for item in win.pinmap_panel.canvas.scene().items()
        if hasattr(item, "text")
    ]
    assert "GND" in scene_texts
    assert "VCC_5V" in scene_texts

    # 9. 좌우 반전 전환 시 '배면' 표시 및 할당 유지 확인 (제3.5절)
    win.pinmap_panel.flip_checkbox.setChecked(True)
    assert conn.flip_horizontal is True
    assert win.pinmap_panel.face_badge_label.text() == "배면"
    assert conn.pins_for_signal("GND") == {"1", "2"}

    # 10. 컨텍스트 메뉴 첫 글자 이동 및 핀맵 신호 할당 확인 (제3.7절)
    ctx_menu = win.pinmap_panel.canvas.build_pin_context_menu("5")
    found_act = ctx_menu.find_first_action_starting_with("v")
    assert found_act is not None and found_act.text() == "VCC_5V"
    win._on_pin_signal_assigned_from_canvas("5", "VCC_5V")
    assert "5" in conn.pins_for_signal("VCC_5V")

    # 11. Delete 키 삭제 차단 및 행 헤더 우클릭 삭제 확인 (제3.6절)
    row_count_before = len(conn.rows)
    win.signal_table_panel.table.selectRow(0)
    del_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Delete,
        Qt.KeyboardModifier.NoModifier,
    )
    win.signal_table_panel.table.keyPressEvent(del_event)
    assert len(conn.rows) == row_count_before

    assert win.signal_table_panel.delete_signal_row(0)
    assert len(conn.rows) == row_count_before - 1
    assert "GND" in conn.signals

    # 12. 연결기 부품 편집기 전환, 핀 추가, 메인 화면 복귀 시 프로젝트 자동 반영 확인 (제3.3절, 제4.4절, 제4.5절)
    win.switch_to_editor_view()
    assert win.stack.currentIndex() == 1
    assert win.editor_widget.is_grid_visible()
    assert win.editor_widget.is_snap_active()

    initial_pin_count = win.editor_widget.current_part.pin_count
    win.editor_widget.activate_tool_mode(MODE_ADD_PIN)
    snapped_pt = win.editor_widget.canvas.snapped_point(
        win.editor_widget.canvas._cursor_scene_pos
    )
    win.editor_widget.add_pin_at(snapped_pt.x(), snapped_pt.y())
    assert win.editor_widget.current_part.pin_count == initial_pin_count + 1
    win.editor_widget.activate_tool_mode(MODE_SELECT)

    # 메인 화면으로 돌아가면 같은 UUID를 쓰는 J1의 프로젝트 부품 사본에 새 핀이 자동 반영됨
    assert win.switch_to_project_view()
    assert win.stack.currentIndex() == 0
    updated_proj_part = win.project.get_part_for_connector(conn)
    assert updated_proj_part is not None
    assert updated_proj_part.pin_count == initial_pin_count + 1

    # 13. 프로젝트 .jnc 파일 저장 및 다시 열기 확인 (제3.2절)
    proj_file = tmp_path / "saved_ui_project.jnc"
    assert win.save_project_to_path(proj_file)
    assert not win.is_dirty
    assert win.load_project_from_path(proj_file)
    assert len(win.project.connectors) == 1
    win.close()
