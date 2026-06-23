"""Minimal llm3 task-graph objects and workflow graph helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any

from .types import ExecutionBrief, UnifiedTurn


@dataclass(frozen=True)
class TaskGraphNodeRecord:
    node_id: str
    graph_id: str
    type: str
    label: str
    status: str
    depends_on: list[str] = field(default_factory=list)
    retry_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskGraphEdgeRecord:
    edge_id: str
    from_node_id: str
    to_node_id: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskGraphRecord:
    graph_id: str
    request_id: str
    turn_id: str
    session_key: str
    mode: str
    created_at: int
    updated_at: int
    status: str
    root_objective: str
    nodes: list[TaskGraphNodeRecord] = field(default_factory=list)
    edges: list[TaskGraphEdgeRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def build_workflow_task_graph(
    *,
    run_id: str,
    turn_id: str,
    session_key: str,
    workflow_id: str,
    root_objective: str,
    created_at: int,
    updated_at: int,
    steps: list[Any],
    metadata: dict[str, Any] | None = None,
) -> TaskGraphRecord:
    graph_id = f"graph:{run_id}"
    nodes: list[TaskGraphNodeRecord] = []
    for step in steps:
        node_id = f"{graph_id}:{step.step_id}"
        nodes.append(
            TaskGraphNodeRecord(
                node_id=node_id,
                graph_id=graph_id,
                type="workflow_step",
                label=step.name,
                status="pending",
                depends_on=list(getattr(step, "depends_on", [])),
                payload={"step_id": step.step_id},
                metadata={
                    "prompt_template": getattr(step, "prompt_template", ""),
                    "continue_on_error": bool(getattr(step, "continue_on_error", False)),
                    "checkpoint_after": bool(getattr(step, "checkpoint_after", False)),
                },
            )
        )
    nodes = _mark_ready_workflow_nodes(nodes)
    return TaskGraphRecord(
        graph_id=graph_id,
        request_id=run_id,
        turn_id=turn_id,
        session_key=session_key,
        mode="workflow",
        created_at=created_at,
        updated_at=updated_at,
        status="planned",
        root_objective=root_objective,
        nodes=nodes,
        edges=_build_graph_edges(graph_id, nodes),
        metadata={"workflow_id": workflow_id, **dict(metadata or {})},
    )


def build_turn_task_graph(
    *,
    turn: UnifiedTurn,
    brief: ExecutionBrief,
) -> TaskGraphRecord:
    graph_id = f"graph:{brief.request_id}"
    execution_node = TaskGraphNodeRecord(
        node_id=f"{graph_id}:execution:{brief.request_id}",
        graph_id=graph_id,
        type="execution",
        label="Turn execution",
        status="pending",
        payload={
            "turn_id": turn.turn_id,
            "request_id": brief.request_id,
            "mode": brief.mode,
        },
        metadata={
            "channel": turn.channel,
            "message_kind": turn.message_kind,
            "objective": brief.objective,
        },
    )
    return TaskGraphRecord(
        graph_id=graph_id,
        request_id=brief.request_id,
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        mode=brief.mode,
        created_at=brief.created_at,
        updated_at=brief.created_at,
        status="planned",
        root_objective=brief.objective,
        nodes=[execution_node],
        edges=[],
        metadata={
            "channel": turn.channel,
            "message_kind": turn.message_kind,
            "mode": brief.mode,
        },
    )


def apply_workflow_run_payload(
    graph: TaskGraphRecord,
    payload: dict[str, Any],
) -> TaskGraphRecord:
    node_statuses: dict[str, dict[str, Any]] = {}
    for step in payload.get("step_states", []):
        if isinstance(step, dict) and isinstance(step.get("step_id"), str):
            node_statuses[step["step_id"]] = step

    timed_out_steps: list[str] = []
    nodes: list[TaskGraphNodeRecord] = []
    for node in graph.nodes:
        step_id = str(node.payload.get("step_id", ""))
        step_state = node_statuses.get(step_id)
        if step_state is None:
            nodes.append(node)
            continue
        timeout_seconds = _timeout_seconds_from_error(step_state.get("error"))
        if timeout_seconds is not None:
            timed_out_steps.append(step_id)
        step_name = step_state.get("name")
        nodes.append(
            replace(
                node,
                label=str(step_name) if isinstance(step_name, str) and step_name else node.label,
                status=_map_workflow_step_status(
                    step_state.get("state"),
                    skipped_reason=step_state.get("skipped_reason"),
                ),
                retry_count=max(int(step_state.get("attempts", 0)) - 1, 0),
                metadata={
                    **node.metadata,
                    "error": step_state.get("error"),
                    "skipped_reason": step_state.get("skipped_reason"),
                    "started_at": step_state.get("started_at"),
                    "finished_at": step_state.get("finished_at"),
                    "output": step_state.get("output"),
                    "timeout_detected": timeout_seconds is not None,
                    "timeout_seconds": timeout_seconds,
                },
            )
        )

    if payload.get("cancel_requested"):
        nodes = _append_workflow_cancellation_reason_node(
            graph.graph_id,
            nodes,
            current_step=str(payload.get("current_step") or ""),
        )
    nodes = _mark_ready_workflow_nodes(nodes)
    deadlock_detected = _is_deadlock_error(payload.get("error"))
    if deadlock_detected:
        nodes = _mark_deadlocked_workflow_nodes(nodes, error=str(payload.get("error") or ""))
    if timed_out_steps:
        nodes = _append_workflow_timeout_reason_nodes(
            graph.graph_id,
            nodes,
            timed_out_steps=timed_out_steps,
            node_statuses=node_statuses,
        )

    partial_step_count = _partial_workflow_step_count(payload.get("step_states", []))
    status_history = _normalize_status_history(payload.get("status_history"))
    last_status = status_history[-1] if status_history else None
    checkpoints = _normalize_workflow_checkpoints(payload.get("checkpoints"))
    last_checkpoint = checkpoints[-1] if checkpoints else None
    session_key = payload.get("session_key")
    return replace(
        graph,
        session_key=str(session_key) if isinstance(session_key, str) and session_key else graph.session_key,
        updated_at=int(payload.get("updated_at", graph.updated_at)),
        status=_map_workflow_run_status(
            payload.get("state"),
            step_states=payload.get("step_states", []),
        ),
        nodes=nodes,
        edges=_build_graph_edges(graph.graph_id, nodes),
        metadata={
            **graph.metadata,
            "version": payload.get("version"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "current_step": payload.get("current_step"),
            "goal_id": payload.get("goal_id"),
            "completed_steps": payload.get("completed_steps"),
            "step_count": payload.get("step_count"),
            "error": payload.get("error"),
            "cancel_requested": bool(payload.get("cancel_requested", False)),
            "deadlock_detected": deadlock_detected,
            "timeout_detected": bool(timed_out_steps),
            "timed_out_steps": sorted(timed_out_steps),
            "partial_step_count": partial_step_count,
            "status_history": status_history,
            "last_status_detail": (last_status.get("detail") if last_status is not None else None),
            "last_status_at": (last_status.get("at") if last_status is not None else None),
            "checkpoints": checkpoints,
            "checkpoint_count": len(checkpoints),
            "last_checkpoint_id": (
                last_checkpoint.get("checkpoint_id") if last_checkpoint is not None else None
            ),
        },
    )


def apply_execution_event(
    graph: TaskGraphRecord,
    *,
    request_id: str,
    event_type: str,
    status: str | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:execution:{request_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    resolved_status = _execution_status(event_type, status)
    if existing is None:
        return graph
    nodes = [
        replace(
            node,
            status=resolved_status if node.node_id == node_id else node.status,
        )
        for node in graph.nodes
    ]
    graph_status = graph.status
    if event_type == "execution_started":
        graph_status = "running"
    elif event_type == "execution_completed":
        graph_status = _graph_status_from_execution(status)
    return _replace_graph(graph, nodes=nodes, status=graph_status)


def apply_tool_event(
    graph: TaskGraphRecord,
    *,
    request_id: str,
    sequence: int,
    tool_name: str,
    status: str,
    detail: str,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:tool:{sequence}:{tool_name}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="tool",
            label=f"Tool {tool_name}",
            status="completed" if status == "ok" else "failed",
            depends_on=[f"{graph.graph_id}:execution:{request_id}"],
            payload={
                "request_id": request_id,
                "tool_name": tool_name,
                "sequence": sequence,
                "status": status,
            },
            metadata={
                "detail": detail,
            },
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_tool_progress_event(
    graph: TaskGraphRecord,
    *,
    request_id: str,
    tool_name: str,
    phase: str,
    call_id: str | None = None,
    sequence: int | None = None,
    detail: str | None = None,
    arguments: dict[str, Any] | None = None,
    result: Any | None = None,
    error: str | None = None,
) -> TaskGraphRecord:
    node_key = call_id or f"{sequence or 0}:{tool_name}"
    node_id = f"{graph.graph_id}:tool:{node_key}"
    status = _tool_progress_status(phase)
    depends_on = [f"{graph.graph_id}:execution:{request_id}"]
    payload = {
        "request_id": request_id,
        "tool_name": tool_name,
        "call_id": call_id,
        "sequence": sequence,
        "phase": phase,
    }
    metadata: dict[str, Any] = {}
    if detail is not None:
        metadata["detail"] = detail
    if arguments is not None:
        metadata["arguments"] = dict(arguments)
    if result is not None:
        metadata["result"] = result
    if error is not None:
        metadata["error"] = error
    nodes = list(graph.nodes)
    for index, node in enumerate(nodes):
        if node.node_id != node_id:
            continue
        nodes[index] = replace(
            node,
            label=f"Tool {tool_name}",
            status=status,
            depends_on=depends_on,
            payload={**node.payload, **payload},
            metadata={**node.metadata, **metadata},
        )
        return _replace_graph(graph, nodes=nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="tool",
            label=f"Tool {tool_name}",
            status=status,
            depends_on=depends_on,
            payload=payload,
            metadata=metadata,
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_reasoning_event(
    graph: TaskGraphRecord,
    *,
    request_id: str,
    content: str,
    status: str,
) -> TaskGraphRecord:
    existing_running = next(
        (
            node
            for node in reversed(graph.nodes)
            if node.type == "reason"
            and node.payload.get("request_id") == request_id
            and node.payload.get("reason_kind") == "stream"
            and node.status == "running"
        ),
        None,
    )
    if existing_running is None:
        if status != "running":
            return graph
        sequence = (
            max(
                (
                    int(node.payload.get("sequence", 0))
                    for node in graph.nodes
                    if node.type == "reason"
                    and node.payload.get("request_id") == request_id
                    and node.payload.get("reason_kind") == "stream"
                ),
                default=0,
            )
            + 1
        )
        node_id = f"{graph.graph_id}:reason:{request_id}:segment:{sequence}"
        nodes = list(graph.nodes)
        nodes.append(
            TaskGraphNodeRecord(
                node_id=node_id,
                graph_id=graph.graph_id,
                type="reason",
                label=f"Reasoning segment {sequence}",
                status="running",
                depends_on=[f"{graph.graph_id}:execution:{request_id}"],
                payload={
                    "request_id": request_id,
                    "sequence": sequence,
                    "reason_kind": "stream",
                },
                metadata={"content": content} if content else {},
            )
        )
        return _replace_graph(graph, nodes=nodes)

    appended_content = f"{existing_running.metadata.get('content', '')}{content}"
    nodes = list(graph.nodes)
    for index, node in enumerate(nodes):
        if node.node_id != existing_running.node_id:
            continue
        nodes[index] = replace(
            node,
            status=status,
            metadata={
                **node.metadata,
                "content": appended_content,
            },
        )
        return _replace_graph(graph, nodes=nodes)
    return graph


def task_graph_snapshot(graph: TaskGraphRecord) -> dict[str, Any]:
    return {
        "graph_id": graph.graph_id,
        "request_id": graph.request_id,
        "turn_id": graph.turn_id,
        "session_key": graph.session_key,
        "mode": graph.mode,
        "created_at": graph.created_at,
        "updated_at": graph.updated_at,
        "status": graph.status,
        "root_objective": graph.root_objective,
        "metadata": dict(graph.metadata),
        "edges": [
            {
                "edge_id": edge.edge_id,
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "kind": edge.kind,
                "metadata": dict(edge.metadata),
            }
            for edge in graph.edges
        ],
        "nodes": [
            {
                "node_id": node.node_id,
                "graph_id": node.graph_id,
                "type": node.type,
                "label": node.label,
                "status": node.status,
                "depends_on": list(node.depends_on),
                "retry_count": node.retry_count,
                "payload": dict(node.payload),
                "metadata": dict(node.metadata),
            }
            for node in graph.nodes
        ],
    }


def apply_worker_event(
    graph: TaskGraphRecord,
    *,
    task_id: str,
    label: str,
    event_type: str,
    worker_id: str | None = None,
    status: str | None = None,
    error: str | None = None,
    attempt: int | None = None,
    total_attempts: int | None = None,
    retry_of_worker_id: str | None = None,
    depends_on: list[str] | None = None,
    stop_reason: str | None = None,
) -> TaskGraphRecord:
    node_id = _worker_node_id(graph.graph_id, task_id, attempt)
    dependencies = _normalize_depends_on(graph.graph_id, depends_on or [])
    nodes = list(graph.nodes)
    existing = next((node for node in nodes if node.node_id == node_id), None)
    resolved_status = _worker_event_status(event_type, status)
    if existing is None:
        nodes.append(
            TaskGraphNodeRecord(
                node_id=node_id,
                graph_id=graph.graph_id,
                type="worker",
                label=label,
                status=resolved_status,
                depends_on=dependencies,
                retry_count=max((attempt or 1) - 1, 0),
                payload={
                    "task_id": task_id,
                    "worker_id": worker_id,
                    "attempt": attempt,
                    "total_attempts": total_attempts,
                },
                metadata={
                    "error": error,
                    "retry_of_worker_id": retry_of_worker_id,
                    "stop_reason": stop_reason,
                },
            )
        )
    else:
        nodes = [
            replace(
                node,
                status=resolved_status if node.node_id == node_id else node.status,
                depends_on=dependencies if node.node_id == node_id else node.depends_on,
                retry_count=max((attempt or 1) - 1, 0) if node.node_id == node_id else node.retry_count,
                payload={
                    **node.payload,
                    "task_id": task_id,
                    "worker_id": worker_id,
                    "attempt": attempt,
                    "total_attempts": total_attempts,
                }
                if node.node_id == node_id
                else node.payload,
                metadata={
                    **node.metadata,
                    "error": error,
                    "retry_of_worker_id": retry_of_worker_id,
                    "stop_reason": stop_reason,
                }
                if node.node_id == node_id
                else node.metadata,
            )
            for node in nodes
        ]
    return _replace_graph(graph, nodes=nodes)


def apply_retry_event(
    graph: TaskGraphRecord,
    *,
    step_id: str,
    attempt: int,
    total_attempts: int | None,
    retry_of_worker_id: str | None,
    prior_error: str | None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:retry:{step_id}:attempt:{attempt}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="reason",
            label=f"Retry {step_id} attempt {attempt}",
            status="completed",
            depends_on=_step_dependency_nodes(graph.graph_id, step_id),
            retry_count=max(attempt - 1, 0),
            payload={
                "step_id": step_id,
                "attempt": attempt,
                "total_attempts": total_attempts,
            },
            metadata={
                "retry_of_worker_id": retry_of_worker_id,
                "prior_error": prior_error,
            },
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_checkpoint_event(
    graph: TaskGraphRecord,
    *,
    step_id: str,
    checkpoint_id: str,
    result_keys: list[str] | None = None,
    context_budget_pct: float | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:checkpoint:{checkpoint_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="checkpoint",
            label=f"Checkpoint {step_id}",
            status="completed",
            depends_on=_step_dependency_nodes(graph.graph_id, step_id),
            payload={
                "step_id": step_id,
                "checkpoint_id": checkpoint_id,
            },
            metadata={
                "result_keys": list(result_keys or []),
                "context_budget_pct": context_budget_pct,
            },
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_merge_event(
    graph: TaskGraphRecord,
    *,
    merge_id: str,
    label: str,
    result_keys: list[str] | None = None,
    summary: str | None = None,
    status: str = "completed",
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:merge:{merge_id}"
    dependencies = _step_dependency_nodes_for_keys(graph.graph_id, result_keys or [])
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    payload = {
        "merge_id": merge_id,
        "result_keys": list(result_keys or []),
    }
    metadata = {"summary": summary} if summary is not None else {}
    if existing is not None:
        return replace(
            graph,
            nodes=[
                replace(
                    node,
                    label=label if node.node_id == node_id else node.label,
                    status=status if node.node_id == node_id else node.status,
                    depends_on=dependencies if node.node_id == node_id else node.depends_on,
                    payload={**node.payload, **payload} if node.node_id == node_id else node.payload,
                    metadata={**node.metadata, **metadata} if node.node_id == node_id else node.metadata,
                )
                for node in graph.nodes
            ],
        )
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="merge",
            label=label,
            status=status,
            depends_on=dependencies,
            payload=payload,
            metadata=metadata,
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_response_candidate_event(
    graph: TaskGraphRecord,
    *,
    request_id: str,
    status: str,
    summary: str,
    final_content: str | None,
    depends_on: list[str] | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:respond_candidate:{request_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    preview = (final_content or "")[:200]
    dependencies = _normalize_depends_on(
        graph.graph_id,
        depends_on or [f"{graph.graph_id}:execution:{request_id}"],
    )
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="respond_candidate",
            label="Response candidate",
            status="completed" if status == "completed" else status,
            depends_on=dependencies,
            payload={
                "request_id": request_id,
                "status": status,
                "final_content_present": bool(final_content),
            },
            metadata={
                "summary": summary,
                "content_preview": preview,
            },
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_review_event(
    graph: TaskGraphRecord,
    *,
    review_id: str,
    request_id: str,
    decision: str,
    rationale: str,
    unmet_criteria: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:review:{review_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    dependencies = _normalize_depends_on(graph.graph_id, depends_on or [])
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="review",
            label=f"Review {decision}",
            status=_decision_status(decision),
            depends_on=dependencies,
            payload={
                "review_id": review_id,
                "request_id": request_id,
                "decision": decision,
            },
            metadata={
                "rationale": rationale,
                "unmet_criteria": list(unmet_criteria or []),
            },
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_validation_event(
    graph: TaskGraphRecord,
    *,
    validation_id: str,
    is_complete: bool,
    confidence: float,
    reasoning: str,
    failed_criteria: list[str] | None = None,
    suggestions: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:validation:{validation_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    dependencies = _normalize_depends_on(graph.graph_id, depends_on or [])
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="validation",
            label="Goal validation",
            status="completed" if is_complete else "failed",
            depends_on=dependencies,
            payload={
                "validation_id": validation_id,
                "is_complete": is_complete,
                "confidence": confidence,
            },
            metadata={
                "reasoning": reasoning,
                "failed_criteria": list(failed_criteria or []),
                "suggestions": list(suggestions or []),
            },
        )
    )
    validation_count = sum(1 for node in nodes if node.type == "validation")
    return replace(
        _replace_graph(graph, nodes=nodes),
        metadata={
            **graph.metadata,
            "last_validation_id": validation_id,
            "last_validation_complete": is_complete,
            "last_validation_confidence": confidence,
            "last_validation_failed_criteria": list(failed_criteria or []),
            "last_validation_suggestions": list(suggestions or []),
            "validation_count": validation_count,
        },
    )


def apply_recovery_event(
    graph: TaskGraphRecord,
    *,
    recovery_id: str,
    reason: str,
    event_type: str,
    status: str | None = None,
    summary: str | None = None,
    source_checkpoint_id: str | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:recovery:{recovery_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    resolved_status = _recovery_status(event_type, status)
    if existing is None:
        nodes = list(graph.nodes)
        nodes.append(
            TaskGraphNodeRecord(
                node_id=node_id,
                graph_id=graph.graph_id,
                type="recovery",
                label=f"Recovery {reason}",
                status=resolved_status,
                depends_on=[],
                payload={
                    "recovery_id": recovery_id,
                    "reason": reason,
                    "status": status,
                },
                metadata={
                    "summary": summary,
                    "source_checkpoint_id": source_checkpoint_id,
                },
            )
        )
        return _replace_graph(graph, nodes=nodes)
    return _replace_graph(
        graph,
        nodes=[
            replace(
                node,
                status=resolved_status if node.node_id == node_id else node.status,
                payload={
                    **node.payload,
                    "status": status,
                }
                if node.node_id == node_id
                else node.payload,
                metadata={
                    **node.metadata,
                    "summary": summary,
                    "source_checkpoint_id": source_checkpoint_id,
                }
                if node.node_id == node_id
                else node.metadata,
            )
            for node in graph.nodes
        ],
    )


def apply_terminal_response_event(
    graph: TaskGraphRecord,
    *,
    response_id: str,
    stop_reason: str,
    final_content_present: bool,
    depends_on: list[str] | None = None,
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:response:{response_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    dependencies = _normalize_depends_on(graph.graph_id, depends_on or [])
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="response",
            label="Terminal response",
            status="completed",
            depends_on=dependencies,
            payload={
                "response_id": response_id,
                "stop_reason": stop_reason,
                "final_content_present": final_content_present,
            },
            metadata={},
        )
    )
    return _replace_graph(graph, nodes=nodes)


def apply_continuation_event(
    graph: TaskGraphRecord,
    *,
    continuation_id: str,
    worker_id: str | None,
    request_id: str | None,
    content_preview: str,
    continuation_kind: str = "subagent_result",
) -> TaskGraphRecord:
    node_id = f"{graph.graph_id}:continuation:{continuation_id}"
    existing = next((node for node in graph.nodes if node.node_id == node_id), None)
    if existing is not None:
        return graph
    depends_on: list[str] = []
    if worker_id:
        depends_on.append(_worker_node_id(graph.graph_id, worker_id, None))
    if request_id:
        depends_on.append(f"{graph.graph_id}:execution:{request_id}")
    nodes = list(graph.nodes)
    nodes.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph.graph_id,
            type="continuation",
            label="Parent turn continuation",
            status="completed",
            depends_on=depends_on,
            payload={
                "continuation_id": continuation_id,
                "worker_id": worker_id,
                "request_id": request_id,
                "continuation_kind": continuation_kind,
            },
            metadata={
                "content_preview": content_preview,
            },
        )
    )
    return _replace_graph(graph, nodes=nodes)


def _map_workflow_run_status(
    state: Any,
    *,
    step_states: list[dict[str, Any]] | None = None,
) -> str:
    if str(state) == "completed" and _partial_workflow_step_count(step_states or []) > 0:
        return "partial"
    mapping = {
        "pending": "planned",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "skipped": "paused",
    }
    return mapping.get(str(state), "planned")


def _map_workflow_step_status(
    state: Any,
    *,
    skipped_reason: Any = None,
) -> str:
    mapping = {
        "pending": "pending",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "skipped": "blocked" if _is_blocked_skip_reason(skipped_reason) else "skipped",
    }
    return mapping.get(str(state), "pending")


def _is_blocked_skip_reason(skipped_reason: Any) -> bool:
    reason = str(skipped_reason or "").strip().lower()
    return reason.startswith("missing step result ")


def _partial_workflow_step_count(step_states: list[dict[str, Any]]) -> int:
    partial_count = 0
    for step_state in step_states:
        if not isinstance(step_state, dict):
            continue
        status = _map_workflow_step_status(
            step_state.get("state"),
            skipped_reason=step_state.get("skipped_reason"),
        )
        if status in {"failed", "blocked", "cancelled"}:
            partial_count += 1
    return partial_count


def _worker_node_id(graph_id: str, task_id: str, attempt: int | None) -> str:
    attempt_value = attempt or 1
    return f"{graph_id}:worker:{task_id}:attempt:{attempt_value}"


def _normalize_depends_on(graph_id: str, depends_on: list[str]) -> list[str]:
    normalized: list[str] = []
    for dep in depends_on:
        normalized.append(f"{graph_id}:{dep}" if not dep.startswith(f"{graph_id}:") else dep)
    return normalized


def _step_dependency_nodes(graph_id: str, step_id: str) -> list[str]:
    return [f"{graph_id}:{step_id}"]


def _step_dependency_nodes_for_keys(graph_id: str, step_ids: list[str]) -> list[str]:
    return [f"{graph_id}:{step_id}" for step_id in step_ids]


def _append_workflow_cancellation_reason_node(
    graph_id: str,
    nodes: list[TaskGraphNodeRecord],
    *,
    current_step: str,
) -> list[TaskGraphNodeRecord]:
    node_id = f"{graph_id}:reason:cancellation-requested"
    existing = next((node for node in nodes if node.node_id == node_id), None)
    depends_on = _step_dependency_nodes(graph_id, current_step) if current_step else []
    if existing is not None:
        return [
            replace(
                node,
                depends_on=depends_on if node.node_id == node_id else node.depends_on,
                payload={
                    **node.payload,
                    "current_step": current_step or node.payload.get("current_step"),
                }
                if node.node_id == node_id
                else node.payload,
            )
            for node in nodes
        ]
    updated = list(nodes)
    updated.append(
        TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph_id,
            type="reason",
            label="Cancellation requested",
            status="completed",
            depends_on=depends_on,
            payload={
                "reason_kind": "cancellation",
                "current_step": current_step or None,
            },
            metadata={},
        )
    )
    return updated


def _append_workflow_timeout_reason_nodes(
    graph_id: str,
    nodes: list[TaskGraphNodeRecord],
    *,
    timed_out_steps: list[str],
    node_statuses: dict[str, dict[str, Any]],
) -> list[TaskGraphNodeRecord]:
    updated = list(nodes)
    for step_id in timed_out_steps:
        node_id = f"{graph_id}:reason:timeout:{step_id}"
        depends_on = _step_dependency_nodes(graph_id, step_id)
        step_state = node_statuses.get(step_id, {})
        timeout_seconds = _timeout_seconds_from_error(step_state.get("error"))
        existing_index = next((i for i, node in enumerate(updated) if node.node_id == node_id), None)
        reason_node = TaskGraphNodeRecord(
            node_id=node_id,
            graph_id=graph_id,
            type="reason",
            label="Step timed out",
            status="completed",
            depends_on=depends_on,
            payload={
                "reason_kind": "timeout",
                "step_id": step_id,
                "timeout_seconds": timeout_seconds,
            },
            metadata={
                "error": step_state.get("error"),
            },
        )
        if existing_index is not None:
            updated[existing_index] = reason_node
        else:
            updated.append(reason_node)
    return updated


def _mark_ready_workflow_nodes(
    nodes: list[TaskGraphNodeRecord],
) -> list[TaskGraphNodeRecord]:
    completed_steps = {
        str(node.payload.get("step_id"))
        for node in nodes
        if node.type == "workflow_step" and node.status == "completed"
    }
    updated: list[TaskGraphNodeRecord] = []
    for node in nodes:
        if node.type != "workflow_step" or node.status != "pending":
            updated.append(node)
            continue
        depends_on = [str(dep) for dep in node.depends_on]
        if all(dep in completed_steps for dep in depends_on):
            updated.append(replace(node, status="ready"))
            continue
        updated.append(node)
    return updated


def _mark_deadlocked_workflow_nodes(
    nodes: list[TaskGraphNodeRecord],
    *,
    error: str,
) -> list[TaskGraphNodeRecord]:
    updated: list[TaskGraphNodeRecord] = []
    for node in nodes:
        if node.type == "workflow_step" and node.status in {"pending", "ready"}:
            updated.append(
                replace(
                    node,
                    status="blocked",
                    metadata={
                        **node.metadata,
                        "blocked_reason": error,
                    },
                )
            )
            continue
        updated.append(node)
    return updated


def _build_graph_edges(
    graph_id: str,
    nodes: list[TaskGraphNodeRecord],
) -> list[TaskGraphEdgeRecord]:
    node_ids = {node.node_id for node in nodes}
    edges: list[TaskGraphEdgeRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for node in nodes:
        for dep in node.depends_on:
            from_node_id = _normalize_edge_node_id(graph_id, dep)
            if from_node_id not in node_ids:
                continue
            _append_edge(
                edges,
                seen,
                from_node_id=from_node_id,
                to_node_id=node.node_id,
                kind="dependency",
            )
            if node.type == "checkpoint":
                _append_edge(
                    edges,
                    seen,
                    from_node_id=from_node_id,
                    to_node_id=node.node_id,
                    kind="checkpoint_after",
                )
            if node.type == "validation":
                _append_edge(
                    edges,
                    seen,
                    from_node_id=from_node_id,
                    to_node_id=node.node_id,
                    kind="validation_of",
                )
            if _should_emit_data_flow_edge(node, from_node_id):
                _append_edge(
                    edges,
                    seen,
                    from_node_id=from_node_id,
                    to_node_id=node.node_id,
                    kind="data_flow",
                )
    return edges


def _normalize_edge_node_id(graph_id: str, node_id: str) -> str:
    return node_id if node_id.startswith(f"{graph_id}:") else f"{graph_id}:{node_id}"


def _append_edge(
    edges: list[TaskGraphEdgeRecord],
    seen: set[tuple[str, str, str]],
    *,
    from_node_id: str,
    to_node_id: str,
    kind: str,
) -> None:
    key = (from_node_id, to_node_id, kind)
    if key in seen:
        return
    seen.add(key)
    edges.append(
        TaskGraphEdgeRecord(
            edge_id=f"{from_node_id}->{kind}->{to_node_id}",
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            kind=kind,
        )
    )


def _should_emit_data_flow_edge(
    node: TaskGraphNodeRecord,
    from_node_id: str,
) -> bool:
    if node.type == "merge":
        result_keys = {
            str(key)
            for key in node.payload.get("result_keys", [])
            if isinstance(key, str)
        }
        return any(from_node_id.endswith(f":{key}") for key in result_keys)
    if node.type == "respond_candidate":
        return bool(node.payload.get("final_content_present")) and from_node_id.endswith(
            f":execution:{node.payload.get('request_id')}"
        )
    if node.type == "continuation":
        worker_id = node.payload.get("worker_id")
        continuation_kind = str(node.payload.get("continuation_kind") or "")
        return (
            continuation_kind == "subagent_result"
            and bool(worker_id)
            and bool(node.metadata.get("content_preview"))
            and from_node_id == _worker_node_id(node.graph_id, str(worker_id), None)
        )
    return False


def _is_deadlock_error(error: Any) -> bool:
    text = str(error or "").strip().lower()
    return text.startswith("deadlocked tasks with unmet dependencies:")


def _timeout_seconds_from_error(error: Any) -> float | None:
    text = str(error or "").strip()
    match = re.match(r"^Timed out after ([0-9]+(?:\.[0-9]+)?) second\(s\)$", text)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _normalize_status_history(history: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(history, list):
        return normalized
    for item in history:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "state": item.get("state"),
                "detail": item.get("detail"),
                "at": item.get("at"),
            }
        )
    return normalized


def _normalize_workflow_checkpoints(checkpoints: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(checkpoints, list):
        return normalized
    for item in checkpoints:
        if not isinstance(item, dict):
            continue
        result_keys = item.get("result_keys")
        normalized.append(
            {
                "step_id": item.get("step_id"),
                "saved_at": item.get("saved_at"),
                "result_keys": list(result_keys) if isinstance(result_keys, list) else [],
                "checkpoint_id": item.get("checkpoint_id"),
                "context_budget_pct": item.get("context_budget_pct"),
            }
        )
    return normalized


def _replace_graph(
    graph: TaskGraphRecord,
    *,
    nodes: list[TaskGraphNodeRecord],
    status: str | None = None,
) -> TaskGraphRecord:
    return replace(
        graph,
        nodes=nodes,
        edges=_build_graph_edges(graph.graph_id, nodes),
        status=graph.status if status is None else status,
        updated_at=graph.updated_at + 1,
    )


def _worker_event_status(event_type: str, status: str | None) -> str:
    if event_type == "worker_task_started":
        return "running"
    if event_type == "worker_task_failed":
        return "failed"
    if status == "completed":
        return "completed"
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "cancelled"
    return "running"


def _decision_status(decision: str) -> str:
    if decision == "accept":
        return "completed"
    if decision in {"retry", "revise", "escalate"}:
        return "failed"
    if decision == "ask_user":
        return "paused"
    return "completed"


def _recovery_status(event_type: str, status: str | None) -> str:
    if event_type == "workflow_recovery_started":
        return "running"
    if status in {"completed", "success"}:
        return "completed"
    if status in {"failed", "cancelled"}:
        return "failed" if status == "failed" else "cancelled"
    return "running"


def _execution_status(event_type: str, status: str | None) -> str:
    if event_type == "execution_started":
        return "running"
    if status == "completed":
        return "completed"
    if status == "partial":
        return "failed"
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "cancelled"
    return "pending"


def _tool_progress_status(phase: str) -> str:
    if phase == "start":
        return "running"
    if phase == "error":
        return "failed"
    return "completed"


def _graph_status_from_execution(status: str | None) -> str:
    if status == "completed":
        return "running"
    if status == "cancelled":
        return "cancelled"
    if status in {"partial", "failed"}:
        return "failed"
    return "running"
