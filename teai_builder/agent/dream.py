"""Memory maintenance utilities inspired by the `/dream` workflow."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from teai_builder.config.paths import get_runtime_subdir


@dataclass
class DreamRecord:
    run_id: str
    created_at: float = field(default_factory=time.time)
    summary: str = ""
    improvements: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "summary": self.summary,
            "improvements": self.improvements,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DreamRecord:
        return cls(
            run_id=data["run_id"],
            created_at=data.get("created_at", time.time()),
            summary=data.get("summary", ""),
            improvements=data.get("improvements", []),
            metadata=data.get("metadata", {}),
        )


class DreamMaintainer:
    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = get_runtime_subdir("dream")
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: DreamRecord) -> Path:
        path = self.storage_dir / f"{record.run_id}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2)
        tmp.replace(path)
        return path

    def load(self, run_id: str) -> DreamRecord | None:
        path = self.storage_dir / f"{run_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return DreamRecord.from_dict(json.load(f))

    def list_recent(self, limit: int = 20) -> list[DreamRecord]:
        records = []
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    records.append(DreamRecord.from_dict(json.load(f)))
            except (OSError, json.JSONDecodeError):
                continue
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[: max(1, limit)]

    def analyze_run(self, run_id: str, run_summary: str, run_metadata: dict[str, Any] | None = None) -> DreamRecord:
        improvements: list[str] = []
        lowered = run_summary.lower()
        if "error" in lowered or "failed" in lowered:
            improvements.append("Reduce failure exposure by adding retries and shorter prompts.")
        if "timeout" in lowered:
            improvements.append("Investigate timeout causes and split large tasks.")
        if "checkpoint" not in lowered:
            improvements.append("Add semantic checkpoints around scaffold and verify phases.")
        if not improvements:
            improvements.append("Keep current workflow shape and monitor token usage.")
        record = DreamRecord(
            run_id=run_id,
            summary=run_summary[:500],
            improvements=improvements,
            metadata=run_metadata or {},
        )
        self.save(record)
        return record


class DreamImprover:
    def __init__(self, maintainer: DreamMaintainer | None = None) -> None:
        self.maintainer = maintainer or get_dream_maintainer()

    def suggest_prompt_changes(self, run_id: str) -> list[str]:
        record = self.maintainer.load(run_id)
        if not record:
            return []
        return record.improvements


# Global singleton
_maintainer: DreamMaintainer | None = None


def get_dream_maintainer() -> DreamMaintainer:
    global _maintainer
    if _maintainer is None:
        try:
            _maintainer = DreamMaintainer()
        except OSError:
            _maintainer = DreamMaintainer(storage_dir=Path("/tmp/teai_builder_dream"))
    return _maintainer
