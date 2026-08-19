"""CATS WAR project package."""

from .actions import (
    ActionResult,
    AdbActionBackend,
    ClickAction,
    DryRunBackend,
    TapAction,
    execute_action,
)
from .adb_discovery import (
    AdbCandidate,
    AdbDevice,
    AdbDiscoveryResult,
    discover_adb,
)
from .city_war import (
    CityWarController,
    CityWarScanResult,
    ControlResult,
    enter_city_war,
    recognize_links_and_buildings,
    return_after_battle,
    return_home,
    select_opponent_and_board,
)
from .screen_state import Marker, ScreenKind, ScreenState, StaticScreenRecognizer
from .run_log import RunEvent, RunRecorder
from .workflow import (
    DEFAULT_CITY_WAR_BOOTSTRAP_PLAN,
    CityWarStep,
    CityWarWorkflow,
    StepTransition,
    WorkflowResult,
)

__all__ = [
    "ActionResult",
    "AdbActionBackend",
    "AdbCandidate",
    "AdbDevice",
    "AdbDiscoveryResult",
    "ClickAction",
    "CityWarController",
    "CityWarScanResult",
    "ControlResult",
    "DryRunBackend",
    "Marker",
    "ScreenKind",
    "ScreenState",
    "StaticScreenRecognizer",
    "RunEvent",
    "RunRecorder",
    "TapAction",
    "CityWarStep",
    "CityWarWorkflow",
    "DEFAULT_CITY_WAR_BOOTSTRAP_PLAN",
    "StepTransition",
    "WorkflowResult",
    "discover_adb",
    "enter_city_war",
    "execute_action",
    "recognize_links_and_buildings",
    "return_after_battle",
    "return_home",
    "select_opponent_and_board",
]
