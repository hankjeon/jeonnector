"""전연결기(jeonnector) 명령 객체(Command) 기반 편집 계층과 실행 취소·다시 실행 (제5.1절, 제3.13절).

프로젝트 편집이 끝날 때마다 상태 스냅샷을 기록하고, 실행 취소·다시 실행은 기록한 스냅샷으로
프로젝트를 되돌린다. 편집 종류마다 되돌리는 코드를 따로 두지 않는다.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from typing import Any, Callable

from jeonnector.model import ConnectorPart, Project, normalize_signal_name

HISTORY_LIMIT = 100


@dataclass
class EditCommand:
    """단일 편집 작업을 나타내는 명령 객체."""

    description: str
    action: Callable[[], bool]

    def execute(self) -> bool:
        return bool(self.action())


@dataclass
class HistoryStep:
    """실행 취소 한 단계: 편집 설명, 편집 전 상태, 편집 전후에 보여 줄 연결기."""

    description: str
    state: dict[str, Any]
    focus_before: str | None
    focus_after: str | None


def project_state(project: Project) -> dict[str, Any]:
    """비교·복원용 프로젝트 상태. 저장 시 바뀌는 이름과 표 정렬에 따른 행 순서는 제외한다."""
    state = copy.deepcopy(project.to_dict())
    state.pop("name", None)
    for conn in state["connectors"]:
        conn["rows"].sort(key=lambda row: row["row_id"])
    return state


class StateHistory:
    """상태 스냅샷 하나를 대상으로 하는 실행 취소·다시 실행 이력 (부품 편집기의 부품별 이력, 제3.13절)."""

    def __init__(self, state: dict[str, Any], limit: int = HISTORY_LIMIT) -> None:
        self._limit = limit
        self._current = copy.deepcopy(state)
        self._undo: list[tuple[str, dict[str, Any]]] = []
        self._redo: list[tuple[str, dict[str, Any]]] = []

    @property
    def history_count(self) -> int:
        return len(self._undo)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_description(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    def redo_description(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def record(self, description: str, state: dict[str, Any]) -> bool:
        """편집을 마친 상태를 기록한다. 바뀌었으면 이전 상태를 한 단계로 남긴다."""
        if state == self._current:
            return False
        self._undo.append((description, self._current))
        del self._undo[: -self._limit]
        self._redo.clear()
        self._current = copy.deepcopy(state)
        return True

    def undo(self) -> tuple[str, dict[str, Any]] | None:
        """한 단계 되돌리고 (설명, 되돌린 상태)를 반환한다."""
        if not self._undo:
            return None
        description, state = self._undo.pop()
        self._redo.append((description, self._current))
        self._current = state
        return description, copy.deepcopy(state)

    def redo(self) -> tuple[str, dict[str, Any]] | None:
        """되돌린 단계를 다시 실행하고 (설명, 다시 실행한 상태)를 반환한다."""
        if not self._redo:
            return None
        description, state = self._redo.pop()
        self._undo.append((description, self._current))
        self._current = state
        return description, copy.deepcopy(state)


class CommandDispatcher:
    """편집 명령을 실행하고 편집 이력으로 실행 취소·다시 실행을 제공하는 편집 계층."""

    def __init__(
        self, project_getter: Callable[[], Project], limit: int = HISTORY_LIMIT
    ) -> None:
        self._project_getter = project_getter
        self._limit = limit
        self._undo: list[HistoryStep] = []
        self._redo: list[HistoryStep] = []
        self._current = project_state(project_getter())
        self._saved: dict[str, Any] | None = self._current

    @property
    def history_count(self) -> int:
        return len(self._undo)

    def reset(self, saved: bool = True) -> None:
        """새로 만들기·열기 후 현재 프로젝트를 기준 상태로 삼고 이력을 비운다."""
        self._undo.clear()
        self._redo.clear()
        self._current = project_state(self._project_getter())
        self._saved = self._current if saved else None

    clear = reset

    def mark_saved(self) -> None:
        self._saved = self._current

    def is_at_saved_state(self) -> bool:
        return self._saved is not None and self._current == self._saved

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_description(self) -> str:
        return self._undo[-1].description if self._undo else ""

    def redo_description(self) -> str:
        return self._redo[-1].description if self._redo else ""

    def record(
        self,
        description: str,
        focus: str | None = None,
        undo_focus: str | None = None,
    ) -> bool:
        """편집을 마친 뒤 호출한다. 상태가 바뀌었으면 이전 상태를 한 단계로 기록한다."""
        state = project_state(self._project_getter())
        if state == self._current:
            return False
        self._undo.append(
            HistoryStep(
                description,
                self._current,
                undo_focus if undo_focus is not None else focus,
                focus,
            )
        )
        del self._undo[: -self._limit]
        self._redo.clear()
        self._current = state
        return True

    def undo(self) -> HistoryStep | None:
        """한 단계 되돌리고 그 단계를 반환한다. 되돌린 뒤에는 focus_before를 보여 준다."""
        if not self._undo:
            return None
        step = self._undo.pop()
        self._redo.append(
            HistoryStep(step.description, self._current, step.focus_before, step.focus_after)
        )
        self._restore(step.state)
        return step

    def redo(self) -> HistoryStep | None:
        """되돌린 단계를 다시 실행하고 그 단계를 반환한다. 다시 실행한 뒤에는 focus_after를 보여 준다."""
        if not self._redo:
            return None
        step = self._redo.pop()
        self._undo.append(
            HistoryStep(step.description, self._current, step.focus_before, step.focus_after)
        )
        self._restore(step.state)
        return step

    def _restore(self, state: dict[str, Any]) -> None:
        # 화면이 참조하는 프로젝트 객체는 그대로 두고 내용만 바꾼다. 이름은 유지한다.
        project = self._project_getter()
        restored = Project.from_dict({**copy.deepcopy(state), "name": project.name})
        for f in fields(Project):
            setattr(project, f.name, getattr(restored, f.name))
        self._current = state

    def execute(
        self,
        description: str,
        action: Callable[[], bool],
        focus: str | None = None,
        undo_focus: str | None = None,
    ) -> bool:
        """명령 객체를 생성해 실행하고 성공하면 편집 이력에 기록한다."""
        ok = EditCommand(description=description, action=action).execute()
        if ok:
            self.record(description, focus, undo_focus)
        return ok

    def add_connector(
        self, designator: str, part: ConnectorPart | None = None
    ) -> bool:
        project = self._project_getter()

        def _do() -> bool:
            project.add_connector(designator, part)
            return True

        return self.execute(
            f"연결기 추가: {designator}", _do, focus=normalize_signal_name(designator)
        )

    def remove_connector(self, designator: str) -> bool:
        project = self._project_getter()
        return self.execute(
            f"연결기 제거: {designator}",
            lambda: project.remove_connector(designator),
            undo_focus=designator,
        )

    def rename_connector(
        self, old_designator: str, new_designator: str
    ) -> bool:
        project = self._project_getter()
        return self.execute(
            f"연결기 식별자 변경: {old_designator} -> {new_designator}",
            lambda: project.rename_connector(old_designator, new_designator),
            focus=new_designator,
            undo_focus=old_designator,
        )

    def change_connector_part(
        self, designator: str, new_part: ConnectorPart | None
    ) -> bool:
        project = self._project_getter()
        return self.execute(
            f"연결기 부품 변경: {designator}",
            lambda: project.change_connector_part(designator, new_part),
            focus=designator,
        )
