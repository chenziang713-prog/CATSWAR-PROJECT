from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .actions import AdbActionBackend
from .automation import AccountAutomationResult, AutomationOptions, CityWarAutomation
from .backends.adb_capture import AdbCaptureBackend
from .config import AccountConfig, AppConfig
from .emulator import EmulatorLauncher
from .run_log import RunRecorder
from .vision import OmniParserClient, OmniParserRecognizer


@dataclass(frozen=True)
class SchedulerResult:
    run_id: str
    results: tuple[AccountAutomationResult, ...]

    @property
    def success(self) -> bool:
        return all(result.success for result in self.results)


class AccountScheduler:
    def __init__(self, config: AppConfig, *, run_id: str | None = None) -> None:
        self.config = config
        self.run_id = run_id or __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
        self.stop_event = threading.Event()
        self.launcher = EmulatorLauncher(adb_path=config.adb_path, launch_command=config.launch_command)

    def run(self, accounts: Iterable[AccountConfig] | None = None, *, select: bool = False) -> SchedulerResult:
        if self.config.stop_file.exists():
            self.config.stop_file.unlink()
        candidates = [account for account in (accounts or self.config.accounts) if account.enabled]
        if select:
            candidates = self._select_accounts(candidates)
        futures: dict[Future[AccountAutomationResult], str] = {}
        results: list[AccountAutomationResult] = []
        with ThreadPoolExecutor(max_workers=self.config.concurrency, thread_name_prefix="catswar") as pool:
            for account in candidates:
                futures[pool.submit(self._run_account, account)] = account.id
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(AccountAutomationResult(futures[future], False, "failed", str(exc), False))
        results.sort(key=lambda result: result.account_id)
        return SchedulerResult(self.run_id, tuple(results))

    def stop(self) -> None:
        self.stop_event.set()
        self.config.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.stop_file.write_text("stop\n", encoding="utf-8")

    def _run_account(self, account: AccountConfig) -> AccountAutomationResult:
        if self.stop_event.is_set() or self.config.stop_file.exists():
            return AccountAutomationResult(account.id, False, "stopped", "stop requested", False)
        launch = self.launcher.start(account)
        if launch.started and not self.launcher.wait_for_device(account.serial, timeout=self.config.wait_timeout,
                                                               poll_interval=self.config.poll_interval):
            return AccountAutomationResult(account.id, False, "failed", "ADB device did not become ready", False)
        checkpoint_id = f"{self.config.resume_run_id}-{account.id}" if self.config.resume_run_id else None
        checkpoint = RunRecorder.load_checkpoint(self.config.output_dir, checkpoint_id) if checkpoint_id else None
        last_result: AccountAutomationResult | None = None
        for attempt in range(max(1, self.config.retry_limit + 1)):
            instance_dir = self.config.screenshot_dir / account.id
            capture_backend = AdbCaptureBackend(self.config.adb_path, account.serial, instance_dir=instance_dir)
            action_backend = AdbActionBackend(
                adb_path=self.config.adb_path,
                adb_serial=account.serial,
                max_actions=10000,
                click_cooldown=0.4,
                min_click_confidence=0.25,
                stop_file=self.config.stop_file,
                instance_dir=instance_dir,
                log_file=self.config.output_dir / "accounts" / account.id / "actions.log",
            )
            recorder = RunRecorder(self.config.output_dir, run_id=f"{self.run_id}-{account.id}")
            client = OmniParserClient(self.config.omni_parser_url, timeout=self.config.wait_timeout)
            recognizer = OmniParserRecognizer(
                client,
                on_parse=lambda image, parsed: recorder.event(
                    "omniparser_result", {"account_id": account.id, "image": image, "parsed": parsed}
                ),
            )
            capture_index = 0

            def capture() -> Path:
                nonlocal capture_index
                capture_index += 1
                return capture_backend.capture(instance_dir / f"state_{capture_index:06d}.png").path

            try:
                runner = CityWarAutomation(
                    account_id=account.id,
                    recognizer=recognizer,
                    backend=action_backend,
                    capture=capture,
                    recorder=recorder,
                    options=AutomationOptions(
                        wait_timeout=self.config.wait_timeout,
                        poll_interval=self.config.poll_interval,
                        retry_limit=self.config.retry_limit,
                        safety_mode=self.config.safety_mode,
                    ),
                    checkpoint=checkpoint,
                )
                last_result = runner.run()
                checkpoint = {"joined": runner.joined, "battles": runner.battles, "skipped": runner.skipped}
                if last_result.success or last_result.status == "stopped":
                    return last_result
            finally:
                action_backend.close()
        return last_result or AccountAutomationResult(account.id, False, "failed", "no attempt result", False)

    @staticmethod
    def _select_accounts(accounts: list[AccountConfig]) -> list[AccountConfig]:
        print("可运行账号:")
        for index, account in enumerate(accounts, 1):
            print(f"  {index}. {account.id} ({account.name}) [{account.serial}]")
        raw = input("选择账号编号（逗号分隔，回车=全部）: ").strip()
        if not raw:
            return accounts
        indexes = {int(item.strip()) for item in raw.split(",") if item.strip().isdigit()}
        return [account for index, account in enumerate(accounts, 1) if index in indexes]
