"""상용 CAD 스타일 조작성을 갖춘 연결기 부품 데이터베이스 및 편집기 화면."""

from __future__ import annotations

import math
from uuid import uuid4

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from jeonnector.commands import StateHistory
from jeonnector.default_parts import (
    PIN_PITCH,
    PIN_SIZE,
    generate_circular_pins,
    generate_grid_pins,
)
from jeonnector.model import (
    ConnectorPart,
    OutlineGraphic,
    PinDefinition,
    is_valid_pin_number_format,
    natural_sort_key,
    pin_is_square,
)
from jeonnector.part_geometry import (
    fit_part_area,
    fitted_circle_outline,
    fitted_polygon_outline,
    snap_coord,
    snap_part_to_grid,
)
from jeonnector.storage import PartLibrary, export_parts, read_parts_file
from jeonnector.ui.pinmap_canvas import ElidedLabel

MODE_SELECT = "SELECT"
MODE_ADD_PIN = "ADD_PIN"

EDITOR_PIN_DIAMETER = 15.0
# 기본 부품 핀 간격의 1/4: 엇갈린 행이 있어도 기본 부품 핀의 가로 위치가 격자에 맞는다 (제4.5절).
DEFAULT_GRID_SPACING = PIN_PITCH / 4.0
MIN_GRID_SCREEN_PX = 6.0
HANDLE_SCREEN_PX = 8.0
SELECT_MODE_HINT = (
    "도구 모드: 선택 / 이동 — 핀이나 외곽 핸들을 드래그해 이동합니다 "
    "(빈 곳 드래그: 영역 선택 · Ctrl+클릭: 선택 추가·해제 · 휠 버튼/스페이스+드래그: 화면 이동 · "
    "다각형: 변 더블클릭 꼭짓점 추가 · 꼭짓점 우클릭 삭제 · 가운데 핸들 전체 이동)"
)
NEW_PART_WIDTH = 400.0
NEW_PART_HEIGHT = 300.0


def polygon_center(points: list[list[float]]) -> QPointF | None:
    """다각형 외곽 전체 이동 핸들 위치(꼭짓점 경계 상자의 중심)."""
    if not points:
        return None
    xs = [float(pt[0]) for pt in points]
    ys = [float(pt[1]) for pt in points]
    return QPointF((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def next_pin_designator(existing: list[str]) -> str:
    """현재 핀 목록을 기준으로 다음에 추가할 핀 번호를 자동 계산한다."""
    if not existing:
        return "1"
    numeric = [int(d) for d in existing if d.isdigit()]
    if numeric:
        return str(max(numeric) + 1)
    last = existing[-1]
    if last.isalpha() and len(last) == 1 and last.upper() < "Z":
        return chr(ord(last) + 1)
    return f"P{len(existing) + 1}"


class AutoPlacementDialog(QDialog):
    """바둑판(격자) 및 원형 핀 자동 배치 대화상자."""

    def __init__(
        self,
        part: ConnectorPart,
        snap_enabled: bool,
        grid_spacing: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("핀 자동 배치 (CAD 배열 생성)")
        self.resize(420, 360)
        self._part = part
        self._snap_enabled = snap_enabled
        self._grid_spacing = grid_spacing

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        # 탭 1: 바둑판(격자) 자동 배치
        grid_tab = QWidget()
        grid_form = QFormLayout(grid_tab)

        self.row_counts_edit = QLineEdit("5, 4")
        self.row_counts_edit.setToolTip(
            "각 행의 핀 개수를 쉼표로 구분해 입력합니다 (예: 5, 4 또는 8, 7, 8)"
        )
        grid_form.addRow("행별 핀 개수 (쉼표 구분):", self.row_counts_edit)

        self.pitch_x_spin = QDoubleSpinBox()
        self.pitch_x_spin.setRange(2.0, 200.0)
        self.pitch_x_spin.setValue(PIN_PITCH)
        grid_form.addRow("가로 핀 간격 (Pitch X):", self.pitch_x_spin)

        self.pitch_y_spin = QDoubleSpinBox()
        self.pitch_y_spin.setRange(2.0, 200.0)
        self.pitch_y_spin.setValue(48.0)
        grid_form.addRow("세로 열 간격 (Pitch Y):", self.pitch_y_spin)

        self.stagger_check = QCheckBox("짝수/홀수 행 반피치 엇갈림 배치")
        self.stagger_check.setChecked(True)
        grid_form.addRow("", self.stagger_check)

        self.grid_prefix_edit = QLineEdit("")
        self.grid_prefix_edit.setPlaceholderText("예: 비워두면 숫자, A 입력 시 A1, A2...")
        grid_form.addRow("핀 번호 접두사:", self.grid_prefix_edit)

        self.grid_start_spin = QSpinBox()
        self.grid_start_spin.setRange(1, 9999)
        self.grid_start_spin.setValue(1)
        grid_form.addRow("시작 번호:", self.grid_start_spin)

        self.tabs.addTab(grid_tab, "바둑판(격자) 배열")

        # 탭 2: 원형 자동 배치
        circ_tab = QWidget()
        circ_form = QFormLayout(circ_tab)

        self.circ_count_spin = QSpinBox()
        self.circ_count_spin.setRange(1, 300)
        self.circ_count_spin.setValue(12)
        circ_form.addRow("총 핀 개수:", self.circ_count_spin)

        self.circ_radius_spin = QDoubleSpinBox()
        self.circ_radius_spin.setRange(5.0, 500.0)
        self.circ_radius_spin.setValue(
            round(min(part.width, part.height) * 0.32, 1)
        )
        circ_form.addRow("배치 반지름 (Radius):", self.circ_radius_spin)

        self.circ_angle_spin = QDoubleSpinBox()
        self.circ_angle_spin.setRange(-360.0, 360.0)
        self.circ_angle_spin.setValue(90.0)
        circ_form.addRow("시작 각도 (도, 90=위쪽):", self.circ_angle_spin)

        self.circ_cw_check = QCheckBox("시계 방향 회전 배치")
        self.circ_cw_check.setChecked(True)
        circ_form.addRow("", self.circ_cw_check)

        self.circ_center_check = QCheckBox("중심에 마지막 핀 1개 배치")
        circ_form.addRow("", self.circ_center_check)

        self.circ_prefix_edit = QLineEdit("")
        circ_form.addRow("핀 번호 접두사:", self.circ_prefix_edit)

        self.tabs.addTab(circ_tab, "원형 배열")

        # 공통 옵션
        common_box = QGroupBox("배치 적용 방식")
        common_layout = QVBoxLayout(common_box)
        self.replace_radio = QRadioButton("기존 핀을 모두 지우고 새로 배치")
        self.append_radio = QRadioButton("기존 핀 뒤에 추가")
        self.replace_radio.setChecked(True)
        self.snap_result_check = QCheckBox(
            "생성된 핀 좌표를 현재 그리드 간격에 스냅"
        )
        self.snap_result_check.setChecked(False)
        common_layout.addWidget(self.replace_radio)
        common_layout.addWidget(self.append_radio)
        common_layout.addWidget(self.snap_result_check)
        layout.addWidget(common_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_pins(self) -> tuple[list[PinDefinition], bool]:
        """설정된 조건에 따라 생성된 핀 목록과 기존 핀 교체 여부(replace)를 반환한다."""
        cx = self._part.width / 2.0
        cy = self._part.height / 2.0
        replace = self.replace_radio.isChecked()

        if self.tabs.currentIndex() == 0:
            raw_counts = [
                int(tok.strip())
                for tok in self.row_counts_edit.text().split(",")
                if tok.strip().isdigit() and int(tok.strip()) > 0
            ]
            if not raw_counts:
                raw_counts = [5, 4]
            pins = generate_grid_pins(
                row_counts=raw_counts,
                pitch_x=self.pitch_x_spin.value(),
                pitch_y=self.pitch_y_spin.value(),
                center_x=cx,
                center_y=cy,
                stagger_odd_rows=self.stagger_check.isChecked(),
                prefix=self.grid_prefix_edit.text().strip(),
                start_number=self.grid_start_spin.value(),
            )
        else:
            pins = generate_circular_pins(
                pin_count=self.circ_count_spin.value(),
                radius=self.circ_radius_spin.value(),
                center_x=cx,
                center_y=cy,
                start_angle_deg=self.circ_angle_spin.value(),
                clockwise=self.circ_cw_check.isChecked(),
                include_center_pin=self.circ_center_check.isChecked(),
                prefix=self.circ_prefix_edit.text().strip(),
                start_number=1,
            )

        if self.snap_result_check.isChecked() and self._grid_spacing > 0:
            for p in pins:
                p.x = snap_coord(p.x, cx, self._grid_spacing)
                p.y = snap_coord(p.y, cy, self._grid_spacing)

        return pins, replace


class EditorCanvas(QGraphicsView):
    """상용 CAD 스타일 도구 모드를 지원하는 연결기 외곽·핀 편집 캔버스."""

    def __init__(self, editor: ConnectorEditorWidget) -> None:
        super().__init__(editor)
        self.editor = editor
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#f1f5f9")))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.mode: str = MODE_SELECT
        self.selected_pins: set[int] = set()

        # 드래그 상태
        self._dragging_pin_index: int = -1  # 마우스로 잡은 핀(스냅 기준)
        self._drag_origins: dict[int, tuple[float, float]] = {}  # 함께 옮길 핀의 시작 좌표
        self._dragging_handle: tuple[str, int] | None = None
        # ("poly_vertex", idx) | ("poly_center", 0) | ("circle_center", 0) | ("circle_radius", 0)
        self._rubber_origin: QPointF | None = None
        self._rubber_rect: QRectF | None = None
        self._rubber_base: set[int] = set()  # Ctrl+영역 선택 시 유지할 기존 선택
        self._panning = False
        self._space_pressed = False
        self._pan_start = QPointF()

        # 핀 찍기 미리보기용 커서 위치
        self._cursor_scene_pos = QPointF(100.0, 60.0)

    @property
    def current_zoom_scale(self) -> float:
        return abs(self.transform().m11())

    def mode_is_idle(self) -> bool:
        """드래그나 영역 선택 중이 아닌지 (실행 취소는 조작이 끝난 뒤에만 한다)."""
        return (
            self._dragging_pin_index < 0
            and self._dragging_handle is None
            and self._rubber_rect is None
        )

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._dragging_pin_index = -1
        self._drag_origins = {}
        self._dragging_handle = None
        self._rubber_origin = None
        self._rubber_rect = None
        if mode == MODE_SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.redraw()

    def set_selected_pins(self, indices: set[int]) -> None:
        """선택한 핀 집합을 바꾸고 핀 목록 표의 선택을 맞춘다."""
        self.selected_pins = set(indices)
        self.editor.select_pins_in_table(self.selected_pins)
        self.redraw()

    def fit_to_view(self) -> None:
        part = self.editor.current_part
        if part is None:
            return
        rect = QRectF(-25.0, -25.0, part.width + 50.0, part.height + 50.0)
        if self.viewport().width() > 10:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.redraw()

    def zoom_by(self, factor: float) -> None:
        new_scale = self.current_zoom_scale * factor
        if 0.15 <= new_scale <= 35.0:
            self.scale(factor, factor)
            self.redraw()

    def snapped_point(self, scene_pos: QPointF) -> QPointF:
        """그리드와 스냅이 켜져 있을 때(Alt 미입력 시) 그리드에 맞춘 좌표를 반환한다."""
        part = self.editor.current_part
        if part is None:
            return scene_pos
        alt_down = bool(
            QGuiApplication.queryKeyboardModifiers()
            & Qt.KeyboardModifier.AltModifier
        )
        if self.editor.is_snap_active() and not alt_down:
            spacing = self.editor.grid_spacing
            sx = snap_coord(scene_pos.x(), part.width / 2.0, spacing)
            sy = snap_coord(scene_pos.y(), part.height / 2.0, spacing)
            return QPointF(sx, sy)
        return QPointF(round(scene_pos.x(), 2), round(scene_pos.y(), 2))

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta != 0:
            self.zoom_by(1.18 if delta > 0 else (1.0 / 1.18))
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.editor.activate_tool_mode(MODE_SELECT)
            self.set_selected_pins(set())
            event.accept()
            return
        if key == Qt.Key.Key_Space:
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.2)
            event.accept()
            return
        if key == Qt.Key.Key_Minus:
            self.zoom_by(1.0 / 1.2)
            event.accept()
            return
        if key in (Qt.Key.Key_0, Qt.Key.Key_F):
            self.fit_to_view()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            if not self._panning:
                self.setCursor(
                    Qt.CursorShape.ArrowCursor
                    if self.mode == MODE_SELECT
                    else Qt.CursorShape.CrossCursor
                )
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _hit_test_handle(self, scene_pos: QPointF) -> tuple[str, int] | None:
        """외곽 제어 핸들(다각형 꼭짓점 또는 원형 중심·반지름) 클릭 판정."""
        part = self.editor.current_part
        if part is None or not part.graphics:
            return None
        tol = max(HANDLE_SCREEN_PX / max(self.current_zoom_scale, 0.1), 3.0)
        g = part.graphics[0]
        if g.type.upper() == "POLYGON":
            pts = g.geometry.get("points", [])
            for idx, pt in enumerate(pts):
                if (
                    abs(scene_pos.x() - float(pt[0])) <= tol
                    and abs(scene_pos.y() - float(pt[1])) <= tol
                ):
                    return ("poly_vertex", idx)
            center = polygon_center(pts)
            if (
                center is not None
                and abs(scene_pos.x() - center.x()) <= tol
                and abs(scene_pos.y() - center.y()) <= tol
            ):
                return ("poly_center", 0)
        elif g.type.upper() == "CIRCLE":
            cx = float(g.geometry.get("cx", part.width / 2.0))
            cy = float(g.geometry.get("cy", part.height / 2.0))
            r = float(g.geometry.get("radius", 80.0))
            if abs(scene_pos.x() - cx) <= tol and abs(scene_pos.y() - cy) <= tol:
                return ("circle_center", 0)
            if (
                abs(scene_pos.x() - (cx + r)) <= tol
                and abs(scene_pos.y() - cy) <= tol
            ):
                return ("circle_radius", 0)
        return None

    def _hit_test_pin(self, scene_pos: QPointF) -> int:
        """클릭한 위치의 핀 인덱스 반환 (없으면 -1)."""
        part = self.editor.current_part
        if part is None:
            return -1
        radius = EDITOR_PIN_DIAMETER / 2.0 + 2.0
        for idx, pin in enumerate(part.pins):
            if (
                abs(scene_pos.x() - pin.x) <= radius
                and abs(scene_pos.y() - pin.y) <= radius
            ):
                return idx
        return -1

    def mousePressEvent(self, event) -> None:  # noqa: N802
        part = self.editor.current_part
        if part is None:
            super().mousePressEvent(event)
            return

        raw_scene_pos = self.mapToScene(event.position().toPoint())
        snapped = self.snapped_point(raw_scene_pos)

        # 휠 클릭 또는 스페이스바+좌클릭: 화면 이동(Panning)
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_pressed
        ):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # 우클릭 처리
        if event.button() == Qt.MouseButton.RightButton:
            if self.mode != MODE_SELECT:
                self.editor.activate_tool_mode(MODE_SELECT)
                event.accept()
                return

            # 선택 모드에서 핸들 또는 핀 우클릭 컨텍스트 메뉴
            handle = self._hit_test_handle(raw_scene_pos)
            if handle is not None and handle[0] == "poly_vertex":
                v_idx = handle[1]
                menu = QMenu(self)
                del_act = menu.addAction(f"외곽 꼭짓점 #{v_idx + 1} 삭제")
                pts = part.graphics[0].geometry.get("points", [])
                del_act.setEnabled(len(pts) > 3)
                if menu.exec(event.globalPosition().toPoint()) == del_act:
                    pts.pop(v_idx)
                    self.editor.on_part_geometry_modified(description="외곽 꼭짓점 삭제")
                event.accept()
                return

            pin_idx = self._hit_test_pin(raw_scene_pos)
            if pin_idx >= 0:
                self.set_selected_pins({pin_idx})
                pin = part.pins[pin_idx]
                menu = QMenu(self)
                ren_act = menu.addAction(f"핀 '{pin.designator}' 번호 변경...")
                del_act = menu.addAction(f"핀 '{pin.designator}' 삭제")
                chosen = menu.exec(event.globalPosition().toPoint())
                if chosen == ren_act:
                    self.editor.prompt_rename_pin(pin_idx)
                elif chosen == del_act:
                    self.editor.delete_pin_at(pin_idx)
                event.accept()
                return

        # 좌클릭 처리
        if event.button() == Qt.MouseButton.LeftButton:
            if self.mode == MODE_ADD_PIN:
                self.editor.add_pin_at(snapped.x(), snapped.y())
                event.accept()
                return

            # MODE_SELECT: 외곽 핸들 우선 판정 -> 핀 판정 -> 빈 공간 영역 선택
            # 가운데 이동 핸들이 핀과 겹치면 핀을 우선한다.
            handle = self._hit_test_handle(raw_scene_pos)
            if handle is not None and handle[0] in ("poly_center", "circle_center"):
                if self._hit_test_pin(raw_scene_pos) >= 0:
                    handle = None
            if handle is not None:
                self._dragging_handle = handle
                event.accept()
                return

            ctrl_down = bool(
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )
            pin_idx = self._hit_test_pin(raw_scene_pos)
            if pin_idx >= 0:
                if ctrl_down:
                    # Ctrl+클릭: 핀 하나를 선택에 넣거나 뺀다.
                    self.set_selected_pins(self.selected_pins ^ {pin_idx})
                    event.accept()
                    return
                if pin_idx not in self.selected_pins:
                    self.set_selected_pins({pin_idx})
                # 잡은 핀을 기준으로 선택된 핀 전체를 함께 옮긴다.
                self._dragging_pin_index = pin_idx
                self._drag_origins = {
                    i: (part.pins[i].x, part.pins[i].y) for i in self.selected_pins
                }
                event.accept()
                return

            # 빈 공간 드래그: 점선 사각형 영역 선택 (Ctrl: 기존 선택에 추가)
            self._rubber_origin = raw_scene_pos
            self._rubber_rect = QRectF(raw_scene_pos, raw_scene_pos)
            self._rubber_base = set(self.selected_pins) if ctrl_down else set()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        part = self.editor.current_part
        if part is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # 선택 모드에서 다각형 외곽 변(선분)을 더블클릭하면 꼭짓점 추가
            if self.mode == MODE_SELECT and part.graphics:
                g = part.graphics[0]
                if g.type.upper() == "POLYGON":
                    scene_pos = self.mapToScene(event.position().toPoint())
                    pts = g.geometry.get("points", [])
                    edge_idx = self._find_polygon_edge(pts, scene_pos)
                    if edge_idx is not None:
                        snapped = self.snapped_point(scene_pos)
                        pts.insert(
                            edge_idx + 1,
                            [round(snapped.x(), 2), round(snapped.y(), 2)],
                        )
                        self.editor.on_part_geometry_modified(description="외곽 꼭짓점 추가")
                        event.accept()
                        return
        super().mouseDoubleClickEvent(event)

    def _find_polygon_edge(
        self, pts: list[list[float]], scene_pos: QPointF
    ) -> int | None:
        if len(pts) < 3:
            return None
        tol = max(8.0 / max(self.current_zoom_scale, 0.1), 4.0)
        best_idx: int | None = None
        best_dist = tol
        for idx in range(len(pts)):
            ax, ay = float(pts[idx][0]), float(pts[idx][1])
            bx, by = (
                float(pts[(idx + 1) % len(pts)][0]),
                float(pts[(idx + 1) % len(pts)][1]),
            )
            dx, dy = bx - ax, by - ay
            len_sq = dx * dx + dy * dy
            t = (
                0.0
                if len_sq == 0
                else min(
                    max(
                        ((scene_pos.x() - ax) * dx + (scene_pos.y() - ay) * dy)
                        / len_sq,
                        0.0,
                    ),
                    1.0,
                )
            )
            px, py = ax + t * dx, ay + t * dy
            dist = math.hypot(scene_pos.x() - px, scene_pos.y() - py)
            if dist <= best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        raw_scene_pos = self.mapToScene(event.position().toPoint())
        snapped = self.snapped_point(raw_scene_pos)
        self._cursor_scene_pos = snapped
        self.editor.coord_status_label.setText(
            f"커서 좌표: ({snapped.x():.1f}, {snapped.y():.1f})"
        )

        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return

        part = self.editor.current_part
        if part is not None:
            # 핀을 마우스로 드래그 이동 시 그리드·스냅 켜짐 상태면 잡은 핀을 그리드에 맞추고,
            # 함께 선택된 핀은 같은 거리만큼 옮겨 서로 간격을 유지한다 (제4.5절).
            if self._dragging_pin_index in self._drag_origins:
                ax, ay = self._drag_origins[self._dragging_pin_index]
                dx = round(snapped.x(), 2) - ax
                dy = round(snapped.y(), 2) - ay
                for i, (ox, oy) in self._drag_origins.items():
                    part.pins[i].x = round(ox + dx, 2)
                    part.pins[i].y = round(oy + dy, 2)
                    self.editor.refresh_pin_table_row(i)
                self.redraw()
                event.accept()
                return

            if self._rubber_origin is not None:
                self._rubber_rect = QRectF(
                    self._rubber_origin, raw_scene_pos
                ).normalized()
                self.redraw()
                event.accept()
                return

            # 외곽 핸들 드래그 이동
            if self._dragging_handle is not None and part.graphics:
                role, h_idx = self._dragging_handle
                g = part.graphics[0]
                if role == "poly_vertex" and g.type.upper() == "POLYGON":
                    pts = g.geometry.get("points", [])
                    if 0 <= h_idx < len(pts):
                        pts[h_idx] = [
                            round(snapped.x(), 2),
                            round(snapped.y(), 2),
                        ]
                        self.redraw()
                elif role == "poly_center" and g.type.upper() == "POLYGON":
                    pts = g.geometry.get("points", [])
                    center = polygon_center(pts)
                    if center is not None:
                        dx = snapped.x() - center.x()
                        dy = snapped.y() - center.y()
                        g.geometry["points"] = [
                            [round(float(x) + dx, 2), round(float(y) + dy, 2)]
                            for x, y in pts
                        ]
                        self.redraw()
                elif role == "circle_center" and g.type.upper() == "CIRCLE":
                    g.geometry["cx"] = round(snapped.x(), 2)
                    g.geometry["cy"] = round(snapped.y(), 2)
                    self.redraw()
                elif role == "circle_radius" and g.type.upper() == "CIRCLE":
                    cx = float(g.geometry.get("cx", part.width / 2.0))
                    cy = float(g.geometry.get("cy", part.height / 2.0))
                    r = max(
                        round(math.hypot(snapped.x() - cx, snapped.y() - cy), 2),
                        10.0,
                    )
                    g.geometry["radius"] = r
                    self.redraw()
                event.accept()
                return

        if self.mode != MODE_SELECT:
            self.redraw()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            self._panning = False
            self.setCursor(
                Qt.CursorShape.ArrowCursor
                if self.mode == MODE_SELECT
                else Qt.CursorShape.CrossCursor
            )
            event.accept()
            return
        if self._rubber_origin is not None:
            # 중심이 사각형 안에 들어온 핀을 선택한다. 끌지 않은 클릭은 선택을 해제한다.
            rect = self._rubber_rect or QRectF()
            part = self.editor.current_part
            inside = {
                i
                for i, pin in enumerate(part.pins if part else [])
                if rect.contains(QPointF(pin.x, pin.y))
            }
            self._rubber_origin = None
            self._rubber_rect = None
            self.set_selected_pins(self._rubber_base | inside)
            event.accept()
            return
        if self._dragging_pin_index >= 0 or self._dragging_handle is not None:
            self._dragging_pin_index = -1
            self._drag_origins = {}
            self._dragging_handle = None
            self.editor.on_part_geometry_modified(description="핀·외곽 이동")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        part = self.editor.current_part
        if part is None:
            return

        # 부품 작업 영역 경계 표시
        area_rect = QRectF(0.0, 0.0, part.width, part.height)
        painter.fillRect(area_rect, QColor("#ffffff"))
        border_pen = QPen(QColor("#cbd5e1"), 1.0, Qt.PenStyle.DashLine)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.drawRect(area_rect)

        # 그리드 표시가 켜져 있고 화면상 점 간격이 충분할 때 격자점 그리기 (제3.5절)
        if not self.editor.is_grid_visible():
            return
        spacing = self.editor.grid_spacing
        if spacing <= 0 or (spacing * self.current_zoom_scale) < MIN_GRID_SCREEN_PX:
            return

        cx = part.width / 2.0
        cy = part.height / 2.0
        steps_x = int(cx // spacing)
        steps_y = int(cy // spacing)
        xs = [cx + s * spacing for s in range(-steps_x, steps_x + 1)]
        ys = [cy + s * spacing for s in range(-steps_y, steps_y + 1)]

        grid_pen = QPen(QColor("#94a3b8"), 2.0)
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)
        for y in ys:
            for x in xs:
                painter.drawPoint(QPointF(x, y))

        # 중심 기준선 표시
        axis_pen = QPen(QColor("#e2e8f0"), 1.0, Qt.PenStyle.DotLine)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        painter.drawLine(QPointF(cx, 0.0), QPointF(cx, part.height))
        painter.drawLine(QPointF(0.0, cy), QPointF(part.width, cy))

    def _add_square_handle(
        self, x: float, y: float, size: float, pen: QPen, brush: QBrush
    ) -> None:
        """꼭짓점·반지름 핸들(정사각형)."""
        self._scene.addRect(
            QRectF(x - size / 2.0, y - size / 2.0, size, size), pen, brush
        )

    def _add_center_handle(
        self, x: float, y: float, size: float, pen: QPen, brush: QBrush
    ) -> None:
        """가운데·중심 이동 핸들(원에 십자선이 겹친 모양)."""
        half = size / 2.0
        arm = size * 0.8
        self._scene.addEllipse(QRectF(x - half, y - half, size, size), pen, brush)
        self._scene.addLine(x - arm, y, x + arm, y, pen)
        self._scene.addLine(x, y - arm, x, y + arm, pen)

    def redraw(self) -> None:
        self._scene.clear()
        part = self.editor.current_part
        if part is None:
            return
        self._scene.setSceneRect(
            QRectF(-20.0, -20.0, part.width + 40.0, part.height + 40.0)
        )

        # 1. 연결기 외곽 및 편집 핸들 표시 (선 굵기는 화면 기준 일정하게 유지)
        outline_pen = QPen(QColor("#1e293b"), 1.8)
        outline_pen.setCosmetic(True)
        handle_size = HANDLE_SCREEN_PX / max(self.current_zoom_scale, 0.1)
        handle_pen = QPen(QColor("#ea580c"), 1.5)
        handle_pen.setCosmetic(True)
        handle_brush = QBrush(QColor("#ffffff"))

        for graphic in part.graphics:
            g_type = graphic.type.upper()
            geom = graphic.geometry
            if g_type == "POLYGON":
                pts = geom.get("points", [])
                if len(pts) >= 3:
                    poly = QPolygonF(
                        [QPointF(float(pt[0]), float(pt[1])) for pt in pts]
                    )
                    self._scene.addPolygon(
                        poly, outline_pen, QBrush(Qt.BrushStyle.NoBrush)
                    )
                    for pt in pts:
                        self._add_square_handle(
                            float(pt[0]), float(pt[1]),
                            handle_size, handle_pen, handle_brush,
                        )
                    center = polygon_center(pts)
                    self._add_center_handle(
                        center.x(), center.y(), handle_size, handle_pen, handle_brush
                    )
            elif g_type == "CIRCLE":
                cx = float(geom.get("cx", part.width / 2.0))
                cy = float(geom.get("cy", part.height / 2.0))
                r = float(geom.get("radius", 80.0))
                self._scene.addEllipse(
                    QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r),
                    outline_pen,
                    QBrush(Qt.BrushStyle.NoBrush),
                )
                self._add_center_handle(cx, cy, handle_size, handle_pen, handle_brush)
                self._add_square_handle(
                    cx + r, cy, handle_size, handle_pen, handle_brush
                )

        # 2. 핀 표시 (부품 단위의 핀 모양·크기 반영, 제4.4절)
        pin_diameter = (
            float(part.pin_size)
            if part.pin_size > 2.0
            else EDITOR_PIN_DIAMETER
        )
        half = pin_diameter / 2.0
        for idx, pin in enumerate(part.pins):
            is_sel = idx in self.selected_pins
            pen = QPen(
                QColor("#0284c7" if is_sel else "#334155"),
                3.2 if is_sel else 1.5,
            )
            pen.setCosmetic(True)
            brush = QBrush(QColor("#bae6fd" if is_sel else "#f8fafc"))
            rect = QRectF(
                pin.x - half,
                pin.y - half,
                pin_diameter,
                pin_diameter,
            )
            if pin_is_square(pin.designator, part.pin_shape):
                self._scene.addRect(rect, pen, brush)
            else:
                self._scene.addEllipse(rect, pen, brush)

            font = QFont("Segoe UI", 6)
            font.setBold(True)
            txt = self._scene.addSimpleText(pin.designator, font)
            txt.setBrush(QBrush(QColor("#0f172a")))
            bounds = txt.boundingRect()
            txt.setPos(
                pin.x - bounds.width() / 2.0,
                pin.y - bounds.height() / 2.0,
            )

        # 3. CAD 도구 모드별 실시간 마우스 작도 프리뷰
        preview_pen = QPen(QColor("#2563eb"), 1.5, Qt.PenStyle.DashLine)
        preview_pen.setCosmetic(True)
        cur = self._cursor_scene_pos

        if self._rubber_rect is not None:
            self._scene.addRect(
                self._rubber_rect, preview_pen, QBrush(QColor(37, 99, 235, 30))
            )

        if self.mode == MODE_ADD_PIN:
            ghost_rect = QRectF(
                cur.x() - half,
                cur.y() - half,
                pin_diameter,
                pin_diameter,
            )
            ghost_brush = QBrush(QColor(37, 99, 235, 50))
            self._scene.addEllipse(ghost_rect, preview_pen, ghost_brush)
            next_des = next_pin_designator([p.designator for p in part.pins])
            lbl = self._scene.addSimpleText(f"+{next_des}", QFont("Segoe UI", 6))
            lbl.setBrush(QBrush(QColor("#1d4ed8")))
            lbl.setPos(cur.x() + half + 2.0, cur.y() - half)


class ConnectorEditorWidget(QMainWindow):
    """전체 화면 전환 방식으로 동작하는 연결기 부품 편집기 화면."""

    backToProjectRequested = Signal()
    libraryUpdated = Signal()
    historyChanged = Signal()

    def __init__(
        self,
        part_library: PartLibrary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.part_library = part_library
        self.current_part: ConnectorPart | None = None
        self._syncing_ui = False
        # 제3.13절: 부품별 실행 취소 이력 (프로그램 실행 중 유지)
        self._histories: dict[str, StateHistory] = {}

        self.setDockNestingEnabled(True)
        self._build_toolbar()
        self._build_docks_and_canvas()
        self.refresh_part_list()

    @property
    def grid_spacing(self) -> float:
        return self.grid_spacing_spin.value()

    def is_grid_visible(self) -> bool:
        return self.grid_show_check.isChecked()

    def is_snap_active(self) -> bool:
        return self.snap_check.isChecked()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("연결기 부품 편집기 도구 모음", self)
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        back_btn = QPushButton("← 프로젝트 핀맵 화면으로 돌아가기")
        back_btn.setStyleSheet(
            "font-weight: bold; padding: 4px 10px; background-color: #e2e8f0;"
        )
        back_btn.clicked.connect(self._on_back_clicked)
        toolbar.addWidget(back_btn)
        toolbar.addSeparator()

        # CAD 스타일 모드 선택 도구 그룹
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)

        self.act_select = QAction("선택 / 이동 (ESC)", self)
        self.act_select.setCheckable(True)
        self.act_select.setChecked(True)
        self.act_select.triggered.connect(
            lambda: self.activate_tool_mode(MODE_SELECT)
        )
        self.tool_group.addAction(self.act_select)
        toolbar.addAction(self.act_select)

        self.act_add_pin = QAction("단일 핀 찍기", self)
        self.act_add_pin.setCheckable(True)
        self.act_add_pin.triggered.connect(
            lambda: self.activate_tool_mode(MODE_ADD_PIN)
        )
        self.tool_group.addAction(self.act_add_pin)
        toolbar.addAction(self.act_add_pin)

        toolbar.addSeparator()
        auto_place_btn = QPushButton("자동 배치 (바둑판/원형)...")
        auto_place_btn.clicked.connect(self.open_auto_placement_dialog)
        toolbar.addWidget(auto_place_btn)

        # 외곽은 누르면 바로 생성하고 핸들로 다듬는다 (제4.4절).
        poly_outline_btn = QPushButton("다각형 외곽")
        poly_outline_btn.clicked.connect(self.create_polygon_outline)
        toolbar.addWidget(poly_outline_btn)
        circle_outline_btn = QPushButton("원형 외곽")
        circle_outline_btn.clicked.connect(self.create_circle_outline)
        toolbar.addWidget(circle_outline_btn)

        toolbar.addSeparator()
        # 그리드 표시와 스냅은 처음부터 켜진 상태로 제공 (제4.5절)
        self.grid_show_check = QCheckBox("그리드 표시")
        self.grid_show_check.setChecked(True)
        self.grid_show_check.toggled.connect(
            lambda: self.canvas.viewport().update()
        )
        toolbar.addWidget(self.grid_show_check)

        self.snap_check = QCheckBox("그리드 스냅")
        self.snap_check.setChecked(True)
        toolbar.addWidget(self.snap_check)

        toolbar.addWidget(QLabel(" 간격:"))
        self.grid_spacing_spin = QDoubleSpinBox()
        self.grid_spacing_spin.setRange(0.5, 200.0)
        self.grid_spacing_spin.setSingleStep(1.0)
        self.grid_spacing_spin.setValue(DEFAULT_GRID_SPACING)
        self.grid_spacing_spin.valueChanged.connect(
            lambda: self.canvas.viewport().update()
        )
        toolbar.addWidget(self.grid_spacing_spin)
        snap_all_btn = QPushButton("스냅에 맞추기")
        snap_all_btn.setToolTip("모든 핀과 외곽을 가장 가까운 격자점으로 옮깁니다")
        snap_all_btn.clicked.connect(self.snap_all_to_grid)
        toolbar.addWidget(snap_all_btn)

        toolbar.addSeparator()
        fit_btn = QPushButton("전체 보기")
        fit_btn.clicked.connect(lambda: self.canvas.fit_to_view())
        toolbar.addWidget(fit_btn)

    def _build_docks_and_canvas(self) -> None:
        # 중앙 CAD 편집 캔버스
        center_widget = QWidget(self)
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(4)

        top_info = QHBoxLayout()
        # 긴 안내 문구가 창 최소 너비를 늘리지 않도록 줄임표·툴팁으로 표시한다.
        self.mode_hint_label = ElidedLabel(SELECT_MODE_HINT)
        self.mode_hint_label.setStyleSheet("color: #334155; font-size: 11px;")
        self.coord_status_label = QLabel("커서 좌표: (0.0, 0.0)")
        self.coord_status_label.setStyleSheet("color: #475569; font-size: 11px;")
        top_info.addWidget(self.mode_hint_label, 1)
        top_info.addWidget(self.coord_status_label)
        center_layout.addLayout(top_info)

        self.canvas = EditorCanvas(self)
        center_layout.addWidget(self.canvas, 1)
        self.setCentralWidget(center_widget)

        # 좌측 도킹 창: 자체 연결기 부품 데이터베이스 목록 및 가져오기/내보내기/기본 부품 복원
        self.library_dock = QDockWidget("연결기 부품 데이터베이스", self)
        self.library_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        lib_panel = QWidget()
        lib_layout = QVBoxLayout(lib_panel)
        lib_layout.setContentsMargins(6, 6, 6, 6)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("종류 필터:"))
        self.family_filter_combo = QComboBox()
        self.family_filter_combo.currentTextChanged.connect(
            self._populate_filtered_parts
        )
        filter_row.addWidget(self.family_filter_combo, 1)
        lib_layout.addLayout(filter_row)

        self.part_list_widget = QListWidget()
        self.part_list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.part_list_widget.currentItemChanged.connect(
            self._on_part_list_selected
        )
        lib_layout.addWidget(self.part_list_widget, 1)

        crud_row = QHBoxLayout()
        self.new_part_btn = QPushButton("새 부품")
        self.dup_part_btn = QPushButton("복제")
        self.del_part_btn = QPushButton("삭제")
        self.new_part_btn.clicked.connect(self.create_new_part)
        self.dup_part_btn.clicked.connect(self.duplicate_current_part)
        self.del_part_btn.clicked.connect(self.delete_selected_part)
        crud_row.addWidget(self.new_part_btn)
        crud_row.addWidget(self.dup_part_btn)
        crud_row.addWidget(self.del_part_btn)
        lib_layout.addLayout(crud_row)

        io_row = QHBoxLayout()
        self.import_btn = QPushButton("부품 가져오기...")
        self.export_btn = QPushButton("선택 부품 내보내기...")
        self.import_btn.clicked.connect(self.import_parts_dialog)
        self.export_btn.clicked.connect(self.export_selected_parts_dialog)
        io_row.addWidget(self.import_btn)
        io_row.addWidget(self.export_btn)
        lib_layout.addLayout(io_row)

        self.restore_defaults_btn = QPushButton("기본 부품 27종 복원")
        self.restore_defaults_btn.clicked.connect(self.restore_default_parts)
        lib_layout.addWidget(self.restore_defaults_btn)

        self.library_dock.setWidget(lib_panel)
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock
        )

        # 우측 도킹 창: 부품 속성(핀 모양·크기 포함) 및 핀 좌표 표
        self.prop_dock = QDockWidget("부품 속성 및 핀 목록", self)
        self.prop_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        prop_panel = QWidget()
        prop_layout = QVBoxLayout(prop_panel)
        prop_layout.setContentsMargins(6, 6, 6, 6)

        info_group = QGroupBox("부품 기본 정보 및 핀 모양·크기")
        info_form = QFormLayout(info_group)
        self.family_edit = QLineEdit()
        self.variant_edit = QLineEdit()
        self.desc_edit = QLineEdit()

        self.pin_shape_combo = QComboBox()
        self.pin_shape_combo.addItem("자동 (1번 사각 / 나머지 원형)", "AUTO")
        self.pin_shape_combo.addItem("원형", "CIRCLE")
        self.pin_shape_combo.addItem("사각형", "SQUARE")

        self.pin_size_spin = QDoubleSpinBox()
        self.pin_size_spin.setRange(6.0, 50.0)
        self.pin_size_spin.setSingleStep(1.0)
        self.pin_size_spin.setValue(PIN_SIZE)

        self.family_edit.editingFinished.connect(self._apply_meta_edits)
        self.variant_edit.editingFinished.connect(self._apply_meta_edits)
        self.desc_edit.editingFinished.connect(self._apply_meta_edits)
        self.pin_shape_combo.currentIndexChanged.connect(self._apply_pin_style_edits)
        self.pin_size_spin.valueChanged.connect(self._apply_pin_style_edits)

        info_form.addRow("분류 (Family):", self.family_edit)
        info_form.addRow("세부명 (Variant):", self.variant_edit)
        info_form.addRow("설명:", self.desc_edit)
        info_form.addRow("핀 모양:", self.pin_shape_combo)
        info_form.addRow("핀 크기:", self.pin_size_spin)
        prop_layout.addWidget(info_group)

        pin_group = QGroupBox("핀 번호 및 좌표 (대소문자 구분, 중복 불가)")
        pin_vlayout = QVBoxLayout(pin_group)
        self.pin_table = QTableWidget(0, 3)
        self.pin_table.setHorizontalHeaderLabels(["핀 번호", "X 좌표", "Y 좌표"])
        self.pin_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.pin_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.pin_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.pin_table.itemChanged.connect(self._on_pin_table_item_changed)
        self.pin_table.itemSelectionChanged.connect(
            self._on_pin_table_selection_changed
        )
        pin_vlayout.addWidget(self.pin_table, 1)

        pin_btn_row = QHBoxLayout()
        add_pin_row_btn = QPushButton("+ 핀 행 추가")
        del_pin_row_btn = QPushButton("- 선택 핀 삭제")
        add_pin_row_btn.clicked.connect(self._add_pin_from_table_btn)
        del_pin_row_btn.clicked.connect(self._delete_selected_pin_from_table)
        pin_btn_row.addWidget(add_pin_row_btn)
        pin_btn_row.addWidget(del_pin_row_btn)
        pin_vlayout.addLayout(pin_btn_row)

        prop_layout.addWidget(pin_group, 1)
        self.prop_dock.setWidget(prop_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.prop_dock)

    def _on_back_clicked(self) -> None:
        """편집기에서 메인 화면으로 전환 요청을 전달한다 (제3.3절 동기화는 MainWindow에서 처리)."""
        self.backToProjectRequested.emit()

    def activate_tool_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        if mode == MODE_SELECT:
            self.act_select.setChecked(True)
            self.mode_hint_label.setText(SELECT_MODE_HINT)
        elif mode == MODE_ADD_PIN:
            self.act_add_pin.setChecked(True)
            self.mode_hint_label.setText(
                "도구 모드: 단일 핀 찍기 — 캔버스를 좌클릭하여 핀을 연속 배치합니다 (ESC 또는 우클릭: 종료)"
            )

    def refresh_part_list(self, select_uuid: str | None = None) -> None:
        parts = self.part_library.list_parts()
        families = sorted({p.family for p in parts if p.family})

        current_filter = self.family_filter_combo.currentText()
        self.family_filter_combo.blockSignals(True)
        self.family_filter_combo.clear()
        self.family_filter_combo.addItem("모든 종류")
        for fam in families:
            self.family_filter_combo.addItem(fam)
        idx = self.family_filter_combo.findText(current_filter)
        self.family_filter_combo.setCurrentIndex(max(idx, 0))
        self.family_filter_combo.blockSignals(False)

        self._populate_filtered_parts(
            self.family_filter_combo.currentText(), select_uuid=select_uuid
        )

    def _populate_filtered_parts(
        self, family_filter: str, select_uuid: str | None = None
    ) -> None:
        target_uuid = select_uuid or (
            self.current_part.uuid if self.current_part else None
        )
        parts = self.part_library.list_parts()
        if family_filter and family_filter != "모든 종류":
            parts = [p for p in parts if p.family == family_filter]

        self.part_list_widget.blockSignals(True)
        self.part_list_widget.clear()
        selected_row = 0
        for row_idx, part in enumerate(parts):
            item = QListWidgetItem(f"{part.name} ({part.pin_count}핀)")
            item.setData(Qt.ItemDataRole.UserRole, part.uuid)
            self.part_list_widget.addItem(item)
            if target_uuid and part.uuid == target_uuid:
                selected_row = row_idx
        self.part_list_widget.blockSignals(False)

        if self.part_list_widget.count() > 0:
            self.part_list_widget.setCurrentRow(selected_row)
            self._load_part_by_uuid(
                str(
                    self.part_list_widget.item(selected_row).data(
                        Qt.ItemDataRole.UserRole
                    )
                )
            )
        else:
            self.current_part = None
            self.canvas.redraw()

    def _on_part_list_selected(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if previous is not None and self.current_part is not None:
            self.save_current_part_to_library()
        if current is None:
            return
        part_uuid = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self._load_part_by_uuid(part_uuid)

    def _load_part_by_uuid(self, part_uuid: str) -> None:
        part = self.part_library.get_part(part_uuid)
        if part is None:
            return
        self.current_part = part.clone()
        if part_uuid not in self._histories:
            self._histories[part_uuid] = StateHistory(self.current_part.to_dict())
        self._show_current_part()
        self.canvas.fit_to_view()
        self.historyChanged.emit()

    def _show_current_part(self) -> None:
        """현재 부품의 정보·핀 목록·캔버스를 다시 표시한다."""
        self._syncing_ui = True
        try:
            self.family_edit.setText(self.current_part.family)
            self.variant_edit.setText(self.current_part.variant)
            self.desc_edit.setText(self.current_part.description)
            shape_idx = self.pin_shape_combo.findData(
                self.current_part.pin_shape
            )
            self.pin_shape_combo.setCurrentIndex(max(shape_idx, 0))
            self.pin_size_spin.setValue(self.current_part.pin_size)
            self._populate_pin_table()
        finally:
            self._syncing_ui = False

        self.canvas.selected_pins = set()
        self.canvas.redraw()

    def _current_history(self) -> StateHistory | None:
        if self.current_part is None:
            return None
        return self._histories.get(self.current_part.uuid)

    def can_undo(self) -> bool:
        history = self._current_history()
        return history is not None and history.can_undo()

    def can_redo(self) -> bool:
        history = self._current_history()
        return history is not None and history.can_redo()

    def undo_description(self) -> str:
        history = self._current_history()
        return history.undo_description() if history else ""

    def redo_description(self) -> str:
        history = self._current_history()
        return history.redo_description() if history else ""

    def _record_part_edit(self, description: str) -> None:
        history = self._current_history()
        if history is not None and history.record(description, self.current_part.to_dict()):
            self.historyChanged.emit()

    def undo(self) -> str:
        """현재 부품의 편집을 한 단계 되돌리고 그 설명을 반환한다 (없으면 빈 문자열)."""
        return self._step_history(redo=False)

    def redo(self) -> str:
        return self._step_history(redo=True)

    def _step_history(self, redo: bool) -> str:
        history = self._current_history()
        step = None
        if history is not None and self.canvas.mode_is_idle():
            step = history.redo() if redo else history.undo()
        if step is None:
            return ""
        description, state = step
        self.current_part = ConnectorPart.from_dict(state)
        self._show_current_part()
        self.save_current_part_to_library()
        self._update_current_list_item()
        self.historyChanged.emit()
        return description

    def _update_current_list_item(self) -> None:
        curr_item = self.part_list_widget.currentItem()
        if curr_item is not None and self.current_part is not None:
            curr_item.setText(
                f"{self.current_part.name} ({self.current_part.pin_count}핀)"
            )

    def _populate_pin_table(self) -> None:
        if self.current_part is None:
            self.pin_table.setRowCount(0)
            return
        self._syncing_ui = True
        try:
            pins = self.current_part.pins
            self.pin_table.setRowCount(len(pins))
            for idx, pin in enumerate(pins):
                self.pin_table.setItem(idx, 0, QTableWidgetItem(pin.designator))
                self.pin_table.setItem(
                    idx, 1, QTableWidgetItem(f"{pin.x:.2f}")
                )
                self.pin_table.setItem(
                    idx, 2, QTableWidgetItem(f"{pin.y:.2f}")
                )
        finally:
            self._syncing_ui = False

    def refresh_pin_table_row(self, idx: int) -> None:
        if self.current_part is None or not (
            0 <= idx < len(self.current_part.pins)
        ):
            return
        self._syncing_ui = True
        try:
            pin = self.current_part.pins[idx]
            self.pin_table.setItem(idx, 0, QTableWidgetItem(pin.designator))
            self.pin_table.setItem(idx, 1, QTableWidgetItem(f"{pin.x:.2f}"))
            self.pin_table.setItem(idx, 2, QTableWidgetItem(f"{pin.y:.2f}"))
        finally:
            self._syncing_ui = False

    def select_pins_in_table(self, indices: set[int]) -> None:
        rows = sorted(i for i in indices if 0 <= i < self.pin_table.rowCount())
        model = self.pin_table.model()
        selection = QItemSelection()
        for row in rows:
            selection.select(
                model.index(row, 0), model.index(row, model.columnCount() - 1)
            )
        self._syncing_ui = True
        try:
            sel_model = self.pin_table.selectionModel()
            sel_model.select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
            if rows:
                sel_model.setCurrentIndex(
                    model.index(rows[0], 0),
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
                self.pin_table.scrollTo(model.index(rows[0], 0))
        finally:
            self._syncing_ui = False

    def _on_pin_table_selection_changed(self) -> None:
        if self._syncing_ui:
            return
        self.canvas.selected_pins = {
            index.row() for index in self.pin_table.selectionModel().selectedRows()
        }
        self.canvas.redraw()

    def _can_use_pin_designator(
        self, candidate: str, exclude_index: int
    ) -> bool:
        if self.current_part is None or not is_valid_pin_number_format(
            candidate
        ):
            return False
        for i, p in enumerate(self.current_part.pins):
            if i != exclude_index and p.designator == candidate:
                return False
        return True

    def _on_pin_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_ui or self.current_part is None:
            return
        row = item.row()
        col = item.column()
        if not (0 <= row < len(self.current_part.pins)):
            return
        pin = self.current_part.pins[row]
        text = item.text()
        if col == 0:
            if self._can_use_pin_designator(text, row):
                pin.designator = text
            else:
                QMessageBox.warning(
                    self,
                    "핀 번호 오류",
                    "핀 번호는 공백을 포함할 수 없으며 부품 안에서 중복될 수 없습니다.",
                )
        elif col == 1:
            try:
                pin.x = round(float(text.strip()), 2)
            except ValueError:
                pass
        elif col == 2:
            try:
                pin.y = round(float(text.strip()), 2)
            except ValueError:
                pass
        self.refresh_pin_table_row(row)
        self.on_part_geometry_modified(rebuild_table=False, description="핀 목록 편집")

    def _apply_meta_edits(self) -> None:
        if self._syncing_ui or self.current_part is None:
            return
        new_family = self.family_edit.text().strip() or "사용자 정의"
        new_variant = self.variant_edit.text().strip() or "기본형"
        candidate_name = f"{new_family} - {new_variant}"
        dup = self.part_library.find_by_name(
            candidate_name, exclude_uuid=self.current_part.uuid
        )
        if dup is not None:
            QMessageBox.warning(
                self,
                "부품명 중복",
                f"연결기 부품 데이터베이스에 '{candidate_name}' 부품이 이미 있습니다.",
            )
            self._syncing_ui = True
            self.family_edit.setText(self.current_part.family)
            self.variant_edit.setText(self.current_part.variant)
            self._syncing_ui = False
            return

        self.current_part.family = new_family
        self.current_part.variant = new_variant
        self.current_part.description = self.desc_edit.text().strip()
        self.save_current_part_to_library()
        self._update_current_list_item()
        self._record_part_edit("부품 정보 변경")

    def _apply_pin_style_edits(self) -> None:
        if self._syncing_ui or self.current_part is None:
            return
        self.current_part.pin_shape = str(
            self.pin_shape_combo.currentData() or "AUTO"
        )
        self.current_part.pin_size = round(self.pin_size_spin.value(), 2)
        self.on_part_geometry_modified(rebuild_table=False, description="핀 모양·크기 변경")

    def on_part_geometry_modified(
        self, rebuild_table: bool = True, description: str = "부품 편집"
    ) -> None:
        if self.current_part is None:
            return
        for idx, pin in enumerate(self.current_part.pins, 1):
            pin.display_order = idx
        # 부품 영역을 외곽·핀에 맞춘다. 좌표가 옮겨지면 화면도 같이 옮겨 제자리에 보이게 한다 (제4.4절).
        view_center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        dx, dy = fit_part_area(self.current_part)
        if dx or dy:
            rebuild_table = True
        if rebuild_table:
            self._populate_pin_table()
        self.save_current_part_to_library()
        self._update_current_list_item()
        self.canvas.redraw()
        if dx or dy:
            self.canvas.centerOn(view_center + QPointF(dx, dy))
        self._record_part_edit(description)

    def save_current_part_to_library(self) -> None:
        if self.current_part is None:
            return
        dup = self.part_library.find_by_name(
            self.current_part.name, exclude_uuid=self.current_part.uuid
        )
        if dup is not None:
            self.current_part.variant = self.part_library.make_unique_variant(
                self.current_part.family, self.current_part.variant
            )
        self.part_library.upsert_part(self.current_part, save_now=True)
        self.libraryUpdated.emit()

    def add_pin_at(self, x: float, y: float) -> None:
        if self.current_part is None:
            return
        des = next_pin_designator([p.designator for p in self.current_part.pins])
        self.current_part.pins.append(
            PinDefinition(
                designator=des,
                x=round(x, 2),
                y=round(y, 2),
                display_order=len(self.current_part.pins) + 1,
            )
        )
        self.canvas.selected_pins = {len(self.current_part.pins) - 1}
        self.on_part_geometry_modified(rebuild_table=True, description=f"핀 {des} 추가")

    def _add_pin_from_table_btn(self) -> None:
        if self.current_part is None:
            return
        cx = round(self.current_part.width / 2.0, 2)
        cy = round(self.current_part.height / 2.0, 2)
        self.add_pin_at(cx, cy)

    def delete_pin_at(self, idx: int) -> None:
        if self.current_part is None or not (
            0 <= idx < len(self.current_part.pins)
        ):
            return
        removed = self.current_part.pins.pop(idx)
        self.canvas.selected_pins = set()
        self.on_part_geometry_modified(
            rebuild_table=True, description=f"핀 {removed.designator} 삭제"
        )

    def _delete_selected_pin_from_table(self) -> None:
        row = self.pin_table.currentRow()
        if row >= 0:
            self.delete_pin_at(row)

    def prompt_rename_pin(self, idx: int) -> None:
        if self.current_part is None or not (
            0 <= idx < len(self.current_part.pins)
        ):
            return
        pin = self.current_part.pins[idx]
        text, ok = QInputDialog.getText(
            self,
            "핀 번호 변경",
            "새 핀 번호 (숫자 또는 A1, B 등 문자 가능, 공백 불가):",
            text=pin.designator,
        )
        if ok and text:
            if not self._can_use_pin_designator(text, idx):
                QMessageBox.warning(
                    self,
                    "핀 번호 오류",
                    "핀 번호는 공백을 포함할 수 없으며 부품 안에서 중복될 수 없습니다.",
                )
                return
            pin.designator = text
            self.on_part_geometry_modified(rebuild_table=True, description="핀 번호 변경")

    def open_auto_placement_dialog(self) -> None:
        if self.current_part is None:
            return
        dlg = AutoPlacementDialog(
            self.current_part,
            snap_enabled=self.is_snap_active(),
            grid_spacing=self.grid_spacing,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_pins, replace = dlg.build_pins()
            if replace:
                self.current_part.pins = new_pins
            else:
                existing_des = {p.designator for p in self.current_part.pins}
                for np in new_pins:
                    if np.designator in existing_des:
                        np.designator = next_pin_designator(list(existing_des))
                    existing_des.add(np.designator)
                    self.current_part.pins.append(np)
            self.on_part_geometry_modified(rebuild_table=True, description="핀 자동 배치")

    def _set_outline(self, outline: OutlineGraphic) -> None:
        if self.current_part is None:
            return
        self.current_part.graphics = [outline]
        self.activate_tool_mode(MODE_SELECT)
        self.on_part_geometry_modified(rebuild_table=False, description="외곽 생성")

    def create_polygon_outline(self) -> None:
        """기존 외곽을 핀 배열에 맞춘 사각형 다각형으로 바꾼다 (제4.4절)."""
        if self.current_part is not None:
            self._set_outline(fitted_polygon_outline(self.current_part))

    def create_circle_outline(self) -> None:
        """기존 외곽을 핀 배열에 맞춘 원으로 바꾼다 (제4.4절)."""
        if self.current_part is not None:
            self._set_outline(fitted_circle_outline(self.current_part))

    def snap_all_to_grid(self, confirm: bool = True) -> bool:
        """모든 핀과 외곽을 가장 가까운 격자점으로 옮긴다 (제4.5절)."""
        if self.current_part is None:
            return False
        try:
            snapped, moved_pins, moved_outline = snap_part_to_grid(
                self.current_part, self.grid_spacing
            )
        except ValueError as exc:
            QMessageBox.information(self, "스냅에 맞추기", f"{exc}\n핀을 옮기지 않았습니다.")
            return False
        if not moved_pins and not moved_outline:
            QMessageBox.information(self, "스냅에 맞추기", "모든 핀과 외곽이 이미 격자에 맞습니다.")
            return False
        if confirm:
            answer = QMessageBox.question(
                self,
                "스냅에 맞추기",
                f"핀 {moved_pins}개, 외곽 점 {moved_outline}개가 이동합니다. 진행할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.current_part.pins = snapped.pins
        self.current_part.graphics = snapped.graphics
        self.on_part_geometry_modified(rebuild_table=True, description="스냅에 맞추기")
        return True

    def create_new_part(self) -> None:
        new_part = ConnectorPart(
            uuid=str(uuid4()),
            family="사용자 정의",
            variant=self.part_library.make_unique_variant(
                "사용자 정의", "신규 연결기"
            ),
            description="사용자 정의 연결기 부품",
            width=NEW_PART_WIDTH,
            height=NEW_PART_HEIGHT,
            pin_size=PIN_SIZE,
        )
        self.part_library.upsert_part(new_part, save_now=True)
        self.refresh_part_list(select_uuid=new_part.uuid)
        self.libraryUpdated.emit()

    def duplicate_current_part(self) -> None:
        if self.current_part is None:
            return
        cloned = self.current_part.clone(new_uuid=True)
        cloned.variant = self.part_library.make_unique_variant(
            cloned.family, f"{cloned.variant}_복제"
        )
        self.part_library.upsert_part(cloned, save_now=True)
        self.refresh_part_list(select_uuid=cloned.uuid)
        self.libraryUpdated.emit()

    def delete_selected_part(self) -> None:
        if self.current_part is None:
            return
        ans = QMessageBox.question(
            self,
            "부품 삭제 확인",
            f"연결기 부품 데이터베이스에서 '{self.current_part.name}' 부품을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._histories.pop(self.current_part.uuid, None)
            self.part_library.delete_part(self.current_part.uuid, save_now=True)
            self.refresh_part_list()
            self.libraryUpdated.emit()

    def restore_default_parts(self) -> None:
        """제4.6절: 기본 부품 27종을 원래 정의로 되돌리거나 다시 추가한다."""
        restored = self.part_library.restore_default_parts(save_now=True)
        # 복원은 부품 정의와 이름을 바꿀 수 있어 기존 이력이 맞지 않으므로 비운다.
        self._histories.clear()
        target_uuid = (
            self.current_part.uuid
            if self.current_part is not None
            else (restored[0].uuid if restored else None)
        )
        self.refresh_part_list(select_uuid=target_uuid)
        self.libraryUpdated.emit()

    def export_selected_parts_dialog(self) -> None:
        selected_items = self.part_list_widget.selectedItems()
        parts_to_export: list[ConnectorPart] = []
        for item in selected_items:
            p_uuid = str(item.data(Qt.ItemDataRole.UserRole) or "")
            p = self.part_library.get_part(p_uuid)
            if p is not None:
                parts_to_export.append(p)
        if not parts_to_export and self.current_part is not None:
            parts_to_export = [self.current_part]
        if not parts_to_export:
            QMessageBox.information(
                self, "부품 내보내기", "내보낼 부품을 먼저 선택해 주세요."
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "선택한 연결기 부품 내보내기 (JSON)",
            "connector_parts.json",
            "JSON 파일 (*.json)",
        )
        if not file_path:
            return
        export_parts(parts_to_export, file_path)
        QMessageBox.information(
            self,
            "부품 내보내기 완료",
            f"선택한 부품 {len(parts_to_export)}종을 내보냈습니다.",
        )

    def import_parts_dialog(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "연결기 부품 가져오기 (JSON)",
            "",
            "JSON 파일 (*.json)",
        )
        if not file_path:
            return
        try:
            incoming_parts = read_parts_file(file_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "부품 가져오기 오류",
                f"부품 파일을 읽을 수 없습니다:\n{exc}",
            )
            return

        imported = self.part_library.import_parts(
            incoming_parts,
            conflict_resolver=self._resolve_import_conflict_ui,
        )
        if imported:
            # 덮어쓴 부품의 이력이 맞지 않게 되므로 비운다.
            self._histories.clear()
            self.refresh_part_list(select_uuid=imported[-1].uuid)
            self.libraryUpdated.emit()
            QMessageBox.information(
                self,
                "부품 가져오기 완료",
                f"부품 {len(imported)}종을 연결기 부품 데이터베이스에 반영했습니다.",
            )

    def _resolve_import_conflict_ui(
        self, existing: ConnectorPart, incoming: ConnectorPart
    ) -> tuple[str, str | None]:
        """동일 UUID 또는 동일 이름 부품을 가져올 때 충돌 처리 (제4.4절)."""
        same_uuid = existing.uuid == incoming.uuid
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("동일 부품 충돌 경고")
        if same_uuid:
            msg.setText(
                f"같은 UUID의 부품 '{existing.name}'이(가) 이미 존재합니다.\n"
                "기존 부품을 덮어쓸지, 이름을 바꾸어 새로 추가할지 선택하세요."
            )
            overwrite_btn = msg.addButton(
                "기존 부품 덮어쓰기", QMessageBox.ButtonRole.AcceptRole
            )
        else:
            msg.setText(
                f"같은 이름의 부품 '{existing.name}'이(가) 이미 존재합니다.\n"
                "이름을 바꾸어야 추가할 수 있습니다."
            )
            overwrite_btn = None

        rename_btn = msg.addButton(
            "이름을 바꾸어 새로 추가", QMessageBox.ButtonRole.ActionRole
        )
        skip_btn = msg.addButton("건너뛰기", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if overwrite_btn is not None and clicked == overwrite_btn:
            return ("overwrite", None)
        if clicked == rename_btn:
            suggested = self.part_library.make_unique_variant(
                incoming.family, incoming.variant
            )
            new_var, ok = QInputDialog.getText(
                self,
                "새 부품 이름 입력",
                f"'{incoming.family}' 분류에 추가할 새 세부 이름(Variant)을 입력하세요:",
                text=suggested,
            )
            if ok and new_var.strip():
                return ("rename", new_var.strip())
            return ("skip", None)
        if clicked == skip_btn:
            return ("skip", None)
        return ("skip", None)
