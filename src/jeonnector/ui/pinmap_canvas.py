"""연결기 핀맵 캔버스 및 상단 헤더 바 위젯 (제3.4절, 제3.5절, 제3.7절, 제3.8절, 제4.1절, 제4.3절)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from jeonnector.label_layout import place_labels
from jeonnector.model import (
    DUPLICATE_PIN_COLOR,
    DUPLICATE_PIN_LABEL,
    EMPTY_PART_MESSAGE,
    NO_COLOR_PIN_FILL,
    UNASSIGNED_PIN_COLOR,
    ConnectorInstance,
    ConnectorPart,
    PinDefinition,
    Project,
    display_pin_x,
    pin_is_square,
)

PIN_DIAMETER = 15.0
NORMAL_OUTLINE_WIDTH = 1.6
NORMAL_PIN_BORDER_WIDTH = 1.5
SELECTED_PIN_BORDER_WIDTH = 3.8
# 확대 시 핀의 화면상 지름(픽셀)이 이 값 이상이면 신호명을 함께 표시한다.
SIGNAL_LABEL_MIN_SCREEN_PX = 20.0
AURA_ALPHA = 68
# 신호 색상과 신호유형 색상이 모두 '없음'인 신호의 주변 영역 색상
AURA_FALLBACK_COLOR = "#94a3b8"
# 신호명 글자 크기: 그림 좌표 기준 크기로 핀과 함께 커지다가 화면 기준 상한에서 멈춘다.
# 자리는 label_layout의 자동 배치(아래·위 × 한 줄·두 줄)로 정한다 (제3.4절).
SIGNAL_LABEL_SCENE_PX = 6.5
SIGNAL_LABEL_MAX_SCREEN_PX = 11.0


class ScrollableSignalMenu(QMenu):
    """스크롤 및 첫 글자 키보드 입력 이동을 지원하는 신호 할당 컨텍스트 메뉴 (제3.7절)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QMenu { menu-scrollable: 1; }")
        self._signal_actions: list[QAction] = []

    def register_signal_action(self, action: QAction) -> None:
        self._signal_actions.append(action)
        self.addAction(action)

    def find_first_action_starting_with(self, text: str) -> QAction | None:
        prefix = text.strip().upper()
        if not prefix:
            return None
        for act in self._signal_actions:
            if act.text().upper().startswith(prefix):
                return act
        return None

    def keyPressEvent(self, event) -> None:  # noqa: N802
        typed = event.text().strip()
        if typed and typed.isalnum():
            target = self.find_first_action_starting_with(typed)
            if target is not None:
                self.setActiveAction(target)
                event.accept()
                return
        super().keyPressEvent(event)


class PinmapCanvas(QGraphicsView):
    """물리적 핀 배열과 신호 할당 상태를 그리는 CAD 스타일 2D 핀맵 캔버스."""

    pinSelected = Signal(str)  # 핀 번호 선택 시 발생 (빈 문자열이면 선택 해제)
    pinSignalAssigned = Signal(str, str)  # (pin_designator, signal_name or "")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#f8fafc")))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._project: Project | None = None
        self._connector: ConnectorInstance | None = None
        self._part: ConnectorPart | None = None
        self._selected_pin: str = ""
        self._selected_signal_override: str = ""

        self._panning = False
        self._space_pressed = False
        self._pan_start = QPointF()
        self._auto_fit_on_resize = True

    @property
    def selected_pin(self) -> str:
        return self._selected_pin

    @property
    def current_zoom_scale(self) -> float:
        return abs(self.transform().m11())

    def _effective_pin_diameter(self) -> float:
        if self._part is not None and self._part.pin_size > 2.0:
            return float(self._part.pin_size)
        return PIN_DIAMETER

    def set_context(
        self,
        project: Project | None,
        connector: ConnectorInstance | None,
        part: ConnectorPart | None,
        reset_view: bool = False,
    ) -> None:
        self._project = project
        self._connector = connector
        self._part = part
        if reset_view:
            self._selected_pin = ""
            self._selected_signal_override = ""
            self._auto_fit_on_resize = True
        self.redraw()
        if reset_view and part is not None:
            self.fit_to_view()

    def select_pin(
        self,
        pin_designator: str,
        signal_name: str = "",
        emit_signal: bool = False,
    ) -> None:
        """특정 핀을 선택·하이라이트한다. 미할당 행 선택 시에는 핀맵 강조 표시를 하지 않는다 (제3.8절)."""
        self._selected_pin = pin_designator.strip()
        self._selected_signal_override = (
            signal_name.strip() if self._selected_pin else ""
        )
        self.redraw()
        if emit_signal:
            self.pinSelected.emit(self._selected_pin)

    def fit_to_view(self) -> None:
        """연결기 전체가 화면에 맞게 들어오도록 배율과 위치를 초기화한다."""
        self._auto_fit_on_resize = True
        rect = self._scene.sceneRect()
        if not rect.isEmpty() and self.viewport().width() > 10:
            padded = rect.adjusted(-24.0, -24.0, 24.0, 24.0)
            self.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)
            self.redraw()

    def zoom_by(self, factor: float) -> None:
        self._auto_fit_on_resize = False
        new_scale = self.current_zoom_scale * factor
        if 0.15 <= new_scale <= 35.0:
            self.scale(factor, factor)
            self.redraw()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._auto_fit_on_resize and self._part is not None:
            self.fit_to_view()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta != 0:
            factor = 1.18 if delta > 0 else (1.0 / 1.18)
            self.zoom_by(factor)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
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
        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            self._auto_fit_on_resize = False
            step = 30
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            if key == Qt.Key.Key_Left:
                hbar.setValue(hbar.value() - step)
            elif key == Qt.Key.Key_Right:
                hbar.setValue(hbar.value() + step)
            elif key == Qt.Key.Key_Up:
                vbar.setValue(vbar.value() - step)
            elif key == Qt.Key.Key_Down:
                vbar.setValue(vbar.value() + step)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            if not self._panning:
                self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _pin_at_scene_pos(self, scene_pos: QPointF) -> str:
        """클릭한 캔버스 좌표에 위치한 핀 번호를 반환한다."""
        if self._part is None or self._connector is None:
            return ""
        radius = self._effective_pin_diameter() / 2.0 + 2.0
        flip = self._connector.flip_horizontal
        for pin in self._part.pins:
            px = display_pin_x(pin.x, self._part.width, flip)
            py = pin.y
            if (
                abs(scene_pos.x() - px) <= radius
                and abs(scene_pos.y() - py) <= radius
            ):
                return pin.designator
        return ""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        scene_pos = self.mapToScene(event.position().toPoint())
        hit_pin = self._pin_at_scene_pos(scene_pos)

        # 화면 이동: 휠 버튼 드래그 또는 스페이스바+왼쪽 드래그 (제4.3절)
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_pressed
        ):
            self._panning = True
            self._auto_fit_on_resize = False
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            if hit_pin:
                self.select_pin(hit_pin, emit_signal=True)
                self._show_pin_context_menu(
                    hit_pin, event.globalPosition().toPoint()
                )
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton:
            if hit_pin:
                self.select_pin(hit_pin, emit_signal=True)
                event.accept()
                return
            # 빈 곳 왼쪽 클릭 시 선택만 해제하며, 빈 곳 왼쪽 드래그에는 기능을 두지 않는다 (제3.8절, 제4.3절)
            if self._selected_pin or self._selected_signal_override:
                self.select_pin("", emit_signal=True)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
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
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.LeftButton,
        ):
            self._panning = False
            if self._space_pressed:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def build_pin_context_menu(self, pin_designator: str) -> ScrollableSignalMenu:
        """핀 우클릭 컨텍스트 메뉴를 생성해 반환한다 (제3.7절)."""
        menu = ScrollableSignalMenu(self)
        if self._connector is None:
            return menu

        header_action = menu.addAction(f"핀 {pin_designator} 신호 할당")
        header_action.setEnabled(False)
        menu.addSeparator()

        signal_names = self._connector.signal_names()
        pin_rows = self._connector.pin_to_row_indices().get(pin_designator, [])
        current_signals = [
            self._connector.rows[idx].signal_name for idx in pin_rows
        ]

        if not signal_names:
            empty_action = menu.addAction(
                "(신호표에 생성된 신호가 없습니다)"
            )
            empty_action.setEnabled(False)
        else:
            for sig_name in signal_names:
                action = QAction(sig_name, menu)
                action.setCheckable(True)
                action.setChecked(
                    len(current_signals) == 1 and current_signals[0] == sig_name
                )
                action.triggered.connect(
                    lambda checked=False, p=pin_designator, s=sig_name: (
                        self.pinSignalAssigned.emit(p, s)
                    )
                )
                menu.register_signal_action(action)

        menu.addSeparator()
        unassign_action = menu.addAction("할당 해제 (미할당)")
        unassign_action.setEnabled(bool(current_signals))
        unassign_action.triggered.connect(
            lambda checked=False, p=pin_designator: (
                self.pinSignalAssigned.emit(p, "")
            )
        )
        return menu

    def _show_pin_context_menu(self, pin_designator: str, global_pos) -> None:
        if self._connector is None:
            return
        menu = self.build_pin_context_menu(pin_designator)
        menu.exec(global_pos)

    def _resolve_active_signal(self) -> str:
        """현재 선택된 핀으로부터 기준 신호명을 구한다."""
        if self._connector is None or not self._selected_pin:
            return ""
        first_idx = self._connector.first_row_index_for_pin(self._selected_pin)
        if first_idx is None:
            return ""
        return self._connector.rows[first_idx].signal_name

    def should_show_signal_labels(self) -> bool:
        """핀맵 뷰가 충분히 확대되었는지 판단한다 (제3.4절)."""
        diameter = self._effective_pin_diameter()
        return (diameter * self.current_zoom_scale) >= SIGNAL_LABEL_MIN_SCREEN_PX

    def redraw(self) -> None:
        """현재 연결기와 핀 할당·선택 상태를 캔버스에 다시 그린다."""
        self._scene.clear()
        if self._connector is None:
            text_item = self._scene.addText(
                "왼쪽 연결기 목록에서 연결기를 선택하거나 우클릭하여 추가해 주세요.",
                QFont("Malgun Gothic", 11),
            )
            text_item.setDefaultTextColor(QColor("#64748b"))
            self._scene.setSceneRect(
                text_item.boundingRect().adjusted(-40, -40, 40, 40)
            )
            return

        if self._part is None:
            # 제3.4절: 부품이 없는 연결기는 핀맵에 "연결기 부품이 선택되지 않았습니다"를 표시한다.
            text_item = self._scene.addText(
                EMPTY_PART_MESSAGE,
                QFont("Malgun Gothic", 11),
            )
            text_item.setDefaultTextColor(QColor("#475569"))
            self._scene.setSceneRect(
                text_item.boundingRect().adjusted(-40, -40, 40, 40)
            )
            return

        width = self._part.width
        height = self._part.height
        flip = self._connector.flip_horizontal
        self._scene.setSceneRect(QRectF(0.0, 0.0, width, height))

        # 1. 연결기 외곽 그리기 (화면 확대 시에도 선 굵기는 일정하게 유지)
        outline_pen = QPen(QColor("#334155"), NORMAL_OUTLINE_WIDTH)
        outline_pen.setCosmetic(True)
        outline_brush = QBrush(QColor("#ffffff"))

        for graphic in self._part.graphics:
            g_type = graphic.type.upper()
            geom = graphic.geometry
            if g_type == "POLYGON":
                pts = geom.get("points", [])
                if len(pts) >= 3:
                    poly = QPolygonF(
                        [
                            QPointF(
                                display_pin_x(float(pt[0]), width, flip),
                                float(pt[1]),
                            )
                            for pt in pts
                        ]
                    )
                    self._scene.addPolygon(poly, outline_pen, outline_brush)
            elif g_type == "CIRCLE":
                cx = display_pin_x(
                    float(geom.get("cx", width / 2.0)), width, flip
                )
                cy = float(geom.get("cy", height / 2.0))
                r = float(geom.get("radius", min(width, height) / 2.0 - 10.0))
                self._scene.addEllipse(
                    QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r),
                    outline_pen,
                    outline_brush,
                )

        # 2. 선택한 핀과 동일한 신호가 할당된 핀들의 주변 영역(Aura) 표시 (제3.4절)
        active_signal = self._resolve_active_signal()
        same_signal_pins = (
            self._connector.pins_for_signal(active_signal)
            if active_signal
            else set()
        )

        diameter = self._effective_pin_diameter()
        min_dist = self._part.min_pin_distance()
        aura_size = max(
            min(min_dist * 0.78, diameter * 1.9), diameter + 5.0
        )

        if same_signal_pins and self._project is not None:
            # 핀 채움 색상(신호 색상 → 신호유형 색상)을 연하게 사용하고, 둘 다 '없음'이면 회색
            aura_hex = self._project.effective_signal_color(
                self._connector, active_signal
            )
            if aura_hex == NO_COLOR_PIN_FILL:
                aura_hex = AURA_FALLBACK_COLOR
            aura_color = QColor(aura_hex)
            aura_color.setAlpha(AURA_ALPHA)
            # 겹치는 주변 영역이 진해지지 않도록 하나의 경로로 합쳐 한 번만 칠한다.
            aura_path = QPainterPath()
            aura_path.setFillRule(Qt.FillRule.WindingFill)

            for pin in self._part.pins:
                if pin.designator not in same_signal_pins:
                    continue
                px = display_pin_x(pin.x, width, flip)
                py = pin.y
                aura_rect = QRectF(
                    px - aura_size / 2.0,
                    py - aura_size / 2.0,
                    aura_size,
                    aura_size,
                )
                if pin_is_square(pin.designator, self._part.pin_shape):
                    aura_path.addRect(aura_rect)
                else:
                    aura_path.addEllipse(aura_rect)

            self._scene.addPath(
                aura_path, QPen(Qt.PenStyle.NoPen), QBrush(aura_color)
            )

        # 3. 개별 핀 도형, 핀 번호 및 확대 시 신호명 표시
        pin_to_rows = self._connector.pin_to_row_indices()
        dup_pins = self._connector.duplicate_pins()
        show_signal_labels = self.should_show_signal_labels()

        labels: dict[str, tuple[str, str, bool]] = {}
        for pin in self._part.pins:
            label = self._draw_single_pin(
                pin=pin,
                width=width,
                flip=flip,
                diameter=diameter,
                pin_shape=self._part.pin_shape,
                row_indices=pin_to_rows.get(pin.designator, []),
                is_duplicate=(pin.designator in dup_pins),
                is_bold=(pin.designator == self._selected_pin),
                show_signal_labels=show_signal_labels,
            )
            if label is not None:
                labels[pin.designator] = label
        if labels:
            self._draw_signal_labels(labels, width, flip, diameter, same_signal_pins)

    def _draw_signal_labels(
        self,
        labels: dict[str, tuple[str, str, bool]],
        width: float,
        flip: bool,
        diameter: float,
        same_signal_pins: set[str],
    ) -> None:
        """신호명을 자동 배치해 화면 픽셀 단위로 그린다 (제3.4절).

        선택한 핀과 같은 신호의 핀을 먼저 배치해 지금 보는 신호가 좋은 자리를 얻게 한다.
        """
        assert self._part is not None
        zoom = self.current_zoom_scale
        fonts: dict[bool, QFont] = {}
        for bold in (False, True):
            font = QFont("Malgun Gothic")
            font.setPixelSize(
                max(1, round(min(SIGNAL_LABEL_MAX_SCREEN_PX, SIGNAL_LABEL_SCENE_PX * zoom)))
            )
            font.setBold(bold)
            fonts[bold] = font
        metrics = {bold: QFontMetricsF(font) for bold, font in fonts.items()}

        def is_bold(des: str) -> bool:
            return labels[des][2] or des == self._selected_pin

        screen = {
            pin.designator: (display_pin_x(pin.x, width, flip) * zoom, pin.y * zoom)
            for pin in self._part.pins
        }
        pin_order = [p.designator for p in self._part.ordered_pins() if p.designator in labels]
        order = sorted(
            pin_order,
            key=lambda d: (d != self._selected_pin, d not in same_signal_pins),
        )
        placements = place_labels(
            screen,
            {des: text for des, (text, _, _) in labels.items()},
            order,
            pin_radius=diameter / 2.0 * zoom,
            line_height=metrics[False].height(),
            measure=lambda des, text: metrics[is_bold(des)].horizontalAdvance(text),
        )
        for des, placement in placements.items():
            text, tooltip, is_duplicate = labels[des]
            sx, sy = screen[des]
            for i, line in enumerate(placement.lines):
                item = self._scene.addSimpleText(line, fonts[is_bold(des)])
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                item.setData(Qt.ItemDataRole.UserRole, text)
                item.setToolTip(tooltip)
                item.setBrush(QBrush(QColor("#b91c1c" if is_duplicate else "#1e293b")))
                item.setPos(sx / zoom, sy / zoom)
                line_width = item.boundingRect().width()
                cx, _ = placement.rect.center
                item.setTransform(QTransform.fromTranslate(
                    cx - sx - line_width / 2.0,
                    placement.rect.top - sy + i * metrics[False].height(),
                ))

    def _draw_single_pin(
        self,
        pin: PinDefinition,
        width: float,
        flip: bool,
        diameter: float,
        pin_shape: str,
        row_indices: list[int],
        is_duplicate: bool,
        is_bold: bool,
        show_signal_labels: bool,
    ) -> tuple[str, str, bool] | None:
        """핀 도형과 번호를 그리고, 표시할 신호명이 있으면 (신호명, 툴팁, 중복 여부)를 돌려준다."""
        assert self._connector is not None
        px = display_pin_x(pin.x, width, flip)
        py = pin.y
        half = diameter / 2.0
        rect = QRectF(px - half, py - half, diameter, diameter)

        signal_label = ""
        if is_duplicate:
            fill_color = QColor(DUPLICATE_PIN_COLOR)
            signal_label = DUPLICATE_PIN_LABEL
        elif row_indices and self._project is not None:
            sig_name = self._connector.rows[row_indices[0]].signal_name
            fill_color = QColor(
                self._project.effective_signal_color(self._connector, sig_name)
            )
            signal_label = sig_name
        else:
            fill_color = QColor(UNASSIGNED_PIN_COLOR)

        if is_bold:
            border_pen = QPen(QColor("#0f172a"), SELECTED_PIN_BORDER_WIDTH)
        else:
            border_pen = QPen(QColor("#334155"), NORMAL_PIN_BORDER_WIDTH)
        border_pen.setCosmetic(True)

        path = QPainterPath()
        if pin_is_square(pin.designator, pin_shape):
            path.addRect(rect)
        else:
            path.addEllipse(rect)

        item = self._scene.addPath(path, border_pen, QBrush(fill_color))

        # 신호 중복 핀은 붉은 신호유형 색상과 구분되도록 빗금 및 '!' 표시를 함께 적용 (제3.4절)
        if is_duplicate:
            hatch_pen = QPen(QColor("#ffffff"), 1.0)
            hatch_pen.setCosmetic(True)
            hatch_brush = QBrush(
                QColor(255, 255, 255, 110), Qt.BrushStyle.BDiagPattern
            )
            self._scene.addPath(path, hatch_pen, hatch_brush)

        tooltip_lines = [f"핀 번호: {pin.designator}"]
        if is_duplicate:
            dup_names = [
                self._connector.rows[i].signal_name for i in row_indices
            ]
            tooltip_lines.append(
                f"상태: {DUPLICATE_PIN_LABEL} ({', '.join(dup_names)})"
            )
        elif signal_label:
            sig = self._connector.get_signal(signal_label)
            s_type = (sig.signal_type if sig and sig.signal_type else "없음")
            tooltip_lines.append(f"할당 신호: {signal_label} (신호유형: {s_type})")
        else:
            tooltip_lines.append("상태: 미할당")
        tooltip_text = "\n".join(tooltip_lines)
        item.setToolTip(tooltip_text)

        # 핀 번호 텍스트 (신호 중복 핀은 '!' 표시 추가)
        pin_text = f"{pin.designator}!" if is_duplicate else pin.designator
        num_font = QFont("Segoe UI", 6)
        num_font.setBold(True)
        num_item = self._scene.addSimpleText(pin_text, num_font)
        luminance = (
            0.299 * fill_color.red()
            + 0.587 * fill_color.green()
            + 0.114 * fill_color.blue()
        )
        num_item.setBrush(
            QBrush(QColor("#ffffff" if luminance < 145 else "#0f172a"))
        )
        num_item.setToolTip(tooltip_text)
        num_bounds = num_item.boundingRect()
        num_item.setPos(
            px - num_bounds.width() / 2.0,
            py - num_bounds.height() / 2.0,
        )

        # 충분히 확대되었을 때(또는 신호 중복 시) 신호명을 표시한다. 자리는 _draw_signal_labels가 정한다.
        if signal_label and (show_signal_labels or is_duplicate):
            return signal_label, tooltip_text, is_duplicate
        return None


class ElidedLabel(QLabel):
    """좁은 패널에서 전체 이름이 최소 너비를 강제하지 않는 제목."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width()),
        ))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()


class PinmapPanel(QWidget):
    """상단 헤더 바(연결기 정보, 부품 선택·변경, 좌우 반전과 정면/배면 표시, 전체 보기)와 핀맵 캔버스를 포함하는 패널 (제3.5절, 제4.1절)."""

    partChangeRequested = Signal(str)  # new_part_uuid
    flipToggled = Signal(bool)
    pinSelected = Signal(str)
    pinSignalAssigned = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating_header = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 핀맵 상단 헤더 바
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(4, 2, 4, 2)
        header_bar.setSpacing(8)

        self.connector_title_label = ElidedLabel("연결기 미선택")
        self.connector_title_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #0f172a;"
        )
        header_bar.addWidget(self.connector_title_label)

        # 제목, 부품 선택, 조작을 나누어 넓은 한 줄이 최소 폭을 강제하지 않게 한다.
        part_bar = QHBoxLayout()
        part_bar.setSpacing(4)
        self.part_action_label = QLabel("부품 선택:")
        part_bar.addWidget(self.part_action_label)

        self.part_combo = QComboBox()
        self.part_combo.setMinimumWidth(0)
        self.part_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.part_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.part_combo.setMinimumContentsLength(2)
        self.part_combo.currentTextChanged.connect(self.part_combo.setToolTip)
        self.part_combo.currentIndexChanged.connect(self._on_part_combo_changed)
        part_bar.addWidget(self.part_combo, 1)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.flip_checkbox = QCheckBox("좌우 반전")
        self.flip_checkbox.toggled.connect(self._on_flip_toggled)
        controls.addWidget(self.flip_checkbox)

        self.face_badge_label = QLabel("정면")
        self.face_badge_label.setStyleSheet(
            "padding: 2px 8px; border-radius: 4px; background: #e2e8f0; color: #0f172a; font-weight: bold;"
        )
        header_bar.addWidget(self.face_badge_label)

        controls.addStretch(1)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_out_btn = QPushButton("−")
        self.zoom_in_btn.setToolTip("확대 (+)")
        self.zoom_out_btn.setToolTip("축소 (-)")
        self.zoom_in_btn.setFixedWidth(28)
        self.zoom_out_btn.setFixedWidth(28)
        self.fit_btn = QPushButton("전체 보기")
        controls.addWidget(self.zoom_in_btn)
        controls.addWidget(self.zoom_out_btn)
        controls.addWidget(self.fit_btn)

        layout.addLayout(header_bar)
        layout.addLayout(part_bar)
        layout.addLayout(controls)

        self.canvas = PinmapCanvas(self)
        self.canvas.setMinimumSize(0, 0)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.canvas, 1)

        self.zoom_in_btn.clicked.connect(lambda: self.canvas.zoom_by(1.2))
        self.zoom_out_btn.clicked.connect(
            lambda: self.canvas.zoom_by(1.0 / 1.2)
        )
        self.fit_btn.clicked.connect(self.canvas.fit_to_view)
        self.canvas.pinSelected.connect(self.pinSelected.emit)
        self.canvas.pinSignalAssigned.connect(self.pinSignalAssigned.emit)

    def _update_face_badge(self, flip_horizontal: bool) -> None:
        """제3.5절: 핀맵 헤더 바에 현재 보는 면을 정면(기본) 또는 배면(반전)으로 표시한다."""
        if flip_horizontal:
            self.face_badge_label.setText("배면")
            self.face_badge_label.setStyleSheet(
                "padding: 2px 8px; border-radius: 4px; background: #fef3c7; color: #92400e; font-weight: bold;"
            )
        else:
            self.face_badge_label.setText("정면")
            self.face_badge_label.setStyleSheet(
                "padding: 2px 8px; border-radius: 4px; background: #e2e8f0; color: #0f172a; font-weight: bold;"
            )

    def update_available_parts(self, parts: list[ConnectorPart]) -> None:
        self._updating_header = True
        try:
            current_uuid = self.part_combo.currentData()
            self.part_combo.clear()
            self.part_combo.addItem("(부품 선택 안 함)", "")
            for part in parts:
                self.part_combo.addItem(
                    f"{part.name} ({part.pin_count}핀)", part.uuid
                )
            if current_uuid is not None:
                idx = self.part_combo.findData(current_uuid)
                if idx >= 0:
                    self.part_combo.setCurrentIndex(idx)
        finally:
            self._updating_header = False

    def set_context(
        self,
        project: Project | None,
        connector: ConnectorInstance | None,
        part: ConnectorPart | None,
        reset_view: bool = False,
    ) -> None:
        self._updating_header = True
        try:
            has_conn = connector is not None
            has_part = has_conn and (part is not None)

            # 제4.1절: 부품이 없는 연결기는 부품 변경이 '부품 선택'으로 동작하고 좌우 반전과 전체 보기는 비활성화
            self.part_action_label.setText(
                "부품 변경:" if has_part else "부품 선택:"
            )
            self.part_combo.setEnabled(has_conn)
            self.flip_checkbox.setEnabled(has_part)
            self.face_badge_label.setEnabled(has_part)
            self.zoom_in_btn.setEnabled(has_part)
            self.zoom_out_btn.setEnabled(has_part)
            self.fit_btn.setEnabled(has_part)

            if connector is None:
                self.connector_title_label.setText("연결기 미선택")
                self.part_combo.setCurrentIndex(0)
                self.flip_checkbox.setChecked(False)
                self._update_face_badge(False)
            else:
                part_title = (
                    part.name if part else EMPTY_PART_MESSAGE
                )
                self.connector_title_label.setText(
                    f"연결기: {connector.designator}  [{part_title}]"
                )
                target_uuid = connector.part_uuid or ""
                idx = self.part_combo.findData(target_uuid)
                if idx < 0 and part is not None:
                    self.part_combo.addItem(
                        f"{part.name} ({part.pin_count}핀)", part.uuid
                    )
                    idx = self.part_combo.findData(part.uuid)
                self.part_combo.setCurrentIndex(max(idx, 0))
                self.flip_checkbox.setChecked(connector.flip_horizontal)
                self._update_face_badge(connector.flip_horizontal)
        finally:
            self._updating_header = False

        self.canvas.set_context(
            project, connector, part, reset_view=reset_view
        )

    def _on_part_combo_changed(self, index: int) -> None:
        if self._updating_header or index < 0:
            return
        new_uuid = str(self.part_combo.itemData(index) or "")
        conn = self.canvas._connector
        if conn is None:
            return
        current_uuid = conn.part_uuid or ""
        if new_uuid == current_uuid:
            return

        # 제3.11절: 부품 교체 전 "모든 신호 할당이 해제됩니다." 확인 창을 띄운다.
        if current_uuid:
            ans = QMessageBox.question(
                self,
                "연결기 부품 교체 확인",
                "모든 신호 할당이 해제됩니다.\n연결기 부품을 교체하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                self._updating_header = True
                try:
                    revert_idx = self.part_combo.findData(current_uuid)
                    self.part_combo.setCurrentIndex(max(revert_idx, 0))
                finally:
                    self._updating_header = False
                return

        self.partChangeRequested.emit(new_uuid)

    def _on_flip_toggled(self, checked: bool) -> None:
        if self._updating_header:
            return
        self._update_face_badge(checked)
        self.flipToggled.emit(checked)
