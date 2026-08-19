from __future__ import annotations

import argparse
from pathlib import Path

from .adb_discovery import discover_adb
from .actions import AdbActionBackend, execute_action
from .backends import AdbCaptureBackend, CaptureBackendError


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


if __name__ == "__main__":
    raise SystemExit(main())
