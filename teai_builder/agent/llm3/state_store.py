"""Minimal in-memory state store for phase 2 LLM3 orchestration."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .task_graph import TaskGraphRecord, task_graph_snapshot
from .types import ExecutionBrief, ExecutionResult, ReviewDecision, UnifiedTurn


@dataclass
class TurnStateRecord:
    turn_id: str
    session_key: str
    status: str
    created_at: int
    updated_at: int
    mode: str | None = None
    request_id: str | None = None
    review: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionStateRecord:
    request_id: str
    turn_id: str
    session_key: str
    status: str
    created_at: int
    updated_at: int
    mode: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerStateRecord:
    worker_id: str
    turn_id: str
    session_key: str
    label: str
    status: str
    created_at: int
    updated_at: int
    task_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckpointStateRecord:
    checkpoint_id: str
    turn_id: str
    session_key: str
    kind: str
    created_at: int
    updated_at: int
    request_id: str | None = None
    worker_id: str | None = None
    summary: str | None = None
    status: str = "created"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryStateRecord:
    recovery_id: str
    turn_id: str
    session_key: str
    reason: str
    status: str
    created_at: int
    updated_at: int
    source_checkpoint_id: str | None = None
    target_request_id: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class InMemoryOrchestrationStateStore:
    """Track minimal phase 2 orchestration state by turn and request id."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._turns: dict[str, TurnStateRecord] = {}
        self._executions: dict[str, ExecutionStateRecord] = {}
        self._workers: dict[str, WorkerStateRecord] = {}
        self._turn_workers: dict[str, list[str]] = {}
        self._checkpoints: dict[str, CheckpointStateRecord] = {}
        self._turn_checkpoints: dict[str, list[str]] = {}
        self._recoveries: dict[str, RecoveryStateRecord] = {}
        self._turn_recoveries: dict[str, list[str]] = {}
        self._graphs: dict[str, TaskGraphRecord] = {}
        self._turn_graphs: dict[str, list[str]] = {}
        self._storage_dir = Path(storage_dir) if storage_dir is not None else None
        if self._storage_dir is not None:
            self._storage_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def ensure_turn_context(
        self,
        turn_id: str,
        session_key: str,
        *,
        status: str = "started",
        metadata: dict[str, Any] | None = None,
    ) -> TurnStateRecord:
        now = self._now_ms()
        record = self._turns.get(turn_id)
        if record is None:
            record = TurnStateRecord(
                turn_id=turn_id,
                session_key=session_key,
                status=status,
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
            self._turns[turn_id] = record
        else:
            record.session_key = session_key
            record.status = status or record.status
            record.updated_at = now
            if metadata:
                record.metadata.update(metadata)
        self._persist_turn(turn_id)
        return record

    def start_turn(self, turn: UnifiedTurn) -> TurnStateRecord:
        return self.ensure_turn_context(
            turn.turn_id,
            turn.session_key,
            status="started",
            metadata={"channel": turn.channel},
        )

    def record_execution_brief(self, brief: ExecutionBrief) -> ExecutionStateRecord:
        now = self._now_ms()
        turn = self.ensure_turn_context(
            brief.turn_id,
            brief.session_key,
            status="executing",
        )
        turn.mode = brief.mode
        turn.request_id = brief.request_id
        record = ExecutionStateRecord(
            request_id=brief.request_id,
            turn_id=brief.turn_id,
            session_key=brief.session_key,
            status="prepared",
            created_at=now,
            updated_at=now,
            mode=brief.mode,
            metadata={"objective": brief.objective},
        )
        self._executions[brief.request_id] = record
        self._persist_turn(brief.turn_id)
        return record

    def record_execution_result(self, result: ExecutionResult) -> ExecutionStateRecord | None:
        now = self._now_ms()
        record = self._executions.get(result.request_id)
        if record is not None:
            record.status = result.status
            record.updated_at = now
            record.metadata["summary"] = result.summary
        turn = self._turns.get(result.turn_id)
        if turn is not None:
            turn.status = "reviewing"
            turn.updated_at = now
            self._persist_turn(result.turn_id)
        return record

    def record_review(self, review: ReviewDecision) -> TurnStateRecord | None:
        now = self._now_ms()
        turn = self._turns.get(review.turn_id)
        if turn is not None:
            turn.review = review.decision
            turn.status = "completed" if review.decision == "accept" else "needs_followup"
            turn.updated_at = now
            self._persist_turn(review.turn_id)
        return turn

    def record_worker_started(
        self,
        *,
        turn_id: str,
        session_key: str,
        worker_id: str,
        label: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerStateRecord:
        now = self._now_ms()
        turn = self.ensure_turn_context(
            turn_id,
            session_key,
            status="workers_running",
            metadata={"worker_activity": True},
        )
        turn.updated_at = now
        record = WorkerStateRecord(
            worker_id=worker_id,
            turn_id=turn_id,
            session_key=session_key,
            label=label,
            status="running",
            created_at=now,
            updated_at=now,
            task_id=task_id,
            metadata=dict(metadata or {}),
        )
        self._workers[worker_id] = record
        worker_ids = self._turn_workers.setdefault(turn_id, [])
        if worker_id not in worker_ids:
            worker_ids.append(worker_id)
        self._persist_turn(turn_id)
        return record

    def record_worker_update(
        self,
        worker_id: str,
        *,
        status: str,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerStateRecord | None:
        now = self._now_ms()
        record = self._workers.get(worker_id)
        if record is None:
            return None
        record.status = status
        record.updated_at = now
        record.error = error
        if metadata:
            record.metadata.update(metadata)
        turn = self._turns.get(record.turn_id)
        if turn is not None:
            turn.updated_at = now
            if status in {"completed", "failed", "cancelled"}:
                active = [
                    wid
                    for wid in self._turn_workers.get(record.turn_id, [])
                    if self._workers.get(wid) is not None
                    and self._workers[wid].status not in {"completed", "failed", "cancelled"}
                ]
                if not active and turn.status == "workers_running":
                    turn.status = "worker_settled"
            self._persist_turn(record.turn_id)
        return record

    def mark_completed(self, turn_id: str) -> TurnStateRecord | None:
        now = self._now_ms()
        turn = self._turns.get(turn_id)
        if turn is not None and turn.status in {
            "executing",
            "reviewing",
            "workers_running",
            "worker_settled",
        }:
            turn.status = "completed"
            turn.updated_at = now
            self._persist_turn(turn_id)
        return turn

    def record_checkpoint(
        self,
        *,
        turn_id: str,
        session_key: str,
        checkpoint_id: str,
        kind: str,
        request_id: str | None = None,
        worker_id: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CheckpointStateRecord:
        now = self._now_ms()
        self.ensure_turn_context(
            turn_id,
            session_key,
            status="workers_running",
            metadata={"checkpoint_activity": True},
        )
        record = CheckpointStateRecord(
            checkpoint_id=checkpoint_id,
            turn_id=turn_id,
            session_key=session_key,
            kind=kind,
            created_at=now,
            updated_at=now,
            request_id=request_id,
            worker_id=worker_id,
            summary=summary,
            metadata=dict(metadata or {}),
        )
        self._checkpoints[checkpoint_id] = record
        checkpoint_ids = self._turn_checkpoints.setdefault(turn_id, [])
        if checkpoint_id not in checkpoint_ids:
            checkpoint_ids.append(checkpoint_id)
        self._persist_turn(turn_id)
        return record

    def start_recovery(
        self,
        *,
        recovery_id: str,
        turn_id: str,
        session_key: str,
        reason: str,
        source_checkpoint_id: str | None = None,
        target_request_id: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecoveryStateRecord:
        now = self._now_ms()
        self.ensure_turn_context(
            turn_id,
            session_key,
            status="workers_running",
            metadata={"recovery_activity": True},
        )
        record = RecoveryStateRecord(
            recovery_id=recovery_id,
            turn_id=turn_id,
            session_key=session_key,
            reason=reason,
            status="running",
            created_at=now,
            updated_at=now,
            source_checkpoint_id=source_checkpoint_id,
            target_request_id=target_request_id,
            summary=summary,
            metadata=dict(metadata or {}),
        )
        self._recoveries[recovery_id] = record
        recovery_ids = self._turn_recoveries.setdefault(turn_id, [])
        if recovery_id not in recovery_ids:
            recovery_ids.append(recovery_id)
        self._persist_turn(turn_id)
        return record

    def complete_recovery(
        self,
        recovery_id: str,
        *,
        status: str,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecoveryStateRecord | None:
        now = self._now_ms()
        record = self._recoveries.get(recovery_id)
        if record is None:
            return None
        record.status = status
        record.updated_at = now
        if summary is not None:
            record.summary = summary
        if metadata:
            record.metadata.update(metadata)
        turn = self._turns.get(record.turn_id)
        if turn is not None:
            turn.updated_at = now
            self._persist_turn(record.turn_id)
        return record

    def record_task_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        graph: TaskGraphRecord,
    ) -> TaskGraphRecord:
        existing_turn = self._turns.get(turn_id)
        turn_status = (
            existing_turn.status
            if existing_turn is not None and existing_turn.status in {"completed", "needs_followup", "cancelled", "failed"}
            else "workers_running"
        )
        self.ensure_turn_context(
            turn_id,
            session_key,
            status=turn_status,
            metadata={"task_graph_activity": True},
        )
        self._graphs[graph.graph_id] = graph
        graph_ids = self._turn_graphs.setdefault(turn_id, [])
        if graph.graph_id not in graph_ids:
            graph_ids.append(graph.graph_id)
        self._persist_turn(turn_id)
        return graph

    def get_task_graph(self, graph_id: str) -> TaskGraphRecord | None:
        return self._graphs.get(graph_id)

    def latest_task_graph_for_turn(self, turn_id: str) -> TaskGraphRecord | None:
        graph_ids = self._turn_graphs.get(turn_id, [])
        if not graph_ids:
            return None
        return self._graphs.get(graph_ids[-1])

    def snapshot(self, turn_id: str) -> dict[str, Any]:
        turn = self._turns.get(turn_id)
        if turn is None:
            return {}
        execution = self._executions.get(turn.request_id or "")
        workers = [
            self._workers[worker_id]
            for worker_id in self._turn_workers.get(turn_id, [])
            if worker_id in self._workers
        ]
        checkpoints = [
            self._checkpoints[checkpoint_id]
            for checkpoint_id in self._turn_checkpoints.get(turn_id, [])
            if checkpoint_id in self._checkpoints
        ]
        recoveries = [
            self._recoveries[recovery_id]
            for recovery_id in self._turn_recoveries.get(turn_id, [])
            if recovery_id in self._recoveries
        ]
        graphs = [
            self._graphs[graph_id]
            for graph_id in self._turn_graphs.get(turn_id, [])
            if graph_id in self._graphs
        ]
        return {
            "turn_id": turn.turn_id,
            "status": turn.status,
            "mode": turn.mode,
            "request_id": turn.request_id,
            "review": turn.review,
            "execution_status": execution.status if execution is not None else None,
            "turn": {
                "turn_id": turn.turn_id,
                "session_key": turn.session_key,
                "status": turn.status,
                "created_at": turn.created_at,
                "updated_at": turn.updated_at,
                "mode": turn.mode,
                "request_id": turn.request_id,
                "review": turn.review,
                "metadata": dict(turn.metadata),
            },
            "execution": (
                {
                    "request_id": execution.request_id,
                    "turn_id": execution.turn_id,
                    "session_key": execution.session_key,
                    "status": execution.status,
                    "created_at": execution.created_at,
                    "updated_at": execution.updated_at,
                    "mode": execution.mode,
                    "metadata": dict(execution.metadata),
                }
                if execution is not None
                else None
            ),
            "workers": [
                {
                    "worker_id": worker.worker_id,
                    "turn_id": worker.turn_id,
                    "session_key": worker.session_key,
                    "label": worker.label,
                    "status": worker.status,
                    "created_at": worker.created_at,
                    "updated_at": worker.updated_at,
                    "task_id": worker.task_id,
                    "error": worker.error,
                    "metadata": dict(worker.metadata),
                }
                for worker in workers
            ],
            "worker_count": len(workers),
            "checkpoints": [
                {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "turn_id": checkpoint.turn_id,
                    "session_key": checkpoint.session_key,
                    "kind": checkpoint.kind,
                    "status": checkpoint.status,
                    "created_at": checkpoint.created_at,
                    "updated_at": checkpoint.updated_at,
                    "request_id": checkpoint.request_id,
                    "worker_id": checkpoint.worker_id,
                    "summary": checkpoint.summary,
                    "metadata": dict(checkpoint.metadata),
                }
                for checkpoint in checkpoints
            ],
            "checkpoint_count": len(checkpoints),
            "recoveries": [
                {
                    "recovery_id": recovery.recovery_id,
                    "turn_id": recovery.turn_id,
                    "session_key": recovery.session_key,
                    "reason": recovery.reason,
                    "status": recovery.status,
                    "created_at": recovery.created_at,
                    "updated_at": recovery.updated_at,
                    "source_checkpoint_id": recovery.source_checkpoint_id,
                    "target_request_id": recovery.target_request_id,
                    "summary": recovery.summary,
                    "metadata": dict(recovery.metadata),
                }
                for recovery in recoveries
            ],
            "recovery_count": len(recoveries),
            "task_graphs": [task_graph_snapshot(graph) for graph in graphs],
            "task_graph_count": len(graphs),
        }

    def _persist_turn(self, turn_id: str) -> None:
        if self._storage_dir is None:
            return
        target = self._storage_dir / f"{turn_id}.json"
        target.write_text(
            json.dumps(self.snapshot(turn_id), ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
