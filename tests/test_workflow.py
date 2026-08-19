from __future__ import annotations

import json

from catswar_project.actions import ActionResult, TapAction
from catswar_project.city_war import CityWarController
from catswar_project.run_log import RunRecorder
from catswar_project.screen_state import Marker, ScreenKind, ScreenState, StaticScreenRecognizer
from catswar_project.workflow import CityWarStep, CityWarWorkflow


class RecordingBackend:

    def __init__(self) -> None:
        self.action_count = 0
        self.taps: list[TapAction] = []
        self.keyevents: list[str] = []

    def click(self, action):
        return self.tap(action)

    def tap(self, action: TapAction) -> ActionResult:
        self.action_count += 1
        self.taps.append(action)
        return ActionResult(
            "adb_tap",
            "executed",
            action.reason,
            action="tap",
            clicked_pos=(action.x, action.y),
        )

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        return ActionResult("wait", "executed", reason, action="wait")

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        self.action_count += 1
        self.keyevents.append(keycode)
        return ActionResult("adb_keyevent", "executed", reason, action="press_back")

    def reset_cycle(self) -> None:
        self.action_count = 0


def marker(name: str, x: int = 100, y: int = 100, confidence: float = 0.95) -> Marker:
    return Marker(name=name, confidence=confidence, center=(x, y))


def test_city_war_workflow_runs_explicit_step_plan(tmp_path) -> None:
    recognizer = StaticScreenRecognizer(
        [
            ScreenState(ScreenKind.HOME),
            ScreenState(ScreenKind.HOME, markers=(marker("city_war_entry", 10, 20),)),
            ScreenState(ScreenKind.CITY_WAR),
            ScreenState(
                ScreenKind.CITY_WAR,
                markers=(marker("link"), marker("building")),
            ),
            ScreenState(ScreenKind.CITY_WAR, markers=(marker("opponent", 30, 40),)),
            ScreenState(ScreenKind.OPPONENT_SELECT, markers=(marker("board_vehicle_button", 50, 60),)),
            ScreenState(ScreenKind.BATTLE_RUNNING),
            ScreenState(ScreenKind.BATTLE_RESULT, markers=(marker("result_confirm_button", 70, 80),)),
            ScreenState(ScreenKind.CITY_WAR),
        ]
    )
    recorder = RunRecorder(tmp_path, run_id="test-run")
    workflow = CityWarWorkflow(
        CityWarController(recognizer=recognizer, backend=RecordingBackend()),
        recorder=recorder,
    )

    result = workflow.run()

    assert result.success is True
    assert result.final_step == CityWarStep.DONE
    assert [transition.current_step for transition in result.transitions] == [
        CityWarStep.RETURN_HOME,
        CityWarStep.ENTER_CITY_WAR,
        CityWarStep.SCAN_MAP,
        CityWarStep.SELECT_OPPONENT_AND_BOARD,
        CityWarStep.RETURN_AFTER_BATTLE,
    ]
    assert (tmp_path / "latest" / "run_id.txt").read_text(encoding="utf-8") == "test-run"
    events = (tmp_path / "runs" / "test-run" / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 5
    assert json.loads(events[2])["payload"]["transition"]["details"]["link_count"] == 1


def test_city_war_workflow_stops_on_failed_step() -> None:
    workflow = CityWarWorkflow(
        CityWarController(
            recognizer=StaticScreenRecognizer([ScreenState(ScreenKind.HOME)]),
            backend=RecordingBackend(),
        )
    )

    result = workflow.run([CityWarStep.ENTER_CITY_WAR, CityWarStep.SCAN_MAP])

    assert result.success is False
    assert result.final_step == CityWarStep.FAILED
    assert len(result.transitions) == 1
    assert result.transitions[0].message == "city_war_entry_not_found"
