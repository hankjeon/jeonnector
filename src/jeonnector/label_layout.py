"""핀맵 신호명 자동 배치 (docs/design.md 제3.4절).

핀마다 아래·위 × 한 줄·두 줄 후보 가운데 다른 핀·신호명과 겹치지 않으면서 가장 많은 글자를
보여 주는 자리를 고른다. 같으면 한 줄, 아래를 우선한다. 넘치는 글자는 줄임표로 줄이고,
최소 글자 수도 못 보여 주면 그 핀의 신호명은 생략한다. 좌표는 화면 픽셀 단위이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

ELLIPSIS = "…"
MIN_VISIBLE_CHARS = 4
PIN_LABEL_GAP_PX = 2.0  # 핀 가장자리와 신호명 사이
LABEL_SPACING_PX = 6.0  # 이웃 신호명 사이 가로 최소 간격
NEAREST_PIN_RATIO = 0.7  # 신호명 가운데가 자기 핀에 다른 핀보다 확실히 가까워야 한다


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def center(self) -> tuple[float, float]:
        return self.left + self.width / 2.0, self.top + self.height / 2.0

    def intersects(self, other: Rect) -> bool:
        return (
            self.left < other.right and other.left < self.right
            and self.top < other.bottom and other.top < self.bottom
        )


class _Grid:
    """주변 항목만 검사하도록 화면을 칸으로 나눈 공간 색인."""

    def __init__(self, cell: float) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list] = {}

    def _span(self, left: float, top: float, right: float, bottom: float):
        c = self.cell
        for gx in range(math.floor(left / c), math.floor(right / c) + 1):
            for gy in range(math.floor(top / c), math.floor(bottom / c) + 1):
                yield gx, gy

    def add(self, rect: Rect, value) -> None:
        for key in self._span(rect.left, rect.top, rect.right, rect.bottom):
            self.cells.setdefault(key, []).append(value)

    def query(self, left: float, top: float, right: float, bottom: float) -> set:
        found = set()
        for key in self._span(left, top, right, bottom):
            found.update(self.cells.get(key, ()))
        return found


@dataclass(frozen=True)
class LabelPlacement:
    lines: tuple[str, ...]
    rect: Rect


def split_two_lines(text: str) -> tuple[str, str]:
    """밑줄 뒤에서 두 줄 길이가 비슷해지게 나눈다. 밑줄이 없으면 가운데에서 나눈다."""
    cuts = [i + 1 for i, ch in enumerate(text[:-1]) if ch == "_"]
    middle = len(text) / 2.0
    cut = min(cuts, key=lambda c: abs(c - middle)) if cuts else max(1, len(text) // 2)
    return text[:cut], text[cut:]


def label_lines(name: str, visible: int, line_count: int) -> tuple[str, ...]:
    """이름의 앞 visible 글자를 한 줄 또는 두 줄로 만든다. 잘리면 끝에 줄임표를 붙인다."""
    if visible >= len(name):
        return (name,) if line_count == 1 else split_two_lines(name)
    if line_count == 1:
        return (name[:visible] + ELLIPSIS,)
    first, second = split_two_lines(name[:visible])
    return first, second + ELLIPSIS


def place_labels(
    pins: dict[str, tuple[float, float]],
    names: dict[str, str],
    order: list[str],
    pin_radius: float,
    line_height: float,
    measure: Callable[[str, str], float],
) -> dict[str, LabelPlacement]:
    """order 순서로 신호명 자리를 정한다.

    pins는 모든 핀의 화면 좌표(장애물), names는 신호명을 표시할 핀만 담는다.
    measure(핀 번호, 글자)는 그 핀 신호명 글꼴로 잰 글자 폭이다.
    """
    pin_boxes = {
        des: Rect(x - pin_radius - 1, y - pin_radius - 1, 2 * pin_radius + 2, 2 * pin_radius + 2)
        for des, (x, y) in pins.items()
    }
    cell = max(4.0 * pin_radius, 24.0)
    pin_grid = _Grid(cell)
    for des, box in pin_boxes.items():
        pin_grid.add(box, des)
    label_grid = _Grid(cell)
    taken: list[Rect] = []
    placements: dict[str, LabelPlacement] = {}

    def rect_for(des: str, lines: tuple[str, ...], below: bool) -> Rect:
        x, y = pins[des]
        width = max(measure(des, line) for line in lines)
        height = line_height * len(lines)
        top = y + pin_radius + PIN_LABEL_GAP_PX if below else y - pin_radius - PIN_LABEL_GAP_PX - height
        return Rect(x - width / 2.0, top, width, height)

    def is_free(des: str, rect: Rect) -> bool:
        nearby_pins = pin_grid.query(rect.left, rect.top, rect.right, rect.bottom)
        if any(rect.intersects(pin_boxes[other]) for other in nearby_pins if other != des):
            return False
        spaced = Rect(rect.left - LABEL_SPACING_PX, rect.top, rect.width + 2 * LABEL_SPACING_PX, rect.height)
        nearby_labels = label_grid.query(spaced.left, spaced.top, spaced.right, spaced.bottom)
        if any(spaced.intersects(taken[i]) for i in nearby_labels):
            return False
        # 다른 핀이 자기 핀보다 (비율을 고려해) 가깝지 않은지: 그 거리 안의 핀만 살펴본다.
        cx, cy = rect.center
        reach = math.dist(pins[des], (cx, cy)) / NEAREST_PIN_RATIO
        for other in pin_grid.query(cx - reach, cy - reach, cx + reach, cy + reach):
            if other != des and math.dist(pins[other], (cx, cy)) <= reach:
                return False
        return True

    for des in order:
        name = names[des]
        best: tuple[tuple[int, int, int], LabelPlacement] | None = None
        for line_count in (1, 2):
            for rank, below in enumerate((True, False)):
                low, high = min(MIN_VISIBLE_CHARS, len(name)), len(name)
                fit: LabelPlacement | None = None
                fit_visible = 0
                # 보이는 글자가 많을수록 넓어지므로 이분 탐색으로 가장 긴 자리를 찾는다.
                while low <= high:
                    visible = (low + high) // 2
                    lines = label_lines(name, visible, line_count)
                    rect = rect_for(des, lines, below)
                    if is_free(des, rect):
                        fit, fit_visible = LabelPlacement(lines, rect), visible
                        low = visible + 1
                    else:
                        high = visible - 1
                if fit is not None:
                    key = (fit_visible, -line_count, -rank)
                    if best is None or key > best[0]:
                        best = (key, fit)
        if best is not None:
            placements[des] = best[1]
            label_grid.add(best[1].rect, len(taken))
            taken.append(best[1].rect)
    return placements
