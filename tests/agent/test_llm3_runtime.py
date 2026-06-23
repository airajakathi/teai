from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.llm3.event_emitter import OrchestrationEventEmitter
from teai_builder.agent.llm3.execution_bridge import ExecutionBridge
from teai_builder.agent.llm3.execution_runtime import LLM3ExecutionRuntime
from teai_builder.agent.llm3.executive import ExecutiveOrchestrator
from teai_builder.agent.llm3.mode_selector import select_mode
from teai_builder.agent.llm3.response_runtime import LLM3ResponseRuntime
from teai_builder.agent.llm3.review import build_review_decision
from teai_builder.agent.llm3.state_store import InMemoryOrchestrationStateStore
from teai_builder.agent.llm3.task_graph import (
    apply_checkpoint_event,
    apply_execution_event,
    apply_merge_event,
    apply_reasoning_event,
    apply_recovery_event,
    apply_review_event,
    apply_response_candidate_event,
    apply_terminal_response_event,
    apply_tool_event,
    apply_tool_progress_event,
    apply_retry_event,
    apply_validation_event,
    apply_worker_event,
    apply_workflow_run_payload,
    build_turn_task_graph,
    build_workflow_task_graph,
)
from teai_builder.agent.llm3.turn_builder import build_execution_brief, build_unified_turn
from teai_builder.agent.llm3.turn_runtime import LLM3TurnRuntime
from teai_builder.agent.parallel_executor import ParallelTask
from teai_builder.bus.events import InboundMessage, OutboundMessage
from teai_builder.bus.queue import MessageBus
from teai_builder.providers.base import LLMResponse
from teai_builder.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY


def test_build_unified_turn_classifies_media_and_capabilities() -> None:
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="Generate an image from this input.",
        media=["/tmp/photo.png", "/tmp/spec.txt"],
        metadata={
            WORKSPACE_SCOPE_METADATA_KEY: {"root": "/tmp/workspace"},
            "image_generation": {"enabled": True},
        },
    )

    turn = build_unified_turn(msg, turn_id="turn-1", session_key="sess-1")

    assert turn.turn_id == "turn-1"
    assert turn.workspace_scope == {"root": "/tmp/workspace"}
    assert len(turn.attachments) == 2
    assert len(turn.image_inputs) == 1
    requested = {item.capability for item in turn.requested_capabilities}
    assert "multimodal_input" in requested
    assert "image_generation" in requested


def test_select_mode_uses_deterministic_phase1_heuristics() -> None:
    simple = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello"),
        turn_id="turn-a",
        session_key="sess-a",
    )
    assisted = build_unified_turn(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="c1",
            content="please analyze this",
        ),
        turn_id="turn-b",
        session_key="sess-b",
    )
    workflow = build_unified_turn(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="c1",
            content="build a full project architecture",
        ),
        turn_id="turn-c",
        session_key="sess-c",
    )

    assert select_mode(simple) == "direct"
    assert select_mode(assisted) == "assisted"
    assert select_mode(workflow) == "workflow"


def test_executive_orchestrator_prepares_plan() -> None:
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="please analyze this request",
    )

    plan = ExecutiveOrchestrator().prepare_turn(
        msg,
        turn_id="turn-plan",
        session_key="sess-plan",
    )

    assert plan.turn.turn_id == "turn-plan"
    assert plan.mode == "assisted"
    assert plan.brief.turn_id == "turn-plan"
    assert plan.brief.request_id.startswith("req-")


@pytest.mark.asyncio
async def test_execution_bridge_returns_structured_result_and_review() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="fix the bug"),
        turn_id="turn-1",
        session_key="sess-1",
    )
    brief = build_execution_brief(turn, mode="assisted")

    async def executor():
        return (
            "Done.",
            ["read_file", "edit_file"],
            [{"role": "assistant", "content": "Done."}],
            "ok",
            False,
        )

    outcome = await ExecutionBridge().execute(
        brief,
        executor,
        tool_events_supplier=lambda: [
            {"name": "read_file", "status": "ok", "detail": "read ok"},
            {"name": "edit_file", "status": "ok", "detail": "edit ok"},
        ],
    )
    review = build_review_decision(outcome.result)

    assert outcome.result.request_id == brief.request_id
    assert outcome.result.status == "completed"
    assert outcome.result.final_user_safe_answer_candidate == "Done."
    assert len(outcome.tool_events) == 2
    assert review.decision == "accept"


@pytest.mark.asyncio
async def test_llm3_execution_runtime_records_execution_and_review_state() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="fix the bug"),
        turn_id="turn-execution-runtime",
        session_key="sess-execution-runtime",
    )
    brief = build_execution_brief(turn, mode="assisted")
    state_store = InMemoryOrchestrationStateStore()
    state_store.start_turn(turn)
    state_store.record_execution_brief(brief)

    async def executor():
        return (
            "Done.",
            ["read_file", "edit_file"],
            [{"role": "assistant", "content": "Done."}],
            "ok",
            False,
        )

    runtime_outcome = await LLM3ExecutionRuntime(state_store=state_store).execute(
        brief,
        executor,
        tool_events_supplier=lambda: [
            {"name": "read_file", "status": "ok", "detail": "read ok"},
            {"name": "edit_file", "status": "ok", "detail": "edit ok"},
        ],
    )

    assert runtime_outcome.execution.result.status == "completed"
    assert runtime_outcome.review.decision == "accept"
    snapshot = state_store.snapshot(turn.turn_id)
    assert snapshot["execution_status"] == "completed"
    assert snapshot["review"] == "accept"


@pytest.mark.asyncio
async def test_llm3_response_runtime_finalizes_response_metadata() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="fix the bug"),
        turn_id="turn-response-runtime",
        session_key="sess-response-runtime",
    )
    brief = build_execution_brief(turn, mode="assisted")
    state_store = InMemoryOrchestrationStateStore()
    turn_runtime = LLM3TurnRuntime(state_store=state_store)
    turn_runtime.start_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="fix the bug"),
        turn_id=turn.turn_id,
        session_key=turn.session_key,
    )
    turn_runtime.record_execution_brief(brief)
    execution_outcome = await LLM3ExecutionRuntime(state_store=state_store).execute(
        brief,
        lambda: AsyncMock(
            return_value=(
                "Done.",
                ["read_file"],
                [{"role": "assistant", "content": "Done."}],
                "ok",
                False,
            )
        )(),
    )
    event_emitter = OrchestrationEventEmitter()
    event_emitter.emit(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        event_type="execution_completed",
        payload={"request_id": brief.request_id},
    )
    outbound = OutboundMessage(
        channel="telegram",
        chat_id="c1",
        content="Done.",
        metadata={},
    )

    finalized = await LLM3ResponseRuntime(
        turn_runtime=turn_runtime,
        event_emitter=event_emitter,
    ).finalize_response(
        outbound,
        turn_id=turn.turn_id,
        turn=turn,
        mode="assisted",
        brief=brief,
        result=execution_outcome.execution.result,
        review=execution_outcome.review,
        stop_reason="ok",
        ephemeral=False,
    )

    assert finalized.metadata["_llm3"]["mode"] == "assisted"
    assert finalized.metadata["_llm3"]["review"] == "accept"
    assert finalized.metadata["_llm3_state"]["status"] == "completed"
    assert finalized.metadata["_llm3_events"]["last_event"] == "response_ready"


def test_state_store_and_event_emitter_record_phase2_state() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="fix the bug"),
        turn_id="turn-state",
        session_key="sess-state",
    )
    brief = build_execution_brief(turn, mode="assisted")
    store = InMemoryOrchestrationStateStore()
    emitter = OrchestrationEventEmitter()

    store.start_turn(turn)
    store.record_execution_brief(brief)
    emitter.emit(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        event_type="turn_started",
        payload={"channel": turn.channel},
    )
    emitter.emit(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        event_type="execution_prepared",
        payload={"request_id": brief.request_id},
    )

    snapshot = store.snapshot(turn.turn_id)
    summary = emitter.summary(turn.turn_id)

    assert snapshot["mode"] == "assisted"
    assert snapshot["request_id"] == brief.request_id
    assert summary["count"] == 2
    assert summary["last_event"] == "execution_prepared"


def test_llm3_turn_runtime_starts_turn_and_records_state() -> None:
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="please analyze this request",
    )
    runtime = LLM3TurnRuntime(state_store=InMemoryOrchestrationStateStore())

    plan = runtime.start_turn(
        msg,
        turn_id="turn-runtime",
        session_key="sess-runtime",
    )

    assert plan.turn.turn_id == "turn-runtime"
    assert plan.mode == "assisted"
    snapshot = runtime.snapshot("turn-runtime")
    assert snapshot is not None
    assert snapshot["turn"]["turn_id"] == "turn-runtime"


def test_state_store_and_event_emitter_persist_to_disk(tmp_path) -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="fix the bug"),
        turn_id="turn-persist",
        session_key="sess-persist",
    )
    brief = build_execution_brief(turn, mode="assisted")
    state_store = InMemoryOrchestrationStateStore(storage_dir=tmp_path / "state")
    emitter = OrchestrationEventEmitter(storage_dir=tmp_path / "events")

    state_store.start_turn(turn)
    state_store.record_execution_brief(brief)
    emitter.emit(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        event_type="turn_started",
        payload={"channel": turn.channel},
    )

    state_payload = (tmp_path / "state" / "turn-persist.json").read_text(encoding="utf-8")
    events_payload = (tmp_path / "events" / "turn-persist.json").read_text(encoding="utf-8")

    assert '"request_id": "' in state_payload
    assert '"type": "turn_started"' in events_payload


def test_state_store_records_worker_lifecycle(tmp_path) -> None:
    store = InMemoryOrchestrationStateStore(storage_dir=tmp_path / "state")

    store.ensure_turn_context(
        "goal-1",
        "workflow:test",
        status="workers_running",
        metadata={"source": "parallel_executor"},
    )
    store.record_worker_started(
        turn_id="goal-1",
        session_key="workflow:test",
        worker_id="wrk-1",
        label="goal-1:plan",
        task_id="plan",
        metadata={"description": "Plan"},
    )
    store.record_worker_update(
        "wrk-1",
        status="completed",
        metadata={"stop_reason": "done"},
    )

    snapshot = store.snapshot("goal-1")
    payload = (tmp_path / "state" / "goal-1.json").read_text(encoding="utf-8")

    assert snapshot["worker_count"] == 1
    assert snapshot["workers"][0]["worker_id"] == "wrk-1"
    assert snapshot["workers"][0]["status"] == "completed"
    assert snapshot["workers"][0]["metadata"]["stop_reason"] == "done"
    assert '"worker_count": 1' in payload
    assert '"worker_id": "wrk-1"' in payload


def test_state_store_records_checkpoint_and_recovery(tmp_path) -> None:
    store = InMemoryOrchestrationStateStore(storage_dir=tmp_path / "state")

    store.ensure_turn_context(
        "goal-recover",
        "workflow:recover",
        status="workers_running",
        metadata={"workflow_id": "app_build_v1"},
    )
    store.record_checkpoint(
        turn_id="goal-recover",
        session_key="workflow:recover",
        checkpoint_id="cp-1",
        kind="workflow",
        summary="After plan",
        metadata={"step_id": "plan"},
    )
    store.start_recovery(
        recovery_id="rec-1",
        turn_id="goal-recover",
        session_key="workflow:recover",
        reason="manual_restore",
        source_checkpoint_id="cp-1",
        summary="Resume run",
    )
    store.complete_recovery("rec-1", status="completed", summary="Resume finished")

    snapshot = store.snapshot("goal-recover")

    assert snapshot["checkpoint_count"] == 1
    assert snapshot["checkpoints"][0]["checkpoint_id"] == "cp-1"
    assert snapshot["checkpoints"][0]["metadata"]["step_id"] == "plan"
    assert snapshot["recovery_count"] == 1
    assert snapshot["recoveries"][0]["recovery_id"] == "rec-1"
    assert snapshot["recoveries"][0]["status"] == "completed"
    assert snapshot["recoveries"][0]["source_checkpoint_id"] == "cp-1"


def test_task_graph_build_and_state_store_snapshot(tmp_path) -> None:
    graph = build_workflow_task_graph(
        run_id="run-1",
        turn_id="goal-graph",
        session_key="workflow:graph",
        workflow_id="wf-1",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(step_id="plan", name="Plan", depends_on=[], prompt_template="plan", continue_on_error=False, checkpoint_after=False),
            SimpleNamespace(step_id="verify", name="Verify", depends_on=["plan"], prompt_template="verify", continue_on_error=False, checkpoint_after=True),
        ],
        metadata={"goal_id": "goal-graph"},
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "version": 1,
            "run_id": "run-1",
            "goal_id": "goal-graph",
            "workflow_id": "wf-1",
            "session_key": "workflow:graph",
            "state": "running",
            "current_step": "verify",
            "started_at": 1,
            "updated_at": 2,
            "finished_at": None,
            "completed_steps": 1,
            "step_count": 2,
            "step_states": [
                {"step_id": "plan", "name": "Plan", "state": "completed", "attempts": 1, "error": None, "output": {"output": "draft"}, "skipped_reason": None, "started_at": 1, "finished_at": 2},
                {"step_id": "verify", "name": "Verify", "state": "running", "attempts": 2, "error": None, "output": None, "skipped_reason": None, "started_at": 2, "finished_at": None},
            ],
        },
    )
    store = InMemoryOrchestrationStateStore(storage_dir=tmp_path / "state")
    store.record_task_graph(turn_id="goal-graph", session_key="workflow:graph", graph=graph)

    snapshot = store.snapshot("goal-graph")

    assert snapshot["task_graph_count"] == 1
    assert snapshot["task_graphs"][0]["graph_id"] == "graph:run-1"
    assert snapshot["task_graphs"][0]["metadata"]["version"] == 1
    assert snapshot["task_graphs"][0]["metadata"]["started_at"] == 1
    assert snapshot["task_graphs"][0]["metadata"]["finished_at"] is None
    assert snapshot["task_graphs"][0]["status"] == "running"
    assert snapshot["task_graphs"][0]["edges"] == [
        {
            "edge_id": "graph:run-1:plan->dependency->graph:run-1:verify",
            "from_node_id": "graph:run-1:plan",
            "to_node_id": "graph:run-1:verify",
            "kind": "dependency",
            "metadata": {},
        }
    ]
    assert snapshot["task_graphs"][0]["nodes"][0]["status"] == "completed"
    assert snapshot["task_graphs"][0]["nodes"][0]["metadata"]["output"] == {"output": "draft"}
    assert snapshot["task_graphs"][0]["nodes"][1]["status"] == "running"
    assert snapshot["task_graphs"][0]["nodes"][1]["retry_count"] == 1


def test_workflow_task_graph_marks_dependency_free_steps_ready() -> None:
    graph = build_workflow_task_graph(
        run_id="run-ready",
        turn_id="goal-ready",
        session_key="workflow:ready",
        workflow_id="wf-ready",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="verify",
                name="Verify",
                depends_on=["plan"],
                prompt_template="verify",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )

    plan_node = next(node for node in graph.nodes if node.payload.get("step_id") == "plan")
    verify_node = next(node for node in graph.nodes if node.payload.get("step_id") == "verify")

    assert plan_node.status == "ready"
    assert verify_node.status == "pending"


def test_task_graph_materializes_workflow_cancellation_request_node() -> None:
    graph = build_workflow_task_graph(
        run_id="run-cancel",
        turn_id="goal-cancel",
        session_key="workflow:cancel",
        workflow_id="wf-cancel",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-cancel",
            "goal_id": "goal-cancel",
            "workflow_id": "wf-cancel",
            "state": "running",
            "current_step": "plan",
            "updated_at": 2,
            "cancel_requested": True,
            "step_count": 1,
            "completed_steps": 0,
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "running",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 1,
                    "finished_at": None,
                }
            ],
        },
    )

    cancellation_nodes = [
        node for node in graph.nodes
        if node.type == "reason" and node.payload.get("reason_kind") == "cancellation"
    ]

    assert graph.metadata["cancel_requested"] is True
    assert len(cancellation_nodes) == 1
    assert cancellation_nodes[0].label == "Cancellation requested"
    assert cancellation_nodes[0].depends_on == [f"{graph.graph_id}:plan"]
    assert cancellation_nodes[0].payload["current_step"] == "plan"


def test_task_graph_materializes_blocked_workflow_dependency_skip() -> None:
    graph = build_workflow_task_graph(
        run_id="run-blocked",
        turn_id="goal-blocked",
        session_key="workflow:blocked",
        workflow_id="wf-blocked",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="review",
                name="Review",
                depends_on=[],
                prompt_template="review",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="optional_summary",
                name="Optional summary",
                depends_on=[],
                prompt_template="summary",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-blocked",
            "goal_id": "goal-blocked",
            "workflow_id": "wf-blocked",
            "state": "running",
            "current_step": "review",
            "updated_at": 2,
            "step_count": 3,
            "completed_steps": 1,
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "completed",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 1,
                    "finished_at": 2,
                },
                {
                    "step_id": "review",
                    "state": "skipped",
                    "attempts": 0,
                    "error": None,
                    "skipped_reason": "missing step result `draft`",
                    "started_at": None,
                    "finished_at": 2,
                },
                {
                    "step_id": "optional_summary",
                    "state": "skipped",
                    "attempts": 0,
                    "error": None,
                    "skipped_reason": "condition `needs_summary` evaluated false",
                    "started_at": None,
                    "finished_at": 2,
                },
            ],
        },
    )

    review_node = next(node for node in graph.nodes if node.payload.get("step_id") == "review")
    optional_summary_node = next(
        node for node in graph.nodes if node.payload.get("step_id") == "optional_summary"
    )

    assert review_node.status == "blocked"
    assert review_node.metadata["skipped_reason"] == "missing step result `draft`"
    assert optional_summary_node.status == "skipped"
    assert optional_summary_node.metadata["skipped_reason"] == "condition `needs_summary` evaluated false"


def test_task_graph_materializes_deadlocked_workflow_nodes_as_blocked() -> None:
    graph = build_workflow_task_graph(
        run_id="run-deadlock",
        turn_id="goal-deadlock",
        session_key="workflow:deadlock",
        workflow_id="wf-deadlock",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=["verify"],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="verify",
                name="Verify",
                depends_on=["plan"],
                prompt_template="verify",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-deadlock",
            "goal_id": "goal-deadlock",
            "workflow_id": "wf-deadlock",
            "state": "failed",
            "current_step": None,
            "updated_at": 2,
            "step_count": 2,
            "completed_steps": 0,
            "error": "Deadlocked tasks with unmet dependencies: ['plan', 'verify']",
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "pending",
                    "attempts": 0,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": None,
                    "finished_at": None,
                },
                {
                    "step_id": "verify",
                    "state": "pending",
                    "attempts": 0,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": None,
                    "finished_at": None,
                },
            ],
        },
    )

    plan_node = next(node for node in graph.nodes if node.payload.get("step_id") == "plan")
    verify_node = next(node for node in graph.nodes if node.payload.get("step_id") == "verify")

    assert graph.status == "failed"
    assert graph.metadata["deadlock_detected"] is True
    assert plan_node.status == "blocked"
    assert verify_node.status == "blocked"
    assert "Deadlocked tasks with unmet dependencies" in plan_node.metadata["blocked_reason"]
    assert "Deadlocked tasks with unmet dependencies" in verify_node.metadata["blocked_reason"]


def test_task_graph_materializes_timed_out_workflow_step_reason_nodes() -> None:
    graph = build_workflow_task_graph(
        run_id="run-timeout",
        turn_id="goal-timeout",
        session_key="workflow:timeout",
        workflow_id="wf-timeout",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-timeout",
            "goal_id": "goal-timeout",
            "workflow_id": "wf-timeout",
            "state": "failed",
            "current_step": None,
            "updated_at": 2,
            "step_count": 1,
            "completed_steps": 0,
            "error": "Timed out after 0.1 second(s)",
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "failed",
                    "attempts": 1,
                    "error": "Timed out after 0.1 second(s)",
                    "skipped_reason": None,
                    "started_at": 1.0,
                    "finished_at": 2.0,
                },
            ],
        },
    )

    plan_node = next(node for node in graph.nodes if node.payload.get("step_id") == "plan")
    timeout_nodes = [
        node for node in graph.nodes
        if node.type == "reason" and node.payload.get("reason_kind") == "timeout"
    ]

    assert graph.status == "failed"
    assert graph.metadata["timeout_detected"] is True
    assert graph.metadata["timed_out_steps"] == ["plan"]
    assert plan_node.status == "failed"
    assert plan_node.metadata["timeout_detected"] is True
    assert plan_node.metadata["timeout_seconds"] == 0.1
    assert len(timeout_nodes) == 1
    assert timeout_nodes[0].depends_on == [f"{graph.graph_id}:plan"]
    assert timeout_nodes[0].payload["step_id"] == "plan"
    assert timeout_nodes[0].payload["timeout_seconds"] == 0.1


def test_task_graph_persists_workflow_status_history_metadata() -> None:
    graph = build_workflow_task_graph(
        run_id="run-history",
        turn_id="goal-history",
        session_key="workflow:history",
        workflow_id="wf-history",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-history",
            "goal_id": "goal-history",
            "workflow_id": "wf-history",
            "state": "running",
            "current_step": "plan",
            "updated_at": 2,
            "step_count": 1,
            "completed_steps": 0,
            "error": None,
            "status_history": [
                {"state": "pending", "detail": "Run created", "at": 1.0},
                {"state": "running", "detail": "Dynamic workflow started", "at": 2.0},
            ],
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "running",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 2.0,
                    "finished_at": None,
                },
            ],
        },
    )

    assert graph.metadata["status_history"] == [
        {"state": "pending", "detail": "Run created", "at": 1.0},
        {"state": "running", "detail": "Dynamic workflow started", "at": 2.0},
    ]
    assert graph.metadata["last_status_detail"] == "Dynamic workflow started"
    assert graph.metadata["last_status_at"] == 2.0


def test_task_graph_persists_workflow_checkpoint_history_metadata() -> None:
    graph = build_workflow_task_graph(
        run_id="run-checkpoints",
        turn_id="goal-checkpoints",
        session_key="workflow:checkpoints",
        workflow_id="wf-checkpoints",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=True,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-checkpoints",
            "goal_id": "goal-checkpoints",
            "workflow_id": "wf-checkpoints",
            "state": "running",
            "current_step": "plan",
            "updated_at": 2,
            "step_count": 1,
            "completed_steps": 1,
            "error": None,
            "checkpoints": [
                {
                    "step_id": "plan",
                    "saved_at": 2.0,
                    "result_keys": ["plan"],
                    "checkpoint_id": "cp-1",
                    "context_budget_pct": 1.0,
                }
            ],
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "completed",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 1.0,
                    "finished_at": 2.0,
                },
            ],
        },
    )

    assert graph.metadata["checkpoint_count"] == 1
    assert graph.metadata["last_checkpoint_id"] == "cp-1"
    assert graph.metadata["checkpoints"] == [
        {
            "step_id": "plan",
            "saved_at": 2.0,
            "result_keys": ["plan"],
            "checkpoint_id": "cp-1",
            "context_budget_pct": 1.0,
        }
    ]


def test_task_graph_persists_workflow_run_completion_metadata_and_step_outputs() -> None:
    graph = build_workflow_task_graph(
        run_id="run-finished",
        turn_id="goal-finished",
        session_key="workflow:finished",
        workflow_id="wf-finished",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "version": 1,
            "run_id": "run-finished",
            "goal_id": "goal-finished",
            "workflow_id": "wf-finished",
            "session_key": "workflow:finished",
            "state": "completed",
            "current_step": None,
            "started_at": 1.0,
            "updated_at": 2,
            "finished_at": 3.0,
            "completed_steps": 1,
            "step_count": 1,
            "step_states": [
                {
                    "step_id": "plan",
                    "name": "Plan",
                    "state": "completed",
                    "attempts": 1,
                    "started_at": 1.0,
                    "finished_at": 2.0,
                    "error": None,
                    "output": {"output": "done", "artifact": "report.md"},
                    "skipped_reason": None,
                }
            ],
        },
    )

    plan_node = next(node for node in graph.nodes if node.payload.get("step_id") == "plan")

    assert graph.session_key == "workflow:finished"
    assert graph.status == "completed"
    assert graph.metadata["version"] == 1
    assert graph.metadata["started_at"] == 1.0
    assert graph.metadata["finished_at"] == 3.0
    assert plan_node.label == "Plan"
    assert plan_node.metadata["finished_at"] == 2.0
    assert plan_node.metadata["output"] == {"output": "done", "artifact": "report.md"}


def test_task_graph_materializes_partial_workflow_completion() -> None:
    graph = build_workflow_task_graph(
        run_id="run-partial",
        turn_id="goal-partial",
        session_key="workflow:partial",
        workflow_id="wf-partial",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="verify",
                name="Verify",
                depends_on=["plan"],
                prompt_template="verify",
                continue_on_error=True,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-partial",
            "goal_id": "goal-partial",
            "workflow_id": "wf-partial",
            "state": "completed",
            "current_step": None,
            "updated_at": 3,
            "step_count": 2,
            "completed_steps": 1,
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "completed",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 1,
                    "finished_at": 2,
                },
                {
                    "step_id": "verify",
                    "state": "failed",
                    "attempts": 1,
                    "error": "lint failed",
                    "skipped_reason": None,
                    "started_at": 2,
                    "finished_at": 3,
                },
            ],
        },
    )

    verify_node = next(node for node in graph.nodes if node.payload.get("step_id") == "verify")

    assert graph.status == "partial"
    assert graph.metadata["partial_step_count"] == 1
    assert verify_node.status == "failed"
    assert verify_node.metadata["error"] == "lint failed"


def test_task_graph_materializes_ready_workflow_step_after_dependency_completion() -> None:
    graph = build_workflow_task_graph(
        run_id="run-ready-next",
        turn_id="goal-ready-next",
        session_key="workflow:ready-next",
        workflow_id="wf-ready-next",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="verify",
                name="Verify",
                depends_on=["plan"],
                prompt_template="verify",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="ship",
                name="Ship",
                depends_on=["verify"],
                prompt_template="ship",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-ready-next",
            "goal_id": "goal-ready-next",
            "workflow_id": "wf-ready-next",
            "state": "running",
            "current_step": "verify",
            "updated_at": 2,
            "step_count": 3,
            "completed_steps": 1,
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "completed",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 1,
                    "finished_at": 2,
                },
                {
                    "step_id": "verify",
                    "state": "running",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 2,
                    "finished_at": None,
                },
                {
                    "step_id": "ship",
                    "state": "pending",
                    "attempts": 0,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": None,
                    "finished_at": None,
                },
            ],
        },
    )

    verify_node = next(node for node in graph.nodes if node.payload.get("step_id") == "verify")
    ship_node = next(node for node in graph.nodes if node.payload.get("step_id") == "ship")

    assert verify_node.status == "running"
    assert ship_node.status == "pending"

    graph = apply_workflow_run_payload(
        graph,
        {
            "run_id": "run-ready-next",
            "goal_id": "goal-ready-next",
            "workflow_id": "wf-ready-next",
            "state": "running",
            "current_step": None,
            "updated_at": 3,
            "step_count": 3,
            "completed_steps": 2,
            "step_states": [
                {
                    "step_id": "plan",
                    "state": "completed",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 1,
                    "finished_at": 2,
                },
                {
                    "step_id": "verify",
                    "state": "completed",
                    "attempts": 1,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": 2,
                    "finished_at": 3,
                },
                {
                    "step_id": "ship",
                    "state": "pending",
                    "attempts": 0,
                    "error": None,
                    "skipped_reason": None,
                    "started_at": None,
                    "finished_at": None,
                },
            ],
        },
    )

    ship_node = next(node for node in graph.nodes if node.payload.get("step_id") == "ship")
    assert ship_node.status == "ready"


def test_task_graph_materializes_worker_retry_and_checkpoint_nodes() -> None:
    graph = build_workflow_task_graph(
        run_id="run-graph-2",
        turn_id="goal-graph-2",
        session_key="workflow:graph-2",
        workflow_id="wf-2",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[
            SimpleNamespace(step_id="plan", name="Plan", depends_on=[], prompt_template="plan", continue_on_error=False, checkpoint_after=True),
        ],
    )
    graph = apply_worker_event(
        graph,
        task_id="plan",
        label="goal:plan",
        event_type="worker_task_started",
        worker_id="wrk-1",
        attempt=1,
        total_attempts=2,
        depends_on=[],
    )
    graph = apply_worker_event(
        graph,
        task_id="plan",
        label="goal:plan",
        event_type="worker_task_finished",
        worker_id="wrk-1",
        status="completed",
        attempt=1,
        total_attempts=2,
        stop_reason="done",
    )
    graph = apply_retry_event(
        graph,
        step_id="plan",
        attempt=2,
        total_attempts=2,
        retry_of_worker_id="wrk-1",
        prior_error="first failure",
    )
    graph = apply_worker_event(
        graph,
        task_id="plan",
        label="goal:plan",
        event_type="worker_task_started",
        worker_id="wrk-2",
        attempt=2,
        total_attempts=2,
        retry_of_worker_id="wrk-1",
        depends_on=[],
    )
    graph = apply_checkpoint_event(
        graph,
        step_id="plan",
        checkpoint_id="cp-1",
        result_keys=["plan"],
    )

    worker_nodes = [node for node in graph.nodes if node.type == "worker"]
    retry_nodes = [node for node in graph.nodes if node.type == "reason"]
    checkpoint_nodes = [node for node in graph.nodes if node.type == "checkpoint"]
    checkpoint_edges = [
        edge for edge in graph.edges
        if edge.kind == "checkpoint_after"
    ]

    assert len(worker_nodes) == 2
    assert worker_nodes[0].status == "completed"
    assert worker_nodes[1].retry_count == 1
    assert worker_nodes[1].metadata["retry_of_worker_id"] == "wrk-1"
    assert len(retry_nodes) == 1
    assert retry_nodes[0].payload["step_id"] == "plan"
    assert len(checkpoint_nodes) == 1
    assert checkpoint_nodes[0].payload["checkpoint_id"] == "cp-1"
    assert checkpoint_nodes[0].depends_on == ["graph:run-graph-2:plan"]
    assert {
        (edge.from_node_id, edge.to_node_id, edge.kind)
        for edge in checkpoint_edges
    } == {
        (
            "graph:run-graph-2:plan",
            "graph:run-graph-2:checkpoint:cp-1",
            "checkpoint_after",
        )
    }


def test_task_graph_materializes_review_and_validation_nodes() -> None:
    graph = build_workflow_task_graph(
        run_id="run-graph-3",
        turn_id="goal-graph-3",
        session_key="workflow:graph-3",
        workflow_id="wf-3",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[SimpleNamespace(step_id="plan", name="Plan", depends_on=[], prompt_template="plan", continue_on_error=False, checkpoint_after=False)],
    )
    graph = apply_validation_event(
        graph,
        validation_id="val-1",
        is_complete=False,
        confidence=0.4,
        reasoning="Missing tests",
        failed_criteria=["tests"],
        suggestions=["run tests"],
    )
    graph = apply_response_candidate_event(
        graph,
        request_id="req-1",
        status="completed",
        summary="Prepared answer",
        final_content="Here is the result.",
    )
    graph = apply_review_event(
        graph,
        review_id="review-1",
        request_id="req-1",
        decision="revise",
        rationale="Needs another pass",
        unmet_criteria=["tests missing"],
        depends_on=[
            f"{graph.graph_id}:respond_candidate:req-1",
            f"{graph.graph_id}:validation:val-1",
        ],
    )

    validation_nodes = [node for node in graph.nodes if node.type == "validation"]
    candidate_nodes = [node for node in graph.nodes if node.type == "respond_candidate"]
    review_nodes = [node for node in graph.nodes if node.type == "review"]
    validation_edges = [edge for edge in graph.edges if edge.kind == "validation_of"]

    assert len(validation_nodes) == 1
    assert validation_nodes[0].status == "failed"
    assert validation_nodes[0].metadata["failed_criteria"] == ["tests"]
    assert graph.metadata["last_validation_id"] == "val-1"
    assert graph.metadata["last_validation_complete"] is False
    assert graph.metadata["last_validation_confidence"] == 0.4
    assert graph.metadata["last_validation_failed_criteria"] == ["tests"]
    assert graph.metadata["last_validation_suggestions"] == ["run tests"]
    assert graph.metadata["validation_count"] == 1
    assert validation_edges == []
    assert len(candidate_nodes) == 1
    assert candidate_nodes[0].metadata["content_preview"] == "Here is the result."
    assert len(review_nodes) == 1
    assert review_nodes[0].status == "failed"
    assert review_nodes[0].payload["decision"] == "revise"
    assert review_nodes[0].depends_on == [
        f"{graph.graph_id}:respond_candidate:req-1",
        f"{graph.graph_id}:validation:val-1",
    ]


def test_task_graph_materializes_recovery_and_terminal_response_nodes() -> None:
    graph = build_workflow_task_graph(
        run_id="run-graph-4",
        turn_id="goal-graph-4",
        session_key="workflow:graph-4",
        workflow_id="wf-4",
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=[SimpleNamespace(step_id="plan", name="Plan", depends_on=[], prompt_template="plan", continue_on_error=False, checkpoint_after=False)],
    )
    graph = apply_recovery_event(
        graph,
        recovery_id="rec-1",
        reason="manual_restore",
        event_type="workflow_recovery_started",
        status="running",
        source_checkpoint_id="cp-1",
    )
    graph = apply_recovery_event(
        graph,
        recovery_id="rec-1",
        reason="manual_restore",
        event_type="workflow_recovery_completed",
        status="completed",
        summary="Recovery finished",
        source_checkpoint_id="cp-1",
    )
    graph = apply_terminal_response_event(
        graph,
        response_id="req-1",
        stop_reason="ok",
        final_content_present=True,
        depends_on=[f"{graph.graph_id}:recovery:rec-1"],
    )

    recovery_nodes = [node for node in graph.nodes if node.type == "recovery"]
    response_nodes = [node for node in graph.nodes if node.type == "response"]

    assert len(recovery_nodes) == 1
    assert recovery_nodes[0].status == "completed"
    assert recovery_nodes[0].metadata["source_checkpoint_id"] == "cp-1"
    assert recovery_nodes[0].metadata["summary"] == "Recovery finished"
    assert len(response_nodes) == 1
    assert response_nodes[0].payload["stop_reason"] == "ok"
    assert response_nodes[0].payload["final_content_present"] is True
    assert response_nodes[0].depends_on == [f"{graph.graph_id}:recovery:rec-1"]


def test_turn_task_graph_build_and_execution_updates() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-direct-1",
        session_key="sess-direct-1",
    )
    brief = build_execution_brief(turn, mode="assisted")
    graph = build_turn_task_graph(turn=turn, brief=brief)
    graph = apply_execution_event(
        graph,
        request_id=brief.request_id,
        event_type="execution_started",
    )
    graph = apply_execution_event(
        graph,
        request_id=brief.request_id,
        event_type="execution_completed",
        status="completed",
    )

    execution_nodes = [node for node in graph.nodes if node.type == "execution"]

    assert graph.graph_id == f"graph:{brief.request_id}"
    assert graph.mode == "assisted"
    assert graph.status == "running"
    assert len(execution_nodes) == 1
    assert execution_nodes[0].status == "completed"
    assert execution_nodes[0].payload["request_id"] == brief.request_id


def test_turn_task_graph_materializes_tool_nodes() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-direct-tools",
        session_key="sess-direct-tools",
    )
    brief = build_execution_brief(turn, mode="assisted")
    graph = build_turn_task_graph(turn=turn, brief=brief)
    graph = apply_tool_event(
        graph,
        request_id=brief.request_id,
        sequence=1,
        tool_name="read_file",
        status="ok",
        detail="read ok",
    )
    graph = apply_tool_event(
        graph,
        request_id=brief.request_id,
        sequence=2,
        tool_name="edit_file",
        status="error",
        detail="edit failed",
    )

    tool_nodes = [node for node in graph.nodes if node.type == "tool"]

    assert len(tool_nodes) == 2
    assert tool_nodes[0].status == "completed"
    assert tool_nodes[0].payload["tool_name"] == "read_file"
    assert tool_nodes[1].status == "failed"
    assert tool_nodes[1].metadata["detail"] == "edit failed"


def test_turn_task_graph_materializes_live_tool_progress_nodes() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-live-tools",
        session_key="sess-live-tools",
    )
    brief = build_execution_brief(turn, mode="assisted")
    graph = build_turn_task_graph(turn=turn, brief=brief)
    graph = apply_tool_progress_event(
        graph,
        request_id=brief.request_id,
        tool_name="read_file",
        phase="start",
        call_id="call-1",
        sequence=1,
        arguments={"path": "README.md"},
    )
    graph = apply_tool_progress_event(
        graph,
        request_id=brief.request_id,
        tool_name="read_file",
        phase="end",
        call_id="call-1",
        sequence=1,
        result={"content": "ok"},
    )

    tool_nodes = [node for node in graph.nodes if node.type == "tool"]

    assert len(tool_nodes) == 1
    assert tool_nodes[0].status == "completed"
    assert tool_nodes[0].payload["call_id"] == "call-1"
    assert tool_nodes[0].payload["phase"] == "end"
    assert tool_nodes[0].metadata["arguments"] == {"path": "README.md"}
    assert tool_nodes[0].metadata["result"] == {"content": "ok"}


def test_turn_task_graph_materializes_live_reasoning_nodes() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-live-reasoning",
        session_key="sess-live-reasoning",
    )
    brief = build_execution_brief(turn, mode="assisted")
    graph = build_turn_task_graph(turn=turn, brief=brief)
    graph = apply_reasoning_event(
        graph,
        request_id=brief.request_id,
        content="Inspect files first. ",
        status="running",
    )
    graph = apply_reasoning_event(
        graph,
        request_id=brief.request_id,
        content="Then validate the result.",
        status="running",
    )
    graph = apply_reasoning_event(
        graph,
        request_id=brief.request_id,
        content="",
        status="completed",
    )

    reason_nodes = [
        node for node in graph.nodes
        if node.type == "reason" and node.payload.get("reason_kind") == "stream"
    ]

    assert len(reason_nodes) == 1
    assert reason_nodes[0].status == "completed"
    assert reason_nodes[0].depends_on == [f"{graph.graph_id}:execution:{brief.request_id}"]
    assert reason_nodes[0].metadata["content"] == "Inspect files first. Then validate the result."


def test_turn_task_graph_bumps_updated_at_on_live_mutations() -> None:
    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-graph-updated-at",
        session_key="sess-graph-updated-at",
    )
    brief = build_execution_brief(turn, mode="assisted")
    graph = build_turn_task_graph(turn=turn, brief=brief)
    initial_updated_at = graph.updated_at

    graph = apply_execution_event(
        graph,
        request_id=brief.request_id,
        event_type="execution_started",
    )
    after_execution_updated_at = graph.updated_at
    graph = apply_reasoning_event(
        graph,
        request_id=brief.request_id,
        content="Inspect files.",
        status="running",
    )
    after_reasoning_updated_at = graph.updated_at
    graph = apply_tool_progress_event(
        graph,
        request_id=brief.request_id,
        tool_name="read_file",
        phase="start",
        call_id="call-1",
        sequence=1,
        arguments={"path": "README.md"},
    )

    assert after_execution_updated_at > initial_updated_at
    assert after_reasoning_updated_at > after_execution_updated_at
    assert graph.updated_at > after_reasoning_updated_at


def test_workflow_task_graph_materializes_merge_nodes_before_validation() -> None:
    workflow = SimpleNamespace(
        workflow_id="wf-merge",
        steps=[
            SimpleNamespace(
                step_id="plan",
                name="Plan",
                depends_on=[],
                prompt_template="plan",
                continue_on_error=False,
                checkpoint_after=False,
            ),
            SimpleNamespace(
                step_id="verify",
                name="Verify",
                depends_on=["plan"],
                prompt_template="verify",
                continue_on_error=False,
                checkpoint_after=False,
            ),
        ],
    )
    graph = build_workflow_task_graph(
        run_id="run-merge",
        turn_id="turn-merge",
        session_key="workflow:merge",
        workflow_id=workflow.workflow_id,
        root_objective="Build app",
        created_at=1,
        updated_at=1,
        steps=workflow.steps,
    )
    graph = apply_merge_event(
        graph,
        merge_id="workflow-results",
        label="Workflow result merge",
        result_keys=["plan", "verify"],
        summary="Merged 2 workflow result(s)",
    )
    graph = apply_validation_event(
        graph,
        validation_id="val-merge",
        is_complete=True,
        confidence=0.9,
        reasoning="Looks good",
        depends_on=[f"{graph.graph_id}:merge:workflow-results"],
    )

    merge_nodes = [node for node in graph.nodes if node.type == "merge"]
    validation_nodes = [node for node in graph.nodes if node.type == "validation"]

    assert len(merge_nodes) == 1
    assert merge_nodes[0].payload["result_keys"] == ["plan", "verify"]
    assert merge_nodes[0].depends_on == [f"{graph.graph_id}:plan", f"{graph.graph_id}:verify"]
    assert len(validation_nodes) == 1
    assert validation_nodes[0].depends_on == [f"{graph.graph_id}:merge:workflow-results"]
    assert graph.metadata["last_validation_id"] == "val-merge"
    assert graph.metadata["last_validation_complete"] is True
    assert graph.metadata["last_validation_confidence"] == 0.9
    assert graph.metadata["validation_count"] == 1
    assert {
        (edge.from_node_id, edge.to_node_id, edge.kind)
        for edge in graph.edges
    } >= {
        (
            f"{graph.graph_id}:plan",
            merge_nodes[0].node_id,
            "data_flow",
        ),
        (
            f"{graph.graph_id}:verify",
            merge_nodes[0].node_id,
            "data_flow",
        ),
        (
            f"{graph.graph_id}:merge:workflow-results",
            validation_nodes[0].node_id,
            "validation_of",
        )
    }


@pytest.mark.asyncio
async def test_loop_process_message_attaches_llm3_metadata(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="All set.", tool_calls=[], usage={})
    )
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )
    loop.tools.get_definitions = MagicMock(return_value=[])

    result = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="c1",
            content="please analyze this request",
        )
    )

    assert result is not None
    assert result.metadata["_llm3"]["mode"] == "assisted"
    assert result.metadata["_llm3"]["review"] == "accept"
    assert result.metadata["_llm3"]["request_id"].startswith("req-")
    assert result.metadata["_llm3_state"]["status"] == "completed"
    assert result.metadata["_llm3_state"]["task_graph_count"] == 1
    graph = result.metadata["_llm3_state"]["task_graphs"][0]
    execution_nodes = [node for node in graph["nodes"] if node["type"] == "execution"]
    candidate_nodes = [node for node in graph["nodes"] if node["type"] == "respond_candidate"]
    review_nodes = [node for node in graph["nodes"] if node["type"] == "review"]
    response_nodes = [node for node in graph["nodes"] if node["type"] == "response"]
    edges = graph["edges"]
    assert graph["mode"] == "assisted"
    assert len(execution_nodes) == 1
    assert execution_nodes[0]["status"] == "completed"
    assert len(candidate_nodes) == 1
    assert candidate_nodes[0]["payload"]["request_id"] == result.metadata["_llm3"]["request_id"]
    assert len(review_nodes) == 1
    assert review_nodes[0]["payload"]["decision"] == "accept"
    assert review_nodes[0]["depends_on"] == [
        f"{graph['graph_id']}:respond_candidate:{result.metadata['_llm3']['request_id']}",
    ]
    assert len(response_nodes) == 1
    assert {
        (edge["from_node_id"], edge["to_node_id"], edge["kind"])
        for edge in edges
    } >= {
        (
            f"{graph['graph_id']}:execution:{result.metadata['_llm3']['request_id']}",
            f"{graph['graph_id']}:respond_candidate:{result.metadata['_llm3']['request_id']}",
            "dependency",
        ),
        (
            f"{graph['graph_id']}:execution:{result.metadata['_llm3']['request_id']}",
            f"{graph['graph_id']}:respond_candidate:{result.metadata['_llm3']['request_id']}",
            "data_flow",
        ),
        (
            f"{graph['graph_id']}:respond_candidate:{result.metadata['_llm3']['request_id']}",
            review_nodes[0]["node_id"],
            "dependency",
        ),
        (
            review_nodes[0]["node_id"],
            response_nodes[0]["node_id"],
            "dependency",
        ),
    }
    assert result.metadata["_llm3_events"]["count"] >= 5
    assert result.metadata["_llm3_events"]["last_event"] == "response_ready"
    assert (tmp_path / ".teai_builder" / "llm3" / "state").is_dir()
    assert (tmp_path / ".teai_builder" / "llm3" / "events").is_dir()


@pytest.mark.asyncio
async def test_loop_materializes_worker_retry_and_checkpoint_graph_nodes(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )

    workflow = SimpleNamespace(
        workflow_id="wf-graph",
        steps=[SimpleNamespace(step_id="plan", name="Plan", depends_on=[], prompt_template="plan", continue_on_error=False, checkpoint_after=True)],
    )
    goal = Goal(
        goal_id="goal-graph-loop",
        description="Build app",
        success_criteria=[],
        metadata={"session_key": "workflow:test"},
    )
    run = SimpleNamespace(
        run_id="run-graph-loop",
        workflow_id="wf-graph",
        started_at=1.0,
        updated_at=1.0,
        metadata={"session_key": "workflow:test", "goal": {"goal_id": goal.goal_id}},
    )
    loop.workflow_engine = SimpleNamespace(
        run_update_payload=lambda current_run: {
            "run_id": current_run.run_id,
            "workflow_id": current_run.workflow_id,
            "goal_id": goal.goal_id,
            "session_key": "workflow:test",
            "state": "running",
            "current_step": "plan",
            "updated_at": 1000,
            "completed_steps": 0,
            "step_count": 1,
            "step_states": [{"step_id": "plan", "state": "running", "attempts": 1}],
        }
    )

    loop.sync_llm3_workflow_graph(workflow=workflow, run=run, goal=goal)
    await loop._record_llm3_worker_task_event(
        goal,
        ParallelTask(goal_id=goal.goal_id, task_id="plan", description="Plan", prompt="plan"),
        "worker_task_finished",
        {
            "task_id": "plan",
            "label": "goal-graph-loop:plan",
            "worker_id": "wrk-1",
            "status": "completed",
            "attempt": 1,
            "total_attempts": 2,
            "retry_of_worker_id": None,
            "depends_on": [],
            "stop_reason": "done",
            "error": None,
        },
    )
    await loop._record_llm3_workflow_step_event(
        run,
        SimpleNamespace(step_id="plan"),
        "workflow_step_retry_started",
        {
            "run_id": run.run_id,
            "step_id": "plan",
            "attempt": 2,
            "total_attempts": 2,
            "retry_of_worker_id": "wrk-1",
            "prior_error": "lint failed",
        },
    )
    await loop._record_llm3_workflow_step_event(
        run,
        SimpleNamespace(step_id="plan"),
        "workflow_checkpoint_created",
        {
            "run_id": run.run_id,
            "step_id": "plan",
            "checkpoint_id": "cp-1",
            "result_keys": ["plan"],
            "context_budget_pct": 0.5,
        },
    )
    await loop._record_llm3_workflow_step_event(
        run,
        None,
        "workflow_goal_validated",
        {
            "run_id": run.run_id,
            "merge_id": "workflow-results",
            "merge_summary": "Merged 1 workflow result(s)",
            "result_keys": ["plan"],
            "validation_id": "val-1",
            "is_complete": False,
            "confidence": 0.5,
            "reasoning": "Missing verification",
            "failed_criteria": ["verification"],
            "suggestions": ["run verify"],
        },
    )
    loop._update_llm3_review_graph(
        SimpleNamespace(
            turn_id=goal.goal_id,
            session_key="workflow:test",
            review_decision=SimpleNamespace(
                review_id="review-1",
                request_id="req-1",
                decision="retry",
                rationale="Validation failed",
                unmet_criteria=["verification"],
            ),
        )
    )
    recovery_id = loop.start_llm3_workflow_recovery(
        run=run,
        goal=goal,
        reason="manual_restore",
        source_checkpoint_id="cp-1",
    )
    loop.complete_llm3_workflow_recovery(
        recovery_id,
        goal=goal,
        run=run,
        status="completed",
        summary="Resume finished",
    )
    loop._update_llm3_response_graph(
        SimpleNamespace(
            turn_id=goal.goal_id,
            session_key="workflow:test",
            execution_result=SimpleNamespace(request_id="req-1"),
            stop_reason="ok",
            final_content="done",
        )
    )

    snapshot = loop._llm3_state_store.snapshot(goal.goal_id)
    graph = snapshot["task_graphs"][0]
    worker_nodes = [node for node in graph["nodes"] if node["type"] == "worker"]
    retry_nodes = [node for node in graph["nodes"] if node["type"] == "reason"]
    checkpoint_nodes = [node for node in graph["nodes"] if node["type"] == "checkpoint"]
    merge_nodes = [node for node in graph["nodes"] if node["type"] == "merge"]
    validation_nodes = [node for node in graph["nodes"] if node["type"] == "validation"]
    review_nodes = [node for node in graph["nodes"] if node["type"] == "review"]
    recovery_nodes = [node for node in graph["nodes"] if node["type"] == "recovery"]
    response_nodes = [node for node in graph["nodes"] if node["type"] == "response"]

    assert snapshot["task_graph_count"] == 1
    assert len(worker_nodes) == 1
    assert worker_nodes[0]["payload"]["worker_id"] == "wrk-1"
    assert len(retry_nodes) == 1
    assert retry_nodes[0]["metadata"]["retry_of_worker_id"] == "wrk-1"
    assert len(checkpoint_nodes) == 1
    assert checkpoint_nodes[0]["payload"]["checkpoint_id"] == "cp-1"
    assert checkpoint_nodes[0]["metadata"]["context_budget_pct"] == 0.5
    assert len(merge_nodes) == 1
    assert merge_nodes[0]["payload"]["result_keys"] == ["plan"]
    assert len(validation_nodes) == 1
    assert validation_nodes[0]["payload"]["is_complete"] is False
    assert validation_nodes[0]["depends_on"] == [f"{graph['graph_id']}:merge:workflow-results"]
    assert len(review_nodes) == 1
    assert review_nodes[0]["payload"]["decision"] == "retry"
    assert review_nodes[0]["depends_on"] == [
        f"{graph['graph_id']}:validation:val-1",
    ]
    assert len(recovery_nodes) == 1
    assert recovery_nodes[0]["status"] == "completed"
    assert len(response_nodes) == 1
    assert response_nodes[0]["payload"]["response_id"] == "req-1"
    assert response_nodes[0]["depends_on"] == [
        f"{graph['graph_id']}:review:review-1",
    ]


@pytest.mark.asyncio
async def test_loop_materializes_tool_graph_nodes_for_direct_turn(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )

    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-tools-loop",
        session_key="telegram:c1",
    )
    brief = build_execution_brief(turn, mode="assisted")
    loop._llm3_state_store.start_turn(turn)
    loop._llm3_state_store.record_execution_brief(brief)
    loop._llm3_state_store.record_task_graph(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        graph=build_turn_task_graph(turn=turn, brief=brief),
    )

    ctx = SimpleNamespace(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        execution_brief=brief,
        tool_events=[
            {"name": "read_file", "status": "ok", "detail": "read ok"},
            {"name": "edit_file", "status": "error", "detail": "edit failed"},
        ],
    )
    loop._update_llm3_tool_graph(ctx)

    snapshot = loop._llm3_state_store.snapshot(turn.turn_id)
    graph = snapshot["task_graphs"][0]
    tool_nodes = [node for node in graph["nodes"] if node["type"] == "tool"]

    assert len(tool_nodes) == 2
    assert tool_nodes[0]["payload"]["tool_name"] == "read_file"
    assert tool_nodes[0]["status"] == "completed"
    assert tool_nodes[1]["payload"]["tool_name"] == "edit_file"
    assert tool_nodes[1]["status"] == "failed"


@pytest.mark.asyncio
async def test_loop_progress_callback_materializes_live_tool_progress_nodes(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    bus = MessageBus()
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )

    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-live-progress",
        session_key="telegram:c1",
    )
    brief = build_execution_brief(turn, mode="assisted")
    loop._llm3_state_store.start_turn(turn)
    loop._llm3_state_store.record_execution_brief(brief)
    loop._llm3_state_store.record_task_graph(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        graph=build_turn_task_graph(turn=turn, brief=brief),
    )

    callback = await loop._build_bus_progress_callback(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id=turn.turn_id,
        request_id=brief.request_id,
        session_key=turn.session_key,
    )
    await callback(
        "",
        tool_events=[
            {
                "phase": "start",
                "call_id": "call-1",
                "name": "read_file",
                "arguments": {"path": "README.md"},
            }
        ],
    )

    snapshot = loop._llm3_state_store.snapshot(turn.turn_id)
    graph = snapshot["task_graphs"][0]
    tool_nodes = [node for node in graph["nodes"] if node["type"] == "tool"]

    assert len(tool_nodes) == 1
    assert tool_nodes[0]["status"] == "running"
    assert tool_nodes[0]["payload"]["call_id"] == "call-1"
    assert tool_nodes[0]["metadata"]["arguments"] == {"path": "README.md"}

    await callback(
        "",
        tool_events=[
            {
                "phase": "end",
                "call_id": "call-1",
                "name": "read_file",
                "arguments": {"path": "README.md"},
                "result": {"content": "ok"},
            }
        ],
    )

    snapshot = loop._llm3_state_store.snapshot(turn.turn_id)
    graph = snapshot["task_graphs"][0]
    tool_nodes = [node for node in graph["nodes"] if node["type"] == "tool"]

    assert len(tool_nodes) == 1
    assert tool_nodes[0]["status"] == "completed"
    assert tool_nodes[0]["payload"]["phase"] == "end"
    assert tool_nodes[0]["metadata"]["result"] == {"content": "ok"}


@pytest.mark.asyncio
async def test_loop_progress_callback_materializes_live_reasoning_nodes(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    bus = MessageBus()
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )

    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-live-reasoning-loop",
        session_key="telegram:c1",
    )
    brief = build_execution_brief(turn, mode="assisted")
    loop._llm3_state_store.start_turn(turn)
    loop._llm3_state_store.record_execution_brief(brief)
    loop._llm3_state_store.record_task_graph(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        graph=build_turn_task_graph(turn=turn, brief=brief),
    )

    callback = await loop._build_bus_progress_callback(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id=turn.turn_id,
        request_id=brief.request_id,
        session_key=turn.session_key,
    )
    await callback("Inspect files first. ", reasoning=True)
    await callback("Then validate. ", reasoning=True)
    await callback("", reasoning_end=True)

    snapshot = loop._llm3_state_store.snapshot(turn.turn_id)
    graph = snapshot["task_graphs"][0]
    reason_nodes = [
        node for node in graph["nodes"]
        if node["type"] == "reason" and node["payload"].get("reason_kind") == "stream"
    ]

    assert len(reason_nodes) == 1
    assert reason_nodes[0]["status"] == "completed"
    assert reason_nodes[0]["payload"]["request_id"] == brief.request_id
    assert reason_nodes[0]["metadata"]["content"] == "Inspect files first. Then validate. "


@pytest.mark.asyncio
async def test_loop_materializes_direct_background_worker_graph_nodes(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )

    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-direct-worker",
        session_key="telegram:c1",
    )
    brief = build_execution_brief(turn, mode="assisted")
    loop._llm3_state_store.start_turn(turn)
    loop._llm3_state_store.record_execution_brief(brief)
    loop._llm3_state_store.record_task_graph(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        graph=build_turn_task_graph(turn=turn, brief=brief),
    )

    await loop._record_llm3_background_worker_event(
        "worker_task_started",
        {
            "worker_id": "wrk-bg-1",
            "label": "research worker",
            "status": "running",
            "task": "inspect project",
            "origin_channel": "telegram",
            "origin_chat_id": "c1",
            "session_key": "telegram:c1",
            "owner_turn_id": turn.turn_id,
            "owner_request_id": brief.request_id,
        },
    )
    await loop._record_llm3_background_worker_event(
        "worker_task_finished",
        {
            "worker_id": "wrk-bg-1",
            "label": "research worker",
            "status": "completed",
            "task": "inspect project",
            "stop_reason": "done",
            "origin_channel": "telegram",
            "origin_chat_id": "c1",
            "session_key": "telegram:c1",
            "owner_turn_id": turn.turn_id,
            "owner_request_id": brief.request_id,
        },
    )

    snapshot = loop._llm3_state_store.snapshot(turn.turn_id)
    graph = snapshot["task_graphs"][0]
    worker_nodes = [node for node in graph["nodes"] if node["type"] == "worker"]

    assert snapshot["task_graph_count"] == 1
    assert snapshot["workers"][0]["worker_id"] == "wrk-bg-1"
    assert snapshot["workers"][0]["status"] == "completed"
    assert len(worker_nodes) == 1
    assert worker_nodes[0]["payload"]["worker_id"] == "wrk-bg-1"
    assert worker_nodes[0]["status"] == "completed"
    assert worker_nodes[0]["depends_on"] == [f"{graph['graph_id']}:execution:{brief.request_id}"]


@pytest.mark.asyncio
async def test_persist_subagent_followup_materializes_continuation_node(tmp_path) -> None:
    from teai_builder.agent.loop import AgentLoop

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )

    turn = build_unified_turn(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="please analyze this request"),
        turn_id="turn-followup",
        session_key="telegram:c1",
    )
    brief = build_execution_brief(turn, mode="assisted")
    loop._llm3_state_store.start_turn(turn)
    loop._llm3_state_store.record_execution_brief(brief)
    loop._llm3_state_store.record_task_graph(
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        graph=build_turn_task_graph(turn=turn, brief=brief),
    )
    await loop._record_llm3_background_worker_event(
        "worker_task_finished",
        {
            "worker_id": "wrk-bg-2",
            "label": "research worker",
            "status": "completed",
            "task": "inspect project",
            "stop_reason": "done",
            "origin_channel": "telegram",
            "origin_chat_id": "c1",
            "session_key": "telegram:c1",
            "owner_turn_id": turn.turn_id,
            "owner_request_id": brief.request_id,
        },
    )
    session = loop.sessions.get_or_create(turn.session_key)

    persisted = await loop._persist_subagent_followup(
        session,
        InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="telegram:c1",
            content="Subagent result content",
            metadata={
                "injected_event": "subagent_result",
                "subagent_task_id": "wrk-bg-2",
                "owner_turn_id": turn.turn_id,
                "owner_request_id": brief.request_id,
                "origin_channel": "telegram",
                "origin_chat_id": "c1",
            },
        ),
    )

    snapshot = loop._llm3_state_store.snapshot(turn.turn_id)
    graph = snapshot["task_graphs"][0]
    continuation_nodes = [node for node in graph["nodes"] if node["type"] == "continuation"]
    edges = graph["edges"]

    assert persisted is True
    assert len(continuation_nodes) == 1
    assert continuation_nodes[0]["payload"]["worker_id"] == "wrk-bg-2"
    assert continuation_nodes[0]["payload"]["request_id"] == brief.request_id
    assert continuation_nodes[0]["depends_on"] == [
        f"{graph['graph_id']}:worker:wrk-bg-2:attempt:1",
        f"{graph['graph_id']}:execution:{brief.request_id}",
    ]
    assert {
        (edge["from_node_id"], edge["to_node_id"], edge["kind"])
        for edge in edges
    } >= {
        (
            f"{graph['graph_id']}:worker:wrk-bg-2:attempt:1",
            continuation_nodes[0]["node_id"],
            "data_flow",
        )
    }
