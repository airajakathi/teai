from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teai_builder.agent.tools.canvas import CanvasTool
from teai_builder.agent.tools.context import RequestContext
from teai_builder.agent.tools.project_state import load_state


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_canvas_tool_records_expo_mobile_and_web_preview_artifacts(tmp_path) -> None:
    project_dir = tmp_path / "projects" / "expo-app"
    _write(project_dir / ".teai_builder" / "state.json", '{\n  "project": "expo-app",\n  "platform": "mobile",\n  "phase": "build",\n  "phases": {},\n  "artifacts": {},\n  "verification": null\n}\n')

    bus = SimpleNamespace(publish_outbound=AsyncMock())
    tool = CanvasTool.create(SimpleNamespace(bus=bus, workspace=str(tmp_path)))
    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1"))

    await tool.execute(type="mobile_url", content="exp://192.168.0.8:8081", title="Expo app")
    await tool.execute(type="url", content="http://127.0.0.1:8081", title="Expo web")

    state = load_state(project_dir)
    assert state["artifacts"]["expo_native_preview"] == "exp://192.168.0.8:8081"
    assert state["artifacts"]["expo_web_preview"] == "http://127.0.0.1:8081"
    assert bus.publish_outbound.await_count == 2


@pytest.mark.asyncio
async def test_canvas_tool_records_standard_web_preview_for_non_mobile_project(tmp_path) -> None:
    project_dir = tmp_path / "projects" / "web-app"
    _write(project_dir / ".teai_builder" / "state.json", '{\n  "project": "web-app",\n  "platform": "web",\n  "phase": "build",\n  "phases": {},\n  "artifacts": {},\n  "verification": null\n}\n')

    bus = SimpleNamespace(publish_outbound=AsyncMock())
    tool = CanvasTool.create(SimpleNamespace(bus=bus, workspace=str(tmp_path)))
    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1"))

    await tool.execute(type="url", content="http://127.0.0.1:4173", title="Web app")

    state = load_state(project_dir)
    assert state["artifacts"]["web_preview"] == "http://127.0.0.1:4173"


@pytest.mark.asyncio
async def test_canvas_tool_ignores_preview_artifacts_when_workspace_has_no_project(tmp_path) -> None:
    bus = SimpleNamespace(publish_outbound=AsyncMock())
    tool = CanvasTool.create(SimpleNamespace(bus=bus, workspace=str(tmp_path)))
    tool.set_context(RequestContext(channel="websocket", chat_id="chat-1"))

    result = await tool.execute(type="url", content="http://127.0.0.1:3000", title="Loose preview")

    assert "pushed url content" in result
    assert not (tmp_path / "projects").exists()
