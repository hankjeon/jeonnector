"""전연결기(jeonnector) 데이터 모델, 이름·행 규칙, 부품 동기화, 기본 부품 27종 및 .jnc 저장소 단위 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jeonnector.default_parts import (
    create_default_parts,
    generate_circular_pins,
    generate_grid_pins,
)
from jeonnector.model import (
    NO_COLOR_PIN_FILL,
    SCHEMA_VERSION,
    ConnectorPart,
    PinDefinition,
    Project,
    ProjectFormatError,
    display_pin_x,
    is_valid_pin_number_format,
    is_valid_signal_name,
    is_valid_signal_type_name,
)
from jeonnector.storage import (
    PartLibrary,
    export_parts,
    load_project,
    read_parts_file,
    save_project,
)


def test_default_27_parts_and_restore(tmp_path: Path) -> None:
    """기본 제공 연결기 27종 구성 및 기본 부품 복원 기능 검증 (제4.6절)."""
    parts = create_default_parts()
    assert len(parts) == 27

    families: dict[str, int] = {}
    for part in parts:
        families[part.family] = families.get(part.family, 0) + 1
        assert part.pin_count == len(part.pins)
        assert part.pin_count > 0
        assert len(part.graphics) >= 1

    assert families["D-SUB SD"] == 5
    assert families["D-SUB HD"] == 5
    assert families["D38999 Series IV"] == 8
    assert families["Micro-D"] == 9

    lib = PartLibrary(storage_path=tmp_path / "lib.json")
    first_uuid = parts[0].uuid
    lib.delete_part(first_uuid)
    assert lib.get_part(first_uuid) is None

    lib.restore_default_parts()
    assert lib.get_part(first_uuid) is not None
    assert len(lib.list_parts()) == 27


def test_default_parts_share_pin_proportion_and_outline_margin() -> None:
    """기본 부품은 핀 간격·지름이 같고 외곽선이 핀 배열에서 일정 여백을 둔다 (제4.6절)."""
    for part in create_default_parts():
        assert part.pin_size == pytest.approx(16.0)
        assert part.min_pin_distance() == pytest.approx(40.0, abs=0.05)
        outline = part.graphics[0]
        if outline.type == "CIRCLE":
            g = outline.geometry
            farthest = max(
                ((p.x - g["cx"]) ** 2 + (p.y - g["cy"]) ** 2) ** 0.5 for p in part.pins
            )
            assert g["radius"] - farthest == pytest.approx(30.0, abs=0.05)
            assert part.width == pytest.approx(2 * (g["radius"] + 12.0), abs=0.05)
        else:
            xs = [x for x, _ in outline.geometry["points"]]
            ys = [y for _, y in outline.geometry["points"]]
            assert min(p.x for p in part.pins) - min(xs) == pytest.approx(30.0)
            assert max(ys) - max(p.y for p in part.pins) == pytest.approx(32.0, abs=0.05)
            assert part.width == pytest.approx(max(xs) + 12.0, abs=0.05)


def test_naming_and_pin_number_rules() -> None:
    """신호명·연결기 식별자, 신호유형 이름, 핀 번호 문자 규칙 및 대소문자 구분 검증 (제3.1, 3.6, 3.9, 3.10절)."""
    # 신호명 규칙: 영문자 시작, 영문 대문자·숫자·_, 대소문자 정규화, 32자 이하
    assert is_valid_signal_name("gnd")
    assert is_valid_signal_name("CLK_100M_P")
    assert not is_valid_signal_name("12V_PWR")
    assert not is_valid_signal_name("SIG+5V")
    assert not is_valid_signal_name("전원신호")
    assert not is_valid_signal_name("A" * 33)

    # 신호유형 이름 규칙: 한글 허용, 공백 불가, 32자 이하
    assert is_valid_signal_type_name("고속차동_LVDS")
    assert is_valid_signal_type_name("pwr_rail")
    assert not is_valid_signal_type_name("고속 차동")
    assert not is_valid_signal_type_name("1순위전원")

    # 핀 번호 규칙: 공백 불가, 대소문자 구분, 자연 정렬(A2 < A10, A < a)
    assert is_valid_pin_number_format("A1")
    assert is_valid_pin_number_format("a1")
    assert not is_valid_pin_number_format("A 1")
    assert not is_valid_pin_number_format(" 1")

    part = ConnectorPart(
        uuid="part-case",
        family="Test",
        variant="CasePin",
        pins=[
            PinDefinition(designator="A10", x=10, y=10),
            PinDefinition(designator="a", x=20, y=10),
            PinDefinition(designator="A2", x=30, y=10),
            PinDefinition(designator="A", x=40, y=10),
        ],
    )
    assert part.has_pin("A")
    assert part.has_pin("a")
    assert not part.has_pin("b")
    assert part.pin_designators() == ["A", "A2", "A10", "a"]


def test_signal_row_rules_and_row_level_rename() -> None:
    """제3.6절 행 규칙, 행 단위 신호명 변경, 핀 색상 결정 순서 및 부품 교체 규칙 검증."""
    project = Project(name="테스트")
    custom_part = ConnectorPart(
        uuid="part-alpha-1",
        family="Custom",
        variant="Alpha 4P",
        width=120.0,
        height=80.0,
        pins=[
            PinDefinition(designator="1", x=20.0, y=40.0, display_order=1),
            PinDefinition(designator="2", x=40.0, y=40.0, display_order=2),
            PinDefinition(designator="A1", x=60.0, y=40.0, display_order=3),
            PinDefinition(designator="B", x=80.0, y=40.0, display_order=4),
        ],
    )

    # 1. 부품 없는 연결기에서 신호 작성 가능, 핀 번호 할당은 거부
    conn_empty = project.add_connector("J_EMPTY", None)
    assert conn_empty.add_or_update_row_signal(0, "pwr_5v")
    assert conn_empty.rows[0].signal_name == "PWR_5V"
    assert not conn_empty.set_row_pin(0, "1", None)

    # 2. 신호 생성 시 기본 신호유형과 색상은 '없음'("")이고 핀 채움색은 흰색(#ffffff)
    conn = project.add_connector("J1", custom_part)
    part = project.get_part_for_connector(conn)
    assert part is not None

    assert conn.add_or_update_row_signal(0, "gnd")
    assert conn.get_signal("GND").signal_type == ""
    assert conn.get_signal("GND").color == ""
    assert project.effective_signal_color(conn, "GND") == NO_COLOR_PIN_FILL

    # GND를 3개 핀(1, 2, A1)에 할당
    assert conn.set_row_pin(0, "1", part)
    assert conn.add_or_update_row_signal(1, "GND")
    assert conn.set_row_pin(1, "2", part)
    assert conn.add_or_update_row_signal(2, "GND")
    assert conn.set_row_pin(2, "A1", part)
    assert len(conn.rows) == 3

    # 3. 제3.6절 신호명 편집: 한 행의 신호명을 바꾸면 그 행만 다른 신호(GROUND)가 되고 다른 두 행은 GND로 유지
    assert conn.add_or_update_row_signal(1, "ground")
    assert conn.rows[0].signal_name == "GND"
    assert conn.rows[1].signal_name == "GROUND"
    assert conn.rows[2].signal_name == "GND"
    assert "GROUND" in conn.signals

    # 4. 제3.6절 행 규칙:
    # - 여러 핀에 할당된 신호(GND: 1, A1)의 한 핀(A1)을 해제하면 그 행은 사라짐
    assert conn.set_row_pin(2, "미할당", part)
    assert len(conn.rows) == 2
    assert conn.pins_for_signal("GND") == {"1"}

    # - 신호의 마지막 핀(GND: 1)이 해제되면 미할당 행 하나로 남음
    assert conn.set_row_pin(0, "", part)
    gnd_rows = [r for r in conn.rows if r.signal_name == "GND"]
    assert len(gnd_rows) == 1
    assert gnd_rows[0].pin_designator == ""

    # 5. 신호유형 추가 시 기본 색상은 '없음'("") (제3.10절)
    new_type = project.ensure_signal_type("고속차동")
    assert new_type == "고속차동"
    assert project.signal_type_color("고속차동") == ""

    # 신호유형 이름 변경 및 삭제 시 신호 반영 확인 (제3.10절)
    conn.set_signal_type("GROUND", "고속차동")
    assert project.rename_signal_type("고속차동", "초고속차동")
    assert conn.get_signal("GROUND").signal_type == "초고속차동"
    assert project.delete_signal_type("초고속차동")
    assert conn.get_signal("GROUND").signal_type == ""

    # 6. 좌우 반전은 표시 좌표만 반전하고 할당은 유지
    conn.flip_horizontal = True
    assert display_pin_x(20.0, 120.0, True) == 100.0

    # 7. 부품 교체 시 각 신호는 미할당 행 하나로 합쳐짐 (제3.11절)
    other_part = create_default_parts()[0]
    project.change_connector_part("J1", other_part)
    assert all(r.pin_designator == "" for r in conn.rows)
    assert {r.signal_name for r in conn.rows} == {"GND", "GROUND"}
    assert len(conn.rows) == 2


def test_pinmap_context_assign_and_sorting_and_part_sync() -> None:
    """제3.7절 핀맵 할당·교체·해제, 제3.6절 정렬, 제3.3절 같은 UUID 부품 변경 동기화 검증."""
    part = create_default_parts()[0]  # D-SUB SD 9핀
    project = Project(name="핀맵할당검증")
    conn = project.add_connector("J1", part)

    conn.add_or_update_row_signal(0, "SIG_ONLY_3")
    conn.set_row_pin(0, "3", part)
    conn.add_or_update_row_signal(1, "SIG_MULTI")
    conn.set_row_pin(1, "1", part)
    conn.add_or_update_row_signal(2, "SIG_MULTI")
    conn.set_row_pin(2, "3", part)  # 3번 핀에 SIG_ONLY_3과 SIG_MULTI가 중복 할당됨
    conn.add_or_update_row_signal(3, "SIG_NEW")

    assert conn.duplicate_pin_count() == 1

    # 3번 핀에 SIG_NEW를 핀맵 우클릭으로 할당하면:
    # - 3번 핀에만 있던 SIG_ONLY_3은 미할당 행 1개로 남고
    # - 1번 핀에도 있던 SIG_MULTI는 3번 핀 행이 사라지고 1번 핀 행만 남으며
    # - SIG_NEW가 3번 핀에 할당되어 중복이 해소됨
    assert conn.assign_signal_from_pinmap("3", "SIG_NEW", part)
    assert conn.duplicate_pin_count() == 0
    assert conn.pins_for_signal("SIG_NEW") == {"3"}
    assert conn.pins_for_signal("SIG_MULTI") == {"1"}
    assert conn.pins_for_signal("SIG_ONLY_3") == set()
    assert conn.row_usage_count("SIG_ONLY_3") == 1

    # 정렬 검증: 미할당 행(SIG_ONLY_3)은 내림차순 정렬에서도 항상 할당 행 뒤에 위치
    conn.sort_rows("pin", descending=True)
    assert [r.pin_designator for r in conn.rows] == ["3", "1", ""]

    # 같은 UUID 부품 정의 변경(3번 핀 삭제, 1번 핀 좌표 이동) 동기화 검증 (제3.3절)
    modified_part = part.clone()
    modified_part.pins = [p for p in modified_part.pins if p.designator != "3"]
    modified_part.pins[0].x += 5.0

    impact = project.preview_part_sync_impact(modified_part)
    assert impact == [("J1", "3", "SIG_NEW")]
    project.sync_part_definition(modified_part)
    assert conn.pins_for_signal("SIG_MULTI") == {"1"}
    assert conn.pins_for_signal("SIG_NEW") == set()


def test_duplicate_pins_and_jnc_schema_validation(tmp_path: Path) -> None:
    """신호 중복 상태 .jnc 저장·복원 및 상위 schema_version/손상 파일 거부 검증 (제3.2절)."""
    part = create_default_parts()[0]
    project = Project(name="중복검증")
    conn = project.add_connector("J1", part)

    conn.add_or_update_row_signal(0, "SIG_B")
    conn.add_or_update_row_signal(1, "SIG_A")
    conn.set_row_pin(0, "3", part)
    conn.set_row_pin(1, "3", part)

    save_file = tmp_path / "dup_project.jnc"
    save_project(project, save_file)

    raw_data = json.loads(save_file.read_text(encoding="utf-8"))
    assert raw_data["schema_version"] == SCHEMA_VERSION

    loaded = load_project(save_file)
    loaded_conn = loaded.get_connector("J1")
    assert loaded_conn is not None
    assert loaded.total_duplicate_pin_warnings() == 1
    # 초기 로드 시 핀 번호 오름차순 + 같은 핀 내 신호명 오름차순(SIG_A, SIG_B) 정렬 확인
    assert loaded_conn.rows[0].signal_name == "SIG_A"
    assert loaded_conn.first_row_index_for_pin("3") == 0

    # 상위 schema_version 파일 열기 거부 확인
    future_file = tmp_path / "future.jnc"
    raw_data["schema_version"] = SCHEMA_VERSION + 1
    future_file.write_text(json.dumps(raw_data), encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        load_project(future_file)

    # 손상된 파일 열기 거부 확인
    corrupt_file = tmp_path / "corrupt.jnc"
    corrupt_file.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        load_project(corrupt_file)


def test_part_library_import_export_and_conflict(tmp_path: Path) -> None:
    """부품 데이터베이스 내보내기·가져오기 및 동일 UUID/동일 이름 충돌 처리 검증 (제4.4절)."""
    lib_path = tmp_path / "library.json"
    lib = PartLibrary(storage_path=lib_path)
    assert len(lib.list_parts()) == 27

    target_part = lib.list_parts()[0].clone()
    target_part.description = "수정된 설명"
    export_file = tmp_path / "exported_parts.json"
    export_parts([target_part], export_file)

    incoming = read_parts_file(export_file)
    assert len(incoming) == 1

    # 1. 같은 UUID 덮어쓰기 선택 시 기존 UUID 유지 및 내용 갱신
    lib.import_parts(
        incoming,
        conflict_resolver=lambda existing, inc: ("overwrite", None),
    )
    updated = lib.get_part(target_part.uuid)
    assert updated is not None
    assert updated.description == "수정된 설명"
    assert len(lib.list_parts()) == 27

    # 2. 이름을 바꾸어 추가 선택 시 새 UUID 발급 및 부품 추가
    lib.import_parts(
        incoming,
        conflict_resolver=lambda existing, inc: ("rename", "9핀_커스텀복제"),
    )
    assert len(lib.list_parts()) == 28
    renamed = lib.find_by_name(f"{target_part.family} - 9핀_커스텀복제")
    assert renamed is not None
    assert renamed.uuid != target_part.uuid


def test_auto_placement_generators() -> None:
    """바둑판 및 원형 자동 배치 핀 생성기 검증."""
    grid_pins = generate_grid_pins(
        row_counts=[5, 4],
        pitch_x=20.0,
        pitch_y=25.0,
        center_x=100.0,
        center_y=60.0,
        stagger_odd_rows=True,
    )
    assert len(grid_pins) == 9
    assert grid_pins[0].designator == "1"
    assert grid_pins[-1].designator == "9"

    circ_pins = generate_circular_pins(
        pin_count=8,
        radius=50.0,
        center_x=100.0,
        center_y=100.0,
        include_center_pin=True,
        prefix="A",
    )
    assert len(circ_pins) == 8
    assert circ_pins[0].designator == "A1"
    assert circ_pins[-1].x == 100.0
    assert circ_pins[-1].y == 100.0


def test_row_rename_copies_or_follows_signal_attributes() -> None:
    """행 신호명 변경: 새 이름은 이전 신호 속성을 복사하고, 기존 이름은 그 신호 속성을 따른다 (제3.6절)."""
    project = Project(name="이름변경")
    part = create_default_parts()[0]
    conn = project.add_connector("J1", part)
    assert conn.add_signal_row("GDN", "1", part, "GROUND", "#111111")
    assert conn.add_signal_row("GDN", "2", part)
    assert conn.add_signal_row("VCC", "3", part, "POWER", "")

    gdn_row = next(i for i, r in enumerate(conn.rows) if r.pin_designator == "1")
    assert conn.add_or_update_row_signal(gdn_row, "GND")
    gnd = conn.get_signal("GND")
    assert (gnd.signal_type, gnd.color) == ("GROUND", "#111111")
    old = conn.get_signal("GDN")
    assert (old.signal_type, old.color) == ("GROUND", "#111111")  # 복사이며 이전 신호는 유지

    vcc_row = next(i for i, r in enumerate(conn.rows) if r.signal_name == "VCC")
    assert conn.add_or_update_row_signal(vcc_row, "GND")
    assert conn.get_signal("GND").signal_type == "GROUND"
    assert conn.get_signal("VCC") is None


def test_part_geometry_outline_area_and_grid_snap() -> None:
    """핀에 맞춘 외곽 생성, 격자를 유지하는 영역 맞춤, 스냅에 맞추기 계산 (제4.4~4.5절)."""
    from jeonnector.part_geometry import (
        fit_part_area,
        fitted_circle_outline,
        fitted_polygon_outline,
        snap_coord,
        snap_part_to_grid,
    )

    for default in create_default_parts():
        part = default.clone()
        assert fit_part_area(part) == (0.0, 0.0)
        assert (part.width, part.height) == pytest.approx((default.width, default.height))

    pins = [PinDefinition(designator=str(i), x=x, y=100.0) for i, x in enumerate((100.0, 140.0), 1)]
    part = ConnectorPart(uuid="u", family="F", variant="V", width=400.0, height=300.0, pins=pins)
    assert fitted_polygon_outline(part).geometry["points"] == [
        [70.0, 78.0], [170.0, 78.0], [170.0, 132.0], [70.0, 132.0]
    ]
    circle = fitted_circle_outline(part).geometry
    assert circle == {"cx": 120.0, "cy": 100.0, "radius": 50.0}

    # 내용에 거의 딱 맞게 줄이고, 중심을 그리드 간격의 배수만큼만 옮겨 격자에 맞춘 핀이 계속 격자 위에 있다.
    def on_grid(target: ConnectorPart) -> bool:
        cx, cy = target.width / 2, target.height / 2
        return all(
            (snap_coord(q.x, cx, 10.0), snap_coord(q.y, cy, 10.0)) == pytest.approx((q.x, q.y))
            for q in target.pins
        )

    assert on_grid(part)
    part.graphics = [fitted_polygon_outline(part)]
    fit_part_area(part, 10.0)
    assert (part.width, part.height) == pytest.approx((124.0, 88.0))  # 딱 맞으면 124×78
    assert on_grid(part)

    # 핀 간격을 좁히고 외곽 오른쪽만 당겨도 영역이 줄어든다 (중심 고정 대칭이면 244 그대로 남음).
    dsub = create_default_parts()[0].clone()
    x0 = min(q.x for q in dsub.pins)
    for q in dsub.pins:
        q.x = round(x0 + (q.x - x0) * 0.75, 2)
    pts = dsub.graphics[0].geometry["points"]
    right = max(q.x for q in dsub.pins) + 30.0
    pts[1][0], pts[2][0] = right, right - 18.0
    fit_part_area(dsub, 10.0)
    assert dsub.width == pytest.approx(204.0)

    part.pins[1].x += 3.0
    part.graphics[0].geometry["points"][0][0] += 4.0
    snapped, moved_pins, moved_outline = snap_part_to_grid(part, 10.0)
    assert moved_pins == 1 and moved_outline >= 1
    cx, cy = part.width / 2, part.height / 2
    assert all(snap_coord(p.x, cx, 10.0) == p.x for p in snapped.pins)
    assert all(
        (snap_coord(x, cx, 10.0), snap_coord(y, cy, 10.0)) == (x, y)
        for x, y in snapped.graphics[0].geometry["points"]
    )

    part.pins[1].x = part.pins[0].x + 4.0
    with pytest.raises(ValueError):
        snap_part_to_grid(part, 10.0)


def test_command_history_undo_redo_limit_and_saved_state() -> None:
    """편집 이력: 기록·실행 취소·다시 실행, 100단계 제한, 저장 시점 판정, 이름 유지 (제3.13절)."""
    from jeonnector.commands import CommandDispatcher

    project = Project(name="이력")
    part = create_default_parts()[0]
    commands = CommandDispatcher(lambda: project)
    assert not commands.can_undo() and commands.is_at_saved_state()
    assert not commands.record("변경 없음")

    commands.add_connector("J1", part)
    conn = project.get_connector("J1")
    conn.add_signal_row("GND", "1", part, "GROUND")
    assert commands.record("신호 추가", focus="J1")
    conn.flip_horizontal = True
    commands.record("좌우 반전", focus="J1")
    commands.mark_saved()
    project.name = "저장된 이름"

    step = commands.undo()
    assert step.description == "좌우 반전" and step.focus_before == "J1"
    assert project.get_connector("J1").flip_horizontal is False
    assert project.name == "저장된 이름"
    assert not commands.is_at_saved_state()
    commands.undo()
    assert not project.get_connector("J1").signals
    assert commands.redo_description() == "신호 추가"
    commands.redo()
    commands.redo()
    assert project.get_connector("J1").flip_horizontal is True
    assert commands.is_at_saved_state()

    # 새 편집을 기록하면 다시 실행 이력은 사라진다.
    commands.undo()
    project.get_connector("J1").signals["GND"].color = "#123456"
    commands.record("색상")
    assert not commands.can_redo()

    for i in range(120):
        project.get_connector("J1").signals["GND"].color = f"#0000{i:02x}"
        commands.record(f"색상 {i}")
    assert commands.history_count == 100

    removed = CommandDispatcher(lambda: project)
    removed.remove_connector("J1")
    assert removed.undo().focus_before == "J1"
    assert project.get_connector("J1") is not None


def test_state_history_undo_redo_and_limit() -> None:
    """부품 편집기용 상태 이력: 기록·되돌리기·다시 실행·100단계 제한 (제3.13절)."""
    from jeonnector.commands import StateHistory

    history = StateHistory({"v": 0})
    assert not history.record("같음", {"v": 0})
    history.record("하나", {"v": 1})
    history.record("둘", {"v": 2})
    assert history.undo() == ("둘", {"v": 1})
    assert history.redo_description() == "둘"
    assert history.undo() == ("하나", {"v": 0})
    assert history.undo() is None
    assert history.redo() == ("하나", {"v": 1})
    history.record("셋", {"v": 3})
    assert not history.can_redo()
    for i in range(150):
        history.record(f"{i}", {"v": 100 + i})
    assert history.history_count == 100


def test_default_signal_types_for_new_project() -> None:
    """새 프로젝트의 기본 신호유형 5종과 색상 (제6.1절). 기존 프로젝트는 저장된 목록을 유지한다."""
    assert Project().signal_types == {
        "POWER": "#dc2626",
        "GROUND": "#8b5a2b",
        "CHASSIS": "#4b5563",
        "ANALOG": "#16a34a",
        "DISCRETE": "#2563eb",
    }
    old = Project.from_dict({"schema_version": 1, "signal_types": {"전원": "#ef4444"}})
    assert old.signal_types == {"전원": "#ef4444"}
