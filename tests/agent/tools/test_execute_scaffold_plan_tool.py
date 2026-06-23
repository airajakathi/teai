from __future__ import annotations

import pytest

from teai_builder.agent.tools.execute_scaffold_plan import ExecuteScaffoldPlanTool


@pytest.mark.asyncio
async def test_execute_scaffold_plan_runs_solution_scaffold(tmp_path) -> None:
    tool = ExecuteScaffoldPlanTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(
        project_name="cursor-suite",
        planner_result={
            "primary_platform": "desktop",
            "scaffold_strategy": "solution-scaffold",
            "scaffold_plan": [
                {
                    "platform": "solution",
                    "template": "desktop-suite",
                    "path": "cursor-suite",
                    "reason": "Desktop app with backend and companion web.",
                }
            ],
        },
    )

    assert result["step_count"] == 1
    assert result["executed_steps"][0]["platform"] == "solution"
    assert (tmp_path / "cursor-suite" / "frontend" / "package.json").exists()
    assert (tmp_path / "cursor-suite" / "backend" / "pyproject.toml").exists()
    assert (tmp_path / "cursor-suite" / "desktop" / "package.json").exists()


@pytest.mark.asyncio
async def test_execute_scaffold_plan_runs_split_scaffold_plan(tmp_path) -> None:
    tool = ExecuteScaffoldPlanTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(
        project_name="research-copilot",
        planner_result={
            "primary_platform": "extension",
            "scaffold_strategy": "split-scaffold",
            "scaffold_plan": [
                {"platform": "extension", "path": "research-copilot/extension"},
                {"platform": "backend", "path": "research-copilot/backend"},
                {"platform": "web", "path": "research-copilot/web", "template": "saas"},
            ],
        },
    )

    assert result["step_count"] == 3
    assert [step["platform"] for step in result["executed_steps"]] == ["extension", "backend", "web"]
    assert (tmp_path / "research-copilot" / "extension" / "manifest.json").exists()
    assert (tmp_path / "research-copilot" / "backend" / "app" / "main.py").exists()
    assert (tmp_path / "research-copilot" / "web" / "frontend" / "package.json").exists()


@pytest.mark.asyncio
async def test_execute_scaffold_plan_blocks_when_planner_requires_questions(tmp_path) -> None:
    tool = ExecuteScaffoldPlanTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(
        project_name="unknown-app",
        planner_result={
            "should_block_scaffolding": True,
            "clarification_questions": ["Which platform should ship first?"],
        },
    )

    assert isinstance(result, str)
    assert result.startswith("Error: planner_result blocks scaffolding")
