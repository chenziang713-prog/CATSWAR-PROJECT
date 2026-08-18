from __future__ import annotations

import subprocess
from pathlib import Path

from catswar_project.backends.adb_capture import AdbCaptureBackend, parse_adb_devices
from catswar_project.backends.capture_backend import CaptureBackendError


def test_parse_adb_devices_only_keeps_connected_devices() -> None:
    output = """
List of devices attached
emulator-5556	device
offline-1	offline
bad-1	unauthorized
"""

    assert parse_adb_devices(output) == ["emulator-5556"]


def test_adb_capture_backend_reads_png_and_returns_frame(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()
    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01"
        b"\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\x0bIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"\xe2!\xbc3"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if command[-1] == "devices":
            return subprocess.CompletedProcess(command, 0, b"List of devices attached\nemulator-5556\tdevice\n", b"")
        return subprocess.CompletedProcess(command, 0, png, b"")

    backend = AdbCaptureBackend(adb, "emulator-5556", runner=runner)
    frame = backend.capture(tmp_path / "capture.png")

    assert calls[0][-1] == "devices"
    assert calls[1][-2:] == ["screencap", "-p"]
    assert frame.path.exists()
    assert frame.title == "ADB emulator-5556"
    assert frame.size == (1, 1)


def test_adb_capture_backend_rejects_missing_device(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, b"List of devices attached\n", b"")

    try:
        AdbCaptureBackend(adb, "emulator-5556", runner=runner)
    except CaptureBackendError as exc:
        assert "returned no connected devices" in str(exc)
    else:
        raise AssertionError("expected CaptureBackendError")
