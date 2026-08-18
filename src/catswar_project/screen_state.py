from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class ScreenKind(StrEnum):
    UNKNOWN = "unknown"
    HOME = "home"
    CITY_WAR = "city_war"
    OPPONENT_SELECT = "opponent_select"
    VEHICLE_SELECT = "vehicle_select"
    BATTLE_RUNNING = "battle_running"
    BATTLE_RESULT = "battle_result"
    POPUP = "popup"
    LOADING = "loading"


@dataclass(frozen=True)
class Marker:
    name: str
    confidence: float
    center: tuple[int, int] | None = None
    bbox: tuple[int, int, int, int] | None = None
    metadata: Mapping[str, str | int | float | bool] | None = None

    @property
    def has_point(self) -> bool:
        return self.center is not None


@dataclass(frozen=True)
class ScreenState:
    kind: ScreenKind
    confidence: float = 0.0
    markers: tuple[Marker, ...] = ()
    source_image: Path | None = None
    reason: str = ""

    def marker(self, *names: str, min_confidence: float = 0.0) -> Marker | None:
        wanted = set(names)
        matches = [
            marker
            for marker in self.markers
            if marker.name in wanted and marker.confidence >= min_confidence
        ]
        if not matches:
            return None
        return max(matches, key=lambda marker: marker.confidence)

    def has(self, *names: str, min_confidence: float = 0.0) -> bool:
        return self.marker(*names, min_confidence=min_confidence) is not None


class ScreenRecognizer(Protocol):
    def recognize(self, image_path: Path | None = None) -> ScreenState:
        raise NotImplementedError


class StaticScreenRecognizer:
    def __init__(self, states: Iterable[ScreenState]) -> None:
        self._states = list(states)
        self._index = 0

    def recognize(self, image_path: Path | None = None) -> ScreenState:
        if not self._states:
            return ScreenState(ScreenKind.UNKNOWN, source_image=image_path, reason="no_static_states")
        state = self._states[min(self._index, len(self._states) - 1)]
        self._index += 1
        if image_path is None:
            return state
        return ScreenState(
            kind=state.kind,
            confidence=state.confidence,
            markers=state.markers,
            source_image=image_path,
            reason=state.reason,
        )
