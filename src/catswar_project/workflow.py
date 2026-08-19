from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .city_war import CityWarController, CityWarScanResult, ControlResult
from .run_log import RunRecorder
from .screen_state import ScreenKind


class CityWarStep(StrEnum):
    RETURN_HOME = "return_home"
    ENTER_CITY_WAR = "enter_city_war"
    SCAN_MAP = "scan_map"
    SELECT_OPPONENT_AND_BOARD = "select_opponent_and_board"
    RETURN_AFTER_BATTLE = "return_after_battle"
    DONE = "done"
    FAILED = "failed"


DEFAULT_CITY_WAR_BOOTSTRAP_PLAN = (
    CityWarStep.RETURN_HOME,
    CityWarStep.ENTER_CITY_WAR,
    CityWarStep.SCAN_MAP,
    CityWarStep.SELECT_OPPONENT_AND_BOARD,
    CityWarStep.RETURN_AFTER_BATTLE,
)


@dataclass(frozen=True)
class StepTransition:
    current_step: CityWarStep
    screen_kind: ScreenKind
    success: bool
    message: str
    next_step: CityWarStep
    details: dict[str, Any]


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str | None
    success: bool
    final_step: CityWarStep
    transitions: tuple[StepTransition, ...]


class CityWarWorkflow:
    def __init__(self, controller: CityWarController, *, recorder: RunRecorder | None = None) -> None:
        self.controller = controller
        self.recorder = recorder

    def run(
        self,
        steps: Iterable[CityWarStep] = DEFAULT_CITY_WAR_BOOTSTRAP_PLAN,
        *,
        stop_on_failure: bool = True,
    ) -> WorkflowResult:
        plan = tuple(steps)
        transitions: list[StepTransition] = []
        for index, step in enumerate(plan):
            fallback_next = plan[index + 1] if index + 1 < len(plan) else CityWarStep.DONE
            transition = self.run_step(step, fallback_next=fallback_next)
            transitions.append(transition)
            if self.recorder is not None:
                self.recorder.event("city_war_step", {"transition": transition})
            if not transition.success and stop_on_failure:
                return WorkflowResult(
                    run_id=None if self.recorder is None else self.recorder.run_id,
                    success=False,
                    final_step=CityWarStep.FAILED,
                    transitions=tuple(transitions),
                )
        return WorkflowResult(
            run_id=None if self.recorder is None else self.recorder.run_id,
            success=all(transition.success for transition in transitions),
            final_step=CityWarStep.DONE,
            transitions=tuple(transitions),
        )

    def run_step(self, step: CityWarStep, *, fallback_next: CityWarStep = CityWarStep.DONE) -> StepTransition:
        if step == CityWarStep.RETURN_HOME:
            return _control_transition(step, self.controller.return_home(), fallback_next)
        if step == CityWarStep.ENTER_CITY_WAR:
            return _control_transition(step, self.controller.enter_city_war(), fallback_next)
        if step == CityWarStep.SCAN_MAP:
            return _scan_transition(step, self.controller.recognize_links_and_buildings(), fallback_next)
        if step == CityWarStep.SELECT_OPPONENT_AND_BOARD:
            return _control_transition(step, self.controller.select_opponent_and_board(), fallback_next)
        if step == CityWarStep.RETURN_AFTER_BATTLE:
            return _control_transition(step, self.controller.return_after_battle(), fallback_next)
        return StepTransition(
            current_step=step,
            screen_kind=ScreenKind.UNKNOWN,
            success=False,
            message="unknown_step",
            next_step=CityWarStep.FAILED,
            details={},
        )


def _control_transition(
    step: CityWarStep,
    result: ControlResult,
    fallback_next: CityWarStep,
) -> StepTransition:
    state_after = result.state_after or result.state_before
    return StepTransition(
        current_step=step,
        screen_kind=state_after.kind,
        success=result.success,
        message=result.message,
        next_step=fallback_next if result.success else CityWarStep.FAILED,
        details={
            "action": result.action_result.to_dict(),
            "target": result.target,
            "state_before": result.state_before,
            "state_after": result.state_after,
        },
    )


def _scan_transition(
    step: CityWarStep,
    result: CityWarScanResult,
    fallback_next: CityWarStep,
) -> StepTransition:
    success = result.state.kind == ScreenKind.CITY_WAR
    return StepTransition(
        current_step=step,
        screen_kind=result.state.kind,
        success=success,
        message="map_scanned" if success else "city_war_screen_not_detected",
        next_step=fallback_next if success else CityWarStep.FAILED,
        details={
            "state": result.state,
            "links": result.links,
            "buildings": result.buildings,
            "link_count": len(result.links),
            "building_count": len(result.buildings),
        },
    )
