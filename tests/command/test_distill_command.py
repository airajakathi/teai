from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace

import pytest

from teai_builder.agent.distill import Distiller
from teai_builder.bus.events import InboundMessage
from teai_builder.command.builtin import cmd_distill
from teai_builder.command.router import CommandContext


def _make_run(run_id: str = "run-1", workflow_id: str = "app_build_v1"):
    return SimpleNamespace(
        run_id=run_id,
        workflow_id=workflow_id,
        state="completed",
        error=None,
        metadata={"source": "test"},
        step_states=OrderedDict(
            [
                (
                    "plan",
                    SimpleNamespace(
                        step_id="plan",
                        name="Plan",
                        state="completed",
                    ),
                ),
                (
                    "verify",
                    SimpleNamespace(
                        step_id="verify",
                        name="Verify",
                        state="completed",
                    ),
                ),
            ]
        ),
    )


def _make_ctx(args: str, runs: list[object]) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=f"/distill {args}")
    loop = SimpleNamespace(
        workflow_engine=SimpleNamespace(
            list_runs=lambda workflow_id=None, limit=10: [
                run for run in runs if workflow_id is None or run.workflow_id == workflow_id
            ][:limit]
        )
    )
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, args=args, loop=loop)


def test_distiller_mines_from_real_run(tmp_path) -> None:
    distiller = Distiller(storage_dir=tmp_path)

    mined = distiller.mine_from_run(_make_run())

    assert mined
    assert any(pattern.metadata["workflow_id"] == "app_build_v1" for pattern in mined)
    assert any("plan" in pattern.tags for pattern in mined)
    assert any("verify" in pattern.tags for pattern in mined)


@pytest.mark.asyncio
async def test_distill_command_mines_recent_runs(monkeypatch, tmp_path) -> None:
    distiller = Distiller(storage_dir=tmp_path)
    monkeypatch.setattr("teai_builder.agent.distill.get_distiller", lambda: distiller)
    ctx = _make_ctx("mine", [_make_run()])

    out = await cmd_distill(ctx)

    assert "Mined" in out.content
    assert "app_build_v1" in out.content
    assert distiller.list_patterns()


@pytest.mark.asyncio
async def test_distill_command_filters_by_workflow(monkeypatch, tmp_path) -> None:
    distiller = Distiller(storage_dir=tmp_path)
    monkeypatch.setattr("teai_builder.agent.distill.get_distiller", lambda: distiller)
    ctx = _make_ctx("mine other_workflow", [_make_run("run-1", "app_build_v1")])

    out = await cmd_distill(ctx)

    assert "No workflow runs found for `other_workflow` to distill." in out.content
