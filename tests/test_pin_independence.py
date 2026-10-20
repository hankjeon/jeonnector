"""확장 신호명과 부품에 독립적인 핀 번호 규칙 검증."""

import pytest

from jeonnector import model
from jeonnector.default_parts import create_default_parts
from jeonnector.model import Project, is_valid_signal_name, is_valid_signal_type_name
from jeonnector.storage import load_project, save_project


@pytest.mark.parametrize("name", [
    "+5v", "-12v", "485_TX", "DATA+", "DATA-", "RESET#", "RD/WR", "P1.0",
    "a_+-#/.", "1", " +5v ", "A" * 32,
])
def test_extended_signal_names(name):
    assert is_valid_signal_name(name)
    conn = Project().add_connector("J1")
    assert conn.add_signal_row(name, "", None)
    assert conn.rows[0].signal_name == name.strip().upper()


@pytest.mark.parametrize("name", [
    "", " ", "_A", "#A", "/A", ".A", "+-", "+_#/.", "A B", "A\tB", "전원",
    "A@B", "A|B", "A" * 33,
])
def test_invalid_extended_signal_names(name):
    assert not is_valid_signal_name(name)


def test_connector_identifier_rules_remain_independent():
    assert hasattr(model, "is_valid_connector_id")
    project = Project()
    conn = project.add_connector(" j1_a ")
    assert conn.designator == "J1_A"
    assert model.is_valid_connector_id(" j2_a ")
    for name in ("+5V", "-12V", "485_TX", "DATA+", "RESET#", "RD/WR", "P1.0"):
        assert not model.is_valid_connector_id(name)
        with pytest.raises(ValueError):
            project.add_connector(name)
        assert not project.rename_connector("J1_A", name)
        assert not is_valid_signal_type_name(name)
    assert project.rename_connector("J1_A", "j2")
    assert conn.designator == "J2"


@pytest.mark.parametrize("with_part", [False, True])
def test_pin_numbers_are_independent_of_part(with_part, tmp_path):
    project = Project()
    part = create_default_parts()[0] if with_part else None
    conn = project.add_connector("J1", part)
    for pin in ("A10", "a", "A2", "A"):
        assert conn.add_signal_row("+5V", pin, part, "POWER", "#123456")
    assert conn.add_signal_row("DATA+", "A", part)
    assert conn.add_signal_row("SPARE", "", part)
    assert conn.set_row_pin(1, "a1", part)
    assert conn.duplicate_pin_count() == 1
    for pin in ("A 1", " 1", "1 ", "\t1", "1\n"):
        before = conn.to_dict()
        assert not conn.add_signal_row("NEW", pin, part)
        assert not conn.set_row_pin(0, pin, part)
        assert conn.to_dict() == before
    path = tmp_path / "independent.jnc"
    save_project(project, path)
    loaded = load_project(path).get_connector("J1")
    assert loaded is not None
    assert [(r.signal_name, r.pin_designator) for r in loaded.rows] == [
        ("+5V", "A"), ("DATA+", "A"), ("+5V", "A2"), ("+5V", "A10"),
        ("+5V", "a1"), ("SPARE", ""),
    ]
    signal = loaded.get_signal("+5V")
    assert signal is not None and signal.color == "#123456"


def test_part_selection_replacement_and_detachment_preserve_rows():
    project = Project()
    conn = project.add_connector("J1")
    assert conn.add_signal_row("GND", "1", None, "GROUND", "#123456")
    assert conn.add_signal_row("GND", "A", None)
    assert conn.add_signal_row("SPARE", "", None)
    original = [(r.row_id, r.signal_name, r.pin_designator) for r in conn.rows]
    for part in (*create_default_parts()[:2], None):
        assert project.change_connector_part("J1", part)
        assert conn.part_uuid == (part.uuid if part else None)
        assert [(r.row_id, r.signal_name, r.pin_designator) for r in conn.rows] == original
        signal = conn.get_signal("GND")
        assert signal is not None and signal.color == "#123456"


def test_same_uuid_pin_removal_and_restore_preserve_rows():
    project = Project()
    part = create_default_parts()[0]
    conn = project.add_connector("J1", part)
    assert conn.add_signal_row("GND", "1", part)
    assert conn.add_signal_row("GND", "2", part)
    original = conn.to_dict()
    updated = part.clone()
    updated.pins = [p for p in updated.pins if p.designator != "2"]
    assert project.preview_part_sync_impact(updated) == [("J1", "2", "GND")]
    assert project.sync_part_definition(updated) == [("J1", "2", "GND")]
    assert conn.to_dict() == original
    assert project.sync_part_definition(part) == []
    assert conn.to_dict() == original


@pytest.mark.parametrize("with_part", [False, True])
def test_pinmap_rejects_nonphysical_pins(with_part):
    project = Project()
    part = create_default_parts()[0] if with_part else None
    conn = project.add_connector("J1", part)
    assert conn.add_signal_row("GND", "", part)
    before = conn.to_dict()
    assert not conn.assign_signal_from_pinmap("999", "GND", part)
    assert conn.to_dict() == before


def test_natural_sort_preserves_non_decimal_numeric_pin_names(tmp_path):
    project = Project()
    conn = project.add_connector("J1")
    for pin in ("A²", "①", "A10", "A2"):
        assert conn.add_signal_row("DATA", pin, None)
    conn.sort_rows("pin")
    assert [row.pin_designator for row in conn.rows] == ["A2", "A10", "A²", "①"]
    path = tmp_path / "numeric.jnc"
    save_project(project, path)
    assert load_project(path).get_connector("J1").to_dict() == conn.to_dict()
