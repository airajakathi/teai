"""Minimal normalized event recorder for phase 2 LLM3 orchestration."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OrchestrationEventRecord:
    event_id: str
    turn_id: str
    session_key: str
    type: str
    created_at: int
    payload: dict[str, Any] = field(default_factory=dict)


class OrchestrationEventEmitter:
    """Store a minimal in-memory event stream per turn."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._events: dict[str, list[OrchestrationEventRecord]] = {}
        self._storage_dir = Path(storage_dir) if storage_dir is not None else None
        if self._storage_dir is not None:
            self._storage_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def emit(
        self,
        *,
        turn_id: str,
        session_key: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> OrchestrationEventRecord:
        record = OrchestrationEventRecord(
            event_id=f"evt-{uuid.uuid4().hex[:10]}",
            turn_id=turn_id,
            session_key=session_key,
            type=event_type,
            created_at=self._now_ms(),
            payload=dict(payload or {}),
        )
        self._events.setdefault(turn_id, []).append(record)
        self._persist_turn_events(turn_id)
        return record

    def summary(self, turn_id: str) -> dict[str, Any]:
        events = self._events.get(turn_id, [])
        if not events:
            return {"count": 0, "last_event": None}
        return {
            "count": len(events),
            "last_event": events[-1].type,
            "types": [event.type for event in events],
        }

    def _persist_turn_events(self, turn_id: str) -> None:
        if self._storage_dir is None:
            return
        events = self._events.get(turn_id, [])
        target = self._storage_dir / f"{turn_id}.json"
        payload = [
            {
                "event_id": event.event_id,
                "turn_id": event.turn_id,
                "session_key": event.session_key,
                "type": event.type,
                "created_at": event.created_at,
                "payload": event.payload,
            }
            for event in events
        ]
        target.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
