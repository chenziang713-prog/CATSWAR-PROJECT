from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AccountConfig:
    id: str
    serial: str
    name: str = ""
    emulator_instance: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    adb_path: Path
    accounts: tuple[AccountConfig, ...]
    concurrency: int = 3
    ldplayer_path: Path | None = None
    launch_command: tuple[str, ...] = ()
    omni_parser_url: str = "http://127.0.0.1:8000/parse/"
    output_dir: Path = Path("output")
    retry_limit: int = 3
    wait_timeout: float = 180.0
    poll_interval: float = 2.0
    safety_mode: str = "aggressive"
    stop_file: Path = Path("output/STOP")
    screenshot_dir: Path = Path("output/screenshots")
    resume_run_id: str | None = None
    selected_accounts: tuple[str, ...] = field(default_factory=tuple)

    def with_accounts(self, account_ids: set[str] | None = None) -> "AppConfig":
        if not account_ids:
            return self
        return AppConfig(
            **{**self.__dict__, "accounts": tuple(a for a in self.accounts if a.id in account_ids)}
        )


def load_config(path: Path) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be an object")
    accounts = tuple(_account(item) for item in raw.get("accounts", []))
    if not accounts:
        raise ValueError("configuration must contain at least one account")
    concurrency = int(raw.get("concurrency", 3))
    if concurrency < 1:
        raise ValueError("concurrency must be greater than zero")
    safety_mode = str(raw.get("safety_mode", "aggressive")).lower()
    if safety_mode not in {"aggressive", "guarded"}:
        raise ValueError("safety_mode must be aggressive or guarded")
    launch = raw.get("launch_command", [])
    if isinstance(launch, str):
        launch = [launch]
    return AppConfig(
        adb_path=Path(raw.get("adb_path", "adb")),
        accounts=accounts,
        concurrency=concurrency,
        ldplayer_path=Path(raw["ldplayer_path"]) if raw.get("ldplayer_path") else None,
        launch_command=tuple(str(item) for item in launch),
        omni_parser_url=str(raw.get("omni_parser_url", "http://127.0.0.1:8000/parse/")),
        output_dir=Path(raw.get("output_dir", "output")),
        retry_limit=int(raw.get("retry_limit", 3)),
        wait_timeout=float(raw.get("wait_timeout", 180.0)),
        poll_interval=float(raw.get("poll_interval", 2.0)),
        safety_mode=safety_mode,
        stop_file=Path(raw.get("stop_file", "output/STOP")),
        screenshot_dir=Path(raw.get("screenshot_dir", "output/screenshots")),
        resume_run_id=str(raw["resume_run_id"]) if raw.get("resume_run_id") else None,
    )


def _account(value: Any) -> AccountConfig:
    if not isinstance(value, dict):
        raise ValueError("each account must be an object")
    account_id = str(value.get("id", "")).strip()
    serial = str(value.get("serial", "")).strip()
    if not account_id or not serial:
        raise ValueError("each account requires id and serial")
    return AccountConfig(
        id=account_id,
        serial=serial,
        name=str(value.get("name", account_id)),
        emulator_instance=str(value.get("emulator_instance", "")),
        enabled=bool(value.get("enabled", True)),
    )
