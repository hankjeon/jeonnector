"""전연결기(jeonnector) JSON 저장소(.jnc 프로젝트 파일) 및 자체 연결기 부품 데이터베이스 관리."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from jeonnector.default_parts import create_default_parts
from jeonnector.model import (
    SCHEMA_VERSION,
    ConnectorPart,
    Project,
    ProjectFormatError,
)


def default_part_library_path() -> Path:
    """사용자 데이터 폴더(Qt QStandardPaths) 기준 연결기 부품 데이터베이스 경로 반환 (제4.4절)."""
    try:
        from PySide6.QtCore import QStandardPaths

        app_data = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        if app_data:
            return Path(app_data) / "jeonnector" / "parts_library.json"
    except Exception:
        pass
    return Path.home() / ".jeonnector" / "parts_library.json"


def save_project(project: Project, path: str | Path) -> None:
    """프로젝트를 .jnc(JSON) 파일로 저장한다. 신호 중복이 남아 있어도 저장한다 (제3.2절)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = project.to_dict()
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_project(path: str | Path) -> Project:
    """.jnc(JSON) 파일에서 프로젝트를 불러온다.

    손상된 파일이나 상위 schema_version 파일은 ProjectFormatError를 발생시킨다 (제3.2절).
    """
    target = Path(path)
    try:
        raw_text = target.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception as exc:
        raise ProjectFormatError(
            f"손상되었거나 읽을 수 없는 프로젝트 파일입니다: {exc}"
        ) from exc
    return Project.from_dict(data)


def export_parts(parts: list[ConnectorPart], path: str | Path) -> None:
    """선택한 연결기 부품 정보만 JSON 파일로 내보낸다 (제4.4절).

    프로젝트의 신호와 할당은 내보내기에 포함하지 않는다.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "format": "jeonnector-parts",
        "parts": [p.to_dict() for p in parts],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_parts_file(path: str | Path) -> list[ConnectorPart]:
    """부품 교환 JSON 파일에서 부품 목록을 읽어 반환한다."""
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"손상된 부품 JSON 파일입니다: {exc}") from exc

    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict) and "parts" in data:
        version = data.get("schema_version", data.get("version", 1))
        if isinstance(version, int) and version > SCHEMA_VERSION:
            raise ValueError(
                f"지원하지 않는 상위 schema_version({version}) 부품 파일입니다."
            )
        raw = data["parts"]
        raw_list = list(raw.values()) if isinstance(raw, dict) else list(raw)
    elif isinstance(data, dict) and "family" in data and "pins" in data:
        raw_list = [data]
    else:
        raise ValueError("유효한 연결기 부품 JSON 형식이 아닙니다.")
    return [ConnectorPart.from_dict(item) for item in raw_list]


class PartLibrary:
    """전연결기 자체 연결기 부품 데이터베이스 (제3.3절, 제4.4절, 제4.6절).

    - 처음 실행 시 기본 제공 연결기 부품 27종을 포함한다.
    - 부품은 UUID로 식별하며, 부품명은 대소문자 구분 없이 중복될 수 없다.
    - '기본 부품 복원'으로 기본 27종을 원래 정의로 되돌리거나 다시 추가할 수 있다.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else default_part_library_path()
        )
        self._parts: dict[str, ConnectorPart] = {}
        self.reload()

    def reload(self) -> None:
        """저장된 부품 데이터베이스를 적재하거나, 처음 실행 시 기본 27종으로 초기화한다."""
        self._parts.clear()
        if not self.storage_path.exists():
            for part in create_default_parts():
                self._parts[part.uuid] = part
            return

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            raw_parts = data.get("parts", [])
            if isinstance(raw_parts, dict):
                raw_parts = list(raw_parts.values())
            for item in raw_parts:
                part = ConnectorPart.from_dict(item)
                self._parts[part.uuid] = part
            if not self._parts:
                for part in create_default_parts():
                    self._parts[part.uuid] = part
        except Exception:
            for part in create_default_parts():
                self._parts[part.uuid] = part

    def restore_default_parts(self, save_now: bool = True) -> list[ConnectorPart]:
        """기본 제공 연결기 27종을 원래 정의(고정 UUID)로 되돌리거나 다시 추가한다 (제4.6절)."""
        restored: list[ConnectorPart] = []
        for default_part in create_default_parts():
            # 다른 UUID가 기본 부품 이름을 쓰고 있다면 이름 충돌을 피하도록 조정
            existing_by_name = self.find_by_name(default_part.name)
            if (
                existing_by_name is not None
                and existing_by_name.uuid != default_part.uuid
            ):
                existing_by_name.variant = self.make_unique_variant(
                    existing_by_name.family, existing_by_name.variant
                )
            self._parts[default_part.uuid] = default_part.clone()
            restored.append(self._parts[default_part.uuid])
        if save_now:
            self.save()
        return restored

    def save(self) -> None:
        """현재 부품 데이터베이스를 로컬 JSON 파일에 저장한다."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "format": "jeonnector-part-library",
            "parts": [p.to_dict() for p in self.list_parts()],
        }
        self.storage_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_parts(self) -> list[ConnectorPart]:
        return list(self._parts.values())

    def get_part(self, part_uuid: str) -> ConnectorPart | None:
        return self._parts.get(part_uuid)

    def find_by_name(
        self, name: str, exclude_uuid: str | None = None
    ) -> ConnectorPart | None:
        """대소문자 구분 없이 부품명으로 부품을 검색한다 (제3.3절)."""
        target = name.strip().lower()
        for part in self._parts.values():
            if exclude_uuid and part.uuid == exclude_uuid:
                continue
            if part.name.strip().lower() == target:
                return part
        return None

    def find_conflict(self, incoming: ConnectorPart) -> ConnectorPart | None:
        """가져오려는 부품과 동일한 UUID 또는 동일한 부품명이 있는지 확인한다."""
        if incoming.uuid in self._parts:
            return self._parts[incoming.uuid]
        by_name = self.find_by_name(incoming.name)
        if by_name is not None:
            return by_name
        return None

    def upsert_part(
        self, part: ConnectorPart, save_now: bool = True
    ) -> ConnectorPart:
        """부품을 추가하거나 갱신한다. 다른 UUID 부품과 이름이 중복되면 예외를 발생시킨다 (제3.3절)."""
        dup_name_part = self.find_by_name(part.name, exclude_uuid=part.uuid)
        if dup_name_part is not None:
            raise ValueError(
                f"연결기 부품 데이터베이스에 같은 이름의 부품이 이미 존재합니다: '{part.name}'"
            )
        cloned = part.clone()
        self._parts[cloned.uuid] = cloned
        if save_now:
            self.save()
        return cloned

    def delete_part(self, part_uuid: str, save_now: bool = True) -> bool:
        if part_uuid in self._parts:
            del self._parts[part_uuid]
            if save_now:
                self.save()
            return True
        return False

    def make_unique_variant(self, family: str, base_variant: str) -> str:
        """이름 충돌 시 중복되지 않는 새 세부 이름(variant)을 생성한다."""
        idx = 2
        candidate = f"{base_variant}_{idx}"
        while self.find_by_name(
            f"{family} - {candidate}" if family else candidate
        ):
            idx += 1
            candidate = f"{base_variant}_{idx}"
        return candidate

    def import_parts(
        self,
        incoming_parts: list[ConnectorPart],
        conflict_resolver: Callable[
            [ConnectorPart, ConnectorPart], tuple[str, str | None]
        ]
        | None = None,
    ) -> list[ConnectorPart]:
        """선택한 부품 목록을 가져온다 (제4.4절).

        - 같은 UUID의 부품이 있으면 덮어쓸지("overwrite"), 이름을 바꾸어 추가할지("rename") 선택한다.
          이름을 바꾸어 추가하면 새 UUID를 발급한다.
        - UUID는 다르지만 부품명이 같으면 이름을 바꾸어야 추가할 수 있다.
        """
        imported: list[ConnectorPart] = []
        for incoming in incoming_parts:
            same_uuid_part = self._parts.get(incoming.uuid)
            same_name_part = self.find_by_name(incoming.name)
            existing = same_uuid_part or same_name_part

            if existing is None:
                added = incoming.clone()
                self._parts[added.uuid] = added
                imported.append(added)
                continue

            if conflict_resolver is None:
                # 같은 UUID면 덮어쓰기 기본, 다른 UUID인데 이름만 같으면 이름 변경 기본
                if same_uuid_part is not None:
                    action, new_name = ("overwrite", None)
                else:
                    action, new_name = ("rename", None)
            else:
                action, new_name = conflict_resolver(existing, incoming)

            # UUID가 다른데 부품명이 같은 경우에는 덮어쓰기 대신 이름을 바꾸어야 추가 가능 (제4.4절)
            if action == "overwrite" and same_uuid_part is None:
                action = "rename"

            if action == "overwrite" and same_uuid_part is not None:
                replaced = incoming.clone()
                replaced.uuid = same_uuid_part.uuid
                # 덮어쓸 때 다른 UUID 부품과 이름이 겹치면 고유 이름 보장
                if (
                    self.find_by_name(
                        replaced.name, exclude_uuid=replaced.uuid
                    )
                    is not None
                ):
                    replaced.variant = self.make_unique_variant(
                        replaced.family, replaced.variant
                    )
                self._parts[same_uuid_part.uuid] = replaced
                imported.append(replaced)
            elif action == "rename":
                renamed = incoming.clone(
                    new_uuid=(same_uuid_part is not None)
                )
                if renamed.uuid in self._parts:
                    renamed = incoming.clone(new_uuid=True)
                if new_name and new_name.strip():
                    cleaned = new_name.strip()
                    if " - " in cleaned:
                        fam, var = cleaned.split(" - ", 1)
                        renamed.family = fam.strip()
                        renamed.variant = var.strip()
                    else:
                        renamed.variant = cleaned
                if self.find_by_name(renamed.name) is not None:
                    renamed.variant = self.make_unique_variant(
                        renamed.family, renamed.variant
                    )
                self._parts[renamed.uuid] = renamed
                imported.append(renamed)

        self.save()
        return imported
