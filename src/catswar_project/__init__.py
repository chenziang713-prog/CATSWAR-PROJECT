"""CATS WAR project package."""

from .account_switch import (
    AccountSwitchController,
    AccountSwitchResult,
    read_account_index,
)
from .actions import (
    ActionResult,
    AdbActionBackend,
    ClickAction,
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
    AccountSwitchStep,
    AccountSwitchWorkflow,
    DEFAULT_ACCOUNT_SWITCH_PLAN,
    DEFAULT_CITY_WAR_BOOTSTRAP_PLAN,
    CityWarStep,
    CityWarWorkflow,
    StepTransition,
    WorkflowResult,
)

__all__ = [
    "AccountSwitchController",
    "AccountSwitchResult",
    "AccountSwitchStep",
    "AccountSwitchWorkflow",
    "ActionResult",
    "AdbActionBackend",
    "AdbCandidate",
    "AdbDevice",
    "AdbDiscoveryResult",
    "ClickAction",
    "CityWarController",
    "CityWarScanResult",
    "CityWarStep",
    "CityWarWorkflow",
    "ControlResult",
    "DEFAULT_ACCOUNT_SWITCH_PLAN",
    "DEFAULT_CITY_WAR_BOOTSTRAP_PLAN",
    "Marker",
    "ScreenKind",
    "ScreenState",
    "StaticScreenRecognizer",
    "RunEvent",
    "RunRecorder",
    "StepTransition",
    "TapAction",
    "WorkflowResult",
    "discover_adb",
    "enter_city_war",
    "execute_action",
    "read_account_index",
    "recognize_links_and_buildings",
    "return_after_battle",
    "return_home",
    "select_opponent_and_board",
]
