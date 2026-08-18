from __future__ import annotations

import argparse
from pathlib import Path

from .adb_discovery import discover_adb
from .actions import AdbActionBackend, DryRunBackend, execute_action
from .backends import AdbCaptureBackend, CaptureBackendError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CATSWAR project ADB helper.")
    parser.add_argument("--discover-adb", action="store_true", help="Scan for adb.exe and exit.")
    parser.add_argument("--adb-path", type=Path, default=None, help="Path to adb.exe.")
    parser.add_argument("--adb-serial", default=None, help="Connected adb serial.")
    parser.add_argument("--capture", type=Path, default=None, help="Save an adb screenshot to this path.")
    parser.add_argument("--tap", nargs=2, type=int, metavar=("X", "Y"), help="Run one ADB tap.")
    parser.add_argument("--back", action="store_true", help="Send one BACK keyevent.")
    parser.add_argument("--wait", type=float, default=None, help="Wait for N seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Use the dry-run backend for actions.")
    return parser


def main(argv: list[str] | None = None) -> int:
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

    if args.capture is not None:
        if args.adb_path is None or args.adb_serial is None:
            raise SystemExit("--adb-path and --adb-serial are required for --capture.")
        backend = AdbCaptureBackend(args.adb_path, args.adb_serial)
        backend.capture(args.capture)
        return 0

    if args.tap or args.back or args.wait is not None:
        if args.dry_run:
            backend = DryRunBackend()
        else:
            if args.adb_path is None or args.adb_serial is None:
                raise SystemExit("--adb-path and --adb-serial are required for real actions.")
            backend = AdbActionBackend(adb_path=args.adb_path, adb_serial=args.adb_serial)
        if args.tap:
            x, y = args.tap
            execute_action({"name": "tap", "params": {"x": x, "y": y}, "reason": "cli"}, backend, dry_run=args.dry_run)
        elif args.back:
            execute_action("press_back", backend, dry_run=args.dry_run)
        else:
            execute_action({"name": "wait", "params": {"seconds": args.wait}, "reason": "cli"}, backend, dry_run=args.dry_run)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
