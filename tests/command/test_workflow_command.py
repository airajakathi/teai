from __future__ import annotations

import asyncio
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teai_builder.agent.workflows import _register_builtins
from teai_builder.bus.events import InboundMessage
from teai_builder.command.builtin import cmd_workflow
from teai_builder.command.router import CommandContext


class FakeWorkflowEngine:
    def __init__(self) -> None:
        self.runs: OrderedDict[str, SimpleNamespace] = OrderedDict()
        self._counter = 0
        self._active: dict[str, asyncio.Task[None]] = {}

    def create_run(self, workflow, goal, variables, *, executor: str = "dynamic"):
        self._counter += 1
        run = SimpleNamespace(
            run_id=f"{workflow.workflow_id}:run-{self._counter}",
            workflow_id=workflow.workflow_id,
            goal_id=goal.goal_id,
            state="pending",
            current_step=None,
            step_results={},
            step_states=OrderedDict(
                (
                    step.step_id,
                    SimpleNamespace(
                        step_id=step.step_id,
                        name=step.name,
                        state="pending",
                        attempts=0,
                        error=None,
                        skipped_reason=None,
                    ),
                )
                for step in workflow.steps
            ),
            error=None,
            metadata={"goal": {"goal_id": goal.goal_id}, "variables": dict(variables)},
        )
        self.runs[run.run_id] = run
        return run

    def register_active_run(self, run_id: str, task: asyncio.Task[None]) -> None:
        self._active[run_id] = task
        task.add_done_callback(lambda _: self._active.pop(run_id, None))

    def is_run_active(self, run_id: str) -> bool:
        task = self._active.get(run_id)
        return task is not None and not task.done()

    def load_run(self, run_id: str):
        return self.runs.get(run_id)

    def list_runs(self, limit: int = 10):
        return list(self.runs.values())[:limit]

    def request_cancel(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        if run is None:
            return False
        run.state = "cancelled"
        task = self._active.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        return True

    @staticmethod
    def goal_from_run(run):
        return SimpleNamespace(goal_id=run.goal_id, description="resumed goal", success_criteria=[], metadata={})

    @staticmethod
    def variables_from_run(run):
        return dict(run.metadata.get("variables", {}))


def _make_ctx(raw: str, *, args: str = "") -> tuple[CommandContext, list[asyncio.Task[None]], AsyncMock, FakeWorkflowEngine]:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    scheduled: list[asyncio.Task[None]] = []
    bus = SimpleNamespace(publish_outbound=AsyncMock())
    workflow_engine = FakeWorkflowEngine()

    recovery_starts: list[tuple[str, str]] = []
    recovery_completions: list[tuple[str, str]] = []
    graph_syncs: list[tuple[str, str]] = []
    runtime_starts: list[str] = []
    runtime_resumes: list[str] = []
    runtime_loads: list[str] = []
    runtime_lists: list[tuple[str | None, int]] = []
    runtime_cancels: list[str] = []
    runtime_active_checks: list[str] = []

    async def _execute(workflow, goal, variables, *, run=None):
        active_run = run or workflow_engine.create_run(workflow, goal, variables)
        active_run.state = "completed"
        active_run.step_results = {"research": {}, "verify": {}}
        for step_run in active_run.step_states.values():
            step_run.state = "completed"
            step_run.attempts = 1
        return active_run

    def _start_workflow(*, workflow, goal, variables, on_completed):
        runtime_starts.append(workflow.workflow_id)
        run = workflow_engine.create_run(workflow, goal, variables, executor="dynamic")
        scheduled.append(asyncio.create_task(on_completed(_execute_sync(run), workflow)))
        return SimpleNamespace(run=run)

    def _resume_workflow(*, workflow, run, goal, variables, on_completed):
        runtime_resumes.append(run.run_id)
        graph_syncs.append((workflow.workflow_id, run.run_id))
        recovery_starts.append((run.run_id, "manual_restore"))
        scheduled.append(asyncio.create_task(on_completed(_resume_sync(run), workflow)))
        recovery_completions.append(("rec-1", "completed"))
        return SimpleNamespace(run=run)

    loop = SimpleNamespace(
        workflow_engine=workflow_engine,
        dynamic_workflow=SimpleNamespace(execute=AsyncMock(side_effect=_execute)),
        bus=bus,
        _schedule_background=lambda coro: scheduled.append(asyncio.create_task(coro)) or scheduled[-1],
        sync_llm3_workflow_graph=lambda *, workflow, run, goal: graph_syncs.append((workflow.workflow_id, run.run_id)),
        start_llm3_workflow_recovery=lambda *, run, goal, reason, source_checkpoint_id=None: recovery_starts.append((run.run_id, reason)) or "rec-1",
        complete_llm3_workflow_recovery=lambda recovery_id, *, goal, run, status, summary=None: recovery_completions.append((recovery_id, status)),
        start_llm3_workflow_execution=_start_workflow,
        resume_llm3_workflow_execution=_resume_workflow,
        load_llm3_workflow_run=lambda run_id: runtime_loads.append(run_id) or workflow_engine.load_run(run_id),
        list_llm3_workflow_runs=lambda workflow_id=None, limit=10: runtime_lists.append((workflow_id, limit)) or workflow_engine.list_runs(limit=limit),
        cancel_llm3_workflow_run=lambda run_id: runtime_cancels.append(run_id) or workflow_engine.request_cancel(run_id),
        is_llm3_workflow_active=lambda run_id: runtime_active_checks.append(run_id) or workflow_engine.is_run_active(run_id),
        llm3_workflow_goal_from_run=lambda run: workflow_engine.goal_from_run(run),
        llm3_workflow_variables_from_run=lambda run: workflow_engine.variables_from_run(run),
        _test_recovery_starts=recovery_starts,
        _test_recovery_completions=recovery_completions,
        _test_graph_syncs=graph_syncs,
        _test_runtime_starts=runtime_starts,
        _test_runtime_resumes=runtime_resumes,
        _test_runtime_loads=runtime_loads,
        _test_runtime_lists=runtime_lists,
        _test_runtime_cancels=runtime_cancels,
        _test_runtime_active_checks=runtime_active_checks,
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)
    return ctx, scheduled, bus.publish_outbound, workflow_engine


def _execute_sync(run):
    run.state = "completed"
    run.step_results = {"research": {}, "verify": {}}
    for step_run in run.step_states.values():
        step_run.state = "completed"
        step_run.attempts = 1
    return run


def _resume_sync(run):
    return _execute_sync(run)


@pytest.mark.asyncio
async def test_workflow_command_runs_background_workflow() -> None:
    _register_builtins()
    ctx, scheduled, publish_outbound, workflow_engine = _make_ctx(
        '/workflow app_build_v1 "My App" mobile "Build a polished mobile app for creators"',
        args='app_build_v1 "My App" mobile "Build a polished mobile app for creators"',
    )

    out = await cmd_workflow(ctx)

    assert "Started workflow `app_build_v1`." in out.content
    assert "Run: `app_build_v1:run-1`" in out.content
    assert len(scheduled) == 1
    assert ctx.loop._test_runtime_starts == ["app_build_v1"]

    await scheduled[0]

    publish_outbound.assert_awaited_once()
    message = publish_outbound.await_args.args[0]
    assert "Workflow `app_build_v1` finished with state `completed`." in message.content
    assert "- `research`: `completed`" in message.content
    assert "- `verify`: `completed`" in message.content
    assert workflow_engine.load_run("app_build_v1:run-1").state == "completed"


@pytest.mark.asyncio
async def test_workflow_command_shows_usage_when_required_inputs_missing() -> None:
    _register_builtins()
    ctx, scheduled, publish_outbound, _ = _make_ctx("/workflow app_build_v1", args="app_build_v1")

    out = await cmd_workflow(ctx)

    assert "Workflow `app_build_v1` is available." in out.content
    assert "Usage: `/workflow app_build_v1 <project_name> <platform> <user_request>`" in out.content
    assert scheduled == []
    publish_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_status_lists_recent_runs() -> None:
    _register_builtins()
    ctx, _, _, workflow_engine = _make_ctx("/workflow status", args="status")
    workflow_engine.runs["run-1"] = SimpleNamespace(
        run_id="run-1",
        workflow_id="app_build_v1",
        state="running",
        current_step="research",
        error=None,
        step_states=OrderedDict(),
    )

    out = await cmd_workflow(ctx)

    assert "Recent workflow runs:" in out.content
    assert "- `run-1` `app_build_v1` `running`" in out.content
    assert ctx.loop._test_runtime_lists == [(None, 5)]


@pytest.mark.asyncio
async def test_workflow_cancel_requests_cancellation() -> None:
    _register_builtins()
    ctx, _, _, workflow_engine = _make_ctx("/workflow cancel run-9", args="cancel run-9")
    workflow_engine.runs["run-9"] = SimpleNamespace(
        run_id="run-9",
        workflow_id="app_build_v1",
        state="running",
        goal_id="goal-1",
        current_step=None,
        error=None,
        step_states=OrderedDict(),
        metadata={},
    )

    out = await cmd_workflow(ctx)

    assert "Cancellation requested for workflow run `run-9`." in out.content
    assert workflow_engine.runs["run-9"].state == "cancelled"
    assert ctx.loop._test_runtime_cancels == ["run-9"]


@pytest.mark.asyncio
async def test_workflow_resume_schedules_existing_run() -> None:
    _register_builtins()
    ctx, scheduled, publish_outbound, workflow_engine = _make_ctx("/workflow resume run-2", args="resume run-2")
    workflow_engine.runs["run-2"] = SimpleNamespace(
        run_id="run-2",
        workflow_id="app_build_v1",
        goal_id="goal-2",
        state="failed",
        current_step="verify",
        error="boom",
        step_results={"research": {}},
        step_states=OrderedDict(
            [
                ("research", SimpleNamespace(step_id="research", name="Research", state="completed", attempts=1, error=None, skipped_reason=None)),
                ("verify", SimpleNamespace(step_id="verify", name="Verify", state="failed", attempts=1, error="boom", skipped_reason=None)),
            ]
        ),
        metadata={"variables": {"project_name": "My App", "platform": "mobile"}, "goal": {"goal_id": "goal-2"}},
    )

    out = await cmd_workflow(ctx)

    assert "Resumed workflow `app_build_v1`." in out.content
    assert len(scheduled) == 1

    await scheduled[0]

    publish_outbound.assert_awaited_once()
    assert ctx.loop._test_graph_syncs == [("app_build_v1", "run-2")]
    assert ctx.loop._test_runtime_resumes == ["run-2"]
    assert ctx.loop._test_runtime_loads == ["run-2"]
    assert ctx.loop._test_runtime_active_checks == ["run-2"]
