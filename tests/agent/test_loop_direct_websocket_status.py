import asyncio
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

import pytest

from teai_builder.agent.loop import AgentLoop
from teai_builder.bus.events import OutboundMessage
from teai_builder.bus.queue import MessageBus
from teai_builder.providers.base import GenerationSettings, LLMResponse
from teai_builder.session.webui_turns import WebuiTurnCoordinator


def _make_loop(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    response = LLMResponse(content="done", tool_calls=[])
    provider.chat_with_retry = AsyncMock(return_value=response)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)

    with patch("teai_builder.agent.loop.WorkflowEngine"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
        )
    WebuiTurnCoordinator(
        bus=bus,
        sessions=loop.sessions,
        schedule_background=lambda coro: loop._schedule_background(coro),
    ).subscribe(loop.runtime_events)
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_process_direct_websocket_clears_run_status(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    response = await loop.process_direct(
        "deliver reminder",
        session_key="cron:reminder-1",
        channel="websocket",
        chat_id="chat-1",
    )

    assert response is not None
    assert response.content == "done"

    events = []
    while loop.bus.outbound_size:
        events.append(await loop.bus.consume_outbound())

    statuses = [
        event.metadata
        for event in events
        if event.metadata.get("_goal_status") is True
    ]
    assert [status["goal_status"] for status in statuses] == ["running", "idle"]
    assert isinstance(statuses[0].get("started_at"), float)
    assert "started_at" not in statuses[1]


@pytest.mark.asyncio
async def test_process_direct_reuses_existing_session_lock(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    session_key = "api:fixed"
    lock = loop._session_locks.setdefault(session_key, asyncio.Lock())
    await lock.acquire()
    entered = asyncio.Event()

    async def _process_message(msg, **_kwargs):
        entered.set()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = _process_message
    task = asyncio.create_task(loop.process_direct("direct", session_key=session_key))
    try:
        await asyncio.sleep(0)
        assert not entered.is_set()

        lock.release()
        response = await asyncio.wait_for(task, timeout=1.0)

        assert entered.is_set()
        assert response is not None
        assert response.content == "direct"
    finally:
        if lock.locked():
            lock.release()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_process_direct_marks_requests_for_inline_subagents(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    seen = {}

    async def _process_message(msg, **_kwargs):
        seen["metadata"] = dict(msg.metadata or {})
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="ok")

    loop._process_message = _process_message

    response = await loop.process_direct("direct", session_key="cli:test")

    assert response is not None
    assert response.content == "ok"
    assert seen["metadata"]["_inline_subagents"] is True
