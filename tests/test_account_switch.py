from __future__ import annotations

from pathlib import Path

from catswar_project.account_switch import (
    AccountSwitchController,
    read_account_index,
)
from catswar_project.actions import ActionResult, TapAction
from catswar_project.screen_state import Marker, ScreenKind, ScreenState, StaticScreenRecognizer


class RecordingBackend:

    def __init__(self, *, app_foreground: bool = True) -> None:
        self.action_count = 0
        self.app_foreground = app_foreground
        self.taps: list[TapAction] = []
        self.keyevents: list[str] = []
        self.launches: list[tuple[str, str]] = []

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

    def is_app_foreground(self, package_name: str, activity_name: str) -> bool:
        return self.app_foreground

    def launch_app(self, package_name: str, activity_name: str, reason: str = "") -> ActionResult:
        self.action_count += 1
        self.launches.append((package_name, activity_name))
        return ActionResult("adb_launch_app", "executed", reason, action="launch_app", message="app_launched")

    def reset_cycle(self) -> None:
        self.action_count = 0


def marker(name: str, x: int = 100, y: int = 100, confidence: float = 0.95) -> Marker:
    return Marker(name=name, confidence=confidence, center=(x, y))


def controller(
    states: list[ScreenState],
    *,
    app_foreground: bool = True,
    cmd_dir: Path | None = None,
) -> tuple[AccountSwitchController, RecordingBackend]:
    backend = RecordingBackend(app_foreground=app_foreground)
    return (
        AccountSwitchController(
            recognizer=StaticScreenRecognizer(states),
            backend=backend,
            cmd_dir=cmd_dir,
        ),
        backend,
    )


class TestReadAccountIndex:
    def test_reads_plain_number(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text("3\n", encoding="utf-8")
        assert read_account_index(tmp_path) == 3

    def test_reads_key_value_text(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text("account=5", encoding="utf-8")
        assert read_account_index(tmp_path) == 5

    def test_reads_json_object(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text('{"account": 7}', encoding="utf-8")
        assert read_account_index(tmp_path) == 7

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert read_account_index(tmp_path) is None

    def test_returns_none_when_no_number(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text("hello", encoding="utf-8")
        assert read_account_index(tmp_path) is None


class TestSwitchAccountFlow:
    def test_full_flow_launches_file_manager_taps_folders_and_opens_cats(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text("3", encoding="utf-8")
        # StaticScreenRecognizer consumes states in order; each step calls
        # _recognize() before AND after the action, so markers must sit at the
        # exact consume positions below.
        states = [
            ScreenState(ScreenKind.UNKNOWN),                                        # open_file_manager: before
            ScreenState(ScreenKind.UNKNOWN),                                        # open_file_manager: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("main_directory"),)),   # tap_main_directory: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_main_directory: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("account_folder"),)),   # tap_account_folder: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_account_folder: after
            ScreenState(ScreenKind.UNKNOWN),                                        # read_account_instruction: before
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("folder_3"),)),         # tap_numbered_folder: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_numbered_folder: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("confirm_button"),)),   # tap_confirm: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_confirm: after
            ScreenState(ScreenKind.UNKNOWN),                                        # open_cats: before
            ScreenState(ScreenKind.UNKNOWN),                                        # open_cats: after
        ]
        ctrl, backend = controller(states, cmd_dir=tmp_path)

        results = ctrl.switch_account()

        assert [result.name for result in results] == [
            "open_file_manager",
            "tap_main_directory",
            "tap_account_folder",
            "read_account_instruction",
            "tap_numbered_folder",
            "tap_confirm",
            "open_cats",
        ]
        assert all(result.success for result in results)
        assert backend.launches == [
            ("com.estrongs.android.pop", ".app.openscreenad.NewSplashActivity"),
            ("com.zeptolab.cats.google", "com.zeptolab.cats.CATSActivity"),
        ]
        assert [tap.reason for tap in backend.taps] == [
            "tap_main_directory",
            "tap_account_folder",
            "tap_numbered_folder_3",
            "tap_confirm",
        ]

    def test_stops_when_main_directory_missing(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text("3", encoding="utf-8")
        states = [
            ScreenState(ScreenKind.UNKNOWN),  # open_file_manager: before
            ScreenState(ScreenKind.UNKNOWN),  # open_file_manager: after
            ScreenState(ScreenKind.UNKNOWN),  # tap_main_directory: before (no marker)
        ]
        ctrl, backend = controller(states, cmd_dir=tmp_path)

        results = ctrl.switch_account()

        assert [result.name for result in results] == ["open_file_manager", "tap_main_directory"]
        assert results[-1].success is False
        assert results[-1].message == "main_directory_not_found"
        assert backend.taps == []

    def test_stops_when_cmd_dir_missing(self, tmp_path: Path) -> None:
        states = [
            ScreenState(ScreenKind.UNKNOWN),                                        # open_file_manager: before
            ScreenState(ScreenKind.UNKNOWN),                                        # open_file_manager: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("main_directory"),)),   # tap_main_directory: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_main_directory: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("account_folder"),)),   # tap_account_folder: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_account_folder: after
            ScreenState(ScreenKind.UNKNOWN),                                        # read_account_instruction: before
        ]
        ctrl, backend = controller(states, cmd_dir=None)

        results = ctrl.switch_account()

        assert [result.name for result in results] == [
            "open_file_manager",
            "tap_main_directory",
            "tap_account_folder",
            "read_account_instruction",
        ]
        assert results[-1].success is False
        assert results[-1].message == "cmd_dir_not_configured"

    def test_stops_when_instruction_has_no_number(self, tmp_path: Path) -> None:
        (tmp_path / "account.txt").write_text("hello", encoding="utf-8")
        states = [
            ScreenState(ScreenKind.UNKNOWN),                                        # open_file_manager: before
            ScreenState(ScreenKind.UNKNOWN),                                        # open_file_manager: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("main_directory"),)),   # tap_main_directory: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_main_directory: after
            ScreenState(ScreenKind.UNKNOWN, markers=(marker("account_folder"),)),   # tap_account_folder: before
            ScreenState(ScreenKind.UNKNOWN),                                        # tap_account_folder: after
            ScreenState(ScreenKind.UNKNOWN),                                        # read_account_instruction: before
        ]
        ctrl, backend = controller(states, cmd_dir=tmp_path)

        results = ctrl.switch_account()

        assert [result.name for result in results] == [
            "open_file_manager",
            "tap_main_directory",
            "tap_account_folder",
            "read_account_instruction",
        ]
        assert results[-1].success is False
        assert results[-1].message == "account_index_not_found"