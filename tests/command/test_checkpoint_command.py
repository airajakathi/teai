from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from teai_builder.agent.checkpoint import Checkpoint, CheckpointStore
from teai_builder.bus.events import InboundMessage
from teai_builder.command.builtin import cmd_checkpoint
from teai_builder.command.router import CommandContext


class FakeSession:
    def __init__(self, key: str = "cli:direct") -> None:
        self.key = key
        self.messages = [{"role": "user", "content": "hello"}]

    def get_history(self, max_messages: int = 0):
        return list(self.messages)


def _make_ctx(args: str, session: FakeSession | None = None) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=f"/checkpoint {args}".strip())
    session = session or FakeSession()
    sessions = SimpleNamespace(
        get_or_create=lambda key: session,
        save=lambda value: None,
    )
    loop = SimpleNamespace(max_iterations=7, sessions=sessions)
    return CommandContext(msg=msg, session=session, key=session.key, raw=msg.content, args=args, loop=loop)


@pytest.mark.asyncio
async def test_checkpoint_rebuild_and_delete(monkeypatch, tmp_path) -> None:
    store = CheckpointStore(storage_dir=tmp_path)
    monkeypatch.setattr("teai_builder.agent.checkpoint.get_checkpoint_store", lambda: store)
    checkpoint = Checkpoint(
        checkpoint_id="cp-1",
        session_key="cli:direct",
        created_at=time.time(),
        context_budget_pct=0.4,
        state={"workflow_id": "app_build_v1", "run_id": "run-1", "step_id": "plan"},
        messages=[],
        metadata={
            "kind": "workflow",
            "workflow_id": "app_build_v1",
            "run_id": "run-1",
            "step_id": "plan",
            "result_keys": ["plan"],
        },
    )
    store.save(checkpoint)

    rebuild = await cmd_checkpoint(_make_ctx("rebuild cp-1"))
    deleted = await cmd_checkpoint(_make_ctx("delete cp-1"))

    assert "Checkpoint: `cp-1`" in rebuild.content
    assert "Resume the workflow with `/workflow resume run-1`" in rebuild.content
    assert "Deleted checkpoint `cp-1`." in deleted.content
    assert store.load("cli:direct", "cp-1") is None


@pytest.mark.asyncio
async def test_checkpoint_list_shows_workflow_metadata(monkeypatch, tmp_path) -> None:
    store = CheckpointStore(storage_dir=tmp_path)
    monkeypatch.setattr("teai_builder.agent.checkpoint.get_checkpoint_store", lambda: store)
    store.save(
        Checkpoint(
            checkpoint_id="cp-2",
            session_key="cli:direct",
            created_at=time.time(),
            context_budget_pct=0.5,
            state={"workflow_id": "app_build_v1", "step_id": "verify"},
            messages=[],
            metadata={"kind": "workflow", "workflow_id": "app_build_v1", "step_id": "verify"},
        )
    )

    out = await cmd_checkpoint(_make_ctx(""))

    assert "## Checkpoints" in out.content
    assert "workflow `app_build_v1`" in out.content
    assert "step `verify`" in out.content
