from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .actions import ActionBackend, ActionResult, TapAction
from .screen_state import Marker, ScreenKind, ScreenRecognizer, ScreenState


HOME_MARKERS = ("home_marker", "main_city", "home_button")
CITY_WAR_ENTRY_MARKERS = ("city_war_entry", "war_button", "city_battle_entry")
CITY_WAR_SCREEN_MARKERS = ("city_war_marker", "city_war_title", "city_war_map")
LINK_MARKERS = ("link", "chain_link", "connection_line")
BUILDING_MARKERS = ("building", "tower", "base", "resource_building")
OPPONENT_MARKERS = ("opponent", "enemy", "target_player")
VEHICLE_MARKERS = ("vehicle", "car", "board_vehicle_button", "deploy_button")
BATTLE_RESULT_MARKERS = ("battle_result", "victory", "defeat", "result_confirm_button")

APP_PACKAGE = "com.zeptolab.cats.google"
APP_ACTIVITY = "com.zeptolab.cats.CATSActivity"


@dataclass(frozen=True)
class ControlResult:
    name: str
    state_before: ScreenState
    action_result: ActionResult
    state_after: ScreenState | None = None
    target: Marker | None = None
    success: bool = False
    message: str = ""


@dataclass(frozen=True)
class CityWarScanResult:
    state: ScreenState
    links: tuple[Marker, ...]
    buildings: tuple[Marker, ...]


class CityWarController:
    def __init__(
        self,
        *,
        recognizer: ScreenRecognizer,
        backend: ActionBackend,
        screenshot_provider: Callable[[], object] | None = None,
        min_confidence: float = 0.80,
        wait_seconds: float = 1.0,
        app_package: str = APP_PACKAGE,
        app_activity: str = APP_ACTIVITY,
    ) -> None:
        self.recognizer = recognizer
        self.backend = backend
        self.screenshot_provider = screenshot_provider
        self.min_confidence = min_confidence
        self.wait_seconds = wait_seconds
        self.app_package = app_package
        self.app_activity = app_activity

    def _ensure_app_foreground(self) -> ActionResult:
        if self.backend.is_app_foreground(self.app_package, self.app_activity):
            return ActionResult(
                "app_check",
                "executed",
                "app_foreground",
                success=True,
                action="ensure_app_foreground",
                message="app_already_foreground",
            )
        return self.backend.launch_app(self.app_package, self.app_activity, reason="return_home")

    def return_home(self, *, max_back_steps: int = 5) -> ControlResult:
        state = self._recognize()
        if state.kind == ScreenKind.HOME or state.has(*HOME_MARKERS, min_confidence=self.min_confidence):
            return ControlResult(
                name="return_home",
                state_before=state,
                action_result=ActionResult("no_action", "no_action", "already_home", action="no_action"),
                state_after=state,
                success=True,
                message="already_home",
            )

        last_result = self._ensure_app_foreground()
        if not last_result.success:
            return ControlResult(
                name="return_home",
                state_before=state,
                action_result=last_result,
                state_after=self._recognize(),
                success=False,
                message="app_not_foreground",
            )
        for _ in range(max_back_steps):
            last_result = self.backend.keyevent("BACK", "return_home")
            after = self._recognize()
            if after.kind == ScreenKind.HOME or after.has(*HOME_MARKERS, min_confidence=self.min_confidence):
                return ControlResult(
                    name="return_home",
                    state_before=state,
                    action_result=last_result,
                    state_after=after,
                    success=bool(last_result.success),
                    message="home_detected",
                )
            if not last_result.success:
                break
        return ControlResult(
            name="return_home",
            state_before=state,
            action_result=last_result,
            state_after=self._recognize(),
            success=False,
            message="home_not_detected",
        )

    def enter_city_war(self) -> ControlResult:
        state = self._recognize()
        if state.kind == ScreenKind.CITY_WAR or state.has(*CITY_WAR_SCREEN_MARKERS, min_confidence=self.min_confidence):
            return ControlResult(
                name="enter_city_war",
                state_before=state,
                action_result=ActionResult("no_action", "no_action", "already_city_war", action="no_action"),
                state_after=state,
                success=True,
                message="already_city_war",
            )

        entry = state.marker(*CITY_WAR_ENTRY_MARKERS, min_confidence=self.min_confidence)
        if entry is None or entry.center is None:
            return ControlResult(
                name="enter_city_war",
                state_before=state,
                action_result=ActionResult(
                    "tap",
                    "target_missing",
                    "city_war_entry_not_found",
                    success=False,
                    action="tap",
                    error="target_missing",
                ),
                success=False,
                message="city_war_entry_not_found",
            )

        action_result = self.backend.tap(_tap(entry, "enter_city_war"))
        after = self._recognize()
        return ControlResult(
            name="enter_city_war",
            state_before=state,
            action_result=action_result,
            state_after=after,
            target=entry,
            success=bool(action_result.success)
            and (after.kind == ScreenKind.CITY_WAR or after.has(*CITY_WAR_SCREEN_MARKERS, min_confidence=self.min_confidence)),
            message="city_war_detected" if after.kind == ScreenKind.CITY_WAR else "city_war_not_confirmed",
        )

    def recognize_links_and_buildings(self) -> CityWarScanResult:
        state = self._recognize()
        links = _filter_markers(state, LINK_MARKERS, self.min_confidence)
        buildings = _filter_markers(state, BUILDING_MARKERS, self.min_confidence)
        return CityWarScanResult(state=state, links=links, buildings=buildings)

    def select_opponent_and_board(self) -> ControlResult:
        state = self._recognize()
        opponent = state.marker(*OPPONENT_MARKERS, min_confidence=self.min_confidence)
        if opponent is None or opponent.center is None:
            return ControlResult(
                name="select_opponent_and_board",
                state_before=state,
                action_result=ActionResult(
                    "tap",
                    "target_missing",
                    "opponent_not_found",
                    success=False,
                    action="tap",
                    error="target_missing",
                ),
                success=False,
                message="opponent_not_found",
            )

        first_result = self.backend.tap(_tap(opponent, "select_opponent"))
        after_select = self._recognize()
        vehicle = after_select.marker(*VEHICLE_MARKERS, min_confidence=self.min_confidence)
        if vehicle is None or vehicle.center is None:
            return ControlResult(
                name="select_opponent_and_board",
                state_before=state,
                action_result=first_result,
                state_after=after_select,
                target=opponent,
                success=False,
                message="vehicle_button_not_found",
            )

        second_result = self.backend.tap(_tap(vehicle, "board_vehicle"))
        after_board = self._recognize()
        return ControlResult(
            name="select_opponent_and_board",
            state_before=state,
            action_result=second_result,
            state_after=after_board,
            target=vehicle,
            success=bool(first_result.success and second_result.success),
            message="board_vehicle_requested",
        )

    def return_after_battle(self, *, max_back_steps: int = 3) -> ControlResult:
        state = self._recognize()
        result_button = state.marker(*BATTLE_RESULT_MARKERS, min_confidence=self.min_confidence)
        if result_button is not None and result_button.center is not None:
            action_result = self.backend.tap(_tap(result_button, "confirm_battle_result"))
        else:
            action_result = self.backend.keyevent("BACK", "return_after_battle")

        after = self._recognize()
        if after.kind in {ScreenKind.CITY_WAR, ScreenKind.HOME}:
            return ControlResult(
                name="return_after_battle",
                state_before=state,
                action_result=action_result,
                state_after=after,
                target=result_button,
                success=bool(action_result.success),
                message="battle_return_confirmed",
            )

        for _ in range(max_back_steps):
            action_result = self.backend.keyevent("BACK", "return_after_battle")
            after = self._recognize()
            if after.kind in {ScreenKind.CITY_WAR, ScreenKind.HOME}:
                return ControlResult(
                    name="return_after_battle",
                    state_before=state,
                    action_result=action_result,
                    state_after=after,
                    success=bool(action_result.success),
                    message="battle_return_confirmed",
                )
        return ControlResult(
            name="return_after_battle",
            state_before=state,
            action_result=action_result,
            state_after=after,
            success=False,
            message="battle_return_not_confirmed",
        )

    def _recognize(self) -> ScreenState:
        image_path = None
        if self.screenshot_provider is not None:
            image_path = self.screenshot_provider()
        return self.recognizer.recognize(image_path)


def return_home(controller: CityWarController, *, max_back_steps: int = 5) -> ControlResult:
    return controller.return_home(max_back_steps=max_back_steps)


def enter_city_war(controller: CityWarController) -> ControlResult:
    return controller.enter_city_war()


def recognize_links_and_buildings(controller: CityWarController) -> CityWarScanResult:
    return controller.recognize_links_and_buildings()


def select_opponent_and_board(controller: CityWarController) -> ControlResult:
    return controller.select_opponent_and_board()


def return_after_battle(controller: CityWarController, *, max_back_steps: int = 3) -> ControlResult:
    return controller.return_after_battle(max_back_steps=max_back_steps)


def _tap(marker: Marker, reason: str) -> TapAction:
    if marker.center is None:
        raise ValueError(f"marker has no center: {marker.name}")
    return TapAction(
        x=marker.center[0],
        y=marker.center[1],
        confidence=marker.confidence,
        reason=reason,
    )


def _filter_markers(
    state: ScreenState,
    names: tuple[str, ...],
    min_confidence: float,
) -> tuple[Marker, ...]:
    wanted = set(names)
    return tuple(
        sorted(
            (
                marker
                for marker in state.markers
                if marker.name in wanted and marker.confidence >= min_confidence
            ),
            key=lambda marker: marker.confidence,
            reverse=True,
        )
    )
