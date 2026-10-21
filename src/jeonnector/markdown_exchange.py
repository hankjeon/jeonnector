"""프로젝트와 분리된 마크다운 신호표 읽기·쓰기."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import html
from pathlib import Path
import re
import string

from .model import (
    ConnectorInstance, Project, SignalDefinition, SignalRow,
    normalize_signal_name, normalize_signal_type_name,
    is_valid_connector_id, is_valid_signal_name, is_valid_signal_type_name,
    is_valid_pin_number_format,
    natural_sort_key,
)


MARKDOWN_TEMPLATE: str = """# 연결기 신호표

이곳에는 용도와 주의사항 등 자유로운 설명을 작성합니다.
아래 예시 행을 실제 신호로 수정하거나 삭제하세요.
식별자를 비우면 자동으로 부여합니다. 부품 없이도 핀 번호를 보존합니다.
색상은 #RRGGBB 형식이며 빈칸이면 개별 색상 없음입니다.

- 식별자 :

| 핀 번호 | 신호명 | 신호유형 | 색상 |
| --- | --- | --- | --- |
| 1 | `+5V` | POWER | |
| 2 | `GND` | GROUND | |
| 3 | `DATA+` | DISCRETE | #2563EB |
| 4 | `RESET#` | DISCRETE | |
| | `SPARE` | | |
"""


@dataclass
class MarkdownImportItem:
    """파일별 검증 결과와 최종 식별자를 가진 등록 대기 연결기."""

    path: Path
    connector: ConnectorInstance | None
    error: str = ""
    warnings: list[str] = field(default_factory=list)


def _code_span_end(text: str, start: int) -> int | None:
    """같은 길이의 백틱 묶음으로 닫힌 인라인 코드의 끝을 찾는다."""
    opening = re.match(r"`+", text[start:])
    if opening is None:
        return None
    width = len(opening[0])
    for closing in re.finditer(r"`+", text[start + width:]):
        if len(closing[0]) == width:
            return start + width + closing.end()
    return None


def _visible_lines(text: str) -> list[str | None]:
    """코드 블록은 빈 줄, 주석은 None으로 가려 표 경계와 원래 줄 번호를 보존한다."""
    result: list[str | None] = []
    fence = ""
    comment = False
    for line in text.splitlines():
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}\s*", line):
                fence = ""
            result.append("")
            continue
        if not comment and line.expandtabs(4).startswith("    "):
            result.append("")
            continue
        match = re.match(r" {0,3}(`{3,}|~{3,})", line) if not comment else None
        if match:
            fence = match[1]
            result.append("")
            continue
        was_comment = comment
        visible = ""
        position = 0
        while position < len(line):
            if comment:
                end = line.find("-->", position)
                if end < 0:
                    break
                position = end + 3
                comment = False
            elif line.startswith("<!--", position):
                was_comment = True
                comment = True
                position += 4
            else:
                end = _code_span_end(line, position) if line[position] == "`" else None
                if end is None:
                    if line[position] == "`":
                        end = position + len(line[position:]) - len(line[position:].lstrip("`"))
                    else:
                        end = position + (2 if line[position] == "\\" else 1)
                visible += line[position:end]
                position = end
        match = re.match(r" {0,3}(`{3,}|~{3,})", visible)
        if match:
            fence = match[1]
            visible = ""
        result.append(None if not match and was_comment and not visible.strip() else visible)
    return result


def _cells(line: str) -> list[str]:
    """역슬래시로 이스케이프한 구분자는 셀 내용으로 보존한다."""
    line = line.strip()
    cells = [""]
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line):
            cells[-1] += line[index:index + 2]
            index += 2
            continue
        if char == "|":
            cells.append("")
        else:
            cells[-1] += char
        index += 1
    if line.startswith("|"):
        cells.pop(0)
    if cells and cells[-1] == "" and line.endswith("|"):
        cells.pop()
    return [cell.strip() for cell in cells]


def _decode_cell(cell: str) -> str:
    for token in re.finditer(r"\\.|`+|[^\\`]+", cell):
        if token[0].startswith("`"):
            end = _code_span_end(cell, token.start())
            if end is not None:
                if token.start() == 0 and end == len(cell):
                    width = len(token[0])
                    return cell[width:-width]
                raise ValueError("셀 전체를 감싸지 않은 인라인 코드는 지원하지 않습니다.")
    unescaped = re.sub(r"\\([" + re.escape(string.punctuation) + r"])", r"\1", cell)
    return html.unescape(unescaped)


def _table_headers(lines: list[str | None], index: int) -> list[str] | None:
    line = lines[index]
    if index + 1 >= len(lines) or line is None or "|" not in line:
        return None
    headers = _cells(line)
    separators = _cells(lines[index + 1] or "")
    if (len(headers) == len(separators)
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators)):
        return headers
    return None


COLUMNS = ("핀 번호", "신호명", "신호유형", "색상")


def _column_key(header: str) -> str | None:
    """공백을 무시하고 열 제목을 인식한다(예: `핀번호`, `신호 유형`)."""
    compact = re.sub(r"\s+", "", header)
    return next((column for column in COLUMNS if column.replace(" ", "") == compact), None)


def _identifier_value(raw: str) -> str:
    """식별자 값을 셀 전체 백틱 한 쌍에서 꺼낸다."""
    value = raw.strip()
    match = re.fullmatch(r"`([^`]*)`", value)
    return match[1] if match else value


def _starts_block(line: str) -> bool:
    return bool(
        re.match(r" {0,3}(?:#{1,6}(?:\s|$)|[-+*](?:\s|$)|\d{1,9}[.)](?:\s|$)|>)", line)
        or re.fullmatch(r" {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,}|=+\s*)", line)
    )


def _parse_document(text: str) -> tuple[ConnectorInstance, list[str]]:
    lines = _visible_lines(text)
    connector = ConnectorInstance("")
    identifier_seen = False
    tables = []
    for index, line in enumerate(lines):
        if line is None:
            continue
        match = re.fullmatch(r"\s*[-+*]\s+(?:\*\*|__)?식별자(?:\*\*|__)?\s*:\s*(.*)", line)
        if match:
            if identifier_seen:
                raise ValueError(f"{index + 1}행: 식별자 항목이 반복됩니다.")
            identifier_seen = True
            connector.designator = normalize_signal_name(_identifier_value(match[1]))
            if connector.designator and not is_valid_connector_id(connector.designator):
                raise ValueError(f"{index + 1}행: 식별자 형식이 올바르지 않습니다(32자 이하): {match[1]}")
        headers = _table_headers(lines, index)
        if headers is not None and "신호명" in map(_column_key, headers):
            tables.append((index, headers))
    if not tables:
        raise ValueError("신호표가 없습니다.")
    if len(tables) > 1:
        raise ValueError(f"{tables[1][0] + 1}행: 신호표가 여러 개입니다.")
    index, headers = tables[0]
    keys = [_column_key(header) for header in headers]
    for column in COLUMNS:
        if keys.count(column) > 1:
            raise ValueError(f"{index + 1}행: {column} 열이 반복됩니다.")
    warnings = []
    unknown = [header or "(빈 제목)" for header, key in zip(headers, keys) if key is None]
    if unknown:
        warnings.append(f"{index + 1}행: 인식하지 못한 열은 무시합니다: {', '.join(unknown)}")
    pin_only: list[tuple[int, str]] = []
    seen_rows: set[tuple[str, str]] = set()
    for line_number, line in enumerate(lines[index + 2:], index + 3):
        if line is None:
            continue
        if (not line.strip() or _starts_block(line)
                or (line_number < len(lines) and "|" in (lines[line_number] or "")
                    and _table_headers(lines, line_number - 1) is not None)):
            break
        cells = _cells(line)
        if not any(cells):
            continue
        if len(cells) != len(headers):
            raise ValueError(
                f"{line_number}행: 표의 열 개수가 맞지 않습니다. 표 바로 다음에 글을 쓰려면 빈 줄을 넣으세요."
            )
        try:
            values = {key: _decode_cell(cell) for key, cell in zip(keys, cells) if key}
        except ValueError as error:
            raise ValueError(f"{line_number}행: {error}") from error
        name = normalize_signal_name(values.get("신호명", ""))
        signal_type = normalize_signal_type_name(values.get("신호유형", ""))
        color = values.get("색상", "").upper()
        pin = values.get("핀 번호", "")
        if not name and pin:
            pin_only.append((line_number, pin))
            continue
        for valid, label in (
            (is_valid_signal_name(name), "신호명"),
            (not signal_type or is_valid_signal_type_name(signal_type), "신호유형"),
            (not color or bool(re.fullmatch(r"#[0-9A-F]{6}", color)), "색상"),
            (not pin or is_valid_pin_number_format(pin), "핀 번호"),
        ):
            if not valid:
                raise ValueError(f"{line_number}행: {label} 형식이 올바르지 않습니다.")
        shared = connector.signals.setdefault(name, SignalDefinition(name))
        for attribute, value, label in (
            ("signal_type", signal_type, "신호유형"), ("color", color, "색상"),
        ):
            previous = getattr(shared, attribute)
            if previous and value and previous != value:
                raise ValueError(f"{line_number}행: {name}의 {label} 속성이 충돌합니다.")
            if value:
                setattr(shared, attribute, value)
        pair = (name, pin)
        if pair in seen_rows:
            warnings.append(f"{line_number}행: 같은 핀 번호·신호명의 중복 행을 합쳤습니다.")
        else:
            seen_rows.add(pair)
            connector.rows.append(SignalRow(name, pin))
    if pin_only:
        warnings.append(
            f"신호명이 없는 핀 번호 {len(pin_only)}개는 가져오지 않습니다: "
            + ", ".join(f"{pin}({line_number}행)" for line_number, pin in pin_only)
        )
    connector.enforce_row_rules()
    for pin in connector.duplicate_pins():
        warnings.append(f"핀 번호 {pin}: 서로 다른 신호가 할당된 신호 중복입니다.")
    return connector, warnings


def prepare_markdown_import(
    paths: list[Path], project: Project,
) -> list[MarkdownImportItem]:
    """원본과 프로젝트를 바꾸지 않고 파일별 가져오기 결과를 준비한다."""
    items = []
    for path in paths:
        try:
            connector, warnings = _parse_document(path.read_text(encoding="utf-8-sig"))
            items.append(MarkdownImportItem(path, connector, warnings=warnings))
        except (OSError, UnicodeError, ValueError) as error:
            items.append(MarkdownImportItem(path, None, f"{path.name}: {error}"))
    used = {normalize_signal_name(conn.designator) for conn in project.connectors}
    reserved = used | {item.connector.designator for item in items if item.connector}
    for item in items:
        connector = item.connector
        if connector is None:
            continue
        base = connector.designator
        if not base:
            number = 1
            while f"J{number}" in reserved:
                number += 1
            connector.designator = f"J{number}"
        elif base in used:
            suffix = 1
            while f"{base}_{suffix}" in reserved:
                suffix += 1
            candidate = f"{base}_{suffix}"
            if len(candidate) > 32:
                item.connector = None
                item.error = f"{item.path.name}: 식별자 {base}에 접미사를 붙이면 32자를 넘습니다."
                continue
            connector.designator = candidate
        used.add(connector.designator)
        reserved.add(connector.designator)
    return items


def apply_markdown_import(
    project: Project, items: list[MarkdownImportItem],
) -> list[str]:
    """정상 항목의 독립 사본을 새 연결기로 등록하고 식별자 목록을 반환한다.

    미리보기 이후 식별자가 선점되었다면 일부만 등록하지 않고 오류를 낸다.
    """
    connectors = [copy.deepcopy(item.connector) for item in items
                  if item.connector is not None and not item.error]
    used = {normalize_signal_name(conn.designator) for conn in project.connectors}
    for connector in connectors:
        if not is_valid_connector_id(connector.designator):
            raise ValueError(f"올바르지 않은 식별자입니다: {connector.designator}")
        if connector.designator in used:
            raise ValueError(f"이미 존재하는 연결기 식별자입니다: {connector.designator}")
        used.add(connector.designator)
    for connector in connectors:
        for signal in connector.signals.values():
            if signal.signal_type:
                project.ensure_signal_type(signal.signal_type)
        target = project.add_connector(connector.designator)
        target.signals = connector.signals
        target.rows = connector.rows
    return [connector.designator for connector in connectors]


WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{device}{number}" for device in ("COM", "LPT") for number in range(10)}
)


def markdown_file_name(designator: str, designators: set[str]) -> str:
    """식별자 기반 내보내기 파일명.

    Windows 예약 이름(`CON`, `AUX`, `COM1` 등)은 확장자를 붙여도 파일을 만들 수 없으므로
    다른 식별자(designators)와 겹치지 않을 때까지 밑줄을 붙인다. 가져오기는 문서 안의
    식별자를 읽으므로 파일명이 달라도 식별자는 그대로 복원된다.
    """
    stem = designator
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem += "_"
        while stem in designators:
            stem += "_"
    return f"{stem}.md"


def _escape_cell(text: str) -> str:
    """읽기 쉽도록 표 구분자·역슬래시·백틱과 HTML 특수 문자만 바꾼다."""
    return re.sub(r"([\\|`])", r"\\\1", html.escape(text, quote=False))


def export_connector(connector: ConnectorInstance) -> str:
    """원본을 바꾸지 않고 식별자와 핀 번호 자연 정렬 신호표를 출력한다."""
    rows = sorted(connector.rows, key=lambda row: (
        not row.pin_designator, natural_sort_key(row.pin_designator),
        natural_sort_key(row.signal_name),
    ))
    lines = [f"- 식별자 : {connector.designator}", "",
             "| 핀 번호 | 신호명 | 신호유형 | 색상 |", "| --- | --- | --- | --- |"]
    for row in rows:
        signal = connector.signals[row.signal_name]
        pin = _escape_cell(row.pin_designator)
        lines.append(f"| {pin} | `{signal.name}` | {signal.signal_type} | {signal.color.upper()} |")
    return "\n".join(lines) + "\n"
