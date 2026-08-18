from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from ..window_capture import WindowFrame


class CaptureBackendError(RuntimeError):
    pass


class CaptureBackend(Protocol):
    name: str

    def capture(self, output_path: Path) -> WindowFrame:
        raise NotImplementedError


def create_capture_backend(
    kind: str,
    *,
    adb_path: Path | None = None,
    adb_serial: str | None = None,
    replay_screens: Sequence[Path] | None = None,
) -> CaptureBackend:
    if kind == "fullscreen":
        from ..window_capture import WindowsDesktopCapture

        return WindowsDesktopCapture()
    if kind == "adb":
        if adb_path is None:
            raise CaptureBackendError("--adb-path is required when --capture-backend adb is used.")
        if adb_serial is None or not adb_serial.strip():
            raise CaptureBackendError("--adb-serial is required when --capture-backend adb is used.")
        from .adb_capture import AdbCaptureBackend

        return AdbCaptureBackend(adb_path, adb_serial)
    raise CaptureBackendError(f"Unsupported capture backend: {kind}")
