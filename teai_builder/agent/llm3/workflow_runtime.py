"""Workflow-specific llm3 graph/state runtime helpers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from teai_builder.agent.llm3.state_store import InMemoryOrchestrationStateStore
from teai_builder.agent.llm3.task_graph import (
    apply_checkpoint_event,
    apply_merge_event,
    apply_recovery_event,
    apply_retry_event,
    apply_validation_event,
    apply_workflow_run_payload,
    build_workflow_task_graph,
)


@dataclass(frozen=True)
class WorkflowRuntimeContext:
    turn_id: str
    session_key: str
    channel: str | None
    chat_id: str | None
    metadata: dict[str, Any]
    event_payload: dict[str, Any]


class WorkflowGraphRuntime:
    """Own llm3 workflow graph mutation and recovery state."""

    def __init__(
        self,
        *,
        state_store: InMemoryOrchestrationStateStore,
        run_payload_builder: Callable[[Any], dict[str, Any]],
    ) -> None:
        self._state_store = state_store
        self._run_payload_builder = run_payload_builder

    @staticmethod
    def _goal_meta(run: Any) -> dict[str, Any]:
        metadata = dict(getattr(run, "metadata", {}) or {})
        goal_meta = metadata.get("goal", {})
        return goal_meta if isinstance(goal_meta, dict) else {}

    @staticmethod
    def _workflow_metadata(run: Any) -> dict[str, Any]:
        return dict(getattr(run, "metadata", {}) or {})

    def _workflow_turn_context(self, run: Any) -> WorkflowRuntimeContext:
        metadata = self._workflow_metadata(run)
        goal_meta = self._goal_meta(run)
        session_key = str(
            metadata.get("session_key")
            or goal_meta.get("session_key")
            or f"workflow:{run.run_id}"
        )
        turn_id = str(goal_meta.get("goal_id") or getattr(run, "goal_id", run.run_id))
        channel = metadata.get("channel") or goal_meta.get("channel")
        chat_id = metadata.get("chat_id") or goal_meta.get("chat_id")
        return WorkflowRuntimeContext(
            turn_id=turn_id,
            session_key=session_key,
            channel=str(channel) if channel is not None else None,
            chat_id=str(chat_id) if chat_id is not None else None,
            metadata=metadata or goal_meta,
            event_payload={},
        )

    def sync_graph(self, *, workflow: Any, run: Any, goal: Any) -> WorkflowRuntimeContext:
        session_key = str(goal.metadata.get("session_key") or f"workflow:{run.run_id}")
        turn_id = str(goal.metadata.get("turn_id") or goal.goal_id)
        created_at = int(float(getattr(run, "started_at", time.time())) * 1000)
        updated_at = int(
            float(getattr(run, "updated_at", getattr(run, "started_at", time.time()))) * 1000
        )
        graph = build_workflow_task_graph(
            run_id=run.run_id,
            turn_id=turn_id,
            session_key=session_key,
            workflow_id=workflow.workflow_id,
            root_objective=goal.description,
            created_at=created_at,
            updated_at=updated_at,
            steps=list(getattr(workflow, "steps", [])),
            metadata={"goal_id": goal.goal_id},
        )
        graph = apply_workflow_run_payload(graph, self._run_payload_builder(run))
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=graph,
        )
        return WorkflowRuntimeContext(
            turn_id=turn_id,
            session_key=session_key,
            channel=str(goal.metadata.get("channel")) if goal.metadata.get("channel") is not None else None,
            chat_id=str(goal.metadata.get("chat_id")) if goal.metadata.get("chat_id") is not None else None,
            metadata=dict(goal.metadata or {}),
            event_payload={
                "graph_id": graph.graph_id,
                "run_id": run.run_id,
                "workflow_id": workflow.workflow_id,
                "goal_id": goal.goal_id,
                "node_count": len(graph.nodes),
            },
        )

    def apply_run_payload(self, payload: dict[str, Any]) -> WorkflowRuntimeContext | None:
        session_key = payload.get("session_key")
        turn_id = payload.get("goal_id")
        run_id = payload.get("run_id")
        if not isinstance(session_key, str) or not isinstance(turn_id, str) or not isinstance(run_id, str):
            return None
        graph = self._state_store.get_task_graph(f"graph:{run_id}")
        if graph is None:
            return None
        updated = apply_workflow_run_payload(graph, payload)
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated,
        )
        return WorkflowRuntimeContext(
            turn_id=turn_id,
            session_key=session_key,
            channel=None,
            chat_id=None,
            metadata={},
            event_payload={
                "graph_id": updated.graph_id,
                "run_id": run_id,
                "workflow_id": payload.get("workflow_id"),
                "status": updated.status,
                "current_step": payload.get("current_step"),
            },
        )

    def record_step_event(
        self,
        run: Any,
        step: Any,
        event_type: str,
        payload: dict[str, Any],
    ) -> WorkflowRuntimeContext:
        ctx = self._workflow_turn_context(run)
        self._state_store.ensure_turn_context(
            ctx.turn_id,
            ctx.session_key,
            status="workers_running",
            metadata={
                "workflow_id": getattr(run, "workflow_id", None),
                "run_id": getattr(run, "run_id", None),
                "source": "workflow_engine",
            },
        )
        if event_type == "workflow_checkpoint_created":
            self._state_store.record_checkpoint(
                turn_id=ctx.turn_id,
                session_key=ctx.session_key,
                checkpoint_id=str(payload.get("checkpoint_id")),
                kind="workflow",
                summary=f"Workflow checkpoint for step {payload.get('step_id')}",
                metadata={
                    "workflow_id": getattr(run, "workflow_id", None),
                    "run_id": getattr(run, "run_id", None),
                    "step_id": payload.get("step_id"),
                    "result_keys": payload.get("result_keys"),
                    "context_budget_pct": payload.get("context_budget_pct"),
                },
            )
        graph = self._state_store.get_task_graph(f"graph:{getattr(run, 'run_id', '')}")
        if graph is not None:
            updated_graph = graph
            if event_type == "workflow_step_retry_started":
                step_id = str(payload.get("step_id") or getattr(step, "step_id", ""))
                if step_id:
                    updated_graph = apply_retry_event(
                        updated_graph,
                        step_id=step_id,
                        attempt=int(payload.get("attempt", 1)),
                        total_attempts=(
                            int(payload["total_attempts"])
                            if payload.get("total_attempts") is not None
                            else None
                        ),
                        retry_of_worker_id=(
                            str(payload["retry_of_worker_id"])
                            if payload.get("retry_of_worker_id") is not None
                            else None
                        ),
                        prior_error=(
                            str(payload["prior_error"])
                            if payload.get("prior_error") is not None
                            else None
                        ),
                    )
            if event_type == "workflow_checkpoint_created" and payload.get("checkpoint_id") is not None:
                step_id = str(payload.get("step_id") or getattr(step, "step_id", ""))
                updated_graph = apply_checkpoint_event(
                    updated_graph,
                    step_id=step_id,
                    checkpoint_id=str(payload["checkpoint_id"]),
                    result_keys=[
                        str(item)
                        for item in payload.get("result_keys", [])
                        if item is not None
                    ],
                    context_budget_pct=(
                        float(payload["context_budget_pct"])
                        if payload.get("context_budget_pct") is not None
                        else None
                    ),
                )
            if event_type == "workflow_goal_validated" and payload.get("validation_id") is not None:
                result_keys = [
                    str(item)
                    for item in payload.get("result_keys", [])
                    if item is not None
                ]
                validation_dependencies: list[str] = []
                if result_keys:
                    merge_id = str(payload.get("merge_id") or "workflow-results")
                    updated_graph = apply_merge_event(
                        updated_graph,
                        merge_id=merge_id,
                        label="Workflow result merge",
                        result_keys=result_keys,
                        summary=(
                            str(payload.get("merge_summary"))
                            if payload.get("merge_summary") is not None
                            else f"Merged {len(result_keys)} workflow result(s)"
                        ),
                    )
                    validation_dependencies = [f"{updated_graph.graph_id}:merge:{merge_id}"]
                updated_graph = apply_validation_event(
                    updated_graph,
                    validation_id=str(payload["validation_id"]),
                    is_complete=bool(payload.get("is_complete")),
                    confidence=float(payload.get("confidence", 0.0)),
                    reasoning=str(payload.get("reasoning") or ""),
                    failed_criteria=[
                        str(item)
                        for item in payload.get("failed_criteria", [])
                        if item is not None
                    ],
                    suggestions=[
                        str(item)
                        for item in payload.get("suggestions", [])
                        if item is not None
                    ],
                    depends_on=validation_dependencies,
                )
            if updated_graph is not graph:
                self._state_store.record_task_graph(
                    turn_id=ctx.turn_id,
                    session_key=ctx.session_key,
                    graph=updated_graph,
                )
        return WorkflowRuntimeContext(
            turn_id=ctx.turn_id,
            session_key=ctx.session_key,
            channel=ctx.channel,
            chat_id=ctx.chat_id,
            metadata=ctx.metadata,
            event_payload={
                "run_id": getattr(run, "run_id", None),
                "workflow_id": getattr(run, "workflow_id", None),
                "step_id": getattr(step, "step_id", None) if step is not None else None,
                **dict(payload),
            },
        )

    def start_recovery(
        self,
        *,
        run: Any,
        goal: Any,
        reason: str,
        source_checkpoint_id: str | None = None,
    ) -> WorkflowRuntimeContext:
        session_key = str(goal.metadata.get("session_key") or f"workflow:{run.run_id}")
        turn_id = str(goal.metadata.get("turn_id") or goal.goal_id)
        recovery_id = f"rec-{uuid.uuid4().hex[:10]}"
        self._state_store.start_recovery(
            recovery_id=recovery_id,
            turn_id=turn_id,
            session_key=session_key,
            reason=reason,
            source_checkpoint_id=source_checkpoint_id,
            summary=f"Recovery started for workflow run {run.run_id}",
            metadata={
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "goal_id": goal.goal_id,
            },
        )
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is not None:
            updated_graph = apply_recovery_event(
                graph,
                recovery_id=recovery_id,
                reason=reason,
                event_type="workflow_recovery_started",
                status="running",
                source_checkpoint_id=source_checkpoint_id,
            )
            self._state_store.record_task_graph(
                turn_id=turn_id,
                session_key=session_key,
                graph=updated_graph,
            )
        return WorkflowRuntimeContext(
            turn_id=turn_id,
            session_key=session_key,
            channel=str(goal.metadata.get("channel")) if goal.metadata.get("channel") is not None else None,
            chat_id=str(goal.metadata.get("chat_id")) if goal.metadata.get("chat_id") is not None else None,
            metadata=dict(goal.metadata or {}),
            event_payload={
                "recovery_id": recovery_id,
                "reason": reason,
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "goal_id": goal.goal_id,
            },
        )

    def complete_recovery(
        self,
        recovery_id: str,
        *,
        goal: Any,
        run: Any,
        status: str,
        summary: str | None = None,
    ) -> WorkflowRuntimeContext:
        turn_id = str(goal.metadata.get("turn_id") or goal.goal_id)
        session_key = str(goal.metadata.get("session_key") or f"workflow:{run.run_id}")
        self._state_store.complete_recovery(
            recovery_id,
            status=status,
            summary=summary,
            metadata={"workflow_id": run.workflow_id, "run_id": run.run_id},
        )
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is not None:
            updated_graph = apply_recovery_event(
                graph,
                recovery_id=recovery_id,
                reason="recovery",
                event_type="workflow_recovery_completed",
                status=status,
                summary=summary,
            )
            self._state_store.record_task_graph(
                turn_id=turn_id,
                session_key=session_key,
                graph=updated_graph,
            )
        return WorkflowRuntimeContext(
            turn_id=turn_id,
            session_key=session_key,
            channel=str(goal.metadata.get("channel")) if goal.metadata.get("channel") is not None else None,
            chat_id=str(goal.metadata.get("chat_id")) if goal.metadata.get("chat_id") is not None else None,
            metadata=dict(goal.metadata or {}),
            event_payload={
                "recovery_id": recovery_id,
                "status": status,
                "summary": summary,
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "goal_id": goal.goal_id,
            },
        )
