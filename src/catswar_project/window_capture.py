from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import ImageGrab


@dataclass(frozen=True)
class WindowFrame:
    path: Path
    title: str
    client_origin: tuple[int, int]
    size: tuple[int, int]

    def to_screen_point(self, point: tuple[int, int]) -> tuple[int, int]:
        return self.client_origin[0] + point[0], self.client_origin[1] + point[1]


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    client_origin: tuple[int, int]
    size: tuple[int, int]


class WindowCaptureError(RuntimeError):
    pass


class WindowsDesktopCapture:
    def __init__(
        self,
        *,
        grabber: Callable[..., Any] = ImageGrab.grab,
        bounds_provider: Callable[[], tuple[int, int, int, int]] | None = None,
    ) -> None:
        self.grabber = grabber
        self.bounds_provider = bounds_provider or _virtual_desktop_bounds

    def capture(self, output_path: Path) -> WindowFrame:
        left, top, width, height = self.bounds_provider()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = self.grabber(all_screens=True)
        image.save(output_path)
        return WindowFrame(
            path=output_path,
            title="Desktop",
            client_origin=(left, top),
            size=(width, height),
        )


def _virtual_desktop_bounds() -> tuple[int, int, int, int]:
    import ctypes

    user32 = ctypes.windll.user32
    return (
        int(user32.GetSystemMetrics(76)),
        int(user32.GetSystemMetrics(77)),
        int(user32.GetSystemMetrics(78)),
        int(user32.GetSystemMetrics(79)),
    )
