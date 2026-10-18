"""전연결기(jeonnector) 기본 제공 연결기 27종 및 자동 배치 생성기.

구성은 docs/design.md 제3.6절에 따라 다음 27종을 기본 제공한다:
- D-SUB SD: 9·15·25·37·50핀 (5종)
- D-SUB HD: 15·26·44·62·78핀 (5종)
- D38999 Series IV: B·C·D·E·F·G·H·J 셸의 -35 배열 (8종)
- Micro-D MDM: 9·15·21·25·31·37·51·69·100핀 (9종)
"""

from __future__ import annotations

import math
from uuid import NAMESPACE_URL, uuid5

from jeonnector.models import ConnectorPart, OutlineGraphic, PinDefinition

D38999_CONTACTS: dict[str, dict[str, object]] = {
    "B": {
        "shell": 11,
        "contacts": [
            [1, 0, 146], [2, 85, 118], [3, 138, 45], [4, 138, -45],
            [5, 85, -118], [6, 0, -146], [7, -85, -118], [8, -138, -45],
            [9, -138, 45], [10, -85, 118], [11, 0, 56], [12, 49, -35],
            [13, -49, -35],
        ],
    },
    "C": {
        "shell": 13,
        "contacts": [
            [1, 45, 197], [2, 126, 158], [3, 182, 88], [4, 203, 0],
            [5, 182, -88], [6, 126, -158], [7, 45, -197], [8, -45, -197],
            [9, -126, -158], [10, -182, -88], [11, -203, 0], [12, -182, 88],
            [13, -126, 158], [14, -45, 197], [15, 45, 107], [16, 117, 26],
            [17, 93, -75], [18, 0, -120], [19, -93, -75], [20, -117, 26],
            [21, -45, 107], [22, 0, -30],
        ],
    },
    "D": {
        "shell": 15,
        "contacts": [
            [1, 45, 262], [2, 123, 217], [3, 211, 160], [4, 254, 80],
            [5, 266, -10], [6, 247, -98], [7, 200, -175], [8, 130, -232],
            [9, 45, -262], [10, -45, -262], [11, -130, -232], [12, -200, -175],
            [13, -247, -98], [14, -266, -10], [15, -254, 80], [16, -211, 160],
            [17, -123, 217], [18, -45, 262], [19, 45, 172], [20, 123, 119],
            [21, 170, 40], [22, 170, -50], [23, 123, -127], [24, 45, -172],
            [25, -45, -172], [26, -123, -127], [27, -170, -50], [28, -170, 40],
            [29, -123, 119], [30, -45, 172], [31, 45, 74], [32, 90, -4],
            [33, 45, -82], [34, -45, -82], [35, -90, -4], [36, -45, 74],
            [37, 0, -4],
        ],
    },
    "E": {
        "shell": 17,
        "contacts": [
            [1, -312, 86], [2, -312, -4], [3, -312, -94], [4, -242, 221],
            [5, -234, 131], [6, -234, 41], [7, -234, -49], [8, -234, -139],
            [9, -234, -229], [10, -172, 279], [11, -156, 176], [12, -156, 86],
            [13, -156, -4], [14, -156, -94], [15, -156, -184], [16, -156, -274],
            [17, -89, 316], [18, -78, 221], [19, -78, 131], [20, -78, 41],
            [21, -78, -49], [22, -78, -139], [23, -78, -229], [24, -78, -319],
            [25, 0, 329], [26, 0, 176], [27, 0, 86], [28, 0, -4],
            [29, 0, -94], [30, 0, -184], [31, 0, -274], [32, 89, 316],
            [33, 78, 221], [34, 78, 131], [35, 78, 41], [36, 78, -49],
            [37, 78, -139], [38, 78, -229], [39, 78, -319], [40, 172, 279],
            [41, 156, 176], [42, 156, 86], [43, 156, -4], [44, 156, -94],
            [45, 156, -184], [46, 156, -274], [47, 242, 221], [48, 234, 131],
            [49, 234, 41], [50, 234, -49], [51, 234, -139], [52, 234, -229],
            [53, 312, 86], [54, 312, -4], [55, 312, -94],
        ],
    },
    "F": {
        "shell": 19,
        "contacts": [
            [1, -357, 90], [2, -357, 0], [3, -357, -90], [4, -279, 225],
            [5, -279, 135], [6, -279, 45], [7, -279, -45], [8, -279, -135],
            [9, -279, -225], [10, -201, 270], [11, -201, 180], [12, -201, 90],
            [13, -201, 0], [14, -201, -90], [15, -201, -180], [16, -201, -270],
            [17, -123, 315], [18, -123, 225], [19, -123, 135], [20, -123, 45],
            [21, -123, -45], [22, -123, -135], [23, -123, -225], [24, -123, -315],
            [25, -45, 360], [26, -45, 270], [27, -45, 180], [28, -45, 90],
            [29, -45, 0], [30, -45, -90], [31, -45, -180], [32, -45, -270],
            [33, -45, -360], [34, 45, 360], [35, 45, 270], [36, 45, 180],
            [37, 45, 90], [38, 45, 0], [39, 45, -90], [40, 45, -180],
            [41, 45, -270], [42, 45, -360], [43, 123, 315], [44, 123, 225],
            [45, 123, 135], [46, 123, 45], [47, 123, -45], [48, 123, -135],
            [49, 123, -225], [50, 123, -315], [51, 201, 270], [52, 201, 180],
            [53, 201, 90], [54, 201, 0], [55, 201, -90], [56, 201, -180],
            [57, 201, -270], [58, 279, 225], [59, 279, 135], [60, 279, 45],
            [61, 279, -45], [62, 279, -135], [63, 279, -225], [64, 357, 90],
            [65, 357, 0], [66, 357, -90],
        ],
    },
    "G": {
        "shell": 21,
        "contacts": [
            [1, 53, 426], [2, 146, 404], [3, 232, 362], [4, 306, 302],
            [5, 365, 227], [6, 406, 141], [7, 427, 48], [8, 427, -48],
            [9, 406, -141], [10, 365, -227], [11, 306, -302], [12, 232, -362],
            [13, 146, -404], [14, 53, -426], [15, -53, -426], [16, -146, -404],
            [17, -232, -362], [18, -306, -302], [19, -365, -227], [20, -406, -141],
            [21, -427, -48], [22, -427, 48], [23, -406, 141], [24, -365, 227],
            [25, -306, 302], [26, -232, 362], [27, -146, 404], [28, -53, 426],
            [29, 0, 323], [30, 98, 322], [31, 184, 280], [32, 258, 220],
            [33, 311, 141], [34, 332, 48], [35, 332, -48], [36, 311, -141],
            [37, 258, -220], [38, 184, -280], [39, 98, -322], [40, 0, -347],
            [41, -98, -322], [42, -184, -280], [43, -258, -220], [44, -311, -141],
            [45, -332, -48], [46, -332, 48], [47, -311, 141], [48, -258, 220],
            [49, -184, 280], [50, -98, 322], [51, -48, 241], [52, 48, 241],
            [53, 134, 199], [54, 208, 139], [55, 237, 48], [56, 237, -48],
            [57, 208, -139], [58, 134, -199], [59, 48, -241], [60, -48, -241],
            [61, -134, -199], [62, -208, -139], [63, -237, -48], [64, -237, 48],
            [65, -208, 139], [66, -134, 199], [67, -48, 146], [68, 48, 146],
            [69, 125, 90], [70, 155, 0], [71, 125, -90], [72, 48, -146],
            [73, -48, -146], [74, -125, -90], [75, -155, 0], [76, -125, 90],
            [77, 0, 53], [78, 48, -29], [79, -48, -29],
        ],
    },
    "H": {
        "shell": 23,
        "contacts": [
            [1, -428, 241], [2, -467, 154], [3, -488, 61], [4, -415, 0],
            [5, -488, -61], [6, -428, -142], [7, -428, -237], [8, -332, 333],
            [9, -332, 238], [10, -332, 143], [11, -332, 48], [12, -332, -47],
            [13, -332, -142], [14, -332, -237], [15, -332, -332], [16, -249, 380],
            [17, -249, 285], [18, -249, 190], [19, -249, 95], [20, -249, 0],
            [21, -249, -95], [22, -249, -190], [23, -249, -285], [24, -249, -380],
            [25, -166, 428], [26, -166, 333], [27, -166, 238], [28, -166, 143],
            [29, -166, 48], [30, -166, -47], [31, -166, -142], [32, -166, -237],
            [33, -166, -332], [34, -166, -427], [35, -83, 475], [36, -83, 380],
            [37, -83, 285], [38, -83, 190], [39, -83, 95], [40, -83, 0],
            [41, -83, -95], [42, -83, -190], [43, -83, -285], [44, -83, -380],
            [45, -83, -475], [46, 0, 428], [47, 0, 333], [48, 0, 238],
            [49, 0, 143], [50, 0, 48], [51, 0, -47], [52, 0, -142],
            [53, 0, -237], [54, 0, -332], [55, 0, -427], [56, 83, 475],
            [57, 83, 380], [58, 83, 285], [59, 83, 190], [60, 83, 95],
            [61, 83, 0], [62, 83, -95], [63, 83, -190], [64, 83, -285],
            [65, 83, -380], [66, 83, -475], [67, 166, 428], [68, 166, 333],
            [69, 166, 238], [70, 166, 143], [71, 166, 48], [72, 166, -47],
            [73, 166, -142], [74, 166, -237], [75, 166, -332], [76, 166, -427],
            [77, 249, 380], [78, 249, 285], [79, 249, 190], [80, 249, 95],
            [81, 249, 0], [82, 249, -95], [83, 249, -190], [84, 249, -285],
            [85, 249, -380], [86, 332, 333], [87, 332, 238], [88, 332, 143],
            [89, 332, 48], [90, 332, -47], [91, 332, -142], [92, 332, -237],
            [93, 332, -332], [94, 428, 241], [95, 467, 154], [96, 488, 61],
            [97, 415, 0], [98, 488, -61], [99, 428, -142], [100, 428, -237],
        ],
    },
    "J": {
        "shell": 25,
        "contacts": [
            [1, -479, 279], [2, -520, 190], [3, -546, 95], [4, -555, 0],
            [5, -546, -95], [6, -520, -190], [7, -479, -279], [8, -424, 357],
            [9, -415, 190], [10, -415, 95], [11, -415, 0], [12, -415, -95],
            [13, -415, -190], [14, -424, -357], [15, -332, 444], [16, -332, 332],
            [17, -332, 237], [18, -332, 142], [19, -332, 47], [20, -332, -47],
            [21, -332, -142], [22, -332, -237], [23, -332, -332], [24, -332, -427],
            [25, -249, 496], [26, -249, 380], [27, -249, 285], [28, -249, 190],
            [29, -249, 95], [30, -249, 0], [31, -249, -95], [32, -249, -190],
            [33, -249, -285], [34, -249, -380], [35, -249, -475], [36, -160, 531],
            [37, -166, 427], [38, -166, 332], [39, -166, 237], [40, -166, 142],
            [41, -166, 47], [42, -166, -47], [43, -166, -142], [44, -166, -237],
            [45, -166, -332], [46, -166, -427], [47, -166, -522], [48, -83, 475],
            [49, -83, 380], [50, -83, 285], [51, -83, 190], [52, -83, 95],
            [53, -83, 0], [54, -83, -95], [55, -83, -190], [56, -83, -285],
            [57, -83, -380], [58, -83, -475], [59, 0, 522], [60, 0, 427],
            [61, 0, 332], [62, 0, 237], [63, 0, 142], [64, 0, 47],
            [65, 0, -47], [66, 0, -142], [67, 0, -237], [68, 0, -332],
            [69, 0, -427], [70, 0, -555], [71, 83, 475], [72, 83, 380],
            [73, 83, 285], [74, 83, 190], [75, 83, 95], [76, 83, 0],
            [77, 83, -95], [78, 83, -190], [79, 83, -285], [80, 83, -380],
            [81, 83, -475], [82, 160, 531], [83, 166, 427], [84, 166, 332],
            [85, 166, 237], [86, 166, 142], [87, 166, 47], [88, 166, -47],
            [89, 166, -142], [90, 166, -237], [91, 166, -332], [92, 166, -427],
            [93, 166, -522], [94, 249, 496], [95, 249, 380], [96, 249, 285],
            [97, 249, 190], [98, 249, 95], [99, 249, 0], [100, 249, -95],
            [101, 249, -190], [102, 249, -285], [103, 249, -380], [104, 249, -475],
            [105, 332, 444], [106, 332, 332], [107, 332, 237], [108, 332, 142],
            [109, 332, 47], [110, 332, -47], [111, 332, -142], [112, 332, -237],
            [113, 332, -332], [114, 332, -427], [115, 424, 357], [116, 415, 190],
            [117, 415, 95], [118, 415, 0], [119, 415, -95], [120, 415, -190],
            [121, 424, -357], [122, 479, 279], [123, 520, 190], [124, 546, 95],
            [125, 555, 0], [126, 546, -95], [127, 520, -190], [128, 479, -279],
        ],
    },
}

MICRO_D_ROWS: dict[int, tuple[int, ...]] = {
    9: (5, 4),
    15: (8, 7),
    21: (11, 10),
    25: (13, 12),
    31: (16, 15),
    37: (19, 18),
    51: (18, 17, 16),
    69: (24, 23, 22),
    100: (26, 25, 24, 25),
}

D_SUB_PRESETS: tuple[
    tuple[str, str, int, tuple[int, ...], tuple[float, ...], str], ...
] = (
    ("SD", "E", 9, (5, 4), (0.0, 0.5), "#20"),
    ("SD", "A", 15, (8, 7), (0.0, 0.5), "#20"),
    ("SD", "B", 25, (13, 12), (0.0, 0.5), "#20"),
    ("SD", "C", 37, (19, 18), (0.0, 0.5), "#20"),
    ("SD", "D", 50, (17, 16, 17), (0.0, 0.5, 0.0), "#20"),
    ("HD", "E", 15, (5, 5, 5), (0.5, 0.0, 0.5), "#22"),
    ("HD", "A", 26, (9, 9, 8), (0.5, 0.0, 0.5), "#22"),
    ("HD", "B", 44, (15, 15, 14), (0.5, 0.0, 0.5), "#22"),
    ("HD", "C", 62, (21, 21, 20), (0.5, 0.0, 0.5), "#22"),
    ("HD", "D", 78, (20, 19, 20, 19), (0.0, 0.5, 0.0, 0.5), "#22"),
)


def _definition_id(family: str, variant: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"jeonnect/default-library/{family}/{variant}"))


def _build_dsub_layout(
    pin_count: int,
    starts: tuple[float, ...],
    counts: tuple[int, ...],
    pitch: float = 24.0,
    row_gap: float = 36.0,
    trapezoid: bool = True,
) -> tuple[float, float, list[PinDefinition], list[OutlineGraphic]]:
    margin = 32.0
    width = 2 * margin + max(
        start + count - 1 for start, count in zip(starts, counts)
    ) * pitch
    height = 70.0 + row_gap * (len(counts) - 1)
    pins: list[PinDefinition] = []
    number = 1
    for row, (start, count) in enumerate(zip(starts, counts)):
        for column in range(count):
            pins.append(
                PinDefinition(
                    designator=str(number),
                    x=round(margin + (start + column) * pitch, 2),
                    y=round(35.0 + row * row_gap, 2),
                    display_order=number,
                )
            )
            number += 1
    assert number == pin_count + 1
    bottom_inset = 25.0 if trapezoid else 12.0
    outline = OutlineGraphic(
        type="POLYGON",
        geometry={
            "points": [
                [12.0, 12.0],
                [round(width - 12.0, 2), 12.0],
                [round(width - bottom_inset, 2), round(height - 12.0, 2)],
                [bottom_inset, round(height - 12.0, 2)],
            ]
        },
        display_order=0,
    )
    return width, height, pins, [outline]


def _build_d38999_layout(
    contacts: list[list[int]],
) -> tuple[float, float, list[PinDefinition], list[OutlineGraphic]]:
    width = height = 420.0
    center = width / 2.0
    maximum = max(math.hypot(x, y) for _, x, y in contacts)
    scale = 178.0 / maximum
    pins = [
        PinDefinition(
            designator=str(number),
            x=round(center + x * scale, 2),
            y=round(center - y * scale, 2),
            display_order=order,
        )
        for order, (number, x, y) in enumerate(contacts, 1)
    ]
    outline = OutlineGraphic(
        type="CIRCLE",
        geometry={"cx": center, "cy": center, "radius": 196.0},
        display_order=0,
    )
    return width, height, pins, [outline]


def create_default_parts() -> list[ConnectorPart]:
    """기본 제공 연결기 27종을 생성하여 반환한다."""
    parts: list[ConnectorPart] = []

    # 1. D-SUB SD (5종) & D-SUB HD (5종)
    for density, shell, count, rows, starts, contact_size in D_SUB_PRESETS:
        family = f"D-SUB {density}"
        variant = f"{shell} / {count}핀 / {contact_size}"
        desc = f"{shell} 셸, {contact_size} 접점 배열, 핀 인서트 정면"
        width, height, pins, graphics = _build_dsub_layout(
            count,
            starts,
            rows,
            pitch=30.0 if density == "SD" else 27.0,
            row_gap=36.0 if density == "SD" else 30.0,
        )
        parts.append(
            ConnectorPart(
                uuid=_definition_id(family, variant),
                family=family,
                variant=variant,
                description=desc,
                width=width,
                height=height,
                pins=pins,
                graphics=graphics,
            )
        )

    # 2. D38999 Series IV (8종)
    for letter, arrangement in D38999_CONTACTS.items():
        shell_num = int(arrangement["shell"])  # type: ignore[arg-type]
        contacts = arrangement["contacts"]  # type: ignore[assignment]
        family = "D38999 Series IV"
        variant = f"{letter} / {shell_num}-35 / {len(contacts)}핀"  # type: ignore[arg-type]
        desc = "MIL-STD-1560C Change 3, #22D 접점 배열"
        width, height, pins, graphics = _build_d38999_layout(contacts)  # type: ignore[arg-type]
        parts.append(
            ConnectorPart(
                uuid=_definition_id(family, variant),
                family=family,
                variant=variant,
                description=desc,
                width=width,
                height=height,
                pins=pins,
                graphics=graphics,
            )
        )

    # 3. Micro-D MDM (9종)
    for count, rows in MICRO_D_ROWS.items():
        starts = tuple((max(rows) - row_count) / 2.0 for row_count in rows)
        family = "Micro-D"
        variant = f"{len(rows)}열 {count}핀"
        desc = "MDM 핀 인서트 앞면의 행별 번호를 따른 논리 도식"
        width, height, pins, graphics = _build_dsub_layout(
            count,
            starts,
            rows,
            pitch=18.0,
            row_gap=28.0,
            trapezoid=len(rows) < 4,
        )
        parts.append(
            ConnectorPart(
                uuid=_definition_id(family, variant),
                family=family,
                variant=variant,
                description=desc,
                width=width,
                height=height,
                pins=pins,
                graphics=graphics,
            )
        )

    return parts


def generate_grid_pins(
    row_counts: list[int],
    pitch_x: float,
    pitch_y: float,
    center_x: float,
    center_y: float,
    stagger_odd_rows: bool = False,
    prefix: str = "",
    start_number: int = 1,
) -> list[PinDefinition]:
    """바둑판(격자) 자동 배치 핀 목록을 생성한다."""
    if not row_counts:
        return []
    num_rows = len(row_counts)
    max_cols = max(row_counts)
    total_height = (num_rows - 1) * pitch_y
    start_y = center_y - total_height / 2.0

    pins: list[PinDefinition] = []
    num = start_number
    order = 1
    for r_idx, count in enumerate(row_counts):
        if count <= 0:
            continue
        row_width = (count - 1) * pitch_x
        if stagger_odd_rows and (r_idx % 2 == 1) and count == max_cols:
            row_start_x = center_x - row_width / 2.0 + pitch_x * 0.5
        else:
            row_start_x = center_x - row_width / 2.0
        y = round(start_y + r_idx * pitch_y, 2)
        for c_idx in range(count):
            x = round(row_start_x + c_idx * pitch_x, 2)
            pins.append(
                PinDefinition(
                    designator=f"{prefix}{num}",
                    x=x,
                    y=y,
                    display_order=order,
                )
            )
            num += 1
            order += 1
    return pins


def generate_circular_pins(
    pin_count: int,
    radius: float,
    center_x: float,
    center_y: float,
    start_angle_deg: float = 90.0,
    clockwise: bool = True,
    include_center_pin: bool = False,
    prefix: str = "",
    start_number: int = 1,
) -> list[PinDefinition]:
    """원형 자동 배치 핀 목록을 생성한다."""
    pins: list[PinDefinition] = []
    if pin_count <= 0:
        return pins

    ring_count = pin_count - 1 if (include_center_pin and pin_count > 1) else pin_count
    direction = -1.0 if clockwise else 1.0
    order = 1
    num = start_number
    for idx in range(ring_count):
        angle_deg = start_angle_deg + direction * (360.0 * idx / ring_count)
        angle_rad = math.radians(angle_deg)
        x = round(center_x + radius * math.cos(angle_rad), 2)
        y = round(center_y - radius * math.sin(angle_rad), 2)
        pins.append(
            PinDefinition(
                designator=f"{prefix}{num}",
                x=x,
                y=y,
                display_order=order,
            )
        )
        num += 1
        order += 1

    if include_center_pin and pin_count > 1:
        pins.append(
            PinDefinition(
                designator=f"{prefix}{num}",
                x=round(center_x, 2),
                y=round(center_y, 2),
                display_order=order,
            )
        )
    return pins
