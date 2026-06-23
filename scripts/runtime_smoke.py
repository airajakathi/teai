#!/usr/bin/env python3
"""Focused runtime smoke checks for TeAi Builder."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import time
from pathlib import Path

from teai_builder.agent.loop import AgentLoop
from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.workflow_engine import WorkflowDefinition, WorkflowStep
from teai_builder.bus.queue import MessageBus
from teai_builder.config.loader import load_config, resolve_config_env_vars, set_config_path
from teai_builder.providers.audio_generation import audio_gen_provider_configs
from teai_builder.providers.image_generation import image_gen_provider_configs
from teai_builder.providers.video_generation import video_gen_provider_configs


def _build_loop(config_path: Path, workspace_path: Path, preset: str | None) -> AgentLoop:
    set_config_path(config_path)
    config = resolve_config_env_vars(load_config(config_path))
    config.agents.defaults.workspace = str(workspace_path)
    config.agents.defaults.model_preset = preset
    return AgentLoop.from_config(
        config,
        MessageBus(),
        image_generation_provider_configs=image_gen_provider_configs(config),
        video_generation_provider_configs=video_gen_provider_configs(config),
        audio_generation_provider_configs=audio_gen_provider_configs(config),
    )


async def _check_models(config_path: Path, workspace_path: Path) -> None:
    presets = [None, "step-3-5-flash", "step-3-5-flash-2603"]
    for preset in presets:
        loop = _build_loop(config_path, workspace_path, preset)
        resolved = loop.model
        expected = f"MODEL_OK:{resolved}"
        try:
            response = await loop.process_direct(
                f"Reply with exactly {expected}",
                session_key=f"cli:runtime-smoke:{preset or 'default'}",
            )
            actual = (response.content if response else "").strip()
            if actual != expected:
                raise RuntimeError(f"model check failed for {resolved}: expected {expected!r}, got {actual!r}")
            print(f"[ok] model {resolved}: {actual}")
        finally:
            await loop.close_mcp()


async def _check_inline_subagent(config_path: Path, workspace_path: Path) -> None:
    loop = _build_loop(config_path, workspace_path, None)
    proof_path = workspace_path / "runtime-smoke-subagent.txt"
    if proof_path.exists():
        proof_path.unlink()
    prompt = (
        "Use exactly one spawn tool call. Delegate the entire task to the subagent. "
        f"The subagent must create the file {proof_path} with exact contents: RUNTIME_SMOKE_SUBAGENT_OK. "
        "Do not claim success until the file truly exists. "
        "After the subagent completes, reply with exactly RUNTIME_SMOKE_MAIN_OK."
    )
    try:
        response = await loop.process_direct(prompt, session_key="cli:runtime-smoke-subagent")
        actual = (response.content if response else "").strip()
        if actual != "RUNTIME_SMOKE_MAIN_OK":
            raise RuntimeError(f"subagent smoke failed: unexpected response {actual!r}")
        if not proof_path.is_file():
            raise RuntimeError("subagent smoke failed: proof file was not created")
        contents = proof_path.read_text(encoding="utf-8").strip()
        if contents != "RUNTIME_SMOKE_SUBAGENT_OK":
            raise RuntimeError(f"subagent smoke failed: unexpected file contents {contents!r}")
        print(f"[ok] subagent orchestration: {proof_path}")
    finally:
        await loop.close_mcp()


async def _check_serious_product_build(config_path: Path, workspace_path: Path) -> None:
    product_brief = (
        "Build a Cursor-like AI coding product with a desktop app, website for downloads, "
        "user login, billing, and account management. It must be a production-shaped multi-surface product."
    )
    with tempfile.TemporaryDirectory(prefix="teai-product-smoke-", dir=str(workspace_path)) as tmp_dir:
        smoke_workspace = Path(tmp_dir)
        project_name = "cursor-suite-smoke"
        loop = _build_loop(config_path, smoke_workspace, None)
        workflow = WorkflowDefinition(
            workflow_id="runtime_product_smoke_v1",
            name="Runtime Product Smoke",
            description="Validate planner-to-scaffold serious product flow.",
            steps=[
                WorkflowStep(
                    step_id="surface_plan",
                    name="Plan product surfaces",
                    prompt_template="auto planner smoke",
                    metadata={
                        "auto_tool": "plan_product_surfaces",
                        "auto_tool_args": {
                            "project_name": "{project_name}",
                            "platform_hint": "{platform}",
                        },
                        "auto_tool_args_from_variables": {
                            "user_request": "user_request",
                        },
                    },
                ),
                WorkflowStep(
                    step_id="scaffold",
                    name="Execute scaffold plan",
                    prompt_template="auto scaffold smoke",
                    depends_on=["surface_plan"],
                    metadata={
                        "auto_tool": "execute_scaffold_plan",
                        "auto_tool_args": {
                            "project_name": "{project_name}",
                        },
                        "auto_tool_args_from_results": {
                            "planner_result": "surface_plan",
                        },
                    },
                ),
            ],
        )
        goal = Goal(
            goal_id=f"runtime-product-smoke-{int(time.time())}",
            description="Validate serious multi-surface planner-to-scaffold flow.",
            success_criteria=[],
            metadata={"session_key": "cli:runtime-smoke-product"},
        )
        variables = {
            "project_name": project_name,
            "platform": "desktop",
            "user_request": product_brief,
        }
        try:
            run = await loop.dynamic_workflow.execute(workflow, goal, variables)
            if run.state != "completed":
                raise RuntimeError(f"serious product smoke failed: workflow state was {run.state!r}, error={run.error!r}")

            planner_result = run.step_results.get("surface_plan") or {}
            if planner_result.get("primary_platform") != "desktop":
                raise RuntimeError(f"serious product smoke failed: unexpected primary platform {planner_result!r}")
            surfaces = [item.get("platform") for item in planner_result.get("surfaces", []) if isinstance(item, dict)]
            if surfaces != ["desktop", "backend", "web"]:
                raise RuntimeError(f"serious product smoke failed: unexpected surfaces {surfaces!r}")
            if planner_result.get("scaffold_strategy") != "solution-scaffold":
                raise RuntimeError(
                    "serious product smoke failed: planner did not choose solution-scaffold "
                    f"({planner_result.get('scaffold_strategy')!r})"
                )

            scaffold_result = run.step_results.get("scaffold") or {}
            executed_steps = scaffold_result.get("executed_steps") or []
            if len(executed_steps) != 1 or executed_steps[0].get("platform") != "solution":
                raise RuntimeError(f"serious product smoke failed: unexpected scaffold execution {scaffold_result!r}")

            project_root = smoke_workspace / project_name
            expected_files = [
                project_root / "desktop" / "package.json",
                project_root / "frontend" / "package.json",
                project_root / "backend" / "pyproject.toml",
                project_root / "docs" / "solution-architecture.md",
            ]
            missing = [str(path) for path in expected_files if not path.is_file()]
            if missing:
                raise RuntimeError(f"serious product smoke failed: missing scaffold files {missing!r}")
            print(f"[ok] serious product planner/scaffold: {project_root}")
        finally:
            await loop.close_mcp()


async def _run(config_path: Path, workspace_path: Path, *, skip_subagent: bool, skip_product_build: bool) -> None:
    await _check_models(config_path, workspace_path)
    if not skip_subagent:
        await _check_inline_subagent(config_path, workspace_path)
    if not skip_product_build:
        await _check_serious_product_build(config_path, workspace_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run focused TeAi Builder runtime smoke checks.")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--workspace", required=True, help="Workspace directory")
    parser.add_argument(
        "--skip-subagent",
        action="store_true",
        help="Skip the inline subagent proof step",
    )
    parser.add_argument(
        "--skip-product-build",
        action="store_true",
        help="Skip the serious multi-surface planner-to-scaffold smoke step",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    workspace_path = Path(args.workspace).expanduser().resolve()
    if not config_path.is_file():
        raise SystemExit(f"Config not found: {config_path}")
    if not workspace_path.is_dir():
        raise SystemExit(f"Workspace not found: {workspace_path}")

    asyncio.run(
        _run(
            config_path,
            workspace_path,
            skip_subagent=args.skip_subagent,
            skip_product_build=args.skip_product_build,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
