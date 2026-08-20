from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from .screen_state import Marker


@dataclass(frozen=True)
class BuildingTarget:
    name: str
    value: int
    required_vehicles: int
    priority: int
    owned_by_us: bool | None = None
    progress: float | None = None
    marker: Marker | None = None


@dataclass(frozen=True)
class VehicleTarget:
    marker: Marker
    index: int
    available: bool = True
    reason: str = "available"


def required_vehicles(value: int) -> int:
    if value < 0:
        raise ValueError("building value must not be negative")
    return math.floor(value / 2) + 1


def parse_building_value(content: str) -> int | None:
    # X is a standalone value beside a building. Never parse digits embedded
    # in a building name such as 仓库1/仓库2.
    normalized = re.sub(r"\s+", "", content).lower()
    normalized = normalized[1:] if normalized.startswith(".") else normalized
    match = re.fullmatch(r"(?:x=)?(\d{1,3})", normalized)
    return int(match.group(1)) if match else None


def rank_buildings(buildings: Iterable[BuildingTarget]) -> tuple[BuildingTarget, ...]:
    return tuple(sorted(
        buildings,
        key=lambda item: (
            item.progress is not None and item.progress > 0.5,
            item.owned_by_us is True,
            item.priority,
            -item.value,
        ),
    ))


def classify_vehicle(marker: Marker, index: int) -> VehicleTarget:
    text = str((marker.metadata or {}).get("content", marker.name)).lower()
    if marker.name == "vehicle_locked" or "锁" in text or "攻击中" in text:
        return VehicleTarget(marker, index, False, "locked")
    if marker.name == "vehicle_repair" or "维修" in text:
        return VehicleTarget(marker, index, False, "repair")
    if marker.name == "busy_popup" or "忙碌" in text:
        return VehicleTarget(marker, index, False, "busy")
    return VehicleTarget(marker, index)


def available_vehicles(markers: Iterable[Marker]) -> tuple[VehicleTarget, ...]:
    return tuple(item for item in (classify_vehicle(marker, i) for i, marker in enumerate(markers)) if item.available)
