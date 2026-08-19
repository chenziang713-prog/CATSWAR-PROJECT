"""Account switching flow for CATS WAR.

Switches the game account through the ES file manager:

1. Open the ES file manager app.
2. Recognize the main directory entry and tap it.
3. Tap the folder that holds per-account files.
4. Read the target account number from a command file in the command folder.
5. Tap the folder whose name carries the account number.
6. Recognize the confirm button and tap it.
7. Open the CATS game app.

The implementation mirrors the existing framework style: recognition goes
through a ``ScreenRecognizer``, actions through an ``ActionBackend``, and
results are reported as ``AccountSwitchResult`` dataclasses.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .actions import ActionBackend, ActionResult, TapAction
from .screen_state import Marker, ScreenRecognizer, ScreenState

APP_PACKAGE = "com.estrongs.android.pop"
APP_ACTIVITY = ".app.openscreenad.NewSplashActivity"
CATS_PACKAGE = "com.zeptolab.cats.google"
CATS_ACTIVITY = "com.zeptolab.cats.CATSActivity"

MAIN_DIRECTORY_MARKERS = ("main_directory", "internal_storage", "root_dir")
ACCOUNT_ROOT_FOLDER_MARKERS = ("account_folder", "backup_folder", "save_folder")
CONFIRM_MARKERS = ("confirm_button", "ok_button", "confirm")

DEFAULT_INSTRUCTION_FILE = "account.txt"

_KEY_CANDIDATES = ("account", "index", "number", "loop", "id")


@dataclass(frozen=True)
class AccountSwitchResult:
    name: str
    state_before: ScreenState
    action_result: ActionResult
    state_after: ScreenState | None = None
    target: Marker | None = None
    success: bool = False
    message: str = ""
    account_index: int | None = None


def read_account_index(
    cmd_dir: Path,
    *,
    filename: str = DEFAULT_INSTRUCTION_FILE,
) -> int | None:
    """Read the target account number from a command file.

    Supported formats:
    - a plain number (``3`` or ``account=3``)
    - a JSON object with any of ``account``/``index``/``number``/``loop``/``id``.

    Returns ``None`` when the file is missing, unreadable, or contains no
    usable number.
    """
    path = cmd_dir / filename
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    stripped = text.strip()
    if not stripped:
        return None

    json_match = re.search(r"\{\s*.*?\}", stripped, flags=re.DOTALL)
    if json_match is not None:
        import json

        try:
            payload = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for key in _KEY_CANDIDATES:
                value = payload.get(key)
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.strip().isdigit():
                    return int(value.strip())

    number_match = re.search(r"\d+", stripped)
    if number_match is not None:
        return int(number_match.group(0))
    return None


class AccountSwitchController:
    def __init__(
        self,
        *,
        recognizer: ScreenRecognizer,
        backend: ActionBackend,
        screenshot_provider: Callable[[], object] | None = None,
        cmd_dir: Path | None = None,
        min_confidence: float = 0.80,
        wait_seconds: float = 1.0,
        app_package: str = APP_PACKAGE,
        app_activity: str = APP_ACTIVITY,
        cats_package: str = CATS_PACKAGE,
        cats_activity: str = CATS_ACTIVITY,
        instruction_file: str = DEFAULT_INSTRUCTION_FILE,
    ) -> None:
        self.recognizer = recognizer
        self.backend = backend
        self.screenshot_provider = screenshot_provider
        self.cmd_dir = Path(cmd_dir) if cmd_dir is not None else None
        self.min_confidence = min_confidence
        self.wait_seconds = wait_seconds
        self.app_package = app_package
        self.app_activity = app_activity
        self.cats_package = cats_package
        self.cats_activity = cats_activity
        self.instruction_file = instruction_file
        self.last_account_index: int | None = None

    def open_file_manager(self) -> AccountSwitchResult:
        state = self._recognize()
        action_result = self.backend.launch_app(self.app_package, self.app_activity, reason="switch_account_open_file_manager")
        after = self._recognize()
        return AccountSwitchResult(
            name="open_file_manager",
            state_before=state,
            action_result=action_result,
            state_after=after,
            success=bool(action_result.success),
            message="file_manager_launch_requested" if action_result.success else "file_manager_launch_failed",
        )

    def tap_main_directory(self) -> AccountSwitchResult:
        state = self._recognize()
        target = state.marker(*MAIN_DIRECTORY_MARKERS, min_confidence=self.min_confidence)
        if target is None or target.center is None:
            return AccountSwitchResult(
                name="tap_main_directory",
                state_before=state,
                action_result=ActionResult("tap", "target_missing", "main_directory_not_found", action="tap", error="target_missing"),
                success=False,
                message="main_directory_not_found",
            )
        action_result = self.backend.tap(_tap(target, "tap_main_directory"))
        after = self._recognize()
        return AccountSwitchResult(
            name="tap_main_directory",
            state_before=state,
            action_result=action_result,
            state_after=after,
            target=target,
            success=bool(action_result.success),
            message="main_directory_tapped",
        )

    def tap_account_folder(self) -> AccountSwitchResult:
        state = self._recognize()
        target = state.marker(*ACCOUNT_ROOT_FOLDER_MARKERS, min_confidence=self.min_confidence)
        if target is None or target.center is None:
            return AccountSwitchResult(
                name="tap_account_folder",
                state_before=state,
                action_result=ActionResult("tap", "target_missing", "account_folder_not_found", action="tap", error="target_missing"),
                success=False,
                message="account_folder_not_found",
            )
        action_result = self.backend.tap(_tap(target, "tap_account_folder"))
        after = self._recognize()
        return AccountSwitchResult(
            name="tap_account_folder",
            state_before=state,
            action_result=action_result,
            state_after=after,
            target=target,
            success=bool(action_result.success),
            message="account_folder_tapped",
        )

    def read_account_instruction(self) -> AccountSwitchResult:
        state = self._recognize()
        if self.cmd_dir is None:
            self.last_account_index = None
            return AccountSwitchResult(
                name="read_account_instruction",
                state_before=state,
                action_result=ActionResult("read_instruction", "no_cmd_dir", "cmd_dir_not_configured", action="read_instruction", error="no_cmd_dir"),
                success=False,
                message="cmd_dir_not_configured",
            )
        account_index = read_account_index(self.cmd_dir, filename=self.instruction_file)
        if account_index is None:
            self.last_account_index = None
            return AccountSwitchResult(
                name="read_account_instruction",
                state_before=state,
                action_result=ActionResult("read_instruction", "instruction_not_found", f"no_number_in_{self.instruction_file}", action="read_instruction", error="instruction_not_found"),
                success=False,
                message="account_index_not_found",
            )
        self.last_account_index = account_index
        return AccountSwitchResult(
            name="read_account_instruction",
            state_before=state,
            action_result=ActionResult("read_instruction", "executed", f"account_index={account_index}", action="read_instruction"),
            success=True,
            message="account_index_read",
            account_index=account_index,
        )

    def tap_numbered_folder(self, account_index: int | None = None) -> AccountSwitchResult:
        state = self._recognize()
        if account_index is None:
            account_index = self.last_account_index
        if account_index is None:
            return AccountSwitchResult(
                name="tap_numbered_folder",
                state_before=state,
                action_result=ActionResult("tap", "target_missing", "no_account_index", action="tap", error="target_missing"),
                success=False,
                message="no_account_index",
            )
        numbered_name = folder_marker_name(account_index)
        target = state.marker(numbered_name, min_confidence=self.min_confidence)
        if target is None or target.center is None:
            return AccountSwitchResult(
                name="tap_numbered_folder",
                state_before=state,
                action_result=ActionResult("tap", "target_missing", f"{numbered_name}_not_found", action="tap", error="target_missing"),
                success=False,
                message=f"{numbered_name}_not_found",
            )
        action_result = self.backend.tap(_tap(target, f"tap_numbered_folder_{account_index}"))
        after = self._recognize()
        return AccountSwitchResult(
            name="tap_numbered_folder",
            state_before=state,
            action_result=action_result,
            state_after=after,
            target=target,
            success=bool(action_result.success),
            message=f"folder_{account_index}_tapped",
        )

    def tap_confirm(self) -> AccountSwitchResult:
        state = self._recognize()
        target = state.marker(*CONFIRM_MARKERS, min_confidence=self.min_confidence)
        if target is None or target.center is None:
            return AccountSwitchResult(
                name="tap_confirm",
                state_before=state,
                action_result=ActionResult("tap", "target_missing", "confirm_button_not_found", action="tap", error="target_missing"),
                success=False,
                message="confirm_button_not_found",
            )
        action_result = self.backend.tap(_tap(target, "tap_confirm"))
        after = self._recognize()
        return AccountSwitchResult(
            name="tap_confirm",
            state_before=state,
            action_result=action_result,
            state_after=after,
            target=target,
            success=bool(action_result.success),
            message="confirm_tapped",
        )

    def open_cats(self) -> AccountSwitchResult:
        state = self._recognize()
        action_result = self.backend.launch_app(self.cats_package, self.cats_activity, reason="switch_account_open_cats")
        after = self._recognize()
        return AccountSwitchResult(
            name="open_cats",
            state_before=state,
            action_result=action_result,
            state_after=after,
            success=bool(action_result.success),
            message="cats_launch_requested" if action_result.success else "cats_launch_failed",
        )

    def switch_account(self) -> tuple[AccountSwitchResult, ...]:
        results: list[AccountSwitchResult] = []
        results.append(self.open_file_manager())
        if not results[-1].success:
            return tuple(results)
        results.append(self.tap_main_directory())
        if not results[-1].success:
            return tuple(results)
        results.append(self.tap_account_folder())
        if not results[-1].success:
            return tuple(results)
        read_result = self.read_account_instruction()
        results.append(read_result)
        if not read_result.success or read_result.account_index is None:
            return tuple(results)
        results.append(self.tap_numbered_folder())
        if not results[-1].success:
            return tuple(results)
        results.append(self.tap_confirm())
        if not results[-1].success:
            return tuple(results)
        results.append(self.open_cats())
        return tuple(results)

    def _recognize(self) -> ScreenState:
        image_path = None
        if self.screenshot_provider is not None:
            image_path = self.screenshot_provider()
        return self.recognizer.recognize(image_path)


def folder_marker_name(account_index: int) -> str:
    return f"folder_{account_index}"


def _tap(marker: Marker, reason: str) -> TapAction:
    if marker.center is None:
        raise ValueError(f"marker has no center: {marker.name}")
    return TapAction(
        x=marker.center[0],
        y=marker.center[1],
        confidence=marker.confidence,
        reason=reason,
    )