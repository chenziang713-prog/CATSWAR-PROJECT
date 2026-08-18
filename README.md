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

## Run

Create a virtual environment, install dependencies, then try:

```powershell
python -m pip install -e .[dev]
python -m catswar_project.main --discover-adb
```
