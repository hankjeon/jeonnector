"""전연결기(jeonnector) 핵심 데이터 모델, 이름·행 검증 규칙 및 부품 동기화 로직."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1

# 새 프로젝트의 기본 신호유형 목록 (이름 -> 색상, 빈 문자열은 색상 '없음')
DEFAULT_SIGNAL_TYPES: dict[str, str] = {
    "전원": "#ef4444",
    "접지": "#475569",
    "고속신호": "#3b82f6",
    "제어신호": "#10b981",
    "아날로그": "#f59e0b",
    "통신": "#8b5cf6",
    "기타": "#06b6d4",
}

# 하위 호환 별칭
DEFAULT_CATEGORIES = DEFAULT_SIGNAL_TYPES

UNASSIGNED_PIN_COLOR = "#e2e8f0"
NO_COLOR_PIN_FILL = "#ffffff"
DUPLICATE_PIN_COLOR = "#dc2626"
DUPLICATE_CELL_BG_COLOR = "#fecaca"
DUPLICATE_PIN_LABEL = "신호 중복"
EMPTY_PART_MESSAGE = "연결기 부품이 선택되지 않았습니다"

_SIGNAL_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_SIGNAL_TYPE_NAME_RE = re.compile(r"^[A-Z가-힣][A-Z가-힣0-9_]{0,31}$")


class ProjectFormatError(ValueError):
    """손상된 프로젝트 파일 또는 지원하지 않는 상위 schema_version 오류."""


def natural_sort_key(text: str) -> list[int | str]:
    """핀 번호·식별자 등의 자연 정렬 키 생성 (대소문자는 ASCII 순서: A2 < A10, A < a)."""
    parts = re.split(r"(\d+)", text)
    return [int(p) if p.isdigit() else p for p in parts]


def normalize_signal_name(raw_name: str) -> str:
    """신호명 및 연결기 식별자 정규화 (앞뒤 공백 제거 후 대문자 변환)."""
    return raw_name.strip().upper()


def is_valid_signal_name(raw_name: str) -> bool:
    """신호명 및 연결기 식별자 유효성 검사 (제3.1절, 제3.6절).

    - 영문 대문자, 숫자, 언더스코어(_)만 사용하며 영문자로 시작
    - 대소문자 구분 없음(대문자로 변환 후 검증)
    - 빈 이름 불가, 32자 이하
    """
    normalized = normalize_signal_name(raw_name)
    if not normalized:
        return False
    return bool(_SIGNAL_NAME_RE.match(normalized))


def normalize_signal_type_name(raw_name: str) -> str:
    """신호유형 이름 정규화 (앞뒤 공백 제거 후 영문은 대문자로 변환)."""
    return raw_name.strip().upper()


def is_valid_signal_type_name(raw_name: str) -> bool:
    """신호유형 이름 유효성 검사 (제3.10절).

    - 영문 대문자·한글·숫자·언더스코어(_)만 사용하고 영문자 또는 한글로 시작
    - 공백 불가, 32자 이하
    """
    normalized = normalize_signal_type_name(raw_name)
    if not normalized:
        return False
    return bool(_SIGNAL_TYPE_NAME_RE.match(normalized))


def is_valid_pin_number_format(raw_pin: str) -> bool:
    """핀 번호 문자 규칙 검사 (제3.9절: 앞뒤·중간 공백 불허, 대소문자 구분)."""
    if not raw_pin:
        return False
    if raw_pin != raw_pin.strip():
        return False
    return not any(ch.isspace() for ch in raw_pin)


def pin_is_square(designator: str, pin_shape: str = "AUTO") -> bool:
    """핀 모양 결정 (기본 AUTO일 때 1번 핀은 사각형, 나머지는 원형)."""
    shape = pin_shape.upper()
    if shape == "SQUARE":
        return True
    if shape == "CIRCLE":
        return False
    return designator.strip() == "1"


def display_pin_x(pin_x: float, width: float, flip_horizontal: bool) -> float:
    """좌우 반전 옵션에 따른 표시용 X 좌표 계산 (외곽 중심 세로축 기준)."""
    return round(width - pin_x, 3) if flip_horizontal else pin_x


@dataclass
class PinDefinition:
    """연결기 부품 내 개별 핀 정의."""

    designator: str
    x: float
    y: float
    display_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "designator": self.designator,
            "x": round(float(self.x), 3),
            "y": round(float(self.y), 3),
            "display_order": int(self.display_order),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_order: int = 0) -> PinDefinition:
        designator = str(data["designator"]).strip()
        if not designator:
            raise ValueError("핀 번호가 비어 있습니다.")
        return cls(
            designator=designator,
            x=float(data["x"]),
            y=float(data["y"]),
            display_order=int(data.get("display_order", default_order)),
        )


@dataclass
class OutlineGraphic:
    """연결기 외곽 그래픽 요소 (POLYGON 또는 CIRCLE)."""

    type: str  # "POLYGON" | "CIRCLE"
    geometry: dict[str, Any]
    display_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "geometry": copy.deepcopy(self.geometry),
            "display_order": int(self.display_order),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_order: int = 0) -> OutlineGraphic:
        geom = data.get("geometry", {})
        if isinstance(geom, str):
            import json

            geom = json.loads(geom)
        return cls(
            type=str(data.get("type", "POLYGON")).upper(),
            geometry=copy.deepcopy(geom),
            display_order=int(data.get("display_order", default_order)),
        )


@dataclass
class ConnectorPart:
    """연결기 부품 정의 (UUID로 식별)."""

    uuid: str
    family: str
    variant: str
    description: str = ""
    width: float = 200.0
    height: float = 120.0
    pins: list[PinDefinition] = field(default_factory=list)
    graphics: list[OutlineGraphic] = field(default_factory=list)
    revision: str = "1"
    pin_shape: str = "AUTO"  # "AUTO" | "CIRCLE" | "SQUARE"
    pin_size: float = 15.0

    @property
    def name(self) -> str:
        if self.family and self.variant:
            return f"{self.family} - {self.variant}"
        return self.family or self.variant or "이름 없는 부품"

    @property
    def pin_count(self) -> int:
        return len(self.pins)

    def ordered_pins(self) -> list[PinDefinition]:
        """자연 정렬(대소문자 ASCII 순서) 기준으로 핀 목록 반환."""
        return sorted(
            self.pins,
            key=lambda p: (
                p.display_order if p.display_order > 0 else 999999,
                natural_sort_key(p.designator),
            ),
        )

    def pin_designators(self) -> list[str]:
        """드롭다운 표시용 자연 정렬된 핀 번호 목록 반환 (제3.9절)."""
        return sorted(
            (p.designator for p in self.pins),
            key=natural_sort_key,
        )

    def pin_map(self) -> dict[str, PinDefinition]:
        return {p.designator: p for p in self.pins}

    def has_pin(self, designator: str) -> bool:
        """대소문자를 구분하여 해당 핀 번호가 부품에 존재하는지 확인."""
        if not is_valid_pin_number_format(designator):
            return False
        return any(p.designator == designator for p in self.pins)

    def min_pin_distance(self) -> float:
        """인접 핀 간 최소 거리 계산 (주변 영역 반경 계산용)."""
        if len(self.pins) < 2:
            return 30.0
        min_dist_sq = float("inf")
        for i, p1 in enumerate(self.pins):
            for p2 in self.pins[i + 1 :]:
                d_sq = (p1.x - p2.x) ** 2 + (p1.y - p2.y) ** 2
                if d_sq > 1e-6 and d_sq < min_dist_sq:
                    min_dist_sq = d_sq
        return (min_dist_sq**0.5) if min_dist_sq != float("inf") else 30.0

    def clone(self, new_uuid: bool = False) -> ConnectorPart:
        cloned = copy.deepcopy(self)
        if new_uuid:
            cloned.uuid = str(uuid4())
        return cloned

    def is_definition_equal(self, other: ConnectorPart) -> bool:
        """같은 UUID 부품의 물리적·표시 정의가 동일한지 비교."""
        return self.to_dict() == other.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "family": self.family,
            "variant": self.variant,
            "description": self.description,
            "revision": self.revision,
            "width": round(float(self.width), 3),
            "height": round(float(self.height), 3),
            "pin_shape": self.pin_shape,
            "pin_size": round(float(self.pin_size), 2),
            "pins": [p.to_dict() for p in self.ordered_pins()],
            "graphics": [g.to_dict() for g in self.graphics],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectorPart:
        if not isinstance(data, dict):
            raise ValueError("부품 데이터가 올바른 객체 형식이 아닙니다.")
        pins = [
            PinDefinition.from_dict(p, idx + 1)
            for idx, p in enumerate(data.get("pins", []))
        ]
        graphics = [
            OutlineGraphic.from_dict(g, idx)
            for idx, g in enumerate(data.get("graphics", []))
        ]
        return cls(
            uuid=str(data.get("uuid") or uuid4()),
            family=str(data.get("family", "")).strip(),
            variant=str(data.get("variant", "")).strip(),
            description=str(data.get("description", "")).strip(),
            revision=str(data.get("revision", "1")),
            width=float(data.get("width", 200.0)),
            height=float(data.get("height", 120.0)),
            pins=pins,
            graphics=graphics,
            pin_shape=str(data.get("pin_shape", "AUTO")).upper(),
            pin_size=float(data.get("pin_size", 15.0)),
        )


@dataclass
class SignalDefinition:
    """연결기 내부에서 신호명을 키로 관리하는 신호 정의 (제2절, 제3.6절).

    신호유형(signal_type)과 색상(color)은 빈 문자열("")이면 '없음'을 뜻한다.
    """

    name: str
    signal_type: str = ""
    color: str = ""

    @property
    def category(self) -> str:
        return self.signal_type

    @category.setter
    def category(self, value: str) -> None:
        self.signal_type = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "signal_type": self.signal_type,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalDefinition:
        raw_name = str(data.get("name", "")).strip()
        name = normalize_signal_name(raw_name) if raw_name else ""
        sig_type = str(
            data.get("signal_type", data.get("category", ""))
        ).strip()
        if sig_type:
            sig_type = normalize_signal_type_name(sig_type)
        return cls(
            name=name,
            signal_type=sig_type,
            color=str(data.get("color", "")).strip(),
        )


@dataclass
class SignalRow:
    """신호표의 개별 행 (신호명 참조 및 핀 번호 할당)."""

    signal_name: str
    pin_designator: str = ""
    row_id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "signal_name": self.signal_name,
            "pin_designator": self.pin_designator,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalRow:
        raw_sig = str(data.get("signal_name", "")).strip()
        sig_name = normalize_signal_name(raw_sig) if raw_sig else ""
        return cls(
            signal_name=sig_name,
            pin_designator=str(data.get("pin_designator", "")).strip(),
            row_id=str(data.get("row_id") or uuid4()),
        )


@dataclass
class ConnectorInstance:
    """프로젝트에 추가된 연결기 인스턴스 (제2절, 제3.1절, 제3.6절)."""

    designator: str
    part_uuid: str | None = None
    flip_horizontal: bool = False
    signals: dict[str, SignalDefinition] = field(default_factory=dict)
    rows: list[SignalRow] = field(default_factory=list)

    @property
    def connector_id(self) -> str:
        return self.designator

    @connector_id.setter
    def connector_id(self, value: str) -> None:
        self.designator = normalize_signal_name(value)

    def signal_names(self) -> list[str]:
        """현재 연결기에 정의된 신호명 목록 (자연 정렬 오름차순)."""
        return sorted(self.signals.keys(), key=natural_sort_key)

    def get_signal(self, signal_name: str) -> SignalDefinition | None:
        return self.signals.get(normalize_signal_name(signal_name))

    def row_usage_count(self, signal_name: str) -> int:
        norm = normalize_signal_name(signal_name)
        return sum(1 for r in self.rows if r.signal_name == norm)

    def assigned_row_count(self, signal_name: str) -> int:
        norm = normalize_signal_name(signal_name)
        return sum(
            1 for r in self.rows if r.signal_name == norm and r.pin_designator
        )

    def enforce_row_rules(
        self, allow_pending_unassigned_row_id: str | None = None
    ) -> None:
        """제3.6절 행 규칙을 적용해 신호와 행의 일관성을 유지한다.

        - 신호는 할당된 핀 수만큼 행을 가지며, 할당된 핀이 없는 신호는 미할당 행 하나를 가진다.
        - 미할당 신호는 신호명으로 관리되므로 같은 신호의 미할당 행은 하나로 합쳐진다.
        - 단, 신호표 마지막 빈 행에서 방금 추가되어 핀 번호 입력을 기다리는 행(allow_pending_unassigned_row_id)은 유지한다.
        - 행이 하나도 남지 않은 신호는 signals 사전에서 제거한다.
        """
        assigned_counts: dict[str, int] = {}
        for row in self.rows:
            row.signal_name = normalize_signal_name(row.signal_name)
            if row.pin_designator:
                assigned_counts[row.signal_name] = (
                    assigned_counts.get(row.signal_name, 0) + 1
                )

        seen_unassigned: set[str] = set()
        new_rows: list[SignalRow] = []
        for row in self.rows:
            sig_name = row.signal_name
            if not sig_name:
                continue
            if row.pin_designator:
                new_rows.append(row)
            else:
                if (
                    allow_pending_unassigned_row_id is not None
                    and row.row_id == allow_pending_unassigned_row_id
                ):
                    if sig_name not in seen_unassigned:
                        seen_unassigned.add(sig_name)
                        new_rows.append(row)
                elif assigned_counts.get(sig_name, 0) > 0:
                    # 이미 할당된 핀이 있는 신호의 불필요한 미할당 행은 제거
                    continue
                elif sig_name not in seen_unassigned:
                    seen_unassigned.add(sig_name)
                    new_rows.append(row)

        self.rows = new_rows
        used_signals = {r.signal_name for r in self.rows}
        for sig_key in list(self.signals.keys()):
            if sig_key not in used_signals:
                del self.signals[sig_key]

    def add_or_update_row_signal(
        self,
        row_index: int,
        signal_name: str,
        default_category: str = "",
    ) -> bool:
        """신호표의 특정 행(또는 마지막 빈 행)의 신호명을 설정하거나 변경한다 (제3.6절).

        - 신호명 규칙(영문자 시작, 영문 대문자·숫자·언더스코어, 32자 이하)을 검증하고 대문자로 정규화한다.
        - 한 행의 신호명을 바꾸면 그 행만 다른 신호가 된다 (다른 행은 기존 신호로 유지).
        - 바꾼 이름의 신호가 이미 있으면 그 행은 해당 신호의 속성을 따른다.
        - 처음 쓰는 이름이면 신호유형과 색상이 '없음'("")인 새 신호가 생성된다.
        - 행이 하나도 남지 않은 이전 신호는 사라진다.
        """
        if not is_valid_signal_name(signal_name):
            return False
        cleaned = normalize_signal_name(signal_name)
        norm_type = (
            normalize_signal_type_name(default_category)
            if default_category.strip()
            else ""
        )

        if row_index >= len(self.rows):
            if cleaned not in self.signals:
                self.signals[cleaned] = SignalDefinition(
                    name=cleaned,
                    signal_type=norm_type,
                    color="",
                )
            new_row = SignalRow(signal_name=cleaned, pin_designator="")
            self.rows.append(new_row)
            self.enforce_row_rules(
                allow_pending_unassigned_row_id=new_row.row_id
            )
            return True

        target_row = self.rows[row_index]
        old_name = target_row.signal_name
        if old_name == cleaned:
            return True

        if cleaned not in self.signals:
            self.signals[cleaned] = SignalDefinition(
                name=cleaned,
                signal_type=norm_type,
                color="",
            )
        target_row.signal_name = cleaned
        pending_id = (
            target_row.row_id if not target_row.pin_designator else None
        )
        self.enforce_row_rules(allow_pending_unassigned_row_id=pending_id)
        return True

    def add_signal_row(
        self, signal_name: str, pin_designator: str,
        part: ConnectorPart | None, signal_type: str = "", color: str = "",
    ) -> bool:
        """입력 중인 행을 모두 검증한 뒤 신호와 할당을 함께 추가한다."""
        if not is_valid_signal_name(signal_name):
            return False
        if not self.validate_pin_designator(pin_designator, part):
            return False
        name = normalize_signal_name(signal_name)
        if name not in self.signals:
            if signal_type and not is_valid_signal_type_name(signal_type):
                return False
            self.signals[name] = SignalDefinition(
                name=name,
                signal_type=normalize_signal_type_name(signal_type),
                color=color,
            )
        self.rows.append(SignalRow(
            signal_name=name,
            pin_designator="" if pin_designator == "미할당" else pin_designator,
        ))
        self.enforce_row_rules()
        return True

    def rename_shared_signal(self, old_name: str, new_name: str) -> bool:
        """같은 신호를 사용하는 모든 행의 신호명을 일괄 변경할 때 사용하는 헬퍼."""
        if not is_valid_signal_name(new_name):
            return False
        norm_old = normalize_signal_name(old_name)
        norm_new = normalize_signal_name(new_name)
        if norm_old not in self.signals:
            return False
        if norm_old == norm_new:
            return True

        old_sig = self.signals.pop(norm_old)
        if norm_new not in self.signals:
            old_sig.name = norm_new
            self.signals[norm_new] = old_sig
        for row in self.rows:
            if row.signal_name == norm_old:
                row.signal_name = norm_new
        self.enforce_row_rules()
        return True

    def set_signal_type(self, signal_name: str, signal_type: str) -> bool:
        """신호의 신호유형을 변경(또는 '없음'으로 해제)하여 모든 사용 행에 반영한다."""
        sig = self.get_signal(signal_name)
        if sig is None:
            return False
        cleaned = signal_type.strip()
        if cleaned in ("", "없음", "(없음)"):
            sig.signal_type = ""
            return True
        if not is_valid_signal_type_name(cleaned):
            return False
        sig.signal_type = normalize_signal_type_name(cleaned)
        return True

    def set_signal_category(self, signal_name: str, category: str) -> bool:
        """set_signal_type의 별칭."""
        return self.set_signal_type(signal_name, category)

    def set_signal_color(self, signal_name: str, color: str) -> bool:
        """신호의 개별 색상을 변경(또는 ''/'없음'으로 해제)하여 모든 사용 행에 반영한다."""
        sig = self.get_signal(signal_name)
        if sig is None:
            return False
        cleaned = color.strip()
        if cleaned in ("없음", "(없음)"):
            cleaned = ""
        sig.color = cleaned
        return True

    def delete_row(self, row_index: int) -> bool:
        """신호 행 삭제 (제3.6절).

        다른 행에도 사용된 신호는 선택한 행만 지우고, 그 행만 가진 신호는 신호도 함께 삭제한다.
        """
        if not (0 <= row_index < len(self.rows)):
            return False
        removed = self.rows.pop(row_index)
        if self.row_usage_count(removed.signal_name) == 0:
            self.signals.pop(removed.signal_name, None)
        return True

    def validate_pin_designator(
        self, pin_designator: str, part: ConnectorPart | None
    ) -> bool:
        """핀 번호 유효성 검사 (제3.9절).

        빈 문자열("") 또는 '미할당'은 할당 해제로 허용한다.
        연결기 부품에 존재하는 핀 번호(대소문자 구분, 공백 불가)만 허용한다.
        """
        if pin_designator in ("", "미할당"):
            return True
        if not is_valid_pin_number_format(pin_designator):
            return False
        if part is None:
            return False
        return part.has_pin(pin_designator)

    def set_row_pin(
        self,
        row_index: int,
        pin_designator: str,
        part: ConnectorPart | None,
    ) -> bool:
        """신호표 행에 핀 번호를 할당하거나 해제한다 (제3.6절 행 규칙 적용).

        - 여러 핀에 할당된 신호의 한 핀을 해제하면 그 행은 사라진다.
        - 신호의 마지막 핀이 해제되면 미할당 행 하나로 남는다.
        - 핀을 할당하면 같은 신호의 잉여 미할당 행은 합쳐진다.
        """
        if not (0 <= row_index < len(self.rows)):
            return False
        if pin_designator == "미할당":
            pin_designator = ""
        if not self.validate_pin_designator(pin_designator, part):
            return False

        target_row = self.rows[row_index]
        target_row.pin_designator = pin_designator
        self.enforce_row_rules()
        return True

    def _unassign_pin_Applying_rules(self, pin_designator: str) -> bool:
        """특정 핀에 할당된 모든 신호를 해제하고 제3.6절 행 규칙을 적용한다."""
        matching = [
            r for r in self.rows if r.pin_designator == pin_designator
        ]
        if not matching:
            return False
        for row in matching:
            row.pin_designator = ""
        self.enforce_row_rules()
        return True

    def assign_signal_from_pinmap(
        self,
        pin_designator: str,
        signal_name: str | None,
        part: ConnectorPart | None,
    ) -> bool:
        """핀맵 우클릭 컨텍스트 메뉴에서 기존 신호를 핀에 할당하거나 해제한다 (제3.7절).

        - 핀맵에서는 새 신호를 만들지 않는다.
        - 이미 신호가 있는 핀(신호 중복 핀 포함)에 다른 신호를 할당하면 기존 신호를 모두 교체한다.
          밀려난 신호 중 그 핀에만 할당되었던 신호는 미할당 신호가 되고,
          다른 핀에도 할당된 신호는 그 행만 사라진다.
        - 할당을 해제하면 그 핀의 신호를 모두 해제하며 각 신호에 제3.6절 행 규칙을 적용한다.
        """
        if not is_valid_pin_number_format(pin_designator):
            return False
        if not self.validate_pin_designator(pin_designator, part):
            return False

        # 할당 해제
        if not signal_name or signal_name in ("미할당", ""):
            return self._unassign_pin_Applying_rules(pin_designator)

        cleaned_sig = normalize_signal_name(signal_name)
        if cleaned_sig not in self.signals:
            return False

        # 먼저 해당 핀의 기존 할당을 모두 해제(교체 대상 정리)
        for row in self.rows:
            if row.pin_designator == pin_designator:
                row.pin_designator = ""
        self.enforce_row_rules()

        # 대상 신호에 미할당 행이 있으면 그 행에 핀 할당, 없으면 새 행 추가
        assigned = False
        for row in self.rows:
            if row.signal_name == cleaned_sig and row.pin_designator == "":
                row.pin_designator = pin_designator
                assigned = True
                break
        if not assigned:
            self.rows.append(
                SignalRow(signal_name=cleaned_sig, pin_designator=pin_designator)
            )

        self.enforce_row_rules()
        return True

    def replace_part(self, new_part_uuid: str | None) -> None:
        """연결기 부품 교체 (제3.11절).

        연결기 식별자와 신호(신호명, 신호유형, 색상)는 유지하고 할당은 모두 해제한다.
        각 신호는 미할당 행 하나로 합쳐진다.
        """
        self.part_uuid = new_part_uuid
        for row in self.rows:
            row.pin_designator = ""
        self.enforce_row_rules()

    def apply_same_uuid_part_update(
        self, updated_part: ConnectorPart
    ) -> list[tuple[str, str]]:
        """같은 UUID 부품의 정의 변경 반영 (제3.3절).

        핀 위치 변경·핀 추가는 기존 할당을 유지하고,
        삭제된 핀에 할당되었던 신호만 할당을 해제(제3.6절 행 규칙 적용)한다.
        반환값: 할당이 해제된 (pin_designator, signal_name) 목록.
        """
        valid_pins = {p.designator for p in updated_part.pins}
        unassigned_list: list[tuple[str, str]] = []
        for row in self.rows:
            if row.pin_designator and row.pin_designator not in valid_pins:
                unassigned_list.append((row.pin_designator, row.signal_name))
                row.pin_designator = ""
        if unassigned_list:
            self.enforce_row_rules()
        return unassigned_list

    def sort_rows(
        self,
        column: str = "pin",
        descending: bool = False,
    ) -> None:
        """신호표 행 정렬 (제3.6절 정렬 규칙).

        - column: 'pin' | 'signal' | 'signal_type'
        - 신호명·신호유형 정렬에서 값이 같은 행은 핀 번호 순서로 놓는다.
        - 같은 핀에 중복된 행끼리는 신호명 오름차순으로 놓는다.
        - 미할당 행은 항상 할당 행 뒤에 두고 미할당 행끼리 정렬한다.
        """
        assigned = [r for r in self.rows if r.pin_designator]
        unassigned = [r for r in self.rows if not r.pin_designator]

        def sig_type_of(r: SignalRow) -> str:
            sig = self.signals.get(r.signal_name)
            return sig.signal_type if sig else ""

        if column == "pin":
            # 핀 번호 주 정렬(오름/내림), 같은 핀에 중복된 행끼리는 신호명 항상 오름차순
            by_pin: dict[str, list[SignalRow]] = {}
            for r in assigned:
                by_pin.setdefault(r.pin_designator, []).append(r)
            sorted_pins = sorted(
                by_pin.keys(),
                key=natural_sort_key,
                reverse=descending,
            )
            sorted_assigned: list[SignalRow] = []
            for p_key in sorted_pins:
                group = sorted(
                    by_pin[p_key],
                    key=lambda r: natural_sort_key(r.signal_name),
                )
                sorted_assigned.extend(group)
            sorted_unassigned = sorted(
                unassigned,
                key=lambda r: natural_sort_key(r.signal_name),
            )
        elif column == "signal":
            by_sig: dict[str, list[SignalRow]] = {}
            for r in assigned:
                by_sig.setdefault(r.signal_name, []).append(r)
            sorted_sigs = sorted(
                by_sig.keys(),
                key=natural_sort_key,
                reverse=descending,
            )
            sorted_assigned = []
            for s_key in sorted_sigs:
                group = sorted(
                    by_sig[s_key],
                    key=lambda r: (
                        natural_sort_key(r.pin_designator),
                        natural_sort_key(r.signal_name),
                    ),
                )
                sorted_assigned.extend(group)
            sorted_unassigned = sorted(
                unassigned,
                key=lambda r: natural_sort_key(r.signal_name),
                reverse=descending,
            )
        else:  # 'signal_type'
            by_type: dict[str, list[SignalRow]] = {}
            for r in assigned:
                by_type.setdefault(sig_type_of(r), []).append(r)
            sorted_types = sorted(
                by_type.keys(),
                key=natural_sort_key,
                reverse=descending,
            )
            sorted_assigned = []
            for t_key in sorted_types:
                group = sorted(
                    by_type[t_key],
                    key=lambda r: (
                        natural_sort_key(r.pin_designator),
                        natural_sort_key(r.signal_name),
                    ),
                )
                sorted_assigned.extend(group)

            by_u_type: dict[str, list[SignalRow]] = {}
            for r in unassigned:
                by_u_type.setdefault(sig_type_of(r), []).append(r)
            sorted_u_types = sorted(
                by_u_type.keys(),
                key=natural_sort_key,
                reverse=descending,
            )
            sorted_unassigned = []
            for t_key in sorted_u_types:
                group = sorted(
                    by_u_type[t_key],
                    key=lambda r: natural_sort_key(r.signal_name),
                )
                sorted_unassigned.extend(group)

        self.rows = sorted_assigned + sorted_unassigned

    def pin_to_row_indices(self) -> dict[str, list[int]]:
        """핀 번호별 할당된 신호표 행 인덱스 목록 반환."""
        mapping: dict[str, list[int]] = {}
        for idx, row in enumerate(self.rows):
            pin = row.pin_designator.strip()
            if pin:
                mapping.setdefault(pin, []).append(idx)
        return mapping

    def duplicate_pins(self) -> dict[str, list[int]]:
        """같은 핀 번호가 2개 이상의 행에 중복 할당된 핀 번호와 행 인덱스 목록."""
        return {
            pin: indices
            for pin, indices in self.pin_to_row_indices().items()
            if len(indices) > 1
        }

    def duplicate_row_indices(self) -> set[int]:
        """중복 할당된 모든 신호표 행의 인덱스 집합."""
        dup_rows: set[int] = set()
        for indices in self.duplicate_pins().values():
            dup_rows.update(indices)
        return dup_rows

    def duplicate_pin_count(self) -> int:
        """이 연결기의 중복된 핀 개수 (중복 핀 1개를 경고 1건으로 집계)."""
        return len(self.duplicate_pins())

    def first_row_index_for_pin(self, pin_designator: str) -> int | None:
        """특정 핀(중복 핀 포함)을 선택했을 때 현재 정렬 순서에서 첫 번째 행의 인덱스."""
        cleaned = pin_designator.strip()
        for idx, row in enumerate(self.rows):
            if row.pin_designator == cleaned:
                return idx
        return None

    def pins_for_signal(self, signal_name: str) -> set[str]:
        """특정 신호가 할당된 모든 핀 번호 집합."""
        norm = normalize_signal_name(signal_name)
        return {
            row.pin_designator
            for row in self.rows
            if row.signal_name == norm and row.pin_designator
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.designator,
            "designator": self.designator,
            "part_uuid": self.part_uuid,
            "flip_horizontal": bool(self.flip_horizontal),
            "signals": [s.to_dict() for s in self.signals.values()],
            "rows": [r.to_dict() for r in self.rows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectorInstance:
        if not isinstance(data, dict):
            raise ProjectFormatError("연결기 데이터가 올바른 객체 형식이 아닙니다.")
        raw_id = str(
            data.get("connector_id", data.get("designator", ""))
        ).strip()
        if not raw_id:
            raise ProjectFormatError("연결기 식별자가 누락되었습니다.")
        conn_id = normalize_signal_name(raw_id)

        signals: dict[str, SignalDefinition] = {}
        for s_data in data.get("signals", []):
            sig = SignalDefinition.from_dict(s_data)
            if sig.name:
                signals[sig.name] = sig

        rows: list[SignalRow] = []
        for r_data in data.get("rows", []):
            row = SignalRow.from_dict(r_data)
            if row.signal_name:
                if row.signal_name not in signals:
                    signals[row.signal_name] = SignalDefinition(
                        name=row.signal_name
                    )
                rows.append(row)

        inst = cls(
            designator=conn_id,
            part_uuid=data.get("part_uuid") or None,
            flip_horizontal=bool(data.get("flip_horizontal", False)),
            signals=signals,
            rows=rows,
        )
        # 신호 중복은 유지하되 미할당 행 규칙을 보장하고 초기 정렬(핀 번호 오름차순) 수행
        inst.enforce_row_rules()
        inst.sort_rows("pin", descending=False)
        return inst


@dataclass
class Project:
    """전연결기 프로젝트 모델 (.jnc, schema_version 관리)."""

    name: str = "새 프로젝트"
    connectors: list[ConnectorInstance] = field(default_factory=list)
    parts: dict[str, ConnectorPart] = field(default_factory=dict)
    signal_types: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_SIGNAL_TYPES)
    )

    @property
    def categories(self) -> dict[str, str]:
        return self.signal_types

    @categories.setter
    def categories(self, value: dict[str, str]) -> None:
        self.signal_types = value

    def sorted_connectors(self) -> list[ConnectorInstance]:
        """사이드바 표시용 연결기 식별자 자연 정렬 목록 (제3.1절)."""
        return sorted(
            self.connectors,
            key=lambda c: natural_sort_key(c.designator),
        )

    def connector_designators(self) -> list[str]:
        return [c.designator for c in self.sorted_connectors()]

    def get_connector(self, designator: str) -> ConnectorInstance | None:
        if not designator.strip():
            return None
        target = normalize_signal_name(designator)
        for conn in self.connectors:
            if normalize_signal_name(conn.designator) == target:
                return conn
        return None

    def get_part_for_connector(
        self, connector: ConnectorInstance
    ) -> ConnectorPart | None:
        if not connector.part_uuid:
            return None
        return self.parts.get(connector.part_uuid)

    def add_connector(
        self,
        designator: str,
        part: ConnectorPart | None = None,
    ) -> ConnectorInstance:
        if not is_valid_signal_name(designator):
            raise ValueError(
                "연결기 식별자는 영문자로 시작하고 영문 대문자·숫자·언더스코어(_)만 사용할 수 있습니다(32자 이하)."
            )
        cleaned = normalize_signal_name(designator)
        if self.get_connector(cleaned) is not None:
            raise ValueError(f"이미 존재하는 연결기 식별자입니다: {cleaned}")

        part_uuid: str | None = None
        if part is not None:
            self.parts[part.uuid] = part.clone()
            part_uuid = part.uuid

        conn = ConnectorInstance(designator=cleaned, part_uuid=part_uuid)
        self.connectors.append(conn)
        self.connectors.sort(key=lambda c: natural_sort_key(c.designator))
        return conn

    def rename_connector(self, old_designator: str, new_designator: str) -> bool:
        """연결기 식별자 변경 (제3.1절: 문자 규칙 검증 및 자연 정렬 유지)."""
        conn = self.get_connector(old_designator)
        if conn is None or not is_valid_signal_name(new_designator):
            return False
        cleaned_new = normalize_signal_name(new_designator)
        existing = self.get_connector(cleaned_new)
        if existing is not None and existing is not conn:
            return False
        conn.designator = cleaned_new
        self.connectors.sort(key=lambda c: natural_sort_key(c.designator))
        return True

    def remove_connector(self, designator: str) -> bool:
        """프로젝트에서 연결기를 제거한다. 부품 데이터베이스의 원본 부품은 유지된다."""
        conn = self.get_connector(designator)
        if conn is None:
            return False
        self.connectors.remove(conn)
        return True

    def change_connector_part(
        self,
        designator: str,
        new_part: ConnectorPart | None,
    ) -> bool:
        """연결기의 부품을 교체하고 기존 핀 할당을 모두 해제한다 (제3.11절)."""
        conn = self.get_connector(designator)
        if conn is None:
            return False
        if new_part is not None:
            self.parts[new_part.uuid] = new_part.clone()
            conn.replace_part(new_part.uuid)
        else:
            conn.replace_part(None)
        return True

    def preview_part_sync_impact(
        self, updated_part: ConnectorPart
    ) -> list[tuple[str, str, str]]:
        """같은 UUID 부품의 변경으로 인해 할당 해제될 (연결기 식별자, 핀 번호, 신호명) 목록을 계산한다 (제3.3절)."""
        valid_pins = {p.designator for p in updated_part.pins}
        impacted: list[tuple[str, str, str]] = []
        for conn in self.connectors:
            if conn.part_uuid != updated_part.uuid:
                continue
            for row in conn.rows:
                if row.pin_designator and row.pin_designator not in valid_pins:
                    impacted.append(
                        (conn.designator, row.pin_designator, row.signal_name)
                    )
        return impacted

    def sync_part_definition(
        self, updated_part: ConnectorPart
    ) -> list[tuple[str, str, str]]:
        """같은 UUID 부품의 정의 변경을 프로젝트 사본과 모든 사용 연결기에 반영한다 (제3.3절)."""
        self.parts[updated_part.uuid] = updated_part.clone()
        impacted: list[tuple[str, str, str]] = []
        for conn in self.connectors:
            if conn.part_uuid == updated_part.uuid:
                unassigned = conn.apply_same_uuid_part_update(updated_part)
                for pin_des, sig_name in unassigned:
                    impacted.append((conn.designator, pin_des, sig_name))
        return impacted

    def ensure_signal_type(self, type_name: str, default_color: str = "") -> str:
        """목록에 없는 신호유형이면 새 신호유형으로 추가한다 (제3.10절: 새로 만들 때 색상은 '없음')."""
        cleaned = type_name.strip()
        if not cleaned or cleaned in ("없음", "(없음)"):
            return ""
        if not is_valid_signal_type_name(cleaned):
            raise ValueError(
                "신호유형 이름은 영문자 또는 한글로 시작하고 영문 대문자·한글·숫자·언더스코어(_)만 사용할 수 있습니다(32자 이하)."
            )
        norm = normalize_signal_type_name(cleaned)
        if norm not in self.signal_types:
            self.signal_types[norm] = default_color.strip()
        return norm

    def ensure_category(self, category_name: str) -> str:
        """ensure_signal_type의 호환 별칭."""
        return self.ensure_signal_type(category_name)

    def rename_signal_type(self, old_name: str, new_name: str) -> bool:
        """신호유형 이름을 변경하고 사용하던 모든 신호가 바뀐 이름을 따라가게 한다 (제3.10절)."""
        norm_old = normalize_signal_type_name(old_name)
        if norm_old not in self.signal_types or not is_valid_signal_type_name(
            new_name
        ):
            return False
        norm_new = normalize_signal_type_name(new_name)
        if norm_old == norm_new:
            return True
        if norm_new in self.signal_types:
            return False
        color = self.signal_types.pop(norm_old)
        self.signal_types[norm_new] = color
        for conn in self.connectors:
            for sig in conn.signals.values():
                if sig.signal_type == norm_old:
                    sig.signal_type = norm_new
        return True

    def set_signal_type_color(self, type_name: str, color: str) -> bool:
        """신호유형의 색상을 변경하거나 '없음'("")으로 설정한다."""
        norm = normalize_signal_type_name(type_name)
        if norm not in self.signal_types:
            return False
        cleaned = color.strip()
        if cleaned in ("없음", "(없음)"):
            cleaned = ""
        self.signal_types[norm] = cleaned
        return True

    def delete_signal_type(self, type_name: str) -> bool:
        """신호유형을 삭제하고 사용하던 모든 신호를 '신호유형 없음'("")으로 만든다 (제3.10절)."""
        norm = normalize_signal_type_name(type_name)
        if norm not in self.signal_types:
            return False
        del self.signal_types[norm]
        for conn in self.connectors:
            for sig in conn.signals.values():
                if sig.signal_type == norm:
                    sig.signal_type = ""
        return True

    def signal_type_color(self, type_name: str) -> str:
        if not type_name:
            return ""
        norm = normalize_signal_type_name(type_name)
        return self.signal_types.get(norm, "")

    def category_color(self, category_name: str) -> str:
        """signal_type_color 호환 별칭 (색상이 '없음'이면 빈 문자열 또는 흰색 처리)."""
        return self.signal_type_color(category_name)

    def effective_signal_color(
        self, connector: ConnectorInstance, signal_name: str
    ) -> str:
        """핀 색상 결정 순서 (제3.4절):
        1. 신호의 개별 색상
        2. 신호유형의 색상
        3. 할당되었지만 두 색상이 모두 '없음'이면 흰색(#ffffff) 채움
        """
        sig = connector.get_signal(signal_name)
        if sig is None:
            return UNASSIGNED_PIN_COLOR
        if sig.color:
            return sig.color
        type_color = self.signal_type_color(sig.signal_type)
        if type_color:
            return type_color
        return NO_COLOR_PIN_FILL

    def total_duplicate_pin_warnings(self) -> int:
        """프로젝트 전체의 신호 중복 경고 수 (중복된 핀 1개를 경고 1건으로 집계, 제3.12절)."""
        return sum(c.duplicate_pin_count() for c in self.connectors)

    def total_unassigned_signal_rows(self) -> int:
        """프로젝트 전체의 미할당 신호 행 수 (정보 수준 표시용)."""
        return sum(
            sum(1 for r in c.rows if not r.pin_designator)
            for c in self.connectors
        )

    def to_dict(self) -> dict[str, Any]:
        used_uuids = {
            c.part_uuid for c in self.connectors if c.part_uuid is not None
        }
        used_parts: dict[str, Any] = {}
        for part_uuid, part in self.parts.items():
            if not used_uuids or part_uuid in used_uuids or part_uuid in self.parts:
                used_parts[part_uuid] = part.to_dict()
        return {
            "schema_version": SCHEMA_VERSION,
            "format": "jeonnector-project",
            "name": self.name,
            "signal_types": dict(self.signal_types),
            "parts": used_parts,
            "connectors": [c.to_dict() for c in self.sorted_connectors()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        if not isinstance(data, dict):
            raise ProjectFormatError("프로젝트 파일 형식이 올바르지 않습니다.")

        version = data.get("schema_version", data.get("version"))
        if version is None or not isinstance(version, int) or version < 1:
            raise ProjectFormatError("프로젝트 파일에 유효한 schema_version이 없습니다.")
        if version > SCHEMA_VERSION:
            raise ProjectFormatError(
                f"현재 버전에서 지원하지 않는 상위 schema_version({version}) 파일입니다."
            )

        raw_types = data.get("signal_types", data.get("categories"))
        if raw_types is None or not isinstance(raw_types, dict):
            signal_types = dict(DEFAULT_SIGNAL_TYPES)
        else:
            signal_types = {}
            for k, v in raw_types.items():
                norm_k = normalize_signal_type_name(str(k))
                if norm_k:
                    signal_types[norm_k] = str(v or "").strip()

        parts: dict[str, ConnectorPart] = {}
        raw_parts = data.get("parts", {})
        if isinstance(raw_parts, dict):
            for p_uuid, p_data in raw_parts.items():
                part = ConnectorPart.from_dict(p_data)
                parts[p_uuid] = part
        elif isinstance(raw_parts, list):
            for p_data in raw_parts:
                part = ConnectorPart.from_dict(p_data)
                parts[part.uuid] = part
        else:
            raise ProjectFormatError("프로젝트의 부품 사본 데이터가 손상되었습니다.")

        raw_connectors = data.get("connectors", [])
        if not isinstance(raw_connectors, list):
            raise ProjectFormatError("프로젝트의 연결기 목록 데이터가 손상되었습니다.")

        connectors = [
            ConnectorInstance.from_dict(c_data) for c_data in raw_connectors
        ]
        project = cls(
            name=str(data.get("name", "새 프로젝트")),
            connectors=connectors,
            parts=parts,
            signal_types=signal_types,
        )
        project.connectors.sort(key=lambda c: natural_sort_key(c.designator))
        for conn in project.connectors:
            for sig in conn.signals.values():
                if sig.signal_type and sig.signal_type not in project.signal_types:
                    project.signal_types[sig.signal_type] = ""
        return project
