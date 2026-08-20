from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from dataclasses import replace

from .adb_discovery import discover_adb
from .actions import AdbActionBackend, execute_action
from .backends import AdbCaptureBackend, CaptureBackendError
from .config import load_config
from .scheduler import AccountScheduler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CATSWAR project ADB helper.")
    parser.add_argument("--discover-adb", action="store_true", help="Scan for adb.exe and exit.")
    parser.add_argument("--adb-path", type=Path, default=None, help="Path to adb.exe.")
    parser.add_argument("--adb-serial", default=None, help="Connected adb serial.")
    parser.add_argument("--instance-dir", type=Path, default=None, help="Per-emulator instance folder for screenshots/output; also serves as the instance id.")
    parser.add_argument("--cmd-dir", type=Path, default=None, help="Shared command folder read by the emulator (optional; reserved for command lookup).")
    parser.add_argument("--capture", type=Path, default=None, help="Save an adb screenshot to this path. If both given, its parent must equal --instance-dir.")
    parser.add_argument("--tap", nargs=2, type=int, metavar=("X", "Y"), help="Run one ADB tap.")
    parser.add_argument("--back", action="store_true", help="Send one BACK keyevent.")
    parser.add_argument("--wait", type=float, default=None, help="Wait for N seconds.")
    return parser


def build_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CATS WAR multi-account automation.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run configured accounts")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--select", action="store_true", help="choose accounts interactively")
    run.add_argument("--account", action="append", default=[], help="run only this account id; repeatable")
    run.add_argument("--concurrency", type=int, default=None)
    run.add_argument("--safety-mode", choices=("aggressive", "guarded"), default=None)
    run.add_argument("--resume-run", default=None, help="resume checkpoints from a previous run id")
    inspect = sub.add_parser("inspect", help="inspect connected ADB devices")
    inspect.add_argument("--adb-path", type=Path, default=Path("adb"))
    inspect.add_argument("--serial", default=None)
    stop = sub.add_parser("stop", help="request a safe stop")
    stop.add_argument("--config", type=Path, default=Path("config/accounts.json"))
    return parser


def validate_capture_paths(capture: Path | None, instance_dir: Path | None) -> None:
    """Validate the relationship between --capture and --instance-dir.

    Either path may be omitted. When both are given, the parent directory of
    --capture must equal --instance-dir. Raises SystemExit otherwise.
    """
    if capture is not None and instance_dir is not None:
        if capture.parent.resolve() != instance_dir.resolve():
            raise SystemExit(
                "--capture and --instance-dir do not correspond: "
                f"parent of --capture ({capture.parent}) must equal --instance-dir ({instance_dir})."
            )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv and argv[0] in {"run", "inspect", "stop"}:
        return _automation_main(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.discover_adb:
        result = discover_adb()
        for candidate in result.candidates:
            devices = ", ".join(f"{device.serial} {device.state}" for device in candidate.devices) or "no devices"
            print(f"{candidate.adb_path} -> {devices}")
        if result.recommended is not None:
            print(f"recommended: {result.recommended.adb_path}")
        return 0

    if args.capture is not None or args.instance_dir is not None:
        validate_capture_paths(args.capture, args.instance_dir)
        if args.adb_path is None or args.adb_serial is None:
            raise SystemExit("--adb-path and --adb-serial are required for capture.")
        backend = AdbCaptureBackend(args.adb_path, args.adb_serial, instance_dir=args.instance_dir)
        backend.capture(args.capture)
        return 0

    if args.tap or args.back or args.wait is not None:
        if args.adb_path is None or args.adb_serial is None:
            raise SystemExit("--adb-path and --adb-serial are required for actions.")
        backend = AdbActionBackend(
            adb_path=args.adb_path,
            adb_serial=args.adb_serial,
            instance_dir=args.instance_dir,
            cmd_dir=args.cmd_dir,
        )
        if args.tap:
            x, y = args.tap
            execute_action({"name": "tap", "params": {"x": x, "y": y}, "reason": "cli"}, backend)
        elif args.back:
            execute_action("press_back", backend)
        else:
            execute_action({"name": "wait", "params": {"seconds": args.wait}, "reason": "cli"}, backend)
        return 0

    parser.print_help()
    return 0


def _automation_main(argv: list[str]) -> int:
    args = build_run_parser().parse_args(argv)
    if args.command == "inspect":
        import subprocess

        result = subprocess.run([str(args.adb_path), "devices"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(result.stderr or "adb devices failed")
            return 1
        print(result.stdout, end="")
        if args.serial and args.serial not in result.stdout:
            return 1
        return 0
    if args.command == "stop":
        config = load_config(args.config) if args.config.exists() else None
        stop_file = config.stop_file if config is not None else Path("output/STOP")
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stop_file.write_text("stop\n", encoding="utf-8")
        print(f"stop requested: {stop_file}")
        return 0
    config = load_config(args.config)
    if args.concurrency is not None:
        if args.concurrency < 1:
            raise SystemExit("--concurrency must be greater than zero")
        config = replace(config, concurrency=args.concurrency)
    if args.safety_mode is not None:
        config = replace(config, safety_mode=args.safety_mode)
    if args.resume_run is not None:
        config = replace(config, resume_run_id=args.resume_run)
    selected = set(args.account) if args.account else None
    scheduler = AccountScheduler(config)
    try:
        result = scheduler.run(config.with_accounts(selected).accounts if selected else None, select=args.select)
    except KeyboardInterrupt:
        scheduler.stop()
        print("stop requested")
        return 130
    print(json.dumps({"run_id": result.run_id, "success": result.success,
                      "results": [item.__dict__ for item in result.results]}, ensure_ascii=False, indent=2, default=str))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
