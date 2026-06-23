"""Tests for subagent tool registration and wiring."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teai_builder.agent.llm3.worker_runtime import WorkerRuntime
from teai_builder.config.schema import AgentDefaults

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_subagent_exec_tool_receives_allowed_env_keys(tmp_path):
    """allowed_env_keys from ExecToolConfig must be forwarded to the subagent's ExecTool."""
    from teai_builder.agent.subagent import SubagentManager, SubagentStatus
    from teai_builder.agent.tools.shell import ExecToolConfig
    from teai_builder.bus.queue import MessageBus
    from teai_builder.config.schema import ToolsConfig

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        tools_config=ToolsConfig(exec=ExecToolConfig(allowed_env_keys=["GOPATH", "JAVA_HOME"])),
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        exec_tool = spec.tools.get("exec")
        assert exec_tool is not None
        assert exec_tool.allowed_env_keys == ["GOPATH", "JAVA_HOME"]
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_subagent_uses_configured_max_iterations(tmp_path):
    """Subagents should honor the configured tool-iteration limit."""
    from teai_builder.agent.subagent import SubagentManager, SubagentStatus
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_iterations=37,
    )
    mgr._announce_result = AsyncMock()

    async def fake_run(spec):
        assert spec.max_iterations == 37
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    status = SubagentStatus(
        task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()
    )
    await mgr._run_subagent(
        "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"}, status
    )

    mgr.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_spawn_forwards_temperature_to_run_spec(tmp_path):
    """A temperature passed to spawn() should reach the AgentRunSpec."""
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    seen = {}

    async def fake_run(spec):
        seen["temperature"] = spec.temperature
        return SimpleNamespace(
            stop_reason="done", final_content="done", error=None, tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    await mgr.spawn(task="do task", temperature=0.9)
    await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)

    assert seen["temperature"] == 0.9


@pytest.mark.asyncio
async def test_spawn_tool_rejects_when_at_concurrency_limit(tmp_path):
    """SpawnTool should return an error string when the concurrency limit is reached."""
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.agent.tools.spawn import SpawnTool
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    mgr._announce_result = AsyncMock()

    # Block the first subagent so it stays "running"
    release = asyncio.Event()

    async def fake_run(spec):
        await release.wait()
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
        )

    mgr.runner.run = AsyncMock(side_effect=fake_run)

    from teai_builder.agent.tools.context import RequestContext

    tool = SpawnTool(mgr)
    tool.set_context(RequestContext(channel="test", chat_id="c1", session_key="test:c1"))

    # First spawn succeeds
    result = await tool.execute(task="first task")
    assert "started" in result

    # Second spawn should be rejected (default limit is 1)
    result = await tool.execute(task="second task")
    assert "Cannot spawn subagent" in result
    assert "concurrency limit reached" in result

    # Release the first subagent
    release.set()
    # Allow cleanup
    await asyncio.gather(*mgr._running_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_runtime_wraps_subagent_spawn_worker(tmp_path):
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    runtime = WorkerRuntime(mgr)
    spawn_mock = AsyncMock(
        return_value={
            "worker_id": "wrk-1",
            "label": "label",
            "launch_message": "Subagent [label] started (id: wrk-1). I'll notify you when it completes.",
        }
    )

    with patch.object(mgr, "spawn_worker", spawn_mock):
        result = await runtime.spawn(
            spec=SimpleNamespace(
                task="do task",
                label="label",
                role=None,
                model=None,
                model_preset=None,
                origin_channel="test",
                origin_chat_id="c1",
                session_key="test:c1",
                origin_message_id=None,
                temperature=None,
                workspace_scope=None,
                owner_turn_id="turn-1",
                owner_request_id="req-1",
            )
        )

    assert result.worker_id == "wrk-1"
    assert result.label == "label"
    assert "started" in result.launch_message
    assert spawn_mock.await_args.kwargs["owner_turn_id"] == "turn-1"
    assert spawn_mock.await_args.kwargs["owner_request_id"] == "req-1"
    assert "on_event" in spawn_mock.await_args.kwargs


@pytest.mark.asyncio
async def test_worker_runtime_wraps_inline_run_worker(tmp_path):
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    runtime = WorkerRuntime(mgr)

    with patch.object(
        mgr,
        "run_worker",
        AsyncMock(
            return_value={
                "worker_id": "wrk-inline-1",
                "label": "inline",
                "status": "completed",
                "final_output": "done",
                "stop_reason": "done",
                "tool_events": [{"name": "read", "status": "ok"}],
                "usage": {"input_tokens": 10},
            }
        ),
    ):
        result = await runtime.run(
            spec=SimpleNamespace(
                task="do task",
                label="inline",
                role=None,
                model=None,
                model_preset=None,
                origin_channel="test",
                origin_chat_id="c1",
                session_key="test:c1",
                origin_message_id=None,
                temperature=None,
                workspace_scope=None,
            )
        )

    assert result.worker_id == "wrk-inline-1"
    assert result.status == "completed"
    assert result.final_output == "done"
    assert result.tool_events == [{"name": "read", "status": "ok"}]


@pytest.mark.asyncio
async def test_spawn_tool_passes_llm3_turn_metadata_to_worker_runtime() -> None:
    from teai_builder.agent.tools.context import RequestContext
    from teai_builder.agent.tools.spawn import SpawnTool

    runtime = MagicMock()
    runtime.get_running_count.return_value = 0
    runtime.max_concurrent_workers = 3
    runtime.spawn = AsyncMock(
        return_value=SimpleNamespace(
            worker_id="wrk-1",
            label="worker",
            launch_message="started",
        )
    )

    tool = SpawnTool(manager=None, worker_runtime=runtime)
    tool.set_context(
        RequestContext(
            channel="telegram",
            chat_id="c1",
            session_key="telegram:c1",
            metadata={"_llm3_turn_id": "turn-1", "_llm3_request_id": "req-1"},
        )
    )

    result = await tool.execute(task="do task", label="worker")

    assert result == "started"
    spec = runtime.spawn.await_args.args[0]
    assert spec.owner_turn_id == "turn-1"
    assert spec.owner_request_id == "req-1"


@pytest.mark.asyncio
async def test_spawn_tool_runs_inline_worker_for_direct_requests() -> None:
    from teai_builder.agent.tools.context import RequestContext
    from teai_builder.agent.tools.spawn import SpawnTool

    manager = MagicMock()
    manager.run_worker = AsyncMock(
        return_value={
            "worker_id": "wrk-inline-1",
            "label": "worker",
            "status": "completed",
            "final_output": "proof complete",
        }
    )
    manager.spawn = AsyncMock()

    tool = SpawnTool(manager=manager)
    tool.set_context(
        RequestContext(
            channel="cli",
            chat_id="direct",
            session_key="cli:direct",
            metadata={"_inline_subagents": True},
        )
    )

    result = await tool.execute(task="do task", label="worker")

    assert result == "Subagent [worker] completed inline.\n\nproof complete"
    manager.run_worker.assert_awaited_once()
    manager.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_subagent_announce_result_includes_llm3_owner_metadata(tmp_path):
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    bus.publish_inbound = AsyncMock()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    await mgr._announce_result(
        "wrk-1",
        "worker",
        "do task",
        "done",
        {"channel": "telegram", "chat_id": "c1", "session_key": "telegram:c1"},
        "ok",
        owner_turn_id="turn-1",
        owner_request_id="req-1",
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.metadata["subagent_task_id"] == "wrk-1"
    assert msg.metadata["owner_turn_id"] == "turn-1"
    assert msg.metadata["owner_request_id"] == "req-1"
    assert msg.metadata["origin_channel"] == "telegram"
    assert msg.metadata["origin_chat_id"] == "c1"


def test_subagent_default_max_concurrent_matches_agent_defaults(tmp_path):
    """Direct SubagentManager construction should use the agent default concurrency limit."""
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    assert mgr.max_concurrent_subagents == AgentDefaults().max_concurrent_subagents


def test_subagent_default_max_iterations_matches_agent_defaults(tmp_path):
    """Direct SubagentManager construction should use the agent default limit."""
    from teai_builder.agent.subagent import SubagentManager
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    assert mgr.max_iterations == AgentDefaults().max_tool_iterations


def test_agent_loop_passes_max_iterations_to_subagents(tmp_path):
    """AgentLoop's configured limit should be shared with spawned subagents."""
    from teai_builder.agent.loop import AgentLoop
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            max_iterations=42,
        )

    assert loop.subagents.max_iterations == 42


@pytest.mark.asyncio
async def test_agent_loop_syncs_updated_max_iterations_before_run(tmp_path):
    """Runtime max_iterations changes should be reflected before tool execution."""
    from teai_builder.agent.loop import AgentLoop
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            max_iterations=42,
        )
    loop.tools.get_definitions = MagicMock(return_value=[])

    async def fake_run(spec):
        assert spec.max_iterations == 55
        assert loop.subagents.max_iterations == 55
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_run)
    loop.max_iterations = 55

    await loop._run_agent_loop([])

    loop.runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_drain_pending_blocks_while_subagents_running(tmp_path):
    """_drain_pending should block when no messages are available but sub-agents are still running."""
    from teai_builder.agent.loop import AgentLoop
    from teai_builder.bus.events import InboundMessage
    from teai_builder.bus.queue import MessageBus
    from teai_builder.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
    session = Session(key="test:drain-block")
    injection_callback = None

    # Capture the injection_callback that _run_agent_loop creates
    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback

        # Simulate: first call to injection_callback should block because
        # sub-agents are running and no messages are in the queue yet.
        # We'll resolve this from a concurrent task.
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    # Register a running sub-agent in the SubagentManager for this session
    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-drain-1")
    loop.subagents._running_tasks["sub-drain-1"] = hang_task

    # Run _run_agent_loop — this defines the _drain_pending closure
    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # Now test the callback directly
    # With sub-agents running and an empty queue, it should block
    drain_task = asyncio.create_task(injection_callback())

    # Let the task enter the blocking queue wait.
    await asyncio.sleep(0)

    # Should still be running (blocked on pending_queue.get())
    assert not drain_task.done(), "drain should block while sub-agents are running"

    # Now put a message in the queue (simulating sub-agent completion)
    await pending_queue.put(InboundMessage(
        sender_id="subagent",
        channel="test",
        chat_id="c1",
        content="Sub-agent result",
        media=None,
        metadata={},
    ))

    # Should unblock and return results
    results = await asyncio.wait_for(drain_task, timeout=2.0)
    assert len(results) >= 1
    assert results[0]["role"] == "user"
    assert "Sub-agent result" in str(results[0]["content"])

    # Cleanup
    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_drain_pending_no_block_when_no_subagents(tmp_path):
    """_drain_pending should not block when no sub-agents are running."""
    from teai_builder.agent.loop import AgentLoop
    from teai_builder.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=None,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # With no sub-agents and empty queue, should return immediately
    results = await asyncio.wait_for(injection_callback(), timeout=1.0)
    assert results == []


@pytest.mark.asyncio
async def test_drain_pending_timeout(tmp_path):
    """_drain_pending should return empty after timeout when sub-agents hang."""
    from teai_builder.agent.loop import AgentLoop
    from teai_builder.bus.queue import MessageBus
    from teai_builder.session.manager import Session

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    pending_queue: asyncio.Queue = asyncio.Queue()
    session = Session(key="test:drain-timeout")
    injection_callback = None

    async def fake_runner_run(spec):
        nonlocal injection_callback
        injection_callback = spec.injection_callback
        return SimpleNamespace(
            stop_reason="done",
            final_content="done",
            error=None,
            tool_events=[],
            messages=[],
            usage={},
            had_injections=False,
            tools_used=[],
        )

    loop.runner.run = AsyncMock(side_effect=fake_runner_run)

    # Register a "running" sub-agent that will never complete
    async def _hang_forever():
        await asyncio.Event().wait()

    hang_task = asyncio.create_task(_hang_forever())
    loop.subagents._session_tasks.setdefault(session.key, set()).add("sub-timeout-1")
    loop.subagents._running_tasks["sub-timeout-1"] = hang_task

    await loop._run_agent_loop(
        [{"role": "user", "content": "test"}],
        session=session,
        channel="test",
        chat_id="c1",
        pending_queue=pending_queue,
    )

    assert injection_callback is not None

    # Patch the timeout path without leaking the queue.get() coroutine.
    async def _timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    with patch("teai_builder.agent.loop.asyncio.wait_for", side_effect=_timeout):
        results = await injection_callback()
        assert results == []

    # Cleanup
    hang_task.cancel()
    try:
        await hang_task
    except asyncio.CancelledError:
        pass
