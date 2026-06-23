from __future__ import annotations

import pytest

from teai_builder.agent.tools.project_gate import ProjectGateTool
from teai_builder.agent.tools.project_state import record_verification_result, resolve_project_dir


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_project_gate_blocks_mobile_delivery_without_preview_evidence(tmp_path) -> None:
    project_dir = tmp_path / "projects" / "expo-app"
    _write(project_dir / "docs" / "architecture.md", "# Architecture\n")

    tool = ProjectGateTool(workspace=str(tmp_path))
    await tool.execute(action="init", project="expo-app", platform="mobile")
    await tool.execute(
        action="record_artifact",
        project="expo-app",
        artifact="architecture",
        path="docs/architecture.md",
    )
    resolved, error = resolve_project_dir(str(tmp_path), "expo-app")
    assert error is None
    assert resolved is not None
    record_verification_result(
        resolved,
        {
            "status": "pass",
            "summary": "VERIFIED: 1 passed, 0 failed, 0 skipped",
            "checks": [],
            "warnings": [],
        },
    )

    result = await tool.execute(action="advance", project="expo-app", to="deliver")

    assert "BLOCKED" in result
    assert "expo_native_preview" in result


@pytest.mark.asyncio
async def test_project_gate_allows_mobile_delivery_with_preview_evidence(tmp_path) -> None:
    project_dir = tmp_path / "projects" / "expo-app"
    _write(project_dir / "docs" / "architecture.md", "# Architecture\n")

    tool = ProjectGateTool(workspace=str(tmp_path))
    await tool.execute(action="init", project="expo-app", platform="mobile")
    await tool.execute(
        action="record_artifact",
        project="expo-app",
        artifact="architecture",
        path="docs/architecture.md",
    )
    await tool.execute(
        action="record_artifact",
        project="expo-app",
        artifact="expo_native_preview",
        path="exp://192.168.0.8:8081",
    )
    await tool.execute(
        action="record_artifact",
        project="expo-app",
        artifact="expo_web_preview",
        path="http://127.0.0.1:8081",
    )
    resolved, error = resolve_project_dir(str(tmp_path), "expo-app")
    assert error is None
    assert resolved is not None
    record_verification_result(
        resolved,
        {
            "status": "pass",
            "summary": "VERIFIED: 1 passed, 0 failed, 0 skipped",
            "checks": [],
            "warnings": [],
        },
    )

    result = await tool.execute(action="advance", project="expo-app", to="deliver")

    assert "advanced" in result
    assert '"phase": "deliver"' in result
