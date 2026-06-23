from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from teai_builder.agent.checkpoint import CheckpointStore
from teai_builder.agent.goal_validator import Goal, ValidationResult
from teai_builder.agent.llm3.dynamic_workflow_executor import (
    DynamicWorkflowExecutor as LLM3DynamicWorkflowExecutor,
)
from teai_builder.agent.llm3.workflow_completion_runtime import LLM3WorkflowCompletionRuntime
from teai_builder.agent.llm3.dynamic_workflow_runtime import LLM3DynamicWorkflowRuntime
from teai_builder.agent.llm3.parallel_task_runtime import LLM3ParallelTaskRuntime
from teai_builder.agent.llm3.parallel_workflow_runtime import LLM3ParallelWorkflowRuntime
from teai_builder.agent.llm3.task_scheduler import LLM3TaskScheduler
from teai_builder.agent.llm3 import workflow_library, workflow_models
from teai_builder.agent.llm3.workflow_host import LLM3WorkflowHost
from teai_builder.agent.llm3.workflow_support import (
    ContextCompactor as LLM3ContextCompactor,
    SemanticCheckpointTrigger as LLM3SemanticCheckpointTrigger,
)
from teai_builder.agent.llm3.workflow_service import LLM3WorkflowService
from teai_builder.agent.llm3.worker_runtime import WorkerExecutionResult
from teai_builder.agent.parallel_executor import ParallelExecutor, ParallelTask, TaskResult, TaskStatus
from teai_builder.agent.workflow_engine import (
    ContextCompactor,
    DynamicWorkflowExecutor,
    SemanticCheckpointTrigger,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowState,
    WorkflowStep,
    get_workflow,
    list_saved_runs,
    list_workflows,
    load_workflows_from_dir,
    register_workflow,
)
from teai_builder.bus.queue import MessageBus


class FakeParallelExecutor:
    def __init__(self, responses: dict[str, list[TaskResult]]) -> None:
        self._responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _run_task(self, goal: Goal, task) -> TaskResult:
        self.calls.append((task.task_id, dict(task.metadata)))
        queue = self._responses[task.task_id]
        return queue.pop(0)

    async def execute(self, goal: Goal, tasks):  # pragma: no cover - not used here
        return {}


class FakeWorkerRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def run(self, spec) -> WorkerExecutionResult:
        self.calls.append((spec.task, spec.model))
        return WorkerExecutionResult(
            worker_id=f"wrk-{len(self.calls)}",
            label=spec.label or "worker",
            status="completed",
            final_output=f"completed: {spec.task}",
            stop_reason="done",
            tool_events=[],
            usage={},
        )


class AutoToolRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __call__(self, name: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, dict(params)))
        if name == "plan_product_surfaces":
            return {
                "primary_platform": "desktop",
                "scaffold_strategy": "solution-scaffold",
                "scaffold_plan": [
                    {
                        "platform": "solution",
                        "template": "desktop-suite",
                        "path": params.get("project_name", "app"),
                    }
                ],
            }
        if name == "execute_scaffold_plan":
            planner_result = params.get("planner_result")
            return {
                "executed": True,
                "planner_result": planner_result,
                "project_name": params.get("project_name"),
            }
        return {"ok": True}


class HangingParallelExecutor(FakeParallelExecutor):
    async def _run_task(self, goal: Goal, task) -> TaskResult:
        self.calls.append((task.task_id, dict(task.metadata)))
        await asyncio.sleep(0.05)
        return TaskResult(task_id=task.task_id, status=TaskStatus.COMPLETED, output={"output": "late"})


class FakeLLM3TaskScheduler:
    def __init__(self, responses: dict[str, list[TaskResult]]) -> None:
        self._responses = {key: list(value) for key, value in responses.items()}
        self.batch_calls: list[list[str]] = []
        self.task_calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, goal: Goal, tasks) -> dict[str, TaskResult]:
        task_list = list(tasks)
        self.batch_calls.append([task.task_id for task in task_list])
        results: dict[str, TaskResult] = {}
        for task in task_list:
            queue = self._responses[task.task_id]
            results[task.task_id] = queue.pop(0)
        return results

    async def run_task(self, goal: Goal, task) -> TaskResult:
        self.task_calls.append((task.task_id, dict(task.metadata)))
        queue = self._responses[task.task_id]
        return queue.pop(0)


@pytest.mark.asyncio
async def test_dynamic_workflow_skips_and_continues_on_error(tmp_path) -> None:
    executor = FakeParallelExecutor(
        {
            "plan": [TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done"})],
            "verify": [TaskResult(task_id="verify", status=TaskStatus.FAILED, error="lint failed")],
        }
    )
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="phase1",
        name="Phase 1",
        description="phase one orchestration",
        steps=[
            WorkflowStep(step_id="plan", name="Plan", prompt_template="plan {topic}"),
            WorkflowStep(
                step_id="optional_review",
                name="Optional review",
                prompt_template="review {topic}",
                run_if="needs_review",
            ),
            WorkflowStep(
                step_id="verify",
                name="Verify",
                prompt_template="verify {topic}",
                continue_on_error=True,
            ),
        ],
    )
    goal = Goal(goal_id="goal-1", description="phase one", success_criteria=[])

    run = await dynamic.execute(workflow, goal, {"topic": "workflow", "needs_review": False})

    assert run.state == WorkflowState.COMPLETED
    assert [task_id for task_id, _ in executor.calls] == ["plan", "verify"]
    assert run.step_states["optional_review"].state == WorkflowState.SKIPPED
    assert run.step_states["verify"].state == WorkflowState.FAILED
    assert run.step_results["verify"] == {"error": "lint failed", "continued": True}
    assert run.metadata["variables"] == {"topic": "workflow", "needs_review": False}


@pytest.mark.asyncio
async def test_parallel_workflow_deadlock_returns_failed_run(tmp_path) -> None:
    engine = WorkflowEngine(
        parallel_executor=ParallelExecutor(
            subagent_manager=SimpleNamespace(model="gpt-4o-mini"),
            bus=MessageBus(),
            max_parallel=2,
        ),
        storage_dir=tmp_path,
    )
    workflow = WorkflowDefinition(
        workflow_id="deadlock",
        name="Deadlock",
        description="deadlock test",
        steps=[
            WorkflowStep(step_id="plan", name="Plan", prompt_template="plan", depends_on=["verify"]),
            WorkflowStep(step_id="verify", name="Verify", prompt_template="verify", depends_on=["plan"]),
        ],
    )
    goal = Goal(goal_id="goal-deadlock", description="deadlock", success_criteria=[])

    run = await engine.run(workflow, goal, {})

    assert run.state == WorkflowState.FAILED
    assert run.error == "Deadlocked tasks with unmet dependencies: ['plan', 'verify']"
    assert run.step_states["plan"].state == WorkflowState.PENDING
    assert run.step_states["verify"].state == WorkflowState.PENDING


@pytest.mark.asyncio
async def test_dynamic_workflow_timeout_returns_failed_step(tmp_path) -> None:
    executor = HangingParallelExecutor({})
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="timeout",
        name="Timeout",
        description="timeout test",
        steps=[
            WorkflowStep(
                step_id="plan",
                name="Plan",
                prompt_template="plan",
                timeout_seconds=0.01,
            ),
        ],
    )
    goal = Goal(goal_id="goal-timeout", description="timeout", success_criteria=[])

    run = await dynamic.execute(workflow, goal, {})

    assert run.state == WorkflowState.FAILED
    assert run.error == "Timed out after 0.01 second(s)"
    assert run.step_states["plan"].state == WorkflowState.FAILED
    assert run.step_states["plan"].error == "Timed out after 0.01 second(s)"


@pytest.mark.asyncio
async def test_dynamic_workflow_resume_retries_failed_step(tmp_path) -> None:
    executor = FakeParallelExecutor(
        {
            "plan": [TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done"})],
            "verify": [
                TaskResult(task_id="verify", status=TaskStatus.FAILED, error="first failure"),
                TaskResult(task_id="verify", status=TaskStatus.COMPLETED, output={"output": "fixed"}),
            ],
        }
    )
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="resumeable",
        name="Resumeable",
        description="resume test",
        steps=[
            WorkflowStep(step_id="plan", name="Plan", prompt_template="plan"),
            WorkflowStep(step_id="verify", name="Verify", prompt_template="verify"),
        ],
    )
    goal = Goal(goal_id="goal-2", description="resume", success_criteria=[])

    first_run = await dynamic.execute(workflow, goal, {})
    assert first_run.state == WorkflowState.FAILED
    assert first_run.step_states["verify"].state == WorkflowState.FAILED

    resumed = await dynamic.execute(workflow, goal, {}, run=first_run)

    assert resumed.run_id == first_run.run_id
    assert resumed.state == WorkflowState.COMPLETED
    assert resumed.step_states["plan"].attempts == 1
    assert resumed.step_states["verify"].attempts == 1
    assert resumed.step_states["verify"].state == WorkflowState.COMPLETED
    assert [task_id for task_id, _ in executor.calls] == ["plan", "verify", "verify"]
    assert executor.calls[1][1]["attempt"] == 1
    assert executor.calls[2][1]["attempt"] == 1


@pytest.mark.asyncio
async def test_dynamic_workflow_uses_llm3_task_scheduler_for_retry_execution(tmp_path) -> None:
    scheduler = FakeLLM3TaskScheduler(
        {
            "plan": [
                TaskResult(task_id="plan", status=TaskStatus.FAILED, error="first failure", output={"worker_id": "wrk-1"}),
                TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done", "worker_id": "wrk-2"}),
            ],
        }
    )
    engine = WorkflowEngine(
        parallel_executor=SimpleNamespace(),
        storage_dir=tmp_path,
        task_scheduler=scheduler,
    )
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="llm3-scheduler",
        name="LLM3 Scheduler",
        description="scheduler test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan", max_retries=1)],
    )
    goal = Goal(goal_id="goal-scheduler", description="scheduler", success_criteria=[])

    run = await dynamic.execute(workflow, goal, {})

    assert run.state == WorkflowState.COMPLETED
    assert scheduler.task_calls[0][1]["attempt"] == 1
    assert scheduler.task_calls[1][1]["attempt"] == 2
    assert scheduler.task_calls[1][1]["retry_of_worker_id"] == "wrk-1"


@pytest.mark.asyncio
async def test_llm3_dynamic_workflow_runtime_executes_dynamic_workflow(tmp_path) -> None:
    executor = FakeParallelExecutor(
        {
            "plan": [TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done"})],
        }
    )
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)
    runtime = LLM3DynamicWorkflowRuntime(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="llm3-runtime",
        name="LLM3 Runtime",
        description="runtime test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan")],
    )
    goal = Goal(goal_id="goal-runtime", description="runtime", success_criteria=[])

    run = await runtime.execute(workflow, goal, {})

    assert run.state == WorkflowState.COMPLETED
    assert run.step_results["plan"] == {"output": "done"}
    assert [task_id for task_id, _ in executor.calls] == ["plan"]


@pytest.mark.asyncio
async def test_llm3_parallel_workflow_runtime_executes_parallel_workflow(tmp_path) -> None:
    scheduler = FakeLLM3TaskScheduler(
        {
            "plan": [TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done"})],
            "verify": [TaskResult(task_id="verify", status=TaskStatus.COMPLETED, output={"output": "verified"})],
        }
    )
    engine = WorkflowEngine(
        parallel_executor=SimpleNamespace(),
        storage_dir=tmp_path,
        task_scheduler=scheduler,
    )
    runtime = LLM3ParallelWorkflowRuntime(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="llm3-parallel-runtime",
        name="LLM3 Parallel Runtime",
        description="parallel runtime test",
        steps=[
            WorkflowStep(step_id="plan", name="Plan", prompt_template="plan"),
            WorkflowStep(step_id="verify", name="Verify", prompt_template="verify"),
        ],
    )
    goal = Goal(goal_id="goal-parallel-runtime", description="parallel runtime", success_criteria=[])

    run = await runtime.execute(workflow, goal, {})

    assert run.state == WorkflowState.COMPLETED
    assert run.step_results["plan"] == {"output": "done"}
    assert run.step_results["verify"] == {"output": "verified"}
    assert scheduler.batch_calls == [["plan", "verify"]]


@pytest.mark.asyncio
async def test_llm3_parallel_workflow_runtime_fails_on_goal_validation(tmp_path) -> None:
    scheduler = FakeLLM3TaskScheduler(
        {
            "plan": [TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done"})],
        }
    )
    host = LLM3WorkflowHost(
        parallel_executor=SimpleNamespace(),
        storage_dir=tmp_path,
        task_scheduler=scheduler,
        goal_validator=SimpleNamespace(
            validate=lambda goal, results: ValidationResult(
                is_complete=False,
                confidence=0.2,
                reasoning="Missing verification",
                failed_criteria=["verification"],
                suggestions=["run verify"],
            )
        ),
    )
    engine = WorkflowEngine(
        parallel_executor=SimpleNamespace(),
        storage_dir=tmp_path,
        workflow_host=host,
    )
    runtime = LLM3ParallelWorkflowRuntime(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="llm3-parallel-validation",
        name="LLM3 Parallel Validation",
        description="parallel validation test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan")],
    )
    goal = Goal(goal_id="goal-parallel-validation", description="parallel validation", success_criteria=[])

    run = await runtime.execute(workflow, goal, {})

    assert isinstance(engine.completion_runtime, LLM3WorkflowCompletionRuntime)
    assert run.state == WorkflowState.FAILED
    assert run.error == "Goal validation failed: verification"


@pytest.mark.asyncio
async def test_llm3_parallel_task_runtime_executes_dependency_batches(tmp_path) -> None:
    runtime = FakeWorkerRuntime()
    executor = ParallelExecutor(
        subagent_manager=SimpleNamespace(model="test-model"),
        bus=MessageBus(),
        max_parallel=2,
        worker_runtime=runtime,
    )
    goal = Goal(
        goal_id="goal-parallel-tasks",
        description="parallel tasks",
        success_criteria=[],
        metadata={"session_key": "workflow:test", "channel": "test", "chat_id": "c1"},
    )
    task_runtime = executor.runtime
    tasks = [
        ParallelTask(
            goal_id=goal.goal_id,
            task_id="plan",
            description="Plan",
            prompt="plan",
        ),
        ParallelTask(
            goal_id=goal.goal_id,
            task_id="verify",
            description="Verify",
            prompt="verify",
            depends_on=["plan"],
        ),
    ]

    results = await task_runtime.execute(goal, tasks)

    assert results["plan"].status == TaskStatus.COMPLETED
    assert results["verify"].status == TaskStatus.COMPLETED
    assert runtime.calls == [("plan", "test-model"), ("verify", "test-model")]
    assert executor._results["plan"].status == TaskStatus.COMPLETED
    assert executor._results["verify"].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_workflow_cancel_marks_run_and_stops_active_task(tmp_path) -> None:
    executor = FakeParallelExecutor({"slow": []})
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)
    workflow = WorkflowDefinition(
        workflow_id="cancelable",
        name="Cancelable",
        description="cancel test",
        steps=[WorkflowStep(step_id="slow", name="Slow", prompt_template="slow")],
    )
    goal = Goal(goal_id="goal-3", description="cancel", success_criteria=[])
    run = engine.create_run(workflow, goal, {})

    event = asyncio.Event()

    async def _slow_task() -> None:
        await event.wait()

    task = asyncio.create_task(_slow_task())
    engine.register_active_run(run.run_id, task)

    cancelled = engine.request_cancel(run.run_id)

    assert cancelled is True
    assert task.cancelled() is False
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = engine.load_run(run.run_id)
    assert stored is not None
    assert stored.cancel_requested is True


@pytest.mark.asyncio
async def test_workflow_save_emits_live_run_update_payload(tmp_path) -> None:
    emitted: list[dict[str, object]] = []
    event = asyncio.Event()

    async def on_run_update(payload: dict[str, object]) -> None:
        emitted.append(payload)
        event.set()

    engine = WorkflowEngine(
        parallel_executor=FakeParallelExecutor({}),
        storage_dir=tmp_path,
        on_run_update=on_run_update,
    )
    workflow = WorkflowDefinition(
        workflow_id="live-updates",
        name="Live updates",
        description="live payload test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan")],
    )
    goal = Goal(
        goal_id="goal-live",
        description="live update goal",
        success_criteria=[],
        metadata={"session_key": "websocket:chat-live"},
    )

    run = engine.create_run(workflow, goal, {"topic": "dashboard"})
    await asyncio.wait_for(event.wait(), timeout=1)

    assert emitted
    payload = emitted[-1]
    assert payload["run_id"] == run.run_id
    assert payload["workflow_id"] == "live-updates"
    assert payload["goal_id"] == "goal-live"
    assert payload["session_key"] == "websocket:chat-live"
    assert payload["state"] == WorkflowState.PENDING
    assert payload["step_count"] == 1
    assert payload["completed_steps"] == 0
    assert payload["status_history"] == [
        {
            "state": WorkflowState.PENDING,
            "detail": "Run created",
            "at": run.status_history[0]["timestamp"],
        }
    ]
    assert payload["step_states"] == [
        {
            "step_id": "plan",
            "name": "Plan",
            "state": WorkflowState.PENDING,
            "attempts": 0,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "output": None,
            "skipped_reason": None,
        }
    ]


@pytest.mark.asyncio
async def test_workflow_engine_emit_wrappers_delegate_to_llm3_workflow_service(tmp_path) -> None:
    emitted_updates: list[dict[str, object]] = []
    emitted_steps: list[tuple[str, dict[str, object]]] = []
    update_event = asyncio.Event()

    async def on_run_update(payload: dict[str, object]) -> None:
        emitted_updates.append(payload)
        update_event.set()

    async def on_step_event(run, step, event_type: str, payload: dict[str, object]) -> None:
        emitted_steps.append((event_type, payload))

    engine = WorkflowEngine(
        parallel_executor=FakeParallelExecutor({}),
        storage_dir=tmp_path,
        on_run_update=on_run_update,
        on_step_event=on_step_event,
    )

    engine._emit_run_update({"run_id": "run-1", "state": "running"})
    await asyncio.wait_for(update_event.wait(), timeout=1)
    await engine._emit_step_event(
        SimpleNamespace(run_id="run-1"),
        None,
        "workflow_goal_validated",
        {"validation_id": "val-1"},
    )

    assert emitted_updates == [{"run_id": "run-1", "state": "running"}]
    assert emitted_steps == [("workflow_goal_validated", {"validation_id": "val-1"})]


@pytest.mark.asyncio
async def test_dynamic_workflow_persists_semantic_checkpoint(tmp_path, monkeypatch) -> None:
    checkpoint_store = CheckpointStore(storage_dir=tmp_path / "checkpoints")
    monkeypatch.setattr("teai_builder.agent.workflow_engine.get_checkpoint_store", lambda: checkpoint_store)
    executor = FakeParallelExecutor(
        {
            "plan": [TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done"})],
        }
    )
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path / "runs")
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="checkpointed",
        name="Checkpointed",
        description="checkpoint test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan", checkpoint_after=True)],
    )
    goal = Goal(
        goal_id="goal-4",
        description="checkpoint",
        success_criteria=[],
        metadata={"session_key": "cli:direct"},
    )

    run = await dynamic.execute(workflow, goal, {})

    checkpoints = checkpoint_store.list_for_session("cli:direct")
    assert run.state == WorkflowState.COMPLETED
    assert checkpoints
    latest = checkpoint_store.latest_for_session("cli:direct")
    assert latest is not None
    assert latest.metadata["kind"] == "workflow"
    assert latest.metadata["workflow_id"] == "checkpointed"
    assert latest.metadata["run_id"] == run.run_id
    assert latest.metadata["step_id"] == "plan"


@pytest.mark.asyncio
async def test_dynamic_workflow_emits_retry_and_checkpoint_events(tmp_path, monkeypatch) -> None:
    checkpoint_store = CheckpointStore(storage_dir=tmp_path / "checkpoints")
    monkeypatch.setattr("teai_builder.agent.workflow_engine.get_checkpoint_store", lambda: checkpoint_store)
    executor = FakeParallelExecutor(
        {
            "plan": [
                TaskResult(task_id="plan", status=TaskStatus.FAILED, error="first failure", output={"worker_id": "wrk-1"}),
                TaskResult(task_id="plan", status=TaskStatus.COMPLETED, output={"output": "done", "worker_id": "wrk-2"}),
            ],
        }
    )
    events: list[tuple[str, dict[str, object]]] = []

    async def on_step_event(run, step, event_type: str, payload: dict[str, object]) -> None:
        events.append((event_type, payload))

    engine = WorkflowEngine(
        parallel_executor=executor,
        storage_dir=tmp_path / "runs",
        on_step_event=on_step_event,
    )
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="retry-checkpoint",
        name="Retry Checkpoint",
        description="retry and checkpoint test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan", max_retries=1, checkpoint_after=True)],
    )
    goal = Goal(
        goal_id="goal-retry",
        description="retry test",
        success_criteria=[],
        metadata={"session_key": "cli:direct"},
    )

    run = await dynamic.execute(workflow, goal, {})

    assert run.state == WorkflowState.COMPLETED
    assert executor.calls[0][1]["attempt"] == 1
    assert executor.calls[1][1]["attempt"] == 2
    assert executor.calls[1][1]["retry_of_worker_id"] == "wrk-1"
    assert [event for event, _ in events] == [
        "workflow_step_retry_started",
        "workflow_checkpoint_created",
        "workflow_goal_validated",
    ]
    assert events[0][1]["retry_of_worker_id"] == "wrk-1"
    assert events[1][1]["checkpoint_id"] is not None
    assert events[1][1]["context_budget_pct"] == 1.0
    assert events[2][1]["is_complete"] is True


@pytest.mark.asyncio
async def test_parallel_executor_uses_worker_runtime_for_workflow_tasks(tmp_path) -> None:
    runtime = FakeWorkerRuntime()
    events: list[tuple[str, dict[str, object]]] = []

    async def on_task_event(goal: Goal, task, event_type: str, payload: dict[str, object]) -> None:
        events.append((event_type, payload))

    executor = ParallelExecutor(
        subagent_manager=SimpleNamespace(model="test-model"),
        bus=MessageBus(),
        worker_runtime=runtime,
        on_task_event=on_task_event,
    )
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)
    workflow = WorkflowDefinition(
        workflow_id="worker-runtime",
        name="Worker runtime",
        description="worker runtime test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan {topic}")],
    )
    goal = Goal(
        goal_id="goal-worker",
        description="worker runtime goal",
        success_criteria=[],
        metadata={"session_key": "workflow:test", "channel": "test", "chat_id": "c1"},
    )

    run = await engine.run(workflow, goal, {"topic": "phase4"})

    assert run.state == WorkflowState.COMPLETED
    assert run.step_results["plan"]["output"] == "completed: plan phase4"
    assert runtime.calls == [("plan phase4", "test-model")]
    assert [event for event, _ in events] == ["worker_task_started", "worker_task_finished"]
    assert events[-1][1]["worker_id"] == "wrk-1"


def test_workflow_engine_defaults_to_llm3_task_scheduler(tmp_path) -> None:
    executor = FakeParallelExecutor({})
    engine = WorkflowEngine(parallel_executor=executor, storage_dir=tmp_path)

    assert isinstance(engine.task_scheduler, LLM3TaskScheduler)


def test_workflow_engine_defaults_to_llm3_workflow_service(tmp_path) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)

    assert isinstance(engine.workflow_service, LLM3WorkflowService)


def test_workflow_engine_reexports_llm3_workflow_models() -> None:
    assert WorkflowDefinition is workflow_models.WorkflowDefinition
    assert WorkflowStep is workflow_models.WorkflowStep
    assert WorkflowState is workflow_models.WorkflowState


def test_workflow_engine_reexports_llm3_workflow_support() -> None:
    assert ContextCompactor is LLM3ContextCompactor
    assert SemanticCheckpointTrigger is LLM3SemanticCheckpointTrigger


def test_workflow_engine_reexports_llm3_dynamic_workflow_executor() -> None:
    assert DynamicWorkflowExecutor is LLM3DynamicWorkflowExecutor


def test_workflow_engine_registry_wrappers_delegate_to_llm3_workflow_library(tmp_path) -> None:
    workflow_id = "llm3-wrapper-registry-test"
    definition = WorkflowDefinition(
        workflow_id=workflow_id,
        name="Registry Wrapper",
        description="registry wrapper test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan")],
    )
    register_workflow(definition)

    workflow_path = tmp_path / "loaded-workflow.json"
    workflow_path.write_text(
        """
{
  "workflow_id": "llm3-loaded-registry-test",
  "name": "Loaded Registry Wrapper",
  "description": "loaded registry wrapper test",
  "steps": [
    {
      "step_id": "verify",
      "name": "Verify",
      "prompt_template": "verify"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    load_workflows_from_dir(tmp_path)

    assert get_workflow(workflow_id) is workflow_library.get_workflow(workflow_id)
    assert get_workflow("llm3-loaded-registry-test") is workflow_library.get_workflow(
        "llm3-loaded-registry-test"
    )
    assert any(
        workflow.workflow_id == "llm3-loaded-registry-test"
        for workflow in list_workflows()
    )


def test_app_build_builtin_starts_with_surface_planner_step() -> None:
    from teai_builder.agent.workflows import _register_builtins

    _register_builtins()
    workflow = get_workflow("app_build_v1")

    assert workflow is not None
    assert workflow.steps[0].step_id == "surface_plan"
    assert workflow.steps[0].metadata["auto_tool"] == "plan_product_surfaces"
    assert workflow.steps[1].step_id == "brief"
    assert workflow.steps[1].depends_on == ["surface_plan"]
    assert workflow.steps[4].step_id == "tasks"
    assert workflow.steps[5].step_id == "scaffold"
    assert workflow.steps[5].metadata["auto_tool"] == "execute_scaffold_plan"
    assert workflow.input_schema["properties"]["user_request"]["type"] == "string"
    assert "user_request" in workflow.input_schema["required"]


@pytest.mark.asyncio
async def test_dynamic_workflow_auto_tool_step_feeds_following_auto_tool(tmp_path) -> None:
    recorder = AutoToolRecorder()
    engine = WorkflowEngine(
        parallel_executor=FakeParallelExecutor({}),
        storage_dir=tmp_path,
        execute_tool=recorder,
    )
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)
    workflow = WorkflowDefinition(
        workflow_id="auto-tool-flow",
        name="Auto tool flow",
        description="auto tool chaining",
        steps=[
            WorkflowStep(
                step_id="surface_plan",
                name="Surface plan",
                prompt_template="ignored",
                metadata={
                    "auto_tool": "plan_product_surfaces",
                    "auto_tool_args": {
                        "project_name": "{project_name}",
                        "platform_hint": "{platform}",
                    },
                    "auto_tool_args_from_variables": {"user_request": "user_request"},
                    "auto_tool_defaults": {"user_request": "Build {project_name} for {platform}."},
                },
            ),
            WorkflowStep(
                step_id="scaffold",
                name="Scaffold",
                prompt_template="ignored",
                depends_on=["surface_plan"],
                metadata={
                    "auto_tool": "execute_scaffold_plan",
                    "auto_tool_args": {"project_name": "{project_name}"},
                    "auto_tool_args_from_results": {"planner_result": "surface_plan"},
                },
            ),
        ],
    )
    goal = Goal(goal_id="goal-auto-tool", description="auto tool", success_criteria=[])

    run = await dynamic.execute(
        workflow,
        goal,
        {"project_name": "cursor-suite", "platform": "desktop", "user_request": "Build Cursor with website and accounts."},
    )

    assert run.state == WorkflowState.COMPLETED
    assert [name for name, _ in recorder.calls] == ["plan_product_surfaces", "execute_scaffold_plan"]
    assert recorder.calls[1][1]["planner_result"]["primary_platform"] == "desktop"
    assert run.step_results["surface_plan"]["primary_platform"] == "desktop"
    assert run.step_results["scaffold"]["executed"] is True


@pytest.mark.asyncio
async def test_parallel_runtime_falls_back_to_dynamic_for_auto_tool_steps(tmp_path) -> None:
    recorder = AutoToolRecorder()
    engine = WorkflowEngine(
        parallel_executor=FakeParallelExecutor({}),
        storage_dir=tmp_path,
        execute_tool=recorder,
    )
    workflow = WorkflowDefinition(
        workflow_id="auto-tool-parallel",
        name="Auto tool parallel",
        description="parallel fallback",
        steps=[
            WorkflowStep(
                step_id="surface_plan",
                name="Surface plan",
                prompt_template="ignored",
                metadata={
                    "auto_tool": "plan_product_surfaces",
                    "auto_tool_args": {"project_name": "{project_name}", "platform_hint": "{platform}"},
                    "auto_tool_defaults": {"user_request": "Build {project_name} for {platform}."},
                },
            ),
        ],
    )
    goal = Goal(goal_id="goal-auto-parallel", description="auto parallel", success_criteria=[])

    run = await engine.run(workflow, goal, {"project_name": "demo-app", "platform": "desktop"})

    assert run.state == WorkflowState.COMPLETED
    assert recorder.calls[0][0] == "plan_product_surfaces"
    assert run.step_results["surface_plan"]["primary_platform"] == "desktop"


def test_workflow_engine_helper_wrappers_delegate_to_llm3_workflow_service(tmp_path) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)
    workflow = WorkflowDefinition(
        workflow_id="helpers",
        name="Helpers",
        description="helper wrapper test",
        steps=[
            WorkflowStep(
                step_id="plan",
                name="Plan",
                prompt_template="plan {topic}",
                continue_on_error=True,
                run_if="needs_plan",
                metadata={"role": "planner"},
            ),
        ],
    )
    goal = Goal(goal_id="goal-helpers", description="helpers", success_criteria=[])

    task_map = engine._build_task_map(workflow, goal, {"topic": "phase", "needs_plan": True})

    assert task_map["plan"].prompt == "plan phase"
    assert task_map["plan"].metadata["workflow_step"] is True
    assert task_map["plan"].metadata["continue_on_error"] is True
    assert task_map["plan"].metadata["run_if"] == "needs_plan"
    assert task_map["plan"].metadata["role"] == "planner"


def test_workflow_engine_serialization_wrappers_delegate_to_llm3_workflow_service(tmp_path) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)
    workflow = WorkflowDefinition(
        workflow_id="serialize",
        name="Serialize",
        description="serialization wrapper test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan {topic}")],
    )
    goal = Goal(goal_id="goal-serialize", description="serialize", success_criteria=[])
    run = engine.create_run(workflow, goal, {"topic": "phase"})

    step_payload = engine._step_run_to_dict(run.step_states["plan"])
    restored_step = engine._step_run_from_dict(step_payload)
    run_payload = engine._run_to_dict(run)
    restored_run = engine._run_from_dict(run_payload)

    assert step_payload["step_id"] == "plan"
    assert restored_step.step_id == "plan"
    assert run_payload["workflow_id"] == "serialize"
    assert restored_run.workflow_id == "serialize"
    assert restored_run.metadata["variables"] == {"topic": "phase"}


def test_dynamic_workflow_executor_wraps_llm3_runtime(tmp_path) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)
    dynamic = DynamicWorkflowExecutor(workflow_engine=engine)

    assert isinstance(dynamic.runtime, LLM3DynamicWorkflowRuntime)
    assert dynamic.runtime.workflow_service is engine.workflow_service


def test_workflow_engine_uses_llm3_workflow_host(tmp_path) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)

    assert isinstance(engine.workflow_host, LLM3WorkflowHost)
    assert engine.task_scheduler is engine.workflow_host.task_scheduler
    assert engine.goal_validator is engine.workflow_host.goal_validator
    assert engine.semantic_checkpoint_trigger is engine.workflow_host.semantic_checkpoint_trigger


def test_list_saved_runs_uses_storage_service_without_workflow_engine(tmp_path, monkeypatch) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)
    workflow = WorkflowDefinition(
        workflow_id="saved-runs",
        name="Saved Runs",
        description="saved runs test",
        steps=[WorkflowStep(step_id="plan", name="Plan", prompt_template="plan {topic}")],
    )
    goal = Goal(
        goal_id="goal-saved-runs",
        description="saved runs",
        success_criteria=[],
        metadata={"session_key": "websocket:test"},
    )
    engine.create_run(workflow, goal, {"topic": "phase"})

    def _boom(*args, **kwargs):
        raise AssertionError("WorkflowEngine should not be constructed for storage-only reads")

    monkeypatch.setattr("teai_builder.agent.workflow_engine.WorkflowEngine", _boom)

    runs = list_saved_runs(session_key="websocket:test", limit=10, storage_dir=tmp_path)

    assert [run.workflow_id for run in runs] == ["saved-runs"]


def test_workflow_engine_wraps_llm3_parallel_runtime(tmp_path) -> None:
    engine = WorkflowEngine(parallel_executor=FakeParallelExecutor({}), storage_dir=tmp_path)

    assert isinstance(engine.parallel_runtime, LLM3ParallelWorkflowRuntime)


def test_parallel_executor_wraps_llm3_parallel_task_runtime() -> None:
    executor = ParallelExecutor(
        subagent_manager=SimpleNamespace(model="test-model"),
        bus=MessageBus(),
    )

    assert isinstance(executor.runtime, LLM3ParallelTaskRuntime)
