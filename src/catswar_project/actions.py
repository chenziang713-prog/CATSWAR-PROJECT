from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO


@dataclass(frozen=True)
class ClickAction:
    x: int
    y: int
    confidence: float
    reason: str
    min_confidence_override: float | None = None


@dataclass(frozen=True)
class TapAction:
    x: int
    y: int
    confidence: float
    reason: str
    min_confidence_override: float | None = None


@dataclass(frozen=True)
class ActionResult:
    action_type: str
    result: str
    reason: str = ""
    notes: str = ""
    success: bool | None = None
    action: str = ""
    message: str = ""
    clicked_pos: tuple[int, int] | None = None
    duration: float = 0.0
    error: str = ""

    def __post_init__(self) -> None:
        if self.success is None:
            object.__setattr__(
                self,
                "success",
                self.result in {"executed", "no_action"},
            )
        if not self.action:
            object.__setattr__(self, "action", self.action_type)
        if not self.message:
            object.__setattr__(self, "message", self.notes or self.result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "action": self.action,
            "message": self.message,
            "clicked_pos": None if self.clicked_pos is None else list(self.clicked_pos),
            "duration": self.duration,
            "error": self.error or None,
            "action_type": self.action_type,
            "result": self.result,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ActionInput:
    name: str
    params: Mapping[str, Any] | None = None
    reason: str = ""


class ActionBackend(Protocol):
    action_count: int

    def click(self, action: ClickAction) -> ActionResult: ...

    def tap(self, action: TapAction) -> ActionResult: ...

    def wait(self, seconds: float, reason: str = "") -> ActionResult: ...

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult: ...

    def is_app_foreground(self, package_name: str, activity_name: str) -> bool: ...

    def launch_app(self, package_name: str, activity_name: str, reason: str = "") -> ActionResult: ...

    def reset_cycle(self) -> None: ...


SubprocessRun = Callable[..., subprocess.CompletedProcess[bytes]]


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


class AdbActionBackend:
    def __init__(
        self,
        *,
        adb_path: Path,
        adb_serial: str,
        max_actions: int = 1,
        click_cooldown: float = 1.0,
        min_click_confidence: float = 0.80,
        stop_file: Path | None = None,
        log_file: Path | None = None,
        runner: SubprocessRun = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        instance_dir: Path | None = None,
        cmd_dir: Path | None = None,
    ) -> None:
        self.adb_path = Path(adb_path)
        self.adb_serial = adb_serial
        self.max_actions = max_actions
        self.click_cooldown = click_cooldown
        self.min_click_confidence = min_click_confidence
        self.stop_file = stop_file
        self.runner = runner
        self.sleep = sleep
        self.instance_dir = Path(instance_dir) if instance_dir is not None else None
        self.cmd_dir = Path(cmd_dir) if cmd_dir is not None else None
        self.action_count = 0
        self.last_click_at = 0.0
        self._log_handle: TextIO | None = None

        if self.instance_dir is not None:
            self.instance_dir.mkdir(parents=True, exist_ok=True)
        if self.cmd_dir is not None and not self.cmd_dir.exists():
            raise ValueError(f"cmd_dir does not exist: {self.cmd_dir}")

        if self.max_actions <= 0:
            raise ValueError("max_actions must be greater than 0.")
        if self.click_cooldown < 0:
            raise ValueError("click_cooldown must not be negative.")
        if not 0 <= self.min_click_confidence <= 1:
            raise ValueError("min_click_confidence must be between 0 and 1.")
        if not self.adb_path.exists():
            raise ValueError(f"ADB executable does not exist: {self.adb_path}")
        if not self.adb_path.is_file():
            raise ValueError(f"ADB path is not a file: {self.adb_path}")
        if not self.adb_serial.strip():
            raise ValueError("adb_serial must not be empty.")
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_file.open("a", encoding="utf-8")

    def click(self, action: ClickAction) -> ActionResult:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping ADB tap: {self.stop_file}")
            return ActionResult("adb_tap", "skipped_stop_file", action.reason)
        min_confidence = (
            self.min_click_confidence
            if action.min_confidence_override is None
            else action.min_confidence_override
        )
        if action.confidence < min_confidence:
            self._emit(
                "Confidence too low for ADB tap "
                f"confidence={action.confidence:.3f} min={min_confidence:.3f}"
            )
            return ActionResult(
                "adb_tap",
                "skipped_confidence_too_low",
                "click_confidence_too_low",
                f"original_reason={action.reason}",
            )
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping ADB tap.")
            return ActionResult("adb_tap", "skipped_max_actions_reached", action.reason)

        now = time.monotonic()
        elapsed = now - self.last_click_at
        if self.action_count > 0 and elapsed < self.click_cooldown:
            wait_seconds = self.click_cooldown - elapsed
            self._emit(f"Waiting {wait_seconds:.2f}s for click cooldown.")
            self.sleep(wait_seconds)
            now = time.monotonic()

        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "shell",
            "input",
            "tap",
            str(action.x),
            str(action.y),
        ]
        result = self._run(command)
        if result.returncode != 0:
            self._emit(f"ADB tap failed: {result.stderr or result.returncode}")
            return ActionResult("adb_tap", "adb_tap_failed", action.reason)

        self.action_count += 1
        self.last_click_at = now
        self._emit(
            "ADB tap "
            f"x={action.x} y={action.y} confidence={action.confidence:.3f} "
            f"reason={action.reason}"
        )
        return ActionResult("adb_tap", "executed", action.reason)

    def tap(self, action: TapAction) -> ActionResult:
        return self.click(
            ClickAction(
                x=action.x,
                y=action.y,
                confidence=action.confidence,
                reason=action.reason,
                min_confidence_override=action.min_confidence_override,
            )
        )

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        safe_seconds = max(0.0, seconds)
        self._emit(f"ADB wait seconds={safe_seconds:.2f} reason={reason}")
        started = time.monotonic()
        self.sleep(safe_seconds)
        return ActionResult(
            "wait",
            "executed",
            reason,
            success=True,
            action="wait",
            message="wait_finished",
            duration=time.monotonic() - started,
        )

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping ADB keyevent: {self.stop_file}")
            return ActionResult("adb_keyevent", "skipped_stop_file", reason)
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping ADB keyevent.")
            return ActionResult("adb_keyevent", "skipped_max_actions_reached", reason)

        now = time.monotonic()
        elapsed = now - self.last_click_at
        if self.action_count > 0 and elapsed < self.click_cooldown:
            wait_seconds = self.click_cooldown - elapsed
            self._emit(f"Waiting {wait_seconds:.2f}s for action cooldown.")
            self.sleep(wait_seconds)
            now = time.monotonic()

        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "shell",
            "input",
            "keyevent",
            keycode,
        ]
        result = self._run(command)
        if result.returncode != 0:
            self._emit(f"ADB keyevent failed: {result.stderr or result.returncode}")
            return ActionResult("adb_keyevent", "adb_keyevent_failed", reason)

        self.action_count += 1
        self.last_click_at = now
        self._emit(f"ADB keyevent keycode={keycode} reason={reason}")
        return ActionResult("adb_keyevent", "executed", reason)

    def is_app_foreground(self, package_name: str, activity_name: str) -> bool:
        if not package_name.strip():
            raise ValueError("package_name must not be empty.")
        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "shell",
            "dumpsys",
            "activity",
            "activities",
        ]
        result = self._run(command)
        if result.returncode != 0:
            self._emit(f"ADB dumpsys failed: {result.stderr or result.returncode}")
            return False
        output = _decode(result.stdout)
        target = f"{package_name}/{activity_name}"
        return target in output or package_name in output

    def launch_app(self, package_name: str, activity_name: str, reason: str = "") -> ActionResult:
        if self.stop_file is not None and self.stop_file.exists():
            self._emit(f"STOP file present, skipping app launch: {self.stop_file}")
            return ActionResult("adb_launch_app", "skipped_stop_file", reason)
        if self.action_count >= self.max_actions:
            self._emit(f"Max actions reached ({self.max_actions}), skipping app launch.")
            return ActionResult("adb_launch_app", "skipped_max_actions_reached", reason)
        if not package_name.strip():
            raise ValueError("package_name must not be empty.")
        if not activity_name.strip():
            raise ValueError("activity_name must not be empty.")

        command = [
            str(self.adb_path),
            "-s",
            self.adb_serial,
            "shell",
            "am",
            "start",
            "-n",
            f"{package_name}/{activity_name}",
        ]
        result = self._run(command)
        if result.returncode != 0:
            self._emit(f"ADB app launch failed: {result.stderr or result.returncode}")
            return ActionResult("adb_launch_app", "adb_launch_failed", reason)

        self.action_count += 1
        self._emit(f"ADB launch app package={package_name} activity={activity_name} reason={reason}")
        return ActionResult(
            "adb_launch_app",
            "executed",
            reason,
            success=True,
            action="launch_app",
            message="app_launched",
        )

    def reset_cycle(self) -> None:
        self.action_count = 0
        self.last_click_at = 0.0

    def close(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return self.runner(command, capture_output=True)
        except OSError as exc:
            self._emit(f"Failed to run ADB tap command: {exc}")
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=str(exc).encode())

    def _emit(self, message: str) -> None:
        print(message)
        if self._log_handle is not None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self._log_handle.write(f"{timestamp} {message}\n")
            self._log_handle.flush()


def normalize_action_input(action: str | Mapping[str, Any] | ActionInput) -> ActionInput:
    if isinstance(action, ActionInput):
        return action
    if isinstance(action, str):
        return ActionInput(name=action, params={}, reason="")
    name = str(action.get("name", "")).strip()
    params = action.get("params", {})
    if not isinstance(params, Mapping):
        params = {}
    reason = str(action.get("reason", ""))
    return ActionInput(name=name, params=params, reason=reason)


def execute_action(
    action: str | Mapping[str, Any] | ActionInput,
    backend: ActionBackend,
    *,
    state_result: Mapping[str, Any] | None = None,
    allowed_markers: set[str] | frozenset[str] | None = None,
    max_wait_seconds: float = 5.0,
) -> ActionResult:
    action_input = normalize_action_input(action)
    name = action_input.name
    params = action_input.params or {}
    reason = action_input.reason
    if name == "no_action":
        return ActionResult("no_action", "no_action", reason, action="no_action")
    if name == "wait":
        seconds = float(params.get("seconds", 0.0))
        seconds = min(seconds, max_wait_seconds)
        return backend.wait(seconds, reason)
    if name == "press_back":
        return backend.keyevent("BACK", reason)
    if name in {"tap", "click"}:
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        confidence = float(params.get("confidence", 1.0))
        return backend.tap(TapAction(x=x, y=y, confidence=confidence, reason=reason))

    return ActionResult(
        name or "unknown_action",
        "unknown_action",
        reason,
        success=False,
        action=name or "unknown_action",
        message="unknown_action",
        error="unknown_action",
    )
