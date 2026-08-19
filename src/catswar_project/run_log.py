from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    event_type: str
    payload: dict[str, Any]
    timestamp: str


class RunRecorder:
    def __init__(self, output_root: Path = Path("output"), *, run_id: str | None = None) -> None:
        self.output_root = output_root
        self.run_id = run_id or _timestamp_id()
        self.run_dir = self.output_root / "runs" / self.run_id
        self.logs_dir = self.run_dir / "logs"
        self.state_results_dir = self.run_dir / "state_results"
        self.events_path = self.logs_dir / "events.jsonl"
        self.latest_path = self.output_root / "latest" / "run_id.txt"

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.state_results_dir.mkdir(parents=True, exist_ok=True)
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        self.latest_path.write_text(self.run_id, encoding="utf-8")

    def event(self, event_type: str, payload: dict[str, Any] | None = None) -> RunEvent:
        event = RunEvent(
            run_id=self.run_id,
            event_type=event_type,
            payload=_to_jsonable(payload or {}),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def write_state_result(self, name: str, payload: dict[str, Any]) -> Path:
        safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in name)
        path = self.state_results_dir / f"{safe_name}.json"
        path.write_text(
            json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path


def _timestamp_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(item) for item in value]
    return value
