"""연결기 부품 편집기의 외곽 생성, 부품 영역 맞춤, 그리드 정렬 계산 (docs/design.md 제4.4~4.5절)."""

from __future__ import annotations

import math

from jeonnector.default_parts import (
    BOTTOM_MARGIN,
    CIRCLE_MARGIN,
    FRAME,
    SIDE_MARGIN,
    TOP_MARGIN,
)
from jeonnector.model import ConnectorPart, OutlineGraphic


def snap_coord(value: float, center: float, spacing: float) -> float:
    """영역 중심(center)을 원점으로 하여 가장 가까운 그리드 격자 좌표를 반환한다."""
    if spacing <= 0:
        return round(value, 3)
    return round(center + round((value - center) / spacing) * spacing, 3)


def fitted_polygon_outline(part: ConnectorPart) -> OutlineGraphic:
    """핀 배열을 기본 부품과 같은 여백으로 둘러싸는 사각형 다각형. 핀이 없으면 영역 안쪽에 둔다."""
    if part.pins:
        left = min(p.x for p in part.pins) - SIDE_MARGIN
        right = max(p.x for p in part.pins) + SIDE_MARGIN
        top = min(p.y for p in part.pins) - TOP_MARGIN
        bottom = max(p.y for p in part.pins) + BOTTOM_MARGIN
    else:
        left, top = FRAME, FRAME
        right, bottom = part.width - FRAME, part.height - FRAME
    left, right, top, bottom = (round(v, 2) for v in (left, right, top, bottom))
    return OutlineGraphic(
        type="POLYGON",
        geometry={"points": [[left, top], [right, top], [right, bottom], [left, bottom]]},
        display_order=0,
    )


def fitted_circle_outline(part: ConnectorPart) -> OutlineGraphic:
    """핀 배열 중심에서 가장 바깥 핀보다 일정 여백 큰 원. 핀이 없으면 영역 안쪽에 둔다."""
    if part.pins:
        cx = (min(p.x for p in part.pins) + max(p.x for p in part.pins)) / 2.0
        cy = (min(p.y for p in part.pins) + max(p.y for p in part.pins)) / 2.0
        radius = max(math.hypot(p.x - cx, p.y - cy) for p in part.pins) + CIRCLE_MARGIN
    else:
        cx, cy = part.width / 2.0, part.height / 2.0
        radius = min(part.width, part.height) / 2.0 - FRAME
    return OutlineGraphic(
        type="CIRCLE",
        geometry={"cx": round(cx, 2), "cy": round(cy, 2), "radius": round(radius, 2)},
        display_order=0,
    )


def _content_points(part: ConnectorPart) -> list[tuple[float, float]]:
    """외곽선과 핀(반지름 포함)의 경계 점."""
    half = part.pin_size / 2.0
    points: list[tuple[float, float]] = []
    for pin in part.pins:
        points += [(pin.x - half, pin.y - half), (pin.x + half, pin.y + half)]
    for graphic in part.graphics:
        geom = graphic.geometry
        if graphic.type.upper() == "CIRCLE":
            cx, cy, r = float(geom["cx"]), float(geom["cy"]), float(geom["radius"])
            points += [(cx - r, cy - r), (cx + r, cy + r)]
        else:
            points += [(float(x), float(y)) for x, y in geom.get("points", [])]
    return points


def translate_part(part: ConnectorPart, dx: float, dy: float) -> None:
    for pin in part.pins:
        pin.x, pin.y = round(pin.x + dx, 2), round(pin.y + dy, 2)
    for graphic in part.graphics:
        geom = graphic.geometry
        if graphic.type.upper() == "CIRCLE":
            geom["cx"] = round(float(geom["cx"]) + dx, 2)
            geom["cy"] = round(float(geom["cy"]) + dy, 2)
        else:
            geom["points"] = [
                [round(float(x) + dx, 2), round(float(y) + dy, 2)]
                for x, y in geom.get("points", [])
            ]


def _grid_offset(offset: float, spacing: float) -> float:
    """중심을 옮길 거리. 그리드 간격이 있으면 그 배수로 반올림해 격자가 밀리지 않게 한다."""
    if spacing <= 0:
        return offset
    return round(offset / spacing) * spacing


def fit_part_area(part: ConnectorPart, spacing: float = 0.0) -> tuple[float, float]:
    """부품 영역을 외곽선·핀의 가장 바깥에서 FRAME만큼 여유를 두고 거의 딱 맞게 맞춘다 (제4.4절).

    영역 중심(그리드 원점)을 내용의 가운데로 옮기되 옮기는 거리를 그리드 간격의 배수로 반올림하고,
    좌표를 함께 옮겨 격자에 맞춘 점이 계속 격자 위에 있게 한다. 그래서 한쪽 여백은 최대
    그리드 간격의 절반만큼 더 남을 수 있다. 내용이 없으면 영역을 그대로 둔다. 옮긴 거리(dx, dy)를 반환한다.
    """
    points = _content_points(part)
    if not points:
        return 0.0, 0.0
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    cx = part.width / 2.0 + _grid_offset((min(xs) + max(xs)) / 2.0 - part.width / 2.0, spacing)
    cy = part.height / 2.0 + _grid_offset((min(ys) + max(ys)) / 2.0 - part.height / 2.0, spacing)
    half_w = round(max(abs(x - cx) for x in xs) + FRAME, 2)
    half_h = round(max(abs(y - cy) for y in ys) + FRAME, 2)
    dx, dy = round(half_w - cx, 2), round(half_h - cy, 2)
    if dx or dy:
        translate_part(part, dx, dy)
    part.width, part.height = 2 * half_w, 2 * half_h
    return dx, dy


def snap_part_to_grid(part: ConnectorPart, spacing: float) -> tuple[ConnectorPart, int, int]:
    """모든 핀과 외곽선(다각형 꼭짓점, 원형 중심·반지름)을 격자에 맞춘 사본과 이동한 핀·외곽 점 수를 반환한다.

    두 핀이 같은 격자점에 모이면 ValueError를 낸다.
    """
    cx, cy = part.width / 2.0, part.height / 2.0
    snapped = part.clone()
    moved_pins = 0
    for pin in snapped.pins:
        x, y = snap_coord(pin.x, cx, spacing), snap_coord(pin.y, cy, spacing)
        if (x, y) != (pin.x, pin.y):
            moved_pins += 1
        pin.x, pin.y = x, y
    if len({(p.x, p.y) for p in snapped.pins}) < len(snapped.pins):
        raise ValueError("그리드 간격이 핀 간격보다 넓어 핀이 겹칩니다.")

    moved_outline = 0
    for graphic in snapped.graphics:
        geom = graphic.geometry
        if graphic.type.upper() == "CIRCLE":
            center = (float(geom["cx"]), float(geom["cy"]))
            new_center = (snap_coord(center[0], cx, spacing), snap_coord(center[1], cy, spacing))
            radius = float(geom["radius"])
            new_radius = max(round(round(radius / spacing) * spacing, 3), spacing)
            moved_outline += (new_center != center) + (new_radius != radius)
            geom["cx"], geom["cy"], geom["radius"] = *new_center, new_radius
        else:
            new_points = []
            for x, y in geom.get("points", []):
                point = [snap_coord(float(x), cx, spacing), snap_coord(float(y), cy, spacing)]
                moved_outline += point != [float(x), float(y)]
                new_points.append(point)
            geom["points"] = new_points
    return snapped, moved_pins, moved_outline
