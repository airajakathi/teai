"""Task-graph lifecycle helpers owned by llm3."""

from __future__ import annotations

from typing import Any

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.parallel_executor import ParallelTask

from .event_runtime import LLM3EventRuntime
from .state_store import InMemoryOrchestrationStateStore
from .task_graph import (
    apply_execution_event,
    apply_reasoning_event,
    apply_response_candidate_event,
    apply_review_event,
    apply_terminal_response_event,
    apply_tool_event,
    apply_tool_progress_event,
    apply_worker_event,
    build_turn_task_graph,
)
from .workflow_runtime import WorkflowGraphRuntime


class LLM3TaskGraphRuntime:
    """Own non-workflow graph mutation plus event publication."""

    def __init__(
        self,
        *,
        state_store: InMemoryOrchestrationStateStore,
        event_runtime: LLM3EventRuntime,
        workflow_runtime: WorkflowGraphRuntime,
    ) -> None:
        self._state_store = state_store
        self._event_runtime = event_runtime
        self._workflow_runtime = workflow_runtime

    @staticmethod
    def _execution_node_id(graph: Any, request_id: str | None) -> str | None:
        if not request_id:
            return None
        node_id = f"{graph.graph_id}:execution:{request_id}"
        return node_id if any(node.node_id == node_id for node in graph.nodes) else None

    @staticmethod
    def _latest_node_id(graph: Any, node_type: str) -> str | None:
        for node in reversed(graph.nodes):
            if node.type == node_type:
                return node.node_id
        return None

    @staticmethod
    def _latest_reason_node_id(graph: Any, request_id: str) -> str | None:
        for node in reversed(graph.nodes):
            if (
                node.type == "reason"
                and node.payload.get("request_id") == request_id
                and node.payload.get("reason_kind") == "stream"
            ):
                return node.node_id
        return None

    def initialize_turn_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        unified_turn: Any,
        execution_brief: Any,
        orchestration_mode: str | None,
    ) -> None:
        if self._state_store.latest_task_graph_for_turn(turn_id) is not None:
            return
        graph = build_turn_task_graph(turn=unified_turn, brief=execution_brief)
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=graph,
        )
        self._event_runtime.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type="task_graph_initialized",
            payload={
                "graph_id": graph.graph_id,
                "request_id": execution_brief.request_id,
                "mode": orchestration_mode,
                "node_count": len(graph.nodes),
            },
        )

    def update_execution_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        request_id: str,
        event_type: str,
        status: str | None = None,
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        updated_graph = apply_execution_event(
            graph,
            request_id=request_id,
            event_type=event_type,
            status=status,
        )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        self._event_runtime.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type="task_graph_updated",
            payload={
                "graph_id": updated_graph.graph_id,
                "request_id": request_id,
                "status": updated_graph.status,
                "execution_event": event_type,
            },
        )

    def update_review_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        review_decision: Any,
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        review_dependencies: list[str] = []
        response_candidate_node_id = self._latest_node_id(graph, "respond_candidate")
        if response_candidate_node_id is not None:
            review_dependencies.append(response_candidate_node_id)
        execution_node_id = self._execution_node_id(graph, review_decision.request_id)
        if execution_node_id is not None and response_candidate_node_id is None:
            review_dependencies.append(execution_node_id)
        validation_node_id = self._latest_node_id(graph, "validation")
        if validation_node_id is not None:
            review_dependencies.append(validation_node_id)
        updated_graph = apply_review_event(
            graph,
            review_id=review_decision.review_id,
            request_id=review_decision.request_id,
            decision=review_decision.decision,
            rationale=review_decision.rationale,
            unmet_criteria=list(review_decision.unmet_criteria),
            depends_on=review_dependencies,
        )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        self._event_runtime.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type="task_graph_updated",
            payload={
                "graph_id": updated_graph.graph_id,
                "request_id": review_decision.request_id,
                "status": updated_graph.status,
                "review_id": review_decision.review_id,
            },
        )

    def update_response_candidate_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        execution_result: Any,
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        updated_graph = apply_response_candidate_event(
            graph,
            request_id=execution_result.request_id,
            status=execution_result.status,
            summary=execution_result.summary,
            final_content=execution_result.final_user_safe_answer_candidate,
        )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        self._event_runtime.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type="task_graph_updated",
            payload={
                "graph_id": updated_graph.graph_id,
                "request_id": execution_result.request_id,
                "status": updated_graph.status,
                "candidate_id": execution_result.request_id,
            },
        )

    def update_response_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        execution_result: Any | None,
        stop_reason: str | None,
        final_content: str | None,
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        response_id = (
            execution_result.request_id
            if execution_result is not None
            else f"turn:{turn_id}"
        )
        response_dependencies: list[str] = []
        review_node_id = self._latest_node_id(graph, "review")
        validation_node_id = self._latest_node_id(graph, "validation")
        execution_node_id = self._execution_node_id(
            graph,
            execution_result.request_id if execution_result is not None else None,
        )
        if review_node_id is not None:
            response_dependencies.append(review_node_id)
        elif validation_node_id is not None:
            response_dependencies.append(validation_node_id)
        if execution_node_id is not None and execution_node_id not in response_dependencies:
            response_dependencies.append(execution_node_id)
        updated_graph = apply_terminal_response_event(
            graph,
            response_id=response_id,
            stop_reason=stop_reason or "ok",
            final_content_present=bool(final_content),
            depends_on=response_dependencies,
        )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        self._event_runtime.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type="task_graph_updated",
            payload={
                "graph_id": updated_graph.graph_id,
                "response_id": response_id,
                "status": updated_graph.status,
            },
        )

    def update_tool_graph(
        self,
        *,
        turn_id: str,
        session_key: str,
        request_id: str,
        tool_events: list[dict[str, Any]],
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        existing_tool_nodes = [
            node
            for node in graph.nodes
            if node.type == "tool" and node.payload.get("request_id") == request_id
        ]
        if len(existing_tool_nodes) >= len(tool_events):
            return
        updated_graph = graph
        for index, event in enumerate(tool_events, start=1):
            tool_name = str(event.get("name") or "tool")
            updated_graph = apply_tool_event(
                updated_graph,
                request_id=request_id,
                sequence=index,
                tool_name=tool_name,
                status=str(event.get("status") or "ok"),
                detail=str(event.get("detail") or ""),
            )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        self._event_runtime.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type="tool_activity_recorded",
            payload={
                "graph_id": updated_graph.graph_id,
                "request_id": request_id,
                "tool_count": len(tool_events),
                "tool_names": [str(item.get("name") or "tool") for item in tool_events],
            },
        )

    async def record_tool_progress_event(
        self,
        *,
        turn_id: str,
        session_key: str,
        channel: str,
        chat_id: str,
        request_id: str,
        tool_events: list[dict[str, Any]],
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        updated_graph = graph
        progress_payloads: list[dict[str, Any]] = []
        for index, event in enumerate(tool_events, start=1):
            tool_name = str(event.get("name") or "tool")
            phase = str(event.get("phase") or "end")
            call_id = str(event.get("call_id") or "") or None
            updated_graph = apply_tool_progress_event(
                updated_graph,
                request_id=request_id,
                tool_name=tool_name,
                phase=phase,
                call_id=call_id,
                sequence=index,
                detail=str(event.get("error") or event.get("detail") or ""),
                arguments=event.get("arguments") if isinstance(event.get("arguments"), dict) else None,
                result=event.get("result"),
                error=str(event.get("error")) if event.get("error") is not None else None,
            )
            progress_payloads.append(
                {
                    "tool_name": tool_name,
                    "phase": phase,
                    "call_id": call_id,
                    "status": "running" if phase == "start" else ("failed" if phase == "error" else "completed"),
                }
            )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        payload = {
            "graph_id": updated_graph.graph_id,
            "request_id": request_id,
            "tools": progress_payloads,
        }
        await self._event_runtime.record(
            turn_id=turn_id,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            metadata={
                "_llm3_turn_id": turn_id,
                "_llm3_request_id": request_id,
            },
            event_type="tool_progress_recorded",
            payload=payload,
        )

    async def record_reasoning_progress_event(
        self,
        *,
        turn_id: str,
        session_key: str,
        channel: str,
        chat_id: str,
        request_id: str,
        content: str,
        status: str,
    ) -> None:
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is None:
            return
        updated_graph = apply_reasoning_event(
            graph,
            request_id=request_id,
            content=content,
            status=status,
        )
        if updated_graph is graph:
            return
        self._state_store.record_task_graph(
            turn_id=turn_id,
            session_key=session_key,
            graph=updated_graph,
        )
        payload = {
            "graph_id": updated_graph.graph_id,
            "request_id": request_id,
            "status": status,
            "node_id": self._latest_reason_node_id(updated_graph, request_id),
        }
        await self._event_runtime.record(
            turn_id=turn_id,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            metadata={
                "_llm3_turn_id": turn_id,
                "_llm3_request_id": request_id,
            },
            event_type="reasoning_recorded",
            payload=payload,
        )

    async def record_worker_task_event(
        self,
        goal: Goal,
        task: ParallelTask,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        metadata = dict(goal.metadata or {})
        session_key = str(metadata.get("session_key") or f"goal:{goal.goal_id}")
        turn_id = str(metadata.get("turn_id") or goal.goal_id)
        label = str(payload.get("label") or f"{goal.goal_id}:{task.task_id}")
        worker_id = payload.get("worker_id")
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is not None:
            updated_graph = apply_worker_event(
                graph,
                task_id=task.task_id,
                label=label,
                event_type=event_type,
                worker_id=str(worker_id) if worker_id is not None else None,
                status=str(payload.get("status")) if payload.get("status") is not None else None,
                error=str(payload["error"]) if payload.get("error") is not None else None,
                attempt=int(payload["attempt"]) if payload.get("attempt") is not None else None,
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
                depends_on=[
                    str(item)
                    for item in payload.get("depends_on", [])
                    if item is not None
                ],
                stop_reason=str(payload["stop_reason"]) if payload.get("stop_reason") is not None else None,
            )
            self._state_store.record_task_graph(
                turn_id=turn_id,
                session_key=session_key,
                graph=updated_graph,
            )
        self._state_store.ensure_turn_context(
            turn_id,
            session_key,
            status="workers_running",
            metadata={
                "goal_id": goal.goal_id,
                "source": "parallel_executor",
                "task_id": task.task_id,
            },
        )
        if worker_id is not None:
            if not self._state_store.record_worker_update(
                str(worker_id),
                status=str(payload.get("status") or "running"),
                error=str(payload["error"]) if payload.get("error") is not None else None,
                metadata={
                    "task_id": task.task_id,
                    "description": task.description,
                    "workflow_step": bool(task.metadata.get("workflow_step")),
                    "attempt": payload.get("attempt"),
                    "total_attempts": payload.get("total_attempts"),
                    "retry_of_worker_id": payload.get("retry_of_worker_id"),
                    "depends_on": payload.get("depends_on"),
                    "stop_reason": payload.get("stop_reason"),
                },
            ):
                self._state_store.record_worker_started(
                    turn_id=turn_id,
                    session_key=session_key,
                    worker_id=str(worker_id),
                    label=label,
                    task_id=task.task_id,
                    metadata={
                        "description": task.description,
                        "workflow_step": bool(task.metadata.get("workflow_step")),
                        "attempt": payload.get("attempt"),
                        "total_attempts": payload.get("total_attempts"),
                        "retry_of_worker_id": payload.get("retry_of_worker_id"),
                        "depends_on": payload.get("depends_on"),
                    },
                )
                self._state_store.record_worker_update(
                    str(worker_id),
                    status=str(payload.get("status") or "running"),
                    error=str(payload["error"]) if payload.get("error") is not None else None,
                    metadata={"stop_reason": payload.get("stop_reason")},
                )
        channel = metadata.get("channel")
        chat_id = metadata.get("chat_id")
        await self._event_runtime.record(
            turn_id=turn_id,
            session_key=session_key,
            channel=str(channel) if channel is not None else None,
            chat_id=str(chat_id) if chat_id is not None else None,
            metadata=metadata,
            event_type=event_type,
            payload={"goal_id": goal.goal_id, "task_id": task.task_id, **dict(payload)},
        )

    async def record_workflow_step_event(
        self,
        run: Any,
        step: Any,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        ctx = self._workflow_runtime.record_step_event(
            run,
            step,
            event_type,
            payload,
        )
        await self._event_runtime.record(
            turn_id=ctx.turn_id,
            session_key=ctx.session_key,
            channel=ctx.channel,
            chat_id=ctx.chat_id,
            metadata=ctx.metadata,
            event_type=event_type,
            payload=ctx.event_payload,
        )

    async def record_background_worker_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        turn_id = payload.get("owner_turn_id")
        session_key = payload.get("session_key")
        worker_id = payload.get("worker_id")
        request_id = payload.get("owner_request_id")
        if not isinstance(turn_id, str) or not isinstance(session_key, str):
            return
        label = str(payload.get("label") or payload.get("task") or worker_id or "worker")
        task_id = str(worker_id or f"spawn:{request_id or turn_id}")
        graph = self._state_store.latest_task_graph_for_turn(turn_id)
        if graph is not None:
            depends_on = [f"execution:{request_id}"] if isinstance(request_id, str) and request_id else []
            updated_graph = apply_worker_event(
                graph,
                task_id=task_id,
                label=label,
                event_type=event_type,
                worker_id=str(worker_id) if worker_id is not None else None,
                status=str(payload.get("status")) if payload.get("status") is not None else None,
                error=str(payload["error"]) if payload.get("error") is not None else None,
                depends_on=depends_on,
                stop_reason=str(payload["stop_reason"]) if payload.get("stop_reason") is not None else None,
            )
            self._state_store.record_task_graph(
                turn_id=turn_id,
                session_key=session_key,
                graph=updated_graph,
            )
        if worker_id is not None:
            worker_metadata = {
                "task": payload.get("task"),
                "request_id": request_id,
                "source": "spawn_tool",
                "stop_reason": payload.get("stop_reason"),
            }
            if event_type == "worker_task_started":
                self._state_store.record_worker_started(
                    turn_id=turn_id,
                    session_key=session_key,
                    worker_id=str(worker_id),
                    label=label,
                    task_id=task_id,
                    metadata=worker_metadata,
                )
            else:
                if self._state_store.record_worker_update(
                    str(worker_id),
                    status=str(payload.get("status") or "completed"),
                    error=str(payload["error"]) if payload.get("error") is not None else None,
                    metadata=worker_metadata,
                ) is None:
                    self._state_store.record_worker_started(
                        turn_id=turn_id,
                        session_key=session_key,
                        worker_id=str(worker_id),
                        label=label,
                        task_id=task_id,
                        metadata=worker_metadata,
                    )
                    self._state_store.record_worker_update(
                        str(worker_id),
                        status=str(payload.get("status") or "completed"),
                        error=str(payload["error"]) if payload.get("error") is not None else None,
                        metadata=worker_metadata,
                    )
        channel = payload.get("origin_channel")
        chat_id = payload.get("origin_chat_id")
        await self._event_runtime.record(
            turn_id=turn_id,
            session_key=session_key,
            channel=str(channel) if channel is not None else None,
            chat_id=str(chat_id) if chat_id is not None else None,
            metadata={
                "_llm3_turn_id": turn_id,
                "_llm3_request_id": request_id,
            },
            event_type=event_type,
            payload=dict(payload),
        )

    def sync_workflow_graph(
        self,
        *,
        workflow: Any,
        run: Any,
        goal: Goal,
    ) -> None:
        ctx = self._workflow_runtime.sync_graph(
            workflow=workflow,
            run=run,
            goal=goal,
        )
        self._event_runtime.emit(
            turn_id=ctx.turn_id,
            session_key=ctx.session_key,
            event_type="task_graph_initialized",
            payload=ctx.event_payload,
        )

    def apply_workflow_payload(self, payload: dict[str, Any]) -> None:
        ctx = self._workflow_runtime.apply_run_payload(payload)
        if ctx is None:
            return
        self._event_runtime.emit(
            turn_id=ctx.turn_id,
            session_key=ctx.session_key,
            event_type="task_graph_updated",
            payload=ctx.event_payload,
        )

    def start_workflow_recovery(
        self,
        *,
        run: Any,
        goal: Goal,
        reason: str,
        source_checkpoint_id: str | None = None,
    ) -> str:
        ctx = self._workflow_runtime.start_recovery(
            run=run,
            goal=goal,
            reason=reason,
            source_checkpoint_id=source_checkpoint_id,
        )
        self._event_runtime.emit(
            turn_id=ctx.turn_id,
            session_key=ctx.session_key,
            event_type="workflow_recovery_started",
            payload=ctx.event_payload,
        )
        return str(ctx.event_payload["recovery_id"])

    def complete_workflow_recovery(
        self,
        recovery_id: str,
        *,
        goal: Goal,
        run: Any,
        status: str,
        summary: str | None = None,
    ) -> None:
        ctx = self._workflow_runtime.complete_recovery(
            recovery_id,
            goal=goal,
            run=run,
            status=status,
            summary=summary,
        )
        self._event_runtime.emit(
            turn_id=ctx.turn_id,
            session_key=ctx.session_key,
            event_type="workflow_recovery_completed",
            payload=ctx.event_payload,
        )
