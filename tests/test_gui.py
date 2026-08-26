from __future__ import annotations

import json
from pathlib import Path

import pytest

from catswar_project.gui import GuiAccount, read_gui_config, write_gui_config


def test_gui_config_round_trip_preserves_runtime_fields(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    payload = {
        "adb_path": "D:/adb.exe",
        "omni_parser_url": "http://192.168.1.20:8000/parse/",
        "launch_command": [],
        "concurrency": 2,
        "output_dir": "runs",
        "accounts": [],
    }
    write_gui_config(path, payload, [GuiAccount("a", "账号 A", "emulator-1", "zaza", True)])
    loaded = read_gui_config(path)
    assert loaded["adb_path"] == "D:/adb.exe"
    assert loaded["omni_parser_url"].startswith("http://192.168.1.20")
    assert loaded["concurrency"] == 2
    assert loaded["accounts"][0]["serial"] == "emulator-1"


def test_gui_config_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="重复"):
        write_gui_config(
            tmp_path / "accounts.json",
            {"adb_path": "adb.exe", "omni_parser_url": "http://localhost:8000/parse/"},
            [GuiAccount("same", serial="one"), GuiAccount("same", serial="two")],
        )


def test_gui_config_rejects_missing_serial(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ID 和 ADB serial"):
        write_gui_config(
            tmp_path / "accounts.json",
            {"adb_path": "adb.exe", "omni_parser_url": "http://localhost:8000/parse/"},
            [GuiAccount("account-1")],
        )


def test_gui_config_accepts_disabled_accounts(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    write_gui_config(
        path,
        {"adb_path": "adb.exe", "omni_parser_url": "http://localhost:8000/parse/"},
        [GuiAccount("account-1", serial="emu-1", enabled=False)],
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["accounts"][0]["enabled"] is False
