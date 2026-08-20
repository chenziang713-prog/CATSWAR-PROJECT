from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .vision import OmniParserRecognizer


def load_memory_frames(mapping_dir: Path, image_dir: Path | None = None) -> tuple[tuple[Path, Path], ...]:
    """Load the numbered 01-44 teaching mappings as local replay frames.

    Mapping JSON files contain the recorded OmniParser response while the
    sibling images directory contains the corresponding screenshot. The old
    absolute ``file`` field is intentionally ignored.
    """
    mapping_dir = Path(mapping_dir)
    image_dir = image_dir or mapping_dir.parent / "images"
    frames: list[tuple[Path, Path]] = []
    for mapping_path in sorted(mapping_dir.glob("*.json")):
        if mapping_path.name.lower() == "anchors.json":
            continue
        try:
            value = json.loads(mapping_path.read_text(encoding="utf-8"))
            idx = str(value.get("idx", "")).zfill(2)
        except (OSError, ValueError, TypeError):
            continue
        if not idx.isdigit():
            continue
        image_path = next((candidate for candidate in (
            image_dir / f"{idx}.png", image_dir / f"{idx}.jpg", image_dir / f"{idx}.jpeg"
        ) if candidate.exists()), None)
        if image_path is not None:
            frames.append((image_path, mapping_path))
    return tuple(frames)


def load_memory_replay(mapping_dir: Path, image_dir: Path | None = None) -> tuple[tuple[Path, Path], ReplayParserClient]:
    frames = load_memory_frames(mapping_dir, image_dir)
    return frames, load_replay_client(mapping_path for _, mapping_path in frames)


class ReplayParserClient:
    """Offline OmniParser-compatible client for recorded parsed_content_list data."""

    def __init__(self, responses: Iterable[list[dict[str, Any]]] | Iterable[dict[str, Any]]) -> None:
        self.responses = []
        for response in responses:
            if isinstance(response, dict):
                response = response.get("parsed_content_list", response.get("parsed", []))
            self.responses.append(list(response))
        self.index = 0

    def parse(self, image_path: Path) -> list[dict[str, Any]]:
        if not self.responses:
            return []
        response = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return response


def load_replay_client(paths: Iterable[Path]) -> ReplayParserClient:
    responses = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        responses.append(value)
    return ReplayParserClient(responses)


def replay_recognizer(paths: Iterable[Path], *, min_confidence: float = 0.35) -> OmniParserRecognizer:
    return OmniParserRecognizer(load_replay_client(paths), min_confidence=min_confidence)
