from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .adb_discovery import parse_adb_devices_output
from .config import AccountConfig


@dataclass(frozen=True)
class EmulatorLaunchResult:
    account_id: str
    started: bool
    serial: str
    message: str


class EmulatorLauncher:
    def __init__(self, *, adb_path: Path, launch_command: Sequence[str] = (),
                 runner: Callable[..., object] = subprocess.Popen,
                 device_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.adb_path = Path(adb_path)
        self.launch_command = tuple(launch_command)
        self.runner = runner
        self.device_runner = device_runner

    def start(self, account: AccountConfig) -> EmulatorLaunchResult:
        if self._is_connected(account.serial):
            return EmulatorLaunchResult(account.id, False, account.serial, "already_connected")
        if not self.launch_command:
            return EmulatorLaunchResult(account.id, False, account.serial, "not_connected_and_no_launch_command")
        command = [part.format(instance=account.emulator_instance, serial=account.serial, account=account.id)
                   for part in self.launch_command]
        self.runner(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return EmulatorLaunchResult(account.id, True, account.serial, "launch_requested")

    def wait_for_device(self, serial: str, *, timeout: float = 120.0, poll_interval: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._is_connected(serial):
                return True
            time.sleep(poll_interval)
        return False

    def _is_connected(self, serial: str) -> bool:
        result = self.device_runner([str(self.adb_path), "devices"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return False
        return any(item.serial == serial and item.state == "device" for item in parse_adb_devices_output(result.stdout))
