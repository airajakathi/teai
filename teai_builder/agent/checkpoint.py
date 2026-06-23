"""Checkpoint and rebuild system for long-horizon agent tasks."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from teai_builder.config.paths import get_runtime_subdir


@dataclass
class Checkpoint:
    """Represents a point-in-time snapshot of agent state."""
    
    checkpoint_id: str
    session_key: str
    created_at: float
    context_budget_pct: float  # 0.0-1.0 of context window used
    state: dict[str, Any]
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "session_key": self.session_key,
            "created_at": self.created_at,
            "context_budget_pct": self.context_budget_pct,
            "state": self.state,
            "messages": self.messages,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            session_key=data["session_key"],
            created_at=data["created_at"],
            context_budget_pct=data["context_budget_pct"],
            state=data["state"],
            messages=data["messages"],
            metadata=data.get("metadata", {}),
        )


class CheckpointStore:
    """Manages checkpoint persistence and retrieval."""
    
    def __init__(self, storage_dir: Path | None = None):
        if storage_dir is None:
            storage_dir = get_runtime_subdir("checkpoints")
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _path_for(self, session_key: str, checkpoint_id: str) -> Path:
        safe_session = session_key.replace("/", "_").replace(":", "_")
        return self.storage_dir / f"{safe_session}_{checkpoint_id}.json"
    
    def save(self, checkpoint: Checkpoint) -> Path:
        """Save checkpoint to disk."""
        path = self._path_for(checkpoint.session_key, checkpoint.checkpoint_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2)
        tmp.replace(path)
        return path
    
    def load(self, session_key: str, checkpoint_id: str) -> Checkpoint | None:
        """Load checkpoint from disk."""
        path = self._path_for(session_key, checkpoint_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Checkpoint.from_dict(data)
    
    def list_for_session(self, session_key: str) -> list[dict[str, Any]]:
        """List all checkpoints for a session."""
        safe_session = session_key.replace("/", "_").replace(":", "_")
        results = []
        for path in self.storage_dir.glob(f"{safe_session}_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append({
                    "checkpoint_id": data["checkpoint_id"],
                    "created_at": data["created_at"],
                    "context_budget_pct": data["context_budget_pct"],
                    "state": data.get("state", {}),
                    "metadata": data.get("metadata", {}),
                    "message_count": len(data.get("messages", [])),
                })
            except (OSError, json.JSONDecodeError):
                continue
        results.sort(key=lambda x: x["created_at"])
        return results
    
    def latest_for_session(self, session_key: str) -> Checkpoint | None:
        """Get the most recent checkpoint for a session."""
        checkpoints = self.list_for_session(session_key)
        if not checkpoints:
            return None
        return self.load(session_key, checkpoints[-1]["checkpoint_id"])
    
    def delete(self, session_key: str, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        path = self._path_for(session_key, checkpoint_id)
        if not path.exists():
            return False
        path.unlink()
        return True


def summarize_checkpoint(checkpoint: Checkpoint) -> dict[str, Any]:
    """Build a user-facing summary for a checkpoint."""
    metadata = dict(checkpoint.metadata or {})
    state = dict(checkpoint.state or {})
    summary = {
        "checkpoint_id": checkpoint.checkpoint_id,
        "session_key": checkpoint.session_key,
        "created_at": checkpoint.created_at,
        "context_budget_pct": checkpoint.context_budget_pct,
        "kind": metadata.get("kind", "session"),
        "message_count": len(checkpoint.messages),
        "workflow_id": metadata.get("workflow_id") or state.get("workflow_id"),
        "run_id": metadata.get("run_id") or state.get("run_id"),
        "step_id": metadata.get("step_id") or state.get("step_id"),
        "label": metadata.get("label"),
        "result_keys": list(metadata.get("result_keys", [])),
        "state_keys": sorted(state.keys()),
    }
    return summary


def build_rebuild_summary(checkpoint: Checkpoint) -> str:
    """Render a concise rebuild plan from a checkpoint."""
    summary = summarize_checkpoint(checkpoint)
    lines = [
        f"Checkpoint: `{summary['checkpoint_id']}`",
        f"Session: `{summary['session_key']}`",
        f"Kind: `{summary['kind']}`",
        f"Messages captured: {summary['message_count']}",
    ]
    if summary["label"]:
        lines.append(f"Label: {summary['label']}")
    if summary["workflow_id"]:
        lines.append(f"Workflow: `{summary['workflow_id']}`")
    if summary["run_id"]:
        lines.append(f"Run: `{summary['run_id']}`")
    if summary["step_id"]:
        lines.append(f"Step: `{summary['step_id']}`")
    if summary["result_keys"]:
        lines.append("Saved results: " + ", ".join(f"`{item}`" for item in summary["result_keys"]))
    if summary["state_keys"]:
        lines.append("State keys: " + ", ".join(f"`{item}`" for item in summary["state_keys"]))
    lines.extend(["", "Rebuild guidance:"])
    if summary["run_id"]:
        lines.append(f"- Inspect workflow progress with `/workflow status {summary['run_id']}`.")
        lines.append(f"- Resume the workflow with `/workflow resume {summary['run_id']}` if it is incomplete.")
    else:
        lines.append(f"- Restore the session snapshot with `/checkpoint restore {summary['checkpoint_id']}`.")
    if summary["step_id"]:
        lines.append(f"- Re-run or verify work after step `{summary['step_id']}`.")
    lines.append("- Review saved messages before continuing if the surrounding context may have changed.")
    return "\n".join(lines)


# Global checkpoint store instance
_checkpoint_store: CheckpointStore | None = None


def get_checkpoint_store() -> CheckpointStore:
    """Get the global checkpoint store."""
    global _checkpoint_store
    if _checkpoint_store is None:
        try:
            _checkpoint_store = CheckpointStore()
        except OSError:
            _checkpoint_store = CheckpointStore(storage_dir=Path("/tmp/teai_builder_checkpoints"))
    return _checkpoint_store


def should_checkpoint(context_budget_pct: float, last_checkpoint_pct: float) -> bool:
    """Determine if a checkpoint should be taken based on context budget.
    
    MiMo-Code pattern: checkpoint at ~20%, ~45%, ~70% of context budget.
    """
    thresholds = [0.20, 0.45, 0.70]
    for threshold in thresholds:
        if last_checkpoint_pct < threshold <= context_budget_pct:
            return True
    return False
