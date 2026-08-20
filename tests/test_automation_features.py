from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image

from catswar_project.actions import ActionResult, TapAction
from catswar_project.automation import AccountAutomationResult, AutomationOptions, CityWarAutomation
from catswar_project.config import load_config
from catswar_project.screen_state import Marker, ScreenKind, ScreenState, StaticScreenRecognizer
from catswar_project.strategy import available_vehicles, parse_building_value, required_vehicles
from catswar_project.vision import OmniParserRecognizer
from catswar_project.emulator import EmulatorLauncher
from catswar_project.config import AccountConfig, AppConfig
from catswar_project.replay import ReplayParserClient, load_memory_replay
from catswar_project.scheduler import AccountScheduler


def marker(name: str, x: int = 100, y: int = 100, content: str | None = None) -> Marker:
    return Marker(name, 0.95, (x, y), (x - 5, y - 5, x + 5, y + 5), {"content": content or name})


def test_config_loads_accounts_and_runtime_options(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"adb_path": "adb.exe", "concurrency": 3, "accounts": [
        {"id": "a", "serial": "emulator-1", "enabled": True}
    ]}), encoding="utf-8")
    config = load_config(path)
    assert config.concurrency == 3
    assert config.accounts[0].id == "a"
    assert config.accounts[0].serial == "emulator-1"


def test_required_vehicles_uses_floor_half_plus_one() -> None:
    assert [required_vehicles(value) for value in (0, 1, 2, 5, 21)] == [1, 1, 2, 3, 11]


def test_building_name_digits_are_never_x_values() -> None:
    assert parse_building_value("仓库1") is None
    assert parse_building_value("仓库 2") is None
    assert parse_building_value("X2") is None
    assert parse_building_value("15") == 15
    assert parse_building_value(".21") == 21


def test_available_vehicles_filters_locked_and_repair() -> None:
    values = available_vehicles((
        marker("vehicle_target"),
        marker("vehicle_locked", content="车辆正在被攻击"),
        marker("vehicle_repair", content="维修中"),
    ))
    assert len(values) == 1
    assert values[0].index == 0


def test_building_value_marker_is_joined_to_nearest_building(tmp_path: Path) -> None:
    runner = CityWarAutomation(
        account_id="a",
        recognizer=StaticScreenRecognizer([]),
        backend=RecordingBackend(),
        capture=lambda: tmp_path / "screen.png",
    )
    state = ScreenState(ScreenKind.BUILDING_MAP, markers=(
        marker("building", 100, 100, "仓库"),
        marker("building_value", 110, 110, "15"),
    ))
    assert runner._buildings(state)[0].value == 15


def test_omniparser_recognizer_classifies_join_page(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    Image.new("RGB", (1000, 1000), "black").save(image)

    class Client:
        def parse(self, _: Path):
            return [{"content": "加入", "bbox": [0.8, 0.8, 0.95, 0.95]},
                    {"content": "城市之王", "bbox": [0.4, 0.1, 0.6, 0.2]}]

    state = OmniParserRecognizer(Client()).recognize(image)
    assert state.kind == ScreenKind.CITY_WAR
    assert state.marker("join_button") is not None


def test_city_king_sign_without_join_context_is_home_entry(tmp_path: Path) -> None:
    state = recognize_items(tmp_path, [
        {"content": "城市之王", "bbox": [0.08, 0.45, 0.25, 0.65]},
        {"content": "1076852", "bbox": [0.08, 0.02, 0.20, 0.09]},
    ])
    assert state.kind == ScreenKind.HOME
    assert state.marker("city_war_promo") is not None
    assert state.marker("guild_entry") is None


def recognize_items(tmp_path: Path, items: list[dict], *, color: str = "black") -> ScreenState:
    image = tmp_path / "recognize.png"
    Image.new("RGB", (1000, 1000), color).save(image)

    class Client:
        def parse(self, _: Path):
            return items

    return OmniParserRecognizer(Client()).recognize(image)


def test_home_and_gift_numbers_are_not_building_values(tmp_path: Path) -> None:
    state = recognize_items(tmp_path, [
        {"content": "123", "bbox": [0.05, 0.02, 0.15, 0.08]},
        {"content": "x20", "bbox": [0.80, 0.15, 0.90, 0.22]},
        {"content": "城市之王", "bbox": [0.80, 0.75, 0.95, 0.88]},
    ])
    assert state.kind == ScreenKind.HOME
    assert state.marker("building_value") is None


def test_gang_war_sign_is_not_the_city_war_entry(tmp_path: Path) -> None:
    state = recognize_items(tmp_path, [
        {"content": "帮派战", "bbox": [0.40, 0.08, 0.55, 0.30]},
    ])
    assert state.kind == ScreenKind.UNKNOWN
    assert state.marker("city_war_entry") is None
    assert state.marker("gang_war_entry") is not None


def test_building_value_requires_nearby_building_context(tmp_path: Path) -> None:
    state = recognize_items(tmp_path, [
        {"content": "仓库", "bbox": [0.40, 0.40, 0.52, 0.48]},
        {"content": "15", "bbox": [0.50, 0.46, 0.55, 0.52]},
        {"content": "999", "bbox": [0.05, 0.03, 0.16, 0.09]},
    ])
    assert state.kind == ScreenKind.BUILDING_MAP
    values = [item for item in state.markers if item.name == "building_value"]
    assert [item.metadata["value"] for item in values] == [15]


def test_action_words_require_complete_text_and_page_context(tmp_path: Path) -> None:
    unrelated = recognize_items(tmp_path, [
        {"content": "加入我们即可开始攻击", "bbox": [0.2, 0.4, 0.8, 0.5]},
        {"content": "攻击力提升", "bbox": [0.2, 0.5, 0.5, 0.6]},
    ])
    assert unrelated.kind == ScreenKind.UNKNOWN
    assert unrelated.marker("join_button") is None
    assert unrelated.marker("loadout_start") is None
    assert unrelated.marker("attack_button") is None

    join_without_context = recognize_items(tmp_path, [
        {"content": "加入", "bbox": [0.7, 0.7, 0.9, 0.82]},
    ])
    assert join_without_context.kind == ScreenKind.UNKNOWN


def test_city_war_waiting_for_warriors_is_city_war_context(tmp_path: Path) -> None:
    state = recognize_items(tmp_path, [
        {"content": "城市之王", "bbox": [0.10, 0.02, 0.30, 0.12]},
        {"content": "等待勇士加入：需要2/5成员", "bbox": [0.30, 0.84, 0.72, 0.94]},
    ])
    assert state.kind == ScreenKind.CITY_WAR
    assert state.has("match_wait")


def test_lower_left_attack_uses_position_context(tmp_path: Path) -> None:
    state = recognize_items(tmp_path, [
        {"content": "攻击", "bbox": [0.05, 0.70, 0.30, 0.88]},
    ])
    assert state.kind == ScreenKind.ATTACK_DEFENSE
    assert state.marker("attack_button") is not None


def test_start_requires_loadout_position_or_city_war_context(tmp_path: Path) -> None:
    center = recognize_items(tmp_path, [
        {"content": "开始", "bbox": [0.40, 0.35, 0.55, 0.45]},
    ])
    assert center.kind == ScreenKind.UNKNOWN

    bottom_right = recognize_items(tmp_path, [
        {"content": "开始", "bbox": [0.70, 0.70, 0.90, 0.85]},
    ])
    assert bottom_right.kind == ScreenKind.LOADOUT_CONFIRM


def test_emulator_launcher_formats_instance_and_waits_for_adb(tmp_path: Path) -> None:
    adb = tmp_path / "adb.exe"
    adb.touch()
    commands: list[list[str]] = []

    def device_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "List of devices attached\nemu-1\tdevice\n", "")

    launcher = EmulatorLauncher(
        adb_path=adb,
        launch_command=["ldconsole.exe", "launch", "--name", "{instance}"],
        runner=lambda command, **kwargs: commands.append(command),
        device_runner=device_runner,
    )
    result = launcher.start(AccountConfig("a", "emu-1", emulator_instance="instance-1"))
    assert result.message == "already_connected"
    assert commands == []


def test_replay_parser_client_repeats_last_response_offline() -> None:
    client = ReplayParserClient([[{"content": "加入", "bbox": [0, 0, 1, 1]}]])
    assert client.parse(Path("first.png"))[0]["content"] == "加入"
    assert client.parse(Path("second.png"))[0]["content"] == "加入"


def test_teaching_mapping_replay_classifies_real_frames() -> None:
    memory = Path(r"C:\Users\shenj\Documents\OmniParser-local\memory")
    if not (memory / "mappings").exists():
        import pytest
        pytest.skip("OmniParser teaching memory is not installed")
    frames, client = load_memory_replay(memory / "mappings", memory / "images")
    recognizer = OmniParserRecognizer(client)
    states = [recognizer.recognize(image) for image, _ in frames]
    by_idx = {mapping.name[:2]: state for state, (_, mapping) in zip(states, frames)}
    assert by_idx["04"].kind == ScreenKind.HOME
    assert by_idx["07"].marker("guild_entry") is not None
    assert by_idx["08"].kind == ScreenKind.CITY_WAR
    assert by_idx["10"].kind == ScreenKind.LOADOUT_CONFIRM
    assert by_idx["12"].kind == ScreenKind.BATTLE_START_CONFIRM
    assert by_idx["14"].kind == ScreenKind.BUILDING_MAP
    assert len([m for m in by_idx["14"].markers if m.name == "building"]) == 6
    assert len([m for m in by_idx["14"].markers if m.name == "building_value"]) == 6
    assert by_idx["15"].kind == ScreenKind.CITY_WAR_ATTACK_ENTRY
    assert by_idx["16"].kind == ScreenKind.ATTACK_DEFENSE
    assert by_idx["17"].has("busy_popup")
    assert by_idx["25"].kind == ScreenKind.BATTLE_RUNNING
    assert by_idx["26"].kind == ScreenKind.BATTLE_RESULT
    assert by_idx["30"].kind == ScreenKind.POPUP
    assert by_idx["44"].kind == ScreenKind.POPUP


def test_scheduler_keeps_other_accounts_running_when_one_fails(tmp_path: Path) -> None:
    accounts = (AccountConfig("a", "emu-a"), AccountConfig("b", "emu-b"))
    config = AppConfig(adb_path=tmp_path / "adb.exe", accounts=accounts, concurrency=2,
                       stop_file=tmp_path / "STOP")
    scheduler = AccountScheduler(config)

    def fake_run(account: AccountConfig):
        return AccountAutomationResult(account.id, account.id == "b",
                                       "completed" if account.id == "b" else "failed", "test", False)

    scheduler._run_account = fake_run
    result = scheduler.run()
    assert [item.account_id for item in result.results] == ["a", "b"]
    assert result.results[0].success is False
    assert result.results[1].success is True


def test_guarded_mode_pauses_before_low_confidence_tap(tmp_path: Path) -> None:
    low_confidence = Marker("join_button", 0.5, (10, 10), (5, 5, 15, 15))
    runner = CityWarAutomation(
        account_id="a",
        recognizer=StaticScreenRecognizer([ScreenState(ScreenKind.CITY_WAR, markers=(low_confidence,))]),
        backend=RecordingBackend(),
        capture=lambda: tmp_path / "screen.png",
        options=AutomationOptions(wait_timeout=0.01, poll_interval=0, safety_mode="guarded"),
    )
    result = runner.run()
    assert result.status == "paused"
    assert "low-confidence" in result.message


class RecordingBackend:
    def __init__(self) -> None:
        self.action_count = 0
        self.taps: list[TapAction] = []
        self.keyevents: list[str] = []

    def tap(self, action: TapAction) -> ActionResult:
        self.action_count += 1
        self.taps.append(action)
        return ActionResult("adb_tap", "executed", action.reason, action="tap", clicked_pos=(action.x, action.y))

    click = tap

    def wait(self, seconds: float, reason: str = "") -> ActionResult:
        return ActionResult("wait", "executed", reason, action="wait")

    def keyevent(self, keycode: str, reason: str = "") -> ActionResult:
        self.action_count += 1
        self.keyevents.append(keycode)
        return ActionResult("adb_keyevent", "executed", reason, action="press_back")

    def reset_cycle(self) -> None:
        self.action_count = 0


def test_city_war_automation_runs_join_one_battle_and_completes(tmp_path: Path) -> None:
    states = [
        ScreenState(ScreenKind.HOME, markers=(marker("city_war_entry"),)),
        ScreenState(ScreenKind.CITY_WAR, markers=(marker("match_wait"),)),
        ScreenState(ScreenKind.CITY_WAR, markers=(marker("join_button"),)),
        ScreenState(ScreenKind.LOADOUT_CONFIRM, markers=(marker("loadout_start"),)),
        ScreenState(ScreenKind.BATTLE_START_CONFIRM, markers=(marker("battle_start_confirm"),)),
        ScreenState(ScreenKind.BUILDING_MAP, markers=(marker("building", content="仓库"), marker("building_value", 110, 110, "5"))),
        ScreenState(ScreenKind.BUILDING_MAP, markers=(marker("building", content="仓库"), marker("building_value", 110, 110, "5"))),
        ScreenState(ScreenKind.ATTACK_DEFENSE, markers=(marker("attack_button"),)),
        ScreenState(ScreenKind.OPPONENT_SELECT, markers=(marker("vehicle_target"),)),
        ScreenState(ScreenKind.BATTLE_RUNNING, markers=(marker("watch_button"),)),
        ScreenState(ScreenKind.BATTLE_RESULT, markers=(marker("result_confirm_button"), marker("victory"))),
        ScreenState(ScreenKind.BUILDING_MAP),
    ]
    backend = RecordingBackend()
    runner = CityWarAutomation(
        account_id="a",
        recognizer=StaticScreenRecognizer(states),
        backend=backend,
        capture=lambda: tmp_path / "screen.png",
        options=AutomationOptions(wait_timeout=0.1, poll_interval=0),
    )
    result = runner.run()
    assert result.success is True
    assert result.joined is True
    assert result.battles == 1
    assert any(t.reason == "join_city_war" for t in backend.taps)


def test_city_war_automation_uses_two_fresh_attack_stages(tmp_path: Path) -> None:
    states = [
        ScreenState(ScreenKind.BUILDING_MAP, markers=(marker("building", 100, 100, "仓库"), marker("building_value", 110, 110, "5"))),
        ScreenState(ScreenKind.CITY_WAR_ATTACK_ENTRY, markers=(marker("attack_entry", 700, 400),)),
        ScreenState(ScreenKind.ATTACK_DEFENSE, markers=(marker("attack_button", 120, 800),)),
        ScreenState(ScreenKind.OPPONENT_SELECT, markers=(marker("vehicle_target", 500, 600),)),
        ScreenState(ScreenKind.BATTLE_RUNNING),
        ScreenState(ScreenKind.BATTLE_RESULT, markers=(marker("result_confirm_button", 500, 800), marker("victory"))),
        ScreenState(ScreenKind.BUILDING_MAP),
        ScreenState(ScreenKind.BUILDING_MAP),
    ]
    backend = RecordingBackend()
    capture_calls: list[Path] = []

    def capture() -> Path:
        path = tmp_path / f"frame_{len(capture_calls)}.png"
        capture_calls.append(path)
        return path

    runner = CityWarAutomation(
        account_id="a", recognizer=StaticScreenRecognizer(states), backend=backend, capture=capture,
        options=AutomationOptions(wait_timeout=0.1, poll_interval=0), checkpoint={"joined": True},
    )
    result = runner.run()
    assert result.success is True
    attack_taps = [tap for tap in backend.taps if "attack" in tap.reason]
    assert [(tap.reason, tap.x, tap.y) for tap in attack_taps] == [
        ("select_red_attack_entry", 700, 400),
        ("select_attack", 120, 800),
    ]
    assert len(capture_calls) >= 3
