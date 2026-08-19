from __future__ import annotations

import subprocess

from catswar_project.actions import ActionResult, AdbActionBackend, execute_action


def make_backend(tmp_path, sleeps=None):
    adb = tmp_path / "adb.exe"
    adb.touch()
    return AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5556",
        runner=lambda command, **_: subprocess.CompletedProcess(command, 0, b"", b""),
        sleep=(sleeps if sleeps is not None else (lambda _: None)),
    )


def test_wait_uses_real_backend_with_maximum_cap(tmp_path) -> None:
    sleeps: list[float] = []
    backend = make_backend(tmp_path, sleeps.append)
    result = execute_action({"name": "wait", "params": {"seconds": 10}}, backend, max_wait_seconds=0.25)
    assert sleeps == [0.25]
    assert result.success is True


def test_press_back_sends_real_adb_keyevent(tmp_path) -> None:
    commands: list[list[str]] = []
    adb = tmp_path / "adb.exe"
    adb.touch()
    backend = AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5556",
        runner=lambda command, **_: commands.append(command) or subprocess.CompletedProcess(command, 0, b"", b""),
        sleep=lambda _: None,
    )
    result = execute_action("press_back", backend)
    assert result.success is True
    assert commands[0][-3:] == ["input", "keyevent", "BACK"]


def test_tap_sends_real_adb_tap(tmp_path) -> None:
    commands: list[list[str]] = []
    adb = tmp_path / "adb.exe"
    adb.touch()
    backend = AdbActionBackend(
        adb_path=adb,
        adb_serial="emulator-5556",
        runner=lambda command, **_: commands.append(command) or subprocess.CompletedProcess(command, 0, b"", b""),
        sleep=lambda _: None,
    )
    result = execute_action({"name": "tap", "params": {"x": 100, "y": 200}}, backend)
    assert result.success is True
    assert commands[0][-4:] == ["input", "tap", "100", "200"]


def test_no_action_does_nothing(tmp_path) -> None:
    result = execute_action("no_action", make_backend(tmp_path))
    assert result.success is True


def test_unknown_action_returns_error(tmp_path) -> None:
    result = execute_action({"name": "tap_point", "reason": "not_yet"}, make_backend(tmp_path))
    assert result.success is False
    assert result.action == "tap_point"
    assert result.error == "unknown_action"


def test_action_result_has_complete_fields() -> None:
    result = ActionResult("wait", "executed", "reason")
    assert set(result.to_dict()) == {
        "success", "action", "message", "clicked_pos", "duration",
        "error", "action_type", "result", "reason",
    }
