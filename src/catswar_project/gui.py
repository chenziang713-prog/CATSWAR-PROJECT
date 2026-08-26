from __future__ import annotations

"""Small Windows desktop front end for the CATSWAR runner.

Tkinter is part of the standard Python installation, so the GUI does not add a
second UI dependency or duplicate any automation logic. The scheduler runs in
a worker thread and all widget updates are marshalled back to Tk's event loop.
"""

import contextlib
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import load_config
from .scheduler import AccountScheduler, SchedulerResult


@dataclass
class GuiAccount:
    account_id: str = ""
    name: str = ""
    serial: str = ""
    instance: str = ""
    enabled: bool = True


def _account_from_raw(value: Any) -> GuiAccount:
    if not isinstance(value, dict):
        raise ValueError("每个账号必须是对象")
    return GuiAccount(
        account_id=str(value.get("id", "")).strip(),
        name=str(value.get("name", value.get("id", ""))).strip(),
        serial=str(value.get("serial", "")).strip(),
        instance=str(value.get("emulator_instance", "")).strip(),
        enabled=bool(value.get("enabled", True)),
    )


def _default_payload() -> dict[str, Any]:
    return {
        "adb_path": "adb.exe",
        "ldplayer_path": "",
        "launch_command": [],
        "concurrency": 1,
        "omni_parser_url": "http://127.0.0.1:8000/parse/",
        "output_dir": "output",
        "screenshot_dir": "output/screenshots",
        "stop_file": "output/STOP",
        "retry_limit": 3,
        "wait_timeout": 180,
        "poll_interval": 2,
        "safety_mode": "guarded",
        "resume_run_id": None,
        "accounts": [],
    }


def read_gui_config(path: Path) -> dict[str, Any]:
    """Read a config file for the GUI while keeping optional fields intact."""
    if not path.exists():
        return _default_payload()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("配置文件根节点必须是对象")
    payload = _default_payload()
    payload.update(value)
    accounts = payload.get("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("accounts 必须是数组")
    payload["accounts"] = [
        {
            "id": account.account_id,
            "name": account.name,
            "serial": account.serial,
            "emulator_instance": account.instance,
            "enabled": account.enabled,
        }
        for account in (_account_from_raw(item) for item in accounts)
    ]
    return payload


def write_gui_config(path: Path, payload: dict[str, Any], accounts: Iterable[GuiAccount]) -> None:
    """Validate and write the values currently shown in the GUI."""
    account_values = []
    seen: set[str] = set()
    for account in accounts:
        account_id = account.account_id.strip()
        serial = account.serial.strip()
        if not account_id or not serial:
            raise ValueError("每个启用或停用的账号都必须填写 ID 和 ADB serial")
        if account_id in seen:
            raise ValueError(f"账号 ID 重复：{account_id}")
        seen.add(account_id)
        account_values.append({
            "id": account_id,
            "name": account.name.strip() or account_id,
            "serial": serial,
            "emulator_instance": account.instance.strip(),
            "enabled": bool(account.enabled),
        })
    if not account_values:
        raise ValueError("至少需要配置一个账号")
    result = dict(payload)
    result["accounts"] = account_values
    result["adb_path"] = str(result.get("adb_path", "")).strip()
    result["omni_parser_url"] = str(result.get("omni_parser_url", "")).strip()
    if not result["adb_path"]:
        raise ValueError("ADB 路径不能为空")
    if not result["omni_parser_url"]:
        raise ValueError("OmniParser 地址不能为空")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class _QueueWriter:
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        self.events = events

    def write(self, value: str) -> int:
        if value.strip():
            self.events.put(("log", value.rstrip()))
        return len(value)

    def flush(self) -> None:
        return None


class CatswarGui:
    def __init__(self, root: Any, *, config_path: Path | None = None) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title("CATSWAR 城战脚本")
        self.root.geometry("1080x760")
        self.root.minsize(900, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.scheduler: AccountScheduler | None = None
        self.worker: threading.Thread | None = None
        self.running = False
        self.rows: list[dict[str, Any]] = []
        self.payload: dict[str, Any] = _default_payload()
        self.config_path = tk.StringVar(value=str(config_path or self._initial_config_path()))
        self.adb_path = tk.StringVar(value="adb.exe")
        self.omni_url = tk.StringVar(value="http://127.0.0.1:8000/parse/")
        self.launch_command = tk.StringVar(value="[]")
        self.output_dir = tk.StringVar(value="output")
        self.screenshot_dir = tk.StringVar(value="output/screenshots")
        self.stop_file = tk.StringVar(value="output/STOP")
        self.concurrency = tk.IntVar(value=1)
        self.retry_limit = tk.IntVar(value=3)
        self.wait_timeout = tk.IntVar(value=180)
        self.poll_interval = tk.DoubleVar(value=2.0)
        self.safety_mode = tk.StringVar(value="guarded")
        self.status = tk.StringVar(value="未运行")
        self.summary = tk.StringVar(value="请先检查 ADB 和 OmniParser 配置")
        self._build()
        self._load_config(silent=True)
        self.root.after(100, self._drain_events)

    def _initial_config_path(self) -> Path:
        cwd = Path.cwd()
        preferred = cwd / "config" / "accounts.json"
        if preferred.exists():
            return preferred
        example = cwd / "config" / "accounts.example.json"
        return example if example.exists() else preferred

    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        title = ttk.Label(outer, text="CATSWAR 城战脚本", font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")
        ttk.Label(outer, text="配置账号、检查连接后启动自动化。脚本只在识别到明确页面上下文时执行点击。",
                  foreground="#555555").pack(anchor="w", pady=(2, 12))

        self._build_general(outer)
        self._build_accounts(outer)
        self._build_actions(outer)
        self._build_log(outer)

    def _build_general(self, parent: Any) -> None:
        tk, ttk = self.tk, self.ttk
        frame = ttk.LabelFrame(parent, text="运行配置", padding=10)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(4, weight=1)

        ttk.Label(frame, text="配置文件").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(frame, textvariable=self.config_path).grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Button(frame, text="打开", command=self._choose_config).grid(row=0, column=4, padx=(6, 0), pady=4)
        ttk.Button(frame, text="加载", command=self._load_config).grid(row=0, column=5, padx=(6, 0), pady=4)
        ttk.Button(frame, text="保存", command=self._save_config).grid(row=0, column=6, padx=(6, 0), pady=4)

        ttk.Label(frame, text="ADB 路径").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(frame, textvariable=self.adb_path).grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Button(frame, text="选择", command=self._choose_adb).grid(row=1, column=4, padx=(6, 0), pady=4)
        ttk.Button(frame, text="检查 ADB", command=self._inspect_adb).grid(row=1, column=5, columnspan=2, padx=(6, 0), pady=4)

        ttk.Label(frame, text="OmniParser 地址").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(frame, textvariable=self.omni_url).grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Label(frame, text="另一台电脑请填局域网 IP，不要用 127.0.0.1", foreground="#7a4e00").grid(
            row=2, column=4, columnspan=3, sticky="w", padx=(6, 0), pady=4
        )

        ttk.Label(frame, text="并发账号").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Spinbox(frame, from_=1, to=16, textvariable=self.concurrency, width=8).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(frame, text="安全模式").grid(row=3, column=2, sticky="e", padx=(12, 6), pady=4)
        ttk.Combobox(frame, textvariable=self.safety_mode, values=("guarded", "aggressive"), state="readonly", width=12).grid(
            row=3, column=3, sticky="w", pady=4
        )
        ttk.Label(frame, text="重试次数").grid(row=3, column=4, sticky="e", padx=(12, 6), pady=4)
        ttk.Spinbox(frame, from_=0, to=20, textvariable=self.retry_limit, width=8).grid(row=3, column=5, sticky="w", pady=4)

        advanced = ttk.Frame(frame)
        advanced.grid(row=4, column=0, columnspan=7, sticky="ew", pady=(6, 0))
        advanced.columnconfigure(1, weight=1)
        advanced.columnconfigure(3, weight=1)
        ttk.Label(advanced, text="模拟器启动命令（JSON 数组，可留空）").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(advanced, textvariable=self.launch_command).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(advanced, text="输出目录").grid(row=0, column=2, sticky="e", padx=(12, 6), pady=3)
        ttk.Entry(advanced, textvariable=self.output_dir).grid(row=0, column=3, sticky="ew", pady=3)
        ttk.Label(advanced, text="等待超时(s)").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Spinbox(advanced, from_=5, to=3600, textvariable=self.wait_timeout, width=10).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(advanced, text="轮询间隔(s)").grid(row=1, column=2, sticky="e", padx=(12, 6), pady=3)
        ttk.Spinbox(advanced, from_=0.2, to=60, increment=0.2, textvariable=self.poll_interval, width=10).grid(row=1, column=3, sticky="w", pady=3)

    def _build_accounts(self, parent: Any) -> None:
        ttk = self.ttk
        frame = ttk.LabelFrame(parent, text="账号列表", padding=10)
        frame.pack(fill="x", pady=(0, 10))
        header = ttk.Frame(frame)
        header.pack(fill="x")
        widths = (("启用", 7), ("账号 ID", 18), ("名称", 18), ("ADB serial", 24), ("模拟器实例", 18), ("操作", 10))
        for column, (label, width) in enumerate(widths):
            header.columnconfigure(column, weight=1 if column in {1, 2, 3, 4} else 0)
            ttk.Label(header, text=label, width=width).grid(row=0, column=column, sticky="w", padx=3)
        self.account_rows = ttk.Frame(frame)
        self.account_rows.pack(fill="x", pady=(4, 4))
        self.account_rows.columnconfigure(1, weight=1)
        self.account_rows.columnconfigure(2, weight=1)
        self.account_rows.columnconfigure(3, weight=1)
        self.account_rows.columnconfigure(4, weight=1)
        ttk.Button(frame, text="+ 添加账号", command=lambda: self._add_account_row()).pack(anchor="w", pady=(4, 0))

    def _build_actions(self, parent: Any) -> None:
        ttk = self.ttk
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(0, 8))
        self.start_button = ttk.Button(frame, text="▶ 启动自动化", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(frame, text="■ 停止", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Button(frame, text="打开输出目录", command=self._open_output).pack(side="left", padx=(8, 0))
        ttk.Label(frame, textvariable=self.status).pack(side="right")
        ttk.Label(parent, textvariable=self.summary, foreground="#555555").pack(anchor="w", pady=(0, 6))

    def _build_log(self, parent: Any) -> None:
        tk, ttk = self.tk, self.ttk
        frame = ttk.LabelFrame(parent, text="运行日志", padding=8)
        frame.pack(fill="both", expand=True)
        self.log = tk.Text(frame, height=16, wrap="word", state="disabled", background="#101418", foreground="#d6e2ea",
                           insertbackground="#ffffff", relief="flat", padx=8, pady=8)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _add_account_row(self, account: GuiAccount | None = None) -> None:
        ttk = self.ttk
        account = account or GuiAccount()
        row = len(self.rows)
        enabled = self.tk.BooleanVar(value=account.enabled)
        variables = {
            "enabled": enabled,
            "id": self.tk.StringVar(value=account.account_id),
            "name": self.tk.StringVar(value=account.name),
            "serial": self.tk.StringVar(value=account.serial),
            "instance": self.tk.StringVar(value=account.instance),
        }
        widgets: list[Any] = []
        checkbutton = ttk.Checkbutton(self.account_rows, variable=enabled)
        checkbutton.grid(row=row, column=0, padx=3, pady=3)
        for column, key in enumerate(("id", "name", "serial", "instance"), 1):
            entry = ttk.Entry(self.account_rows, textvariable=variables[key])
            entry.grid(row=row, column=column, sticky="ew", padx=3, pady=3)
            widgets.append(entry)
        button = ttk.Button(self.account_rows, text="删除", command=lambda: self._remove_account_row(row_data))
        button.grid(row=row, column=5, padx=3, pady=3)
        row_data = {"variables": variables, "widgets": widgets, "button": button, "checkbutton": checkbutton}
        self.rows.append(row_data)

    def _remove_account_row(self, row_data: dict[str, Any]) -> None:
        if row_data not in self.rows:
            return
        self.rows.remove(row_data)
        for widget in row_data["widgets"] + [row_data["button"], row_data["checkbutton"]]:
            widget.destroy()
        row_data["variables"]["enabled"].set(False)
        self._regrid_account_rows()

    def _regrid_account_rows(self) -> None:
        for row, row_data in enumerate(self.rows):
            row_data["checkbutton"].grid_configure(row=row, column=0)
            for column, widget in enumerate(row_data["widgets"], 1):
                widget.grid_configure(row=row, column=column)
            row_data["button"].grid_configure(row=row, column=5)

    def _accounts(self) -> list[GuiAccount]:
        result = []
        for row in self.rows:
            values = row["variables"]
            result.append(GuiAccount(
                account_id=values["id"].get(), name=values["name"].get(), serial=values["serial"].get(),
                instance=values["instance"].get(), enabled=bool(values["enabled"].get()),
            ))
        return result

    def _payload_from_widgets(self) -> dict[str, Any]:
        launch = json.loads(self.launch_command.get() or "[]")
        if not isinstance(launch, list) or not all(isinstance(item, str) for item in launch):
            raise ValueError("模拟器启动命令必须是 JSON 字符串数组")
        result = dict(self.payload)
        result.update({
            "adb_path": self.adb_path.get().strip(),
            "launch_command": launch,
            "omni_parser_url": self.omni_url.get().strip(),
            "concurrency": int(self.concurrency.get()),
            "output_dir": self.output_dir.get().strip() or "output",
            "screenshot_dir": self.screenshot_dir.get().strip() or "output/screenshots",
            "stop_file": self.stop_file.get().strip() or "output/STOP",
            "retry_limit": int(self.retry_limit.get()),
            "wait_timeout": int(self.wait_timeout.get()),
            "poll_interval": float(self.poll_interval.get()),
            "safety_mode": self.safety_mode.get().strip().lower(),
            "resume_run_id": None,
            "accounts": [],
        })
        return result

    def _choose_config(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择配置文件", filetypes=(("JSON", "*.json"), ("所有文件", "*.*")))
        if path:
            self.config_path.set(path)
            self._load_config()

    def _choose_adb(self) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择 adb.exe", filetypes=(("ADB", "adb.exe"), ("所有文件", "*.*")))
        if path:
            self.adb_path.set(path)

    def _load_config(self, *, silent: bool = False) -> None:
        try:
            payload = read_gui_config(Path(self.config_path.get()))
            self.payload = dict(payload)
            self.adb_path.set(str(payload.get("adb_path", "adb.exe")))
            self.omni_url.set(str(payload.get("omni_parser_url", "http://127.0.0.1:8000/parse/")))
            self.launch_command.set(json.dumps(payload.get("launch_command", []), ensure_ascii=False))
            self.output_dir.set(str(payload.get("output_dir", "output")))
            self.screenshot_dir.set(str(payload.get("screenshot_dir", "output/screenshots")))
            self.stop_file.set(str(payload.get("stop_file", "output/STOP")))
            self.concurrency.set(int(payload.get("concurrency", 1)))
            self.retry_limit.set(int(payload.get("retry_limit", 3)))
            self.wait_timeout.set(int(payload.get("wait_timeout", 180)))
            self.poll_interval.set(float(payload.get("poll_interval", 2)))
            self.safety_mode.set(str(payload.get("safety_mode", "guarded")))
            for row in list(self.rows):
                self._remove_account_row(row)
            for raw in payload.get("accounts", []):
                self._add_account_row(_account_from_raw(raw))
            if not silent:
                self._set_summary(f"已加载 {len(self.rows)} 个账号")
        except Exception as exc:
            if not silent:
                self._error(str(exc))

    def _save_config(self) -> bool:
        try:
            payload = self._payload_from_widgets()
            write_gui_config(Path(self.config_path.get()), payload, self._accounts())
            self._set_summary(f"配置已保存：{self.config_path.get()}")
            return True
        except Exception as exc:
            self._error(str(exc))
            return False

    def _inspect_adb(self) -> None:
        if self.running:
            return
        adb = self.adb_path.get().strip()
        self._set_status("正在检查 ADB…")
        threading.Thread(target=self._inspect_adb_worker, args=(adb,), daemon=True).start()

    def _inspect_adb_worker(self, adb: str) -> None:
        try:
            result = subprocess.run([adb, "devices"], capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "adb devices 执行失败")
            output = result.stdout.strip() or "没有检测到设备"
            self.events.put(("adb", output))
        except Exception as exc:
            self.events.put(("error", f"ADB 检查失败：{exc}"))

    def _start(self) -> None:
        if self.running:
            return
        if not self._save_config():
            return
        try:
            config = load_config(Path(self.config_path.get()))
        except Exception as exc:
            self._error(str(exc))
            return
        self.scheduler = AccountScheduler(config)
        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._set_status("运行中")
        self._set_summary("正在截图识别，首次识别可能需要一些时间…")
        self._append_log(f"开始运行：{self.config_path.get()}")
        self.worker = threading.Thread(target=self._run_worker, args=(self.scheduler,), daemon=True)
        self.worker.start()

    def _run_worker(self, scheduler: AccountScheduler) -> None:
        writer = _QueueWriter(self.events)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                result = scheduler.run()
            self.events.put(("result", result))
        except Exception as exc:
            self.events.put(("error", f"运行失败：{exc}"))

    def _stop(self) -> None:
        if self.scheduler is not None and self.running:
            self.scheduler.stop()
            self._append_log("已发送停止请求，等待当前动作安全结束…")
            self._set_status("停止中")

    def _open_output(self) -> None:
        path = Path(self.output_dir.get()).resolve()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os_startfile = getattr(__import__("os"), "startfile")
            os_startfile(str(path))
        except (AttributeError, OSError) as exc:
            self._error(f"无法打开输出目录：{exc}")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(value))
                elif kind == "adb":
                    self._append_log(str(value))
                    self._set_status("ADB 检查完成")
                    self._set_summary("设备列表已显示在日志中")
                elif kind == "result":
                    self._finish_run(value)
                elif kind == "error":
                    self._error(str(value))
                    if self.running:
                        self._finish_run(None)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _finish_run(self, result: SchedulerResult | None) -> None:
        self.running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if result is None:
            self._set_status("失败")
            return
        self._set_status("完成" if result.success else "部分失败")
        lines = [f"运行结束：run_id={result.run_id}"]
        for item in result.results:
            lines.append(f"{item.account_id}: {item.status}，战斗 {item.battles} 场，{item.message}")
        self._append_log("\n".join(lines))
        self._set_summary(f"完成 {len(result.results)} 个账号，成功 {sum(item.success for item in result.results)} 个")

    def _on_close(self) -> None:
        if self.running and self.scheduler is not None:
            self.scheduler.stop()
        self.root.destroy()

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, value: str) -> None:
        self.status.set(value)

    def _set_summary(self, value: str) -> None:
        self.summary.set(value)

    def _error(self, message: str) -> None:
        self._append_log(f"错误：{message}")
        self._set_status("配置错误")
        try:
            from tkinter import messagebox
            messagebox.showerror("CATSWAR", message)
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CATSWAR Windows desktop GUI")
    parser.add_argument("--config", type=Path, default=None, help="配置文件路径")
    args = parser.parse_args(argv)
    try:
        import tkinter as tk
    except ImportError:
        print("当前 Python 未安装 Tkinter，无法启动 GUI。", file=sys.stderr)
        return 1
    root = tk.Tk()
    CatswarGui(root, config_path=args.config)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
