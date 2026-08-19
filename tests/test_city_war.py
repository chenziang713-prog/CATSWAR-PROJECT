from __future__ import annotations

from catswar_project.actions import ActionResult, TapAction
from catswar_project.city_war import (
    CityWarController,
    enter_city_war,
    recognize_links_and_buildings,
    return_after_battle,
    return_home,
    select_opponent_and_board,
)
from catswar_project.screen_state import Marker, ScreenKind, ScreenState, StaticScreenRecognizer


class RecordingBackend:

    def __init__(self) -> None:
        self.action_count = 0
        self.taps: list[TapAction] = []
        self.keyevents: list[str] = []
        self.waits: list[float] = []

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
        self.waits.append(seconds)
        return ActionResult("wait", "executed", reason, action="wait")

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        self.action_count += 1
        self.keyevents.append(keycode)
        return ActionResult("adb_keyevent", "executed", reason, action="press_back")

    def reset_cycle(self) -> None:
        self.action_count = 0


def marker(name: str, x: int = 100, y: int = 100, confidence: float = 0.95) -> Marker:
    return Marker(name=name, confidence=confidence, center=(x, y))


def controller(states: list[ScreenState]) -> tuple[CityWarController, RecordingBackend]:
    backend = RecordingBackend()
    return CityWarController(recognizer=StaticScreenRecognizer(states), backend=backend), backend


def test_return_home_presses_back_until_home_detected() -> None:
    ctrl, backend = controller(
        [
            ScreenState(ScreenKind.CITY_WAR),
            ScreenState(ScreenKind.POPUP),
            ScreenState(ScreenKind.HOME, markers=(marker("home_marker"),)),
        ]
    )

    result = return_home(ctrl)

    assert result.success is True
    assert result.message == "home_detected"
    assert backend.keyevents == ["BACK", "BACK"]


def test_return_home_noops_when_already_home() -> None:
    ctrl, backend = controller([ScreenState(ScreenKind.HOME)])

    result = return_home(ctrl)

    assert result.success is True
    assert result.action_result.action == "no_action"
    assert backend.action_count == 0


def test_enter_city_war_taps_entry_and_confirms_city_war() -> None:
    ctrl, backend = controller(
        [
            ScreenState(ScreenKind.HOME, markers=(marker("city_war_entry", 320, 640),)),
            ScreenState(ScreenKind.CITY_WAR, markers=(marker("city_war_marker"),)),
        ]
    )

    result = enter_city_war(ctrl)

    assert result.success is True
    assert result.target is not None
    assert result.target.name == "city_war_entry"
    assert backend.taps[0].x == 320
    assert backend.taps[0].y == 640


def test_enter_city_war_reports_missing_entry() -> None:
    ctrl, backend = controller([ScreenState(ScreenKind.HOME)])

    result = enter_city_war(ctrl)

    assert result.success is False
    assert result.message == "city_war_entry_not_found"
    assert backend.action_count == 0


def test_recognize_links_and_buildings_filters_city_war_markers() -> None:
    ctrl, _ = controller(
        [
            ScreenState(
                ScreenKind.CITY_WAR,
                markers=(
                    marker("link", confidence=0.91),
                    marker("building", confidence=0.93),
                    marker("opponent", confidence=0.99),
                    marker("tower", confidence=0.50),
                ),
            )
        ]
    )

    result = recognize_links_and_buildings(ctrl)

    assert [item.name for item in result.links] == ["link"]
    assert [item.name for item in result.buildings] == ["building"]


def test_select_opponent_and_board_taps_opponent_then_vehicle() -> None:
    ctrl, backend = controller(
        [
            ScreenState(ScreenKind.CITY_WAR, markers=(marker("opponent", 10, 20),)),
            ScreenState(ScreenKind.OPPONENT_SELECT, markers=(marker("board_vehicle_button", 30, 40),)),
            ScreenState(ScreenKind.BATTLE_RUNNING),
        ]
    )

    result = select_opponent_and_board(ctrl)

    assert result.success is True
    assert result.message == "board_vehicle_requested"
    assert [(tap.x, tap.y, tap.reason) for tap in backend.taps] == [
        (10, 20, "select_opponent"),
        (30, 40, "board_vehicle"),
    ]


def test_select_opponent_and_board_reports_missing_vehicle() -> None:
    ctrl, backend = controller(
        [
            ScreenState(ScreenKind.CITY_WAR, markers=(marker("opponent", 10, 20),)),
            ScreenState(ScreenKind.OPPONENT_SELECT),
        ]
    )

    result = select_opponent_and_board(ctrl)

    assert result.success is False
    assert result.message == "vehicle_button_not_found"
    assert len(backend.taps) == 1


def test_return_after_battle_confirms_result_button() -> None:
    ctrl, backend = controller(
        [
            ScreenState(ScreenKind.BATTLE_RESULT, markers=(marker("result_confirm_button", 500, 600),)),
            ScreenState(ScreenKind.CITY_WAR),
        ]
    )

    result = return_after_battle(ctrl)

    assert result.success is True
    assert result.message == "battle_return_confirmed"
    assert backend.taps[0].reason == "confirm_battle_result"


def test_return_after_battle_uses_back_when_no_result_button() -> None:
    ctrl, backend = controller(
        [
            ScreenState(ScreenKind.BATTLE_RESULT),
            ScreenState(ScreenKind.UNKNOWN),
            ScreenState(ScreenKind.HOME),
        ]
    )

    result = return_after_battle(ctrl)

    assert result.success is True
    assert backend.keyevents == ["BACK", "BACK"]
