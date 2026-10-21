"""마크다운 신호표 교환의 공개 계약 검증."""

from pathlib import Path

import pytest

from jeonnector.model import Project


def document(tmp_path: Path, text: str, name: str = "신호표.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_prepare_reads_signal_table_without_mutating_project(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    path = document(tmp_path, "- 식별자 : j7\n\n| 핀 번호 | 신호명 | 신호유형 | 색상 |\n| --- | --- | --- | --- |\n| 2 | `data` | power | #aBc123 |\n")
    project = Project()
    before = project.to_dict()
    [item] = prepare_markdown_import([path], project)
    assert item.path == path
    assert item.error == ""
    assert item.warnings == []
    assert item.connector.designator == "J7"
    assert item.connector.part_uuid is None
    assert item.connector.rows[0].pin_designator == "2"
    signal = item.connector.signals["DATA"]
    assert signal.signal_type == "POWER"
    assert signal.color.upper() == "#ABC123"
    assert project.to_dict() == before
    assert path.read_text(encoding="utf-8").startswith("- 식별자 : j7")


def test_only_real_signal_table_is_read_with_optional_reordered_columns(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = """\ufeff# 설명
```markdown
- 식별자 : BAD
| 신호명 |
| --- |
| BAD |
```
~~~
- 식별자 : BAD2
~~~
<!--
- 식별자 : BAD3
| 신호명 |
| --- |
| BAD3 |
-->
| 설명 | 값 |
| --- | --- |
| 용도 | 시험 |

- 식별자 : j3

| 추가 | 신호유형 | 신호명 |
| :--- | ---: | :---: |
| 설명 | analog | DATA |
| | | |
| 무시 | | `GND` |
"""
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.connector.designator == "J3"
    assert list(item.connector.signals) == ["DATA", "GND"]
    assert item.connector.signals["DATA"].signal_type == "ANALOG"
    assert all(not row.pin_designator for row in item.connector.rows)


@pytest.mark.parametrize("text, reason", [
    ("# 설명만 있습니다", "신호표"),
    ("| 신호명 |\n| --- |\n\n| 신호명 |\n| --- |", "여러"),
    ("- 식별자 : J1\n- 식별자 : J2\n| 신호명 |\n| --- |", "식별자"),
])
def test_document_structure_errors_are_reported_per_file(tmp_path, text, reason):
    from jeonnector.markdown_exchange import prepare_markdown_import

    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert reason in item.error


def test_unreadable_sources_do_not_abort_other_files(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    bad_encoding = tmp_path / "잘못된인코딩.md"
    bad_encoding.write_bytes(b"\xff\xfe")
    valid = document(tmp_path, "| 신호명 |\n| --- |")
    items = prepare_markdown_import([tmp_path / "없음.md", bad_encoding, tmp_path, valid], Project())
    assert all(item.error and item.connector is None for item in items[:3])
    assert items[3].error == ""
    assert items[3].connector.rows == []


@pytest.mark.parametrize("row, reason", [
    ("| | | POWER | |", "신호명"),
    ("| 1 | BAD NAME | | |", "신호명"),
    ("| 1 | _BAD | | |", "신호명"),
    ("| 1 | A | 2BAD | |", "신호유형"),
    ("| 1 | A | BAD TYPE | |", "신호유형"),
    ("| 1 | A | | red |", "색상"),
    ("| 1 | A | | #abc |", "색상"),
    ("| 1 | A | | #12345678 |", "색상"),
    ("| A B | A | | |", "핀 번호"),
    ("| 1 | A |", "열"),
])
def test_invalid_row_rejects_entire_file_with_source_line(tmp_path, row, reason):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "# 설명\n\n| 핀 번호 | 신호명 | 신호유형 | 색상 |\n| --- | --- | --- | --- |\n| 2 | VALID | | |\n" + row
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "신호표.md" in item.error
    assert "6행" in item.error
    assert reason in item.error


def test_extended_signal_names_use_model_rules(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    names = ["+5v", "-12v", "485_tx", "data+", "data-", "reset#", "rd/wr", "p1.0", "uart_tx"]
    text = "| 신호명 |\n| --- |\n" + "\n".join(f"| `{name}` |" for name in names)
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert list(item.connector.signals) == [name.upper() for name in names]


@pytest.mark.parametrize("identifier", ["1J", "J-1", "J 1", "J/1", "J.1", "J#1", "J" * 33, "`J 1`"])
def test_invalid_explicit_identifier_is_not_repaired(tmp_path, identifier):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = f"- 식별자 : {identifier}\n| 신호명 |\n| --- |"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "1행" in item.error
    assert "식별자" in item.error


def test_batch_reserves_explicit_ids_before_suffixes_and_automatic_numbers(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    project = Project()
    for identifier in ["J1", "X", "X_1"]:
        project.add_connector(identifier)
    paths = [document(tmp_path, f"- 식별자 : {identifier}\n| 신호명 |\n| --- |", f"{index}.md")
             for index, identifier in enumerate(["", " j2 ", "x", "X_2", "X", ""])]
    before = project.to_dict()
    items = prepare_markdown_import(paths, project)
    assert [item.path for item in items] == paths
    assert all(not item.error for item in items)
    assert [item.connector.designator for item in items] == ["J3", "J2", "X_3", "X_2", "X_4", "J4"]
    assert project.to_dict() == before


def test_suffix_overflow_is_an_error_without_truncation(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    identifier = "A" * 32
    project = Project()
    project.add_connector(identifier)
    text = f"- 식별자 : {identifier}\n| 신호명 |\n| --- |"
    [item] = prepare_markdown_import([document(tmp_path, text)], project)
    assert item.connector is None
    assert "32" in item.error
    assert identifier in item.error


def test_shared_signal_fills_empty_attributes_and_deduplicates_rows_with_warning(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = """| 핀 번호 | 신호명 | 신호유형 | 색상 |
| --- | --- | --- | --- |
| 1 | data | | #abc123 |
| 2 | `DATA` | analog | |
| 1 | DATA | ANALOG | #ABC123 |
| | DATA | | |
| | SPARE | | |
| | SPARE | | |
| 2 | OTHER | | |
"""
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert not item.error
    assert item.connector.signals["DATA"].signal_type == "ANALOG"
    assert item.connector.signals["DATA"].color.upper() == "#ABC123"
    assert [(r.signal_name, r.pin_designator) for r in item.connector.rows] == [
        ("DATA", "1"), ("DATA", "2"), ("SPARE", ""), ("OTHER", "2")]
    assert any("5행" in warning and "중복" in warning for warning in item.warnings)
    assert any("8행" in warning and "중복" in warning for warning in item.warnings)
    assert any("2" in warning and "신호 중복" in warning for warning in item.warnings)


@pytest.mark.parametrize("second_type, second_color, reason", [
    ("GROUND", "#123456", "신호유형"),
    ("POWER", "#654321", "색상"),
])
def test_conflicting_shared_attributes_reject_even_duplicate_pair(tmp_path, second_type, second_color, reason):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = ("| 핀 번호 | 신호명 | 신호유형 | 색상 |\n| --- | --- | --- | --- |\n"
            "| 1 | DATA | POWER | #123456 |\n"
            f"| 1 | data | {second_type} | {second_color} |")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "4행" in item.error
    assert reason in item.error
    assert "충돌" in item.error


def test_apply_registers_valid_items_reuses_types_and_copies_mutable_data(tmp_path):
    from jeonnector.markdown_exchange import apply_markdown_import, prepare_markdown_import

    project = Project(signal_types={"ANALOG": "#654321"})
    project.add_connector("J1")
    text = ("- 식별자 : J1\n| 핀 번호 | 신호명 | 신호유형 | 색상 |\n| --- | --- | --- | --- |\n"
            "| 1 | DATA | analog | #abc123 |\n| A2 | SPARE | 새유형 | |")
    paths = [document(tmp_path, text), document(tmp_path, "설명뿐", "오류.md")]
    items = prepare_markdown_import(paths, project)
    assert project.signal_types == {"ANALOG": "#654321"}
    assert apply_markdown_import(project, items) == ["J1_1"]
    assert project.signal_types == {"ANALOG": "#654321", "새유형": ""}
    assert project.parts == {}
    imported = project.get_connector("J1_1")
    assert imported.to_dict() == items[0].connector.to_dict()
    assert imported is not items[0].connector
    assert imported.rows is not items[0].connector.rows
    assert imported.signals is not items[0].connector.signals
    items[0].connector.rows[0].pin_designator = "CHANGED"
    items[0].connector.signals["DATA"].color = "#000000"
    assert imported.rows[0].pin_designator == "1"
    assert imported.signals["DATA"].color == "#ABC123"
    imported.signals["SPARE"].signal_type = ""
    assert items[0].connector.signals["SPARE"].signal_type == "새유형"
    assert project.get_connector("J1").rows == []


def test_apply_rejects_stale_id_collision_without_overwriting(tmp_path):
    from jeonnector.markdown_exchange import apply_markdown_import, prepare_markdown_import

    project = Project()
    paths = [document(tmp_path, "| 신호명 |\n| --- |", f"{i}.md") for i in range(2)]
    items = prepare_markdown_import(paths, project)
    project.add_connector("J2")
    before = project.to_dict()
    with pytest.raises(ValueError, match="J2"):
        apply_markdown_import(project, items)
    assert project.to_dict() == before


def test_export_writes_only_id_and_four_column_table_in_natural_pin_order(tmp_path):
    from jeonnector.markdown_exchange import export_connector, prepare_markdown_import
    from jeonnector.model import ConnectorInstance, SignalDefinition, SignalRow

    connector = ConnectorInstance("J9", part_uuid="부품정보제외", signals={
        name: SignalDefinition(name, "ANALOG", "#abc123")
        for name in ["SPARE", "DATA10", "DATA2", "+5V"]}, rows=[
            SignalRow("SPARE"), SignalRow("DATA10", "A10"),
            SignalRow("DATA2", "A2"), SignalRow("+5V", "1")])
    before = connector.to_dict()
    text = export_connector(connector)
    assert text == ("- 식별자 : J9\n\n| 핀 번호 | 신호명 | 신호유형 | 색상 |\n"
                    "| --- | --- | --- | --- |\n| 1 | `+5V` | ANALOG | #ABC123 |\n"
                    "| A2 | `DATA2` | ANALOG | #ABC123 |\n| A10 | `DATA10` | ANALOG | #ABC123 |\n"
                    "|  | `SPARE` | ANALOG | #ABC123 |\n")
    assert connector.to_dict() == before
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.connector.designator == "J9"
    assert all(item.connector.signals[name].color == "#ABC123" for name in connector.signals)
    assert [row.pin_designator for row in item.connector.rows] == ["1", "A2", "A10", ""]


@pytest.mark.parametrize("pin", ["|", "A|B", "\\", "\\|", "A\\B", "`", "``", "`A`", "<A>", "<!--A-->", "&amp;", "&#124;", "*A*", "_A_", "²", "①"])
def test_export_import_preserves_arbitrary_non_whitespace_pin_text(tmp_path, pin):
    from jeonnector.markdown_exchange import export_connector, prepare_markdown_import
    from jeonnector.model import ConnectorInstance, SignalDefinition, SignalRow

    connector = ConnectorInstance("J1", signals={"DATA": SignalDefinition("DATA")}, rows=[SignalRow("DATA", pin)])
    text = export_connector(connector)
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.connector.rows[0].pin_designator == pin


def test_template_is_ready_to_import_and_explains_examples(tmp_path):
    from jeonnector.markdown_exchange import MARKDOWN_TEMPLATE, prepare_markdown_import

    assert isinstance(MARKDOWN_TEMPLATE, str)
    assert "부품명" not in MARKDOWN_TEMPLATE
    assert "예시" in MARKDOWN_TEMPLATE and "삭제" in MARKDOWN_TEMPLATE
    assert "#RRGGBB" in MARKDOWN_TEMPLATE
    [item] = prepare_markdown_import([document(tmp_path, MARKDOWN_TEMPLATE)], Project())
    assert not item.error
    assert item.connector.designator == "J1"
    assert {"+5V", "GND", "DATA+", "RESET#", "SPARE"} <= item.connector.signals.keys()
    assert item.connector.rows[-1].pin_designator == ""


def test_comments_inside_table_do_not_truncate_valid_rows_or_line_numbers(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = ("| 신호명 |\n| --- |\n| FIRST |\n<!--\n| BAD NAME |\n-->\n"
            "| SECOND |\n\n| 설명 |\n| --- |\n| 무시 |")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert not item.error
    assert list(item.connector.signals) == ["FIRST", "SECOND"]
    text = text.replace("| SECOND |", "| BAD NAME |")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "7행" in item.error


def test_fence_info_comment_marker_does_not_hide_following_real_table(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = ("~~~ <!-- 예제\n| 신호명 |\n| --- |\n| EXAMPLE |\n~~~\n"
            "- 식별자 : J8\n| 신호명 |\n| --- |\n| REAL |")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.connector.designator == "J8"
    assert list(item.connector.signals) == ["REAL"]


@pytest.mark.parametrize("headers", ["신호명 | 신호명", "신호명 | 색상 | 색상", "신호명 | 핀 번호 | 핀 번호"])
def test_repeated_known_headers_do_not_silently_drop_values(tmp_path, headers):
    from jeonnector.markdown_exchange import prepare_markdown_import

    delimiter = " | ".join("---" for _ in headers.split("|"))
    [item] = prepare_markdown_import([document(tmp_path, f"| {headers} |\n| {delimiter} |")], Project())
    assert item.connector is None
    assert "1행" in item.error
    assert "열" in item.error


def test_single_column_table_accepts_plain_data_rows(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "| 신호명 |\n| --- |\nFIRST\nSECOND\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert list(item.connector.signals) == ["FIRST", "SECOND"]


@pytest.mark.parametrize("boundary", [
    "# 설명", "- 설명", "1. 설명", "> 설명", "---", "***",
    "| 설명 |\n| --- |\n| 무시 |",
])
def test_single_column_table_stops_at_following_block(tmp_path, boundary):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "| 신호명 |\n| --- |\n| FIRST |\n" + boundary + "\nIGNORED\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert list(item.connector.signals) == ["FIRST"]


@pytest.mark.parametrize("indent", ["    ", "\t"])
@pytest.mark.parametrize("real_table", [False, True])
def test_indented_code_examples_are_not_imported(tmp_path, indent, real_table):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "\n".join(indent + line for line in [
        "- 식별자 : BAD", "| 핀 번호 | 신호명 |", "| --- | --- |", "| 9 | EXAMPLE |",
    ]) + "\n\n"
    if real_table:
        text += "- 식별자 : J7\n| 신호명 |\n| --- |\n| REAL |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    if real_table:
        assert item.error == ""
        assert item.connector.designator == "J7"
        assert list(item.connector.signals) == ["REAL"]
    else:
        assert item.connector is None
        assert "신호표가 없습니다" in item.error


def test_indented_code_markers_do_not_hide_real_table_or_change_error_line(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = ("    <!--\n    ```\n\n~~~\n예제\n~~~\n<!-- 주석 -->\n"
            "| 신호명 |\n| --- |\n| BAD NAME |\n")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "10행" in item.error
    assert "신호명" in item.error


@pytest.mark.parametrize("pin", ["<!--A-->", "<!--", "A&#43;", r"A\B", r"\+", "X`A`X"])
def test_code_pin_preserves_literal_text(tmp_path, pin):
    from jeonnector.markdown_exchange import prepare_markdown_import

    ticks = "``" if "`" in pin else "`"
    text = f"| 핀 번호 | 신호명 |\n| --- | --- |\n| {ticks}{pin}{ticks} | DATA |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.connector.rows[0].pin_designator == pin


@pytest.mark.parametrize("name", ["`A&#43;`", r"`A\+`", "``A&#43;``"])
def test_code_signal_entities_and_escapes_are_not_decoded(tmp_path, name):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = f"| 핀 번호 | 신호명 |\n| --- | --- |\n| 1 | {name} |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "3행" in item.error
    assert "신호명" in item.error


def test_inline_code_comment_marker_in_description_does_not_hide_table(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "설명의 `<!--` 표기와 `` `<!--` `` 표기\n\n| 신호명 |\n| --- |\n| REAL |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert list(item.connector.signals) == ["REAL"]


@pytest.mark.parametrize("pin", ["`A B`", "` A`", "`A `"])
def test_code_pin_whitespace_is_rejected_without_trimming(tmp_path, pin):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = f"| 핀 번호 | 신호명 |\n| --- | --- |\n| {pin} | DATA |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "3행" in item.error
    assert "핀 번호" in item.error


@pytest.mark.parametrize("pin", ["`A&#43;`X", r"X`A\+`", "`A`X`B`"])
def test_mixed_code_pin_is_rejected_instead_of_silently_decoded(tmp_path, pin):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = f"| 핀 번호 | 신호명 |\n| --- | --- |\n| {pin} | DATA |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "3행" in item.error
    assert "코드" in item.error


def test_plain_cell_entities_and_escapes_remain_supported(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "| 핀 번호 | 신호명 |\n| --- | --- |\n| A&#43; | A\\+ |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.connector.rows[0].pin_designator == "A+"
    assert item.connector.rows[0].signal_name == "A+"


@pytest.mark.parametrize("example", [
    "```\nEXAMPLE\n```", "    EXAMPLE", "~~~\nEXAMPLE\n~~~",
])
def test_code_block_ends_single_column_table(tmp_path, example):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "| 신호명 |\n| --- |\nFIRST\n" + example + "\nIGNORED\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert list(item.connector.signals) == ["FIRST"]


def test_unmatched_backtick_run_does_not_turn_comment_into_code(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = ("설명 ``<!--` 주석 시작\n| 신호명 |\n| --- |\n| EXAMPLE |\n-->\n"
            "| 신호명 |\n| --- |\n| REAL |\n")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert list(item.connector.signals) == ["REAL"]


@pytest.mark.parametrize("pin_header, type_header", [("핀번호", "신호 유형"), ("핀  번호", "신호유형 ")])
def test_headers_ignore_spacing(tmp_path, pin_header, type_header):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = f"| {pin_header} | 신 호 명 | {type_header} |\n| --- | --- | --- |\n| 1 | VCC | POWER |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.warnings == []
    assert item.connector.rows[0].pin_designator == "1"
    assert item.connector.signals["VCC"].signal_type == "POWER"


def test_unknown_columns_are_reported_as_warning(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "| 핀 번호 | 신호명 | 비고 | |\n| --- | --- | --- | --- |\n| 1 | VCC | 확인 | |\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert item.warnings == ["1행: 인식하지 못한 열은 무시합니다: 비고, (빈 제목)"]
    assert item.connector.rows[0].pin_designator == "1"


def test_pin_only_rows_are_skipped_with_one_warning(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = ("| 핀 번호 | 신호명 | 신호유형 | 색상 |\n| --- | --- | --- | --- |\n"
            "| 1 | VCC | | |\n| 2 | | | |\n| 3 | GND | | |\n| A B | | POWER | |\n")
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.error == ""
    assert [(row.pin_designator, row.signal_name) for row in item.connector.rows] == [("1", "VCC"), ("3", "GND")]
    assert item.warnings == ["신호명이 없는 핀 번호 2개는 가져오지 않습니다: 2(4행), A B(6행)"]


@pytest.mark.parametrize("line", ["- **식별자** : J7", "* __식별자__: J7", "- 식별자 : `j7`"])
def test_identifier_accepts_bold_label_and_code_value(tmp_path, line):
    from jeonnector.markdown_exchange import prepare_markdown_import

    [item] = prepare_markdown_import([document(tmp_path, f"{line}\n\n| 신호명 |\n| --- |\n| A |\n")], Project())
    assert item.error == ""
    assert item.connector.designator == "J7"


def test_export_keeps_common_pin_text_readable():
    from jeonnector.markdown_exchange import export_connector
    from jeonnector.model import ConnectorInstance, SignalDefinition, SignalRow

    pins = ["A-1", "1.2", "B_3", "C*4", "D+", "E#"]
    connector = ConnectorInstance("J1", signals={f"S{i}": SignalDefinition(f"S{i}") for i in range(len(pins))},
                                  rows=[SignalRow(f"S{i}", pin) for i, pin in enumerate(pins)])
    text = export_connector(connector)
    assert "\\" not in text
    for pin in pins:
        assert f"| {pin} |" in text


def test_paragraph_right_after_table_explains_blank_line(tmp_path):
    from jeonnector.markdown_exchange import prepare_markdown_import

    text = "| 핀 번호 | 신호명 |\n| --- | --- |\n| 1 | VCC |\n비고: 확인 필요\n"
    [item] = prepare_markdown_import([document(tmp_path, text)], Project())
    assert item.connector is None
    assert "4행" in item.error and "빈 줄" in item.error
