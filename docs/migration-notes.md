# Migration Notes

This repository currently carries over the ADB and basic control layer from the
previous `CATS Automatic` codebase.

## Sources used

- `docs/PROGRESS.md`
- `docs/RUN_IN_IDEA.md`
- `src/cats_automatic/adb_discovery.py`
- `src/cats_automatic/actions.py`
- `src/cats_automatic/backends/adb_capture.py`
- `src/cats_automatic/window_capture.py`
- `tests/test_adb_discovery.py`
- `tests/test_actions.py`
- `tests/test_adb_capture.py`

## What was intentionally left behind

- The full vision/template-matching stack.
- Game strategy logic.
- GUI tooling.
- The larger replay/window capture machinery.
