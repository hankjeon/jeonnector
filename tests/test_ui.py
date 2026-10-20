"""전연결기(jeonnector) UI 통합 테스트 (핀맵, 신호표, 신호유형 관리, 연결기 부품 편집기, 메인 윈도우)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QSizePolicy,
)

from jeonnector.default_parts import create_default_parts
from jeonnector.model import (
    DUPLICATE_CELL_BG_COLOR,
    EMPTY_PART_MESSAGE,
)
from jeonnector.storage import PartLibrary
from jeonnector.ui.connector_editor import (
    DEFAULT_GRID_SPACING,
    AutoPlacementDialog,
    MODE_ADD_PIN,
    MODE_SELECT,
    polygon_center,
    snap_coord,
)
from jeonnector.ui.main_window import MainWindow
from jeonnector.ui.pinmap_canvas import (
    AURA_ALPHA,
    AURA_FALLBACK_COLOR,
    SELECTED_PIN_BORDER_WIDTH,
)
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
    assert win.signal_table_panel.apply_cell_edit(0, COL_SIGNAL_TYPE, "GROUND")
    assert win.signal_table_panel.apply_cell_edit(
        2, COL_SIGNAL_TYPE, "사용자전원유형"
    )
    assert "사용자전원유형" in win.project.signal_types
    # 새로 만든 신호유형의 초기 색상은 '없음'("")이어야 함
    assert win.project.signal_type_color("사용자전원유형") == ""
    # 같은 신호(GND)의 다른 행에도 신호유형이 즉시 공유 반영되어야 함
    assert (
        win.signal_table_panel.table.item(1, COL_SIGNAL_TYPE).text() == "GROUND"
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

    # 7. 핀 선택 시 선택한 핀만 굵은 외곽선, 동일 신호 핀들의 주변 영역(Aura) 검증 (제3.4절, 제3.8절)
    def bold_items():
        return [
            item
            for item in win.pinmap_panel.canvas.scene().items()
            if hasattr(item, "pen")
            and abs(item.pen().widthF() - SELECTED_PIN_BORDER_WIDTH) < 0.01
        ]

    def aura_items():
        return [
            item
            for item in win.pinmap_panel.canvas.scene().items()
            if hasattr(item, "brush")
            and item.brush().color().alpha() == AURA_ALPHA
        ]

    def pin_center(designator):
        pin = next(p for p in part_9p.pins if p.designator == designator)
        return QPointF(pin.x, pin.y)

    win.pinmap_panel.canvas.zoom_by(2.5)
    win.pinmap_panel.canvas.select_pin("1", emit_signal=True)
    assert win.signal_table_panel.table.currentRow() == 0

    # 같은 신호(GND)의 2번 핀은 원래 굵기를 유지하고 선택한 1번 핀만 굵은 외곽선
    assert len(bold_items()) == 1
    assert bold_items()[0].path().contains(pin_center("1"))

    # 동일 신호 핀(1, 2번)의 주변 영역은 겹쳐도 진해지지 않도록 하나의 경로로 칠하고 핀 채움 색상을 사용
    assert len(aura_items()) == 1
    aura_item = aura_items()[0]
    assert aura_item.path().fillRule() == Qt.FillRule.WindingFill
    assert aura_item.path().contains(pin_center("1"))
    assert aura_item.path().contains(pin_center("2"))
    assert not aura_item.path().contains(pin_center("3"))
    expected_hex = win.project.effective_signal_color(conn, "GND")
    assert aura_item.brush().color().name() == expected_hex.lower()

    # 신호 색상과 신호유형 색상이 모두 '없음'인 신호(VCC_5V)는 회색 주변 영역 표시
    win.pinmap_panel.canvas.select_pin("3", emit_signal=True)
    assert len(aura_items()) == 1
    assert aura_items()[0].path().contains(pin_center("3"))
    assert aura_items()[0].brush().color().name() == AURA_FALLBACK_COLOR

    # 축소해서 핀 사이 공간이 좁아져도 주변 영역을 생략하지 않음
    win.pinmap_panel.canvas.zoom_by(
        0.25 / win.pinmap_panel.canvas.current_zoom_scale
    )
    win.pinmap_panel.canvas.select_pin("1", emit_signal=True)
    assert len(aura_items()) == 1

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
    assert win.editor_widget.grid_spacing == pytest.approx(DEFAULT_GRID_SPACING)

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


def test_default_grid_aligns_with_default_row_pin_columns() -> None:
    """기본 그리드 간격(핀 간격의 1/4)에서 D-SUB·Micro-D 기본 부품 핀의 가로 위치가 격자에 맞는다 (제4.5절)."""
    assert DEFAULT_GRID_SPACING == pytest.approx(10.0)
    for part in create_default_parts():
        if part.family == "D38999 Series IV":
            continue
        for pin in part.pins:
            assert snap_coord(pin.x, part.width / 2.0, DEFAULT_GRID_SPACING) == pytest.approx(pin.x)


def _has_center_handle(canvas, x: float, y: float) -> bool:
    """(x, y)에 원과 가로·세로 십자선이 겹친 가운데 핸들이 그려졌는지 확인한다."""
    items = canvas.scene().items()
    has_circle = any(
        isinstance(item, QGraphicsEllipseItem)
        and item.rect().center() == QPointF(x, y)
        and item.pen().color().name() == "#ea580c"
        for item in items
    )
    lines = [item.line() for item in items if isinstance(item, QGraphicsLineItem)]
    has_h = any(ln.y1() == ln.y2() == y and ln.center() == QPointF(x, y) for ln in lines)
    has_v = any(ln.x1() == ln.x2() == x and ln.center() == QPointF(x, y) for ln in lines)
    return has_circle and has_h and has_v


def test_editor_new_part_outline_tools_and_snap(qapp: QApplication, tmp_path: Path) -> None:
    """새 부품 빈 시작, 자동 배치 기본값, 외곽 즉시 생성, 영역 자동 맞춤, 스냅에 맞추기 (제4.4~4.5절)."""
    lib = PartLibrary(storage_path=tmp_path / "editor_lib.json")
    win = MainWindow(part_library=lib)
    editor = win.editor_widget
    editor.create_new_part()
    part = editor.current_part
    assert part is not None and not part.pins and not part.graphics
    assert (part.width, part.height, part.pin_size) == (400.0, 300.0, 16.0)
    assert not hasattr(editor, "width_spin")

    dialog = AutoPlacementDialog(part, snap_enabled=True, grid_spacing=editor.grid_spacing)
    assert (dialog.pitch_x_spin.value(), dialog.pitch_y_spin.value()) == (40.0, 48.0)
    dialog.row_counts_edit.setText("3, 2")
    part.pins, _ = dialog.build_pins()
    editor.on_part_geometry_modified()
    center_offsets = [(p.x - part.width / 2, p.y - part.height / 2) for p in part.pins]

    editor.create_polygon_outline()
    points = part.graphics[0].geometry["points"]
    assert len(points) == 4
    assert min(x for x, _ in points) == pytest.approx(min(p.x for p in part.pins) - 30.0)
    assert part.width == pytest.approx(max(x for x, _ in points) - min(x for x, _ in points) + 24.0)
    assert [(p.x - part.width / 2, p.y - part.height / 2) for p in part.pins] == pytest.approx(center_offsets)
    center = polygon_center(points)
    assert _has_center_handle(editor.canvas, center.x(), center.y())

    editor.create_circle_outline()
    assert part.graphics[0].type == "CIRCLE"
    geom = part.graphics[0].geometry
    assert _has_center_handle(editor.canvas, geom["cx"], geom["cy"])
    assert part.width == pytest.approx(2 * (part.graphics[0].geometry["radius"] + 12.0))

    part.pins[0].x += 3.0
    assert editor.snap_all_to_grid(confirm=False)
    cx, cy = part.width / 2, part.height / 2
    assert all(
        snap_coord(p.x, cx, editor.grid_spacing) == pytest.approx(p.x)
        and snap_coord(p.y, cy, editor.grid_spacing) == pytest.approx(p.y)
        for p in part.pins
    )
    stored = lib.get_part(part.uuid)
    assert stored is not None and stored.pins[0].x == pytest.approx(part.pins[0].x)
    win.mark_dirty(False)
    win.close()


def test_editor_multi_select_and_group_move(qapp: QApplication, tmp_path: Path) -> None:
    """영역 드래그·Ctrl+클릭 다중 선택, 핀 목록 표 연동, 간격을 유지한 그룹 이동 (제4.4~4.5절)."""
    win = MainWindow(part_library=PartLibrary(storage_path=tmp_path / "lib.json"))
    editor = win.editor_widget
    editor.create_new_part()
    part = editor.current_part
    dialog = AutoPlacementDialog(part, snap_enabled=True, grid_spacing=editor.grid_spacing)
    dialog.row_counts_edit.setText("3, 2")
    part.pins, _ = dialog.build_pins()
    editor.on_part_geometry_modified()
    canvas = editor.canvas
    viewport = canvas.viewport()
    left, ctrl, none = (
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.KeyboardModifier.NoModifier,
    )

    def at(x: float, y: float):
        return canvas.mapFromScene(QPointF(x, y))

    def table_rows() -> set[int]:
        return {i.row() for i in editor.pin_table.selectionModel().selectedRows()}

    top_y = min(p.y for p in part.pins)
    top = {i for i, p in enumerate(part.pins) if p.y == top_y}
    bottom = set(range(len(part.pins))) - top
    assert len(top) == 3 and len(bottom) == 2

    # 빈 곳 드래그로 윗줄만 감싸 선택
    QTest.mousePress(viewport, left, none, at(1.0, 1.0))
    QTest.mouseMove(viewport, at(part.width - 1.0, top_y + 12.0))
    assert canvas._rubber_rect is not None
    QTest.mouseRelease(viewport, left, none, at(part.width - 1.0, top_y + 12.0))
    assert canvas.selected_pins == top and table_rows() == top

    # Ctrl+클릭: 추가·해제
    b = min(bottom)
    QTest.mouseClick(viewport, left, ctrl, at(part.pins[b].x, part.pins[b].y))
    assert canvas.selected_pins == top | {b} and table_rows() == top | {b}
    QTest.mouseClick(viewport, left, ctrl, at(part.pins[b].x, part.pins[b].y))
    assert canvas.selected_pins == top

    # 잡은 핀만 격자에 맞추고 나머지는 같은 거리만큼 옮긴다.
    anchor = min(top)
    part.pins[max(top)].x += 3.0  # 격자에서 벗어난 핀도 간격이 유지되어야 한다.
    before = {i: (p.x, p.y) for i, p in enumerate(part.pins)}
    ax, ay = before[anchor]
    QTest.mousePress(viewport, left, none, at(ax, ay))
    QTest.mouseMove(viewport, at(ax + 13.0, ay + 2.0))
    QTest.mouseRelease(viewport, left, none, at(ax + 13.0, ay + 2.0))
    shift = (part.pins[anchor].x - part.pins[b].x) - (ax - before[b][0])
    assert shift == pytest.approx(editor.grid_spacing)
    for i in top:
        assert part.pins[i].x - part.pins[anchor].x == pytest.approx(before[i][0] - ax)
        assert part.pins[i].y - part.pins[anchor].y == pytest.approx(before[i][1] - ay)
    for i in bottom:
        assert part.pins[i].x - part.pins[b].x == pytest.approx(before[i][0] - before[b][0])

    # 표에서 여러 행을 고르면 캔버스 선택에 반영된다.
    editor.pin_table.selectionModel().clearSelection()
    editor.pin_table.selectRow(0)
    editor.pin_table.selectionModel().select(
        editor.pin_table.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert canvas.selected_pins == {0, 1}

    # 빈 곳 클릭과 Esc는 선택을 해제한다.
    QTest.mouseClick(viewport, left, none, at(1.0, 1.0))
    assert canvas.selected_pins == set() and table_rows() == set()
    canvas.set_selected_pins({0})
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.selected_pins == set()
    win.mark_dirty(False)
    win.close()


def test_editor_undo_redo_per_part(qapp: QApplication, tmp_path: Path) -> None:
    """부품 편집기 실행 취소·다시 실행: 부품별 이력, 메뉴 공유, 부품 데이터베이스 반영 (제3.13절)."""
    lib = PartLibrary(storage_path=tmp_path / "undo_lib.json")
    win = MainWindow(part_library=lib)
    win.switch_to_editor_view()
    editor = win.editor_widget
    editor.create_new_part()
    part_uuid = editor.current_part.uuid
    assert not win.undo_act.isEnabled()

    editor.add_pin_at(200.0, 150.0)
    editor.add_pin_at(240.0, 150.0)
    editor.create_polygon_outline()
    editor.pin_size_spin.setValue(20.0)
    assert win.undo_act.text() == "실행 취소: 핀 모양·크기 변경"

    assert win.undo()
    assert editor.current_part.pin_size == 16.0
    assert win.undo()  # 외곽 생성 취소
    assert not editor.current_part.graphics
    assert lib.get_part(part_uuid).graphics == []  # 부품 데이터베이스에도 반영
    assert win.undo()
    assert [p.designator for p in editor.current_part.pins] == ["1"]
    assert win.redo_act.text() == "다시 실행: 핀 2 추가"
    assert win.redo() and win.redo()
    assert editor.current_part.graphics and len(editor.current_part.pins) == 2

    editor.family_edit.setText("검증")
    editor._apply_meta_edits()
    assert win.undo_act.text() == "실행 취소: 부품 정보 변경"
    assert win.undo()
    assert editor.current_part.family == "사용자 정의"
    assert editor.family_edit.text() == "사용자 정의"

    # 다른 부품을 고르면 그 부품의 이력을 쓰고, 돌아오면 이전 이력이 남아 있다.
    other = lib.list_parts()[0]
    editor._load_part_by_uuid(other.uuid)
    assert not win.undo_act.isEnabled()
    editor._load_part_by_uuid(part_uuid)
    assert win.undo_act.isEnabled()

    # 메인 화면으로 돌아가면 프로젝트 이력으로 바뀐다.
    win.switch_to_project_view()
    assert not win.undo_act.isEnabled()
    win.mark_dirty(False)
    win.close()


def test_signal_label_size_caps_and_reveals_more_text_on_zoom(qapp: QApplication, tmp_path: Path) -> None:
    """신호명 글자는 화면 11px에서 더 커지지 않고, 확대로 넓어진 핀 간격만큼 더 많이 보인다 (제3.4절)."""
    win = MainWindow(part_library=PartLibrary(storage_path=tmp_path / "label_lib.json"))
    part = win.part_library.list_parts()[0]
    win.add_connector("J1", part)
    conn = win.current_connector
    long_name = "HEATER_POWER_28V_MAIN_BUS"
    conn.add_signal_row(long_name, "1", part)
    canvas = win.pinmap_panel.canvas

    def label_at(zoom: float):
        canvas._auto_fit_on_resize = False
        canvas.resetTransform()
        canvas.scale(zoom, zoom)
        canvas.redraw()
        item = next(
            item for item in canvas.scene().items()
            if item.data(Qt.ItemDataRole.UserRole) == long_name
        )
        return item.text(), item.font().pixelSize()  # 다음 redraw에서 항목이 지워지므로 값만 읽는다.

    (near, near_px), (mid, mid_px), (far, far_px) = label_at(1.5), label_at(3.0), label_at(12.0)
    assert near_px < 11
    assert mid_px == far_px == 11
    assert near.endswith("…") and mid.endswith("…")
    assert len(near) < len(mid)
    assert far == long_name
    win.mark_dirty(False)
    win.close()


def test_window_minimum_size_follows_visible_screen(qapp: QApplication, tmp_path: Path) -> None:
    """창 최소 크기는 보이는 화면 기준이며 숨은 편집기 화면과 긴 안내 문구가 늘리지 않는다 (제4.1절)."""
    win = MainWindow(part_library=PartLibrary(storage_path=tmp_path / "min_lib.json"))
    win.show()
    qapp.processEvents()
    project_min = win.minimumSizeHint().width()
    assert project_min < 700
    hint = win.editor_widget.mode_hint_label
    assert hint.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert win.editor_widget.mode_hint_label.toolTip() == win.editor_widget.mode_hint_label._full_text
    win.resize(300, 200)
    win.switch_to_editor_view()
    qapp.processEvents()
    editor_min = win.minimumSizeHint().width()
    assert project_min < editor_min < 1000
    assert win.width() >= editor_min  # 편집기로 전환하면 편집기 최소 크기까지 커진다.
    win.switch_to_project_view()
    win.resize(300, 200)
    qapp.processEvents()
    assert win.width() == project_min
    win.mark_dirty(False)
    win.close()
