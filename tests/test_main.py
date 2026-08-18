from __future__ import annotations

from pathlib import Path

import pytest

from catswar_project.main import validate_capture_paths


class TestValidateCapturePaths:
    def test_both_filled_matching_parent_is_accepted(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "inst1"
        capture = instance_dir / "screenshot.png"
        # Should not raise.
        validate_capture_paths(capture, instance_dir)

    def test_both_filled_mismatch_parent_raises_SystemExit(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "inst1"
        capture = tmp_path / "other" / "screenshot.png"
        with pytest.raises(SystemExit) as excinfo:
            validate_capture_paths(capture, instance_dir)
        assert "do not correspond" in str(excinfo.value)

    def test_nested_subdirectory_is_not_a_corresponding_parent(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "inst1"
        capture = instance_dir / "sub" / "screenshot.png"
        with pytest.raises(SystemExit) as excinfo:
            validate_capture_paths(capture, instance_dir)
        assert "do not correspond" in str(excinfo.value)

    def test_only_capture_is_allowed(self, tmp_path: Path) -> None:
        capture = tmp_path / "screenshot.png"
        # Should not raise.
        validate_capture_paths(capture, None)

    def test_only_instance_dir_is_allowed(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "inst1"
        # Should not raise.
        validate_capture_paths(None, instance_dir)

    def test_both_empty_is_allowed(self) -> None:
        # Should not raise.
        validate_capture_paths(None, None)
