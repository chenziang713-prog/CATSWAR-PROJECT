from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .actions import ActionBackend, ActionResult, TapAction
from .city_war import CITY_WAR_ENTRY_MARKERS, _tap
from .run_log import RunRecorder
from .screen_state import Marker, ScreenKind, ScreenState
from .strategy import BuildingTarget, available_vehicles, parse_building_value, rank_buildings, required_vehicles


@dataclass(frozen=True)
class AutomationOptions:
    wait_timeout: float = 180.0
    poll_interval: float = 2.0
    retry_limit: int = 3
    safety_mode: str = "aggressive"


@dataclass(frozen=True)
class AccountAutomationResult:
    account_id: str
    success: bool
    status: str
    message: str
    joined: bool
    battles: int = 0
    skipped: tuple[str, ...] = ()
    last_state: ScreenKind = ScreenKind.UNKNOWN


class CityWarAutomation:
    """State-driven end-to-end runner for one ADB-connected account."""

    def __init__(
        self,
        *,
        account_id: str,
        recognizer,
        backend: ActionBackend,
        capture: Callable[[], Path],
        recorder: RunRecorder | None = None,
        options: AutomationOptions | None = None,
        checkpoint: dict[str, object] | None = None,
    ) -> None:
        self.account_id = account_id
        self.recognizer = recognizer
        self.backend = backend
        self.capture = capture
        self.recorder = recorder
        self.options = options or AutomationOptions()
        self.checkpoint = checkpoint or {}
        self.joined = bool(self.checkpoint.get("joined", False))
        self.battles = int(self.checkpoint.get("battles", 0))
        self.skipped: list[str] = list(self.checkpoint.get("skipped", []))
        self.last_state = ScreenKind.UNKNOWN

    def run(self) -> AccountAutomationResult:
        try:
            if not self.joined:
                self._join_flow()
                self.joined = True
                self._checkpoint("joined")
            self._battle_loop()
            self._checkpoint("completed")
            return AccountAutomationResult(self.account_id, True, "completed", "no_available_vehicles", True,
                                           self.battles, tuple(self.skipped), self.last_state)
        except AutomationPaused as exc:
            self._checkpoint("paused", error=str(exc))
            return AccountAutomationResult(self.account_id, False, "paused", str(exc), self.joined,
                                           self.battles, tuple(self.skipped), self.last_state)
        except Exception as exc:
            self._checkpoint("failed", error=str(exc))
            return AccountAutomationResult(self.account_id, False, "failed", str(exc), self.joined,
                                           self.battles, tuple(self.skipped), self.last_state)

    def _join_flow(self) -> None:
        state = self._state()
        if state.kind == ScreenKind.BUILDING_MAP:
            return
        self._dismiss_popup(state)
        if state.kind == ScreenKind.HOME:
            # The safe live entry is the top guild/people icon. Keep the
            # legacy city_war_entry name for synthetic tests and checkpoints.
            self._tap_named(state, ("guild_entry", "city_war_entry"), "enter_city_war")
            state = self._wait_for({ScreenKind.CITY_WAR, ScreenKind.BUILDING_MAP})
        if state.kind == ScreenKind.BUILDING_MAP:
            return
        state = self._wait_for_markers({"join_button"}, {ScreenKind.CITY_WAR, ScreenKind.BUILDING_MAP})
        if state.kind == ScreenKind.BUILDING_MAP:
            return
        join = state.marker("join_button")
        if join is not None:
            self._tap(join, "join_city_war")
        state = self._wait_for({ScreenKind.LOADOUT_CONFIRM, ScreenKind.BATTLE_START_CONFIRM, ScreenKind.BUILDING_MAP})
        if state.kind == ScreenKind.LOADOUT_CONFIRM:
            self._tap_named(state, ("loadout_start",), "confirm_loadout")
            state = self._wait_for({ScreenKind.BATTLE_START_CONFIRM, ScreenKind.BUILDING_MAP})
        if state.kind == ScreenKind.BATTLE_START_CONFIRM:
            self._tap_named(state, ("battle_start_confirm",), "start_city_war")
            self._wait_for({ScreenKind.BUILDING_MAP})

    def _battle_loop(self) -> None:
        for _ in range(100):
            state = self._state()
            if state.kind == ScreenKind.POPUP:
                self._dismiss_popup(state)
                continue
            if state.kind != ScreenKind.BUILDING_MAP:
                if state.kind in {ScreenKind.BATTLE_RESULT, ScreenKind.BATTLE_RUNNING}:
                    self._finish_battle(state)
                    continue
                state = self._wait_for({ScreenKind.BUILDING_MAP})
            targets = self._buildings(state)
            ranked = rank_buildings(targets)
            if not ranked:
                return
            target = ranked[0]
            if target.marker is None or target.marker.center is None:
                self.skipped.append(f"{target.name}:missing_point")
                return
            self._tap(target.marker, f"select_building:{target.name}")
            state = self._wait_for({ScreenKind.CITY_WAR_ATTACK_ENTRY, ScreenKind.ATTACK_DEFENSE,
                                    ScreenKind.VEHICLE_SELECT, ScreenKind.OPPONENT_SELECT,
                                    ScreenKind.BUILDING_MAP})
            if state.kind == ScreenKind.BUILDING_MAP:
                continue
            # City-war has two separate attack controls. The red entry opens
            # the battle panel; only a fresh recognition may authorize the
            # lower-left attack tap that follows it.
            if state.kind == ScreenKind.CITY_WAR_ATTACK_ENTRY:
                self._tap_named(state, ("attack_entry",), "select_red_attack_entry")
                state = self._wait_for({ScreenKind.ATTACK_DEFENSE})
            if state.kind == ScreenKind.ATTACK_DEFENSE:
                self._tap_named(state, ("attack_button",), "select_attack")
                state = self._wait_for({ScreenKind.VEHICLE_SELECT, ScreenKind.OPPONENT_SELECT})
            own_vehicles = available_vehicles(_own_vehicle_markers(state))
            if own_vehicles:
                self._tap(own_vehicles[0].marker, f"select_own_vehicle:{own_vehicles[0].index + 1}")
                state = self._state()
            vehicles = available_vehicles(_vehicle_markers(state))
            if not vehicles:
                self.skipped.append(f"{target.name}:no_available_vehicle")
                self._back_to_map()
                continue
            attacked = False
            for vehicle in vehicles:
                self._tap(vehicle.marker, f"select_vehicle:{vehicle.index}")
                after = self._state()
                if after.kind == ScreenKind.POPUP and after.has("busy_popup"):
                    self._tap_named(after, ("result_confirm_button",), "dismiss_busy")
                    self.skipped.append(f"{target.name}:vehicle_{vehicle.index}:busy")
                    continue
                if after.kind in {ScreenKind.VEHICLE_SELECT, ScreenKind.OPPONENT_SELECT, ScreenKind.BATTLE_RUNNING}:
                    watch = after.marker("watch_button")
                    if watch is not None:
                        self._tap(watch, "watch_battle")
                    self._finish_battle(self._wait_for({ScreenKind.BATTLE_RUNNING, ScreenKind.BATTLE_RESULT,
                                                         ScreenKind.BUILDING_MAP}))
                    self.battles += 1
                    attacked = True
                    break
            if not attacked:
                self._back_to_map()
        raise AutomationPaused("automation iteration limit reached")

    def _finish_battle(self, state: ScreenState) -> None:
        if state.kind == ScreenKind.BATTLE_RUNNING:
            state = self._wait_for({ScreenKind.BATTLE_RESULT, ScreenKind.BUILDING_MAP})
        if state.kind == ScreenKind.BATTLE_RESULT:
            button = state.marker("result_confirm_button")
            if button is not None:
                self._tap(button, "confirm_battle_result")
        self._wait_for({ScreenKind.BUILDING_MAP, ScreenKind.HOME})

    def _back_to_map(self) -> None:
        self.backend.keyevent("BACK", "return_to_building_map")
        self._wait_for({ScreenKind.BUILDING_MAP, ScreenKind.HOME})

    def _state(self) -> ScreenState:
        state = self.recognizer.recognize(self.capture())
        self.last_state = state.kind
        if self.recorder:
            self.recorder.event("screen_state", {"account_id": self.account_id, "state": state})
        return state

    def _wait_for(self, kinds: set[ScreenKind]) -> ScreenState:
        deadline = time.monotonic() + self.options.wait_timeout
        last = self._state()
        while time.monotonic() < deadline:
            if last.kind in kinds:
                return last
            if last.kind == ScreenKind.POPUP:
                self._dismiss_popup(last)
            time.sleep(self.options.poll_interval)
            last = self._state()
        raise AutomationPaused(f"timeout waiting for {','.join(kind.value for kind in kinds)}; got {last.kind.value}")

    def _wait_for_markers(self, names: set[str], kinds: set[ScreenKind]) -> ScreenState:
        deadline = time.monotonic() + self.options.wait_timeout
        last = self._state()
        while time.monotonic() < deadline:
            if last.kind in kinds and any(last.has(name) for name in names):
                return last
            if last.kind == ScreenKind.POPUP:
                self._dismiss_popup(last)
            time.sleep(self.options.poll_interval)
            last = self._state()
        raise AutomationPaused(f"timeout waiting for markers {sorted(names)}")

    def _dismiss_popup(self, state: ScreenState) -> None:
        if state.has("distraction_popup"):
            self.backend.keyevent("BACK", "dismiss_distraction")
            return
        confirm = state.marker("popup_confirm_button", "result_confirm_button")
        if confirm is not None:
            self._tap(confirm, "dismiss_popup")
        else:
            self.backend.keyevent("BACK", "dismiss_popup")

    def _tap_named(self, state: ScreenState, names: tuple[str, ...], reason: str) -> ActionResult:
        target = state.marker(*names)
        if target is None:
            raise AutomationPaused(f"marker not found: {','.join(names)}")
        return self._tap(target, reason)

    def _tap(self, marker: Marker, reason: str) -> ActionResult:
        if marker.center is None:
            raise AutomationPaused(f"marker has no point: {marker.name}")
        if self.options.safety_mode == "guarded" and marker.confidence < 0.80:
            raise AutomationPaused(
                f"guarded mode rejected low-confidence action {reason}: {marker.confidence:.3f}"
            )
        result = self.backend.tap(_tap(marker, reason))
        if not result.success:
            raise AutomationPaused(f"action failed: {reason}")
        if self.recorder:
            self.recorder.event("action", {"account_id": self.account_id, "reason": reason, "result": result})
        return result

    def _buildings(self, state: ScreenState) -> tuple[BuildingTarget, ...]:
        markers = [marker for marker in state.markers if marker.name == "building"]
        values = [marker for marker in state.markers if marker.name == "building_value"]
        result = []
        ordered = _order_buildings(markers)
        unused_values = set(range(len(values)))
        for priority, marker in enumerate(ordered):
            content = str((marker.metadata or {}).get("content", marker.name))
            value = parse_building_value(content)
            matched_index = None
            if value is None and marker.center is not None and unused_values:
                matched_index = min(unused_values, key=lambda index: _distance(marker, values[index]))
                candidate = values[matched_index]
                if _distance(marker, candidate) <= 300:
                    value = int((candidate.metadata or {}).get("value", 0)) or parse_building_value(
                        str((candidate.metadata or {}).get("content", ""))
                    )
                else:
                    matched_index = None
            if matched_index is not None:
                unused_values.remove(matched_index)
            if value is None:
                # A building without an independently associated X is not a
                # valid target; never invent X=1 from a label or resource digit.
                continue
            metadata = marker.metadata or {}
            side = metadata.get("side")
            owned_by_us = side == "us" if side in {"us", "enemy"} else None
            result.append(BuildingTarget(content, value, required_vehicles(value), priority,
                                         owned_by_us=owned_by_us, marker=marker))
        return tuple(result)

    def _checkpoint(self, status: str, **extra: object) -> None:
        payload = {"account_id": self.account_id, "status": status, "joined": self.joined,
                   "battles": self.battles, "skipped": self.skipped, "last_state": self.last_state, **extra}
        if self.recorder:
            self.recorder.write_checkpoint(payload)
            self.recorder.event("checkpoint", payload)


class AutomationPaused(RuntimeError):
    pass


def _vehicle_markers(state: ScreenState) -> tuple[Marker, ...]:
    return tuple(marker for marker in state.markers if marker.name in {
        "vehicle_target", "vehicle_locked", "vehicle_repair",
    })


def _own_vehicle_markers(state: ScreenState) -> tuple[Marker, ...]:
    return tuple(marker for marker in state.markers if marker.name in {
        "own_vehicle_selector", "own_vehicle_repair",
    })


def _order_buildings(markers: list[Marker]) -> tuple[Marker, ...]:
    points = [marker.center for marker in markers if marker.center is not None]
    if len(points) < 2:
        return tuple(markers)
    cx = sum(point[0] for point in points) / len(points)
    cy = sum(point[1] for point in points) / len(points)
    return tuple(sorted(
        markers,
        key=lambda marker: math.atan2((marker.center or (0, 0))[1] - cy,
                                      (marker.center or (0, 0))[0] - cx),
    ))


def _distance(left: Marker, right: Marker) -> int:
    if left.center is None or right.center is None:
        return 10**9
    return abs(left.center[0] - right.center[0]) + abs(left.center[1] - right.center[1])
