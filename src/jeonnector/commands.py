"""전연결기(jeonnector) 명령 객체(Command) 기반 편집 계층 (제5.1절).

모든 프로젝트·연결기·신호·신호유형 편집을 명령 객체를 통해 실행하고
추후 실행 취소·다시 실행(Undo/Redo)을 도입할 수 있도록 상태 스냅샷 및 이력을 관리한다.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from jeonnector.model import ConnectorPart, Project


@dataclass
class EditCommand:
    """단일 편집 작업을 나타내는 명령 객체."""

    description: str
    action: Callable[[], bool]

    def execute(self) -> bool:
        return bool(self.action())


class CommandDispatcher:
    """편집 명령을 실행하고 실행 전후 프로젝트 스냅샷 이력을 보관하는 편집 계층."""

    def __init__(self, project_getter: Callable[[], Project]) -> None:
        self._project_getter = project_getter
        self._history: list[tuple[str, dict[str, Any]]] = []
        self._redo_stack: list[tuple[str, dict[str, Any]]] = []

    @property
    def history_count(self) -> int:
        return len(self._history)

    def clear(self) -> None:
        self._history.clear()
        self._redo_stack.clear()

    def execute(
        self, description: str, action: Callable[[], bool]
    ) -> bool:
        """명령 객체를 생성해 실행하고 성공 시 변경 전 스냅샷을 이력에 기록한다."""
        project = self._project_getter()
        before_snapshot = copy.deepcopy(project.to_dict())
        cmd = EditCommand(description=description, action=action)
        ok = cmd.execute()
        if ok:
            self._history.append((description, before_snapshot))
            self._redo_stack.clear()
        return ok

    def add_connector(
        self, designator: str, part: ConnectorPart | None = None
    ) -> bool:
        project = self._project_getter()

        def _do() -> bool:
            project.add_connector(designator, part)
            return True

        return self.execute(f"연결기 추가: {designator}", _do)

    def remove_connector(self, designator: str) -> bool:
        project = self._project_getter()
        return self.execute(
            f"연결기 제거: {designator}",
            lambda: project.remove_connector(designator),
        )

    def rename_connector(
        self, old_designator: str, new_designator: str
    ) -> bool:
        project = self._project_getter()
        return self.execute(
            f"연결기 식별자 변경: {old_designator} -> {new_designator}",
            lambda: project.rename_connector(old_designator, new_designator),
        )

    def change_connector_part(
        self, designator: str, new_part: ConnectorPart | None
    ) -> bool:
        project = self._project_getter()
        return self.execute(
            f"연결기 부품 변경: {designator}",
            lambda: project.change_connector_part(designator, new_part),
        )
