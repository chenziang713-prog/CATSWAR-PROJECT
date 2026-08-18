# CATSWAR PROJECT

This repository starts from the ADB interaction and basic control layer from the
previous CATS prototype.

## What moved

- ADB device discovery and recommendation.
- ADB screenshot capture.
- Dry-run and real ADB action backends.
- Basic action execution for `wait`, `press_back`, `tap`, and `no_action`.

## Notes on earlier chat history

I could not find a separate chat transcript file in the workspace. The usable
project record is the old repository itself, especially:

- `docs/PROGRESS.md`
- `docs/RUN_IN_IDEA.md`
- `src/cats_automatic/adb_discovery.py`
- `src/cats_automatic/actions.py`
- `src/cats_automatic/backends/adb_capture.py`
- `tests/test_adb_discovery.py`
- `tests/test_actions.py`

## Current feature set

- ADB device discovery and recommendation via `--discover-adb`.
- ADB screenshot capture (`adb exec-out screencap`) saved through `--capture`.
- Dry-run and real ADB action backends.
- Basic action execution for `wait`, `press_back`, `tap`, and `no_action`.
- **Per-instance output folder** (`--instance-dir`) — each emulator gets its own
  folder for screenshots and output; the folder also serves as the instance id.
- **Shared command folder** (`--cmd-dir`) — multiple emulators may point to the
  same folder that will hold command files read later (reserved, not yet read).
- Capture-target vs. instance-folder correspondence check (see below).

## Instance folder / capture path rules

In the current testing phase the two folders are optional and may be given in
any combination:

- Only `--instance-dir`: screenshots default into that instance folder.
- Only `--capture`: screenshots go to the given path.
- Neither: allowed; an error is raised only when a screenshot is actually
  requested with no output path available.
- **Both given:** the parent directory of `--capture` must equal `--instance-dir`,
  otherwise the run fails with `--capture and --instance-dir do not correspond`.

These rules are enforced by `validate_capture_paths()` in
`src/catswar_project/main.py` and covered by `tests/test_main.py`.

## Run

Create a virtual environment, install dependencies, then try:

```powershell
python -m pip install -e .[dev]
python -m catswar_project.main --discover-adb
```

Basic usage examples:

```powershell
# Discover and recommend ADB.
python -m catswar_project.main --discover-adb

# Save a screenshot into an instance folder.
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --instance-dir D:\runs\inst1 --capture

# Save a screenshot to an explicit path (no instance folder).
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --capture D:\shots\screen.png

# Two emulators sharing one command folder (multi-instance).
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --instance-dir D:\runs\inst1 --cmd-dir D:\commands
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5556 --instance-dir D:\runs\inst2 --cmd-dir D:\commands

# Run a single tap / back press / wait (dry-run supported).
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --tap 100 200
python -m catswar_project.main --adb-path "C:\LDPlayer\adb.exe" --adb-serial emulator-5554 --back
python -m catswar_project.main --dry-run --tap 100 200
```

Run the test suite from the repository root:

```powershell
python -m pytest -q
```
