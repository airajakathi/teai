"""Execute a scaffold plan produced by the product surface planner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.scaffold import ScaffoldProjectTool
from teai_builder.agent.tools.schema import BooleanSchema, ObjectSchema, StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        project_name=StringSchema("Top-level project name for this scaffold execution."),
        planner_result=ObjectSchema(
            description="Structured output returned by the plan_product_surfaces tool.",
            additional_properties=True,
        ),
        force=BooleanSchema(
            description="Overwrite scaffold targets when they already exist.",
            default=False,
        ),
        required=["project_name", "planner_result"],
    )
)
class ExecuteScaffoldPlanTool(Tool):
    """Run scaffold_project according to a structured planner result."""

    _scopes = {"core", "subagent"}

    def __init__(self, workspace: str | Path | None = None, restrict_to_workspace: bool = False) -> None:
        self._workspace = Path(workspace) if workspace is not None else None
        self._restrict_to_workspace = restrict_to_workspace

    @classmethod
    def create(cls, ctx: Any) -> "ExecuteScaffoldPlanTool":
        tools_cfg = getattr(ctx, "config", None)
        restrict = bool(getattr(tools_cfg, "restrict_to_workspace", False))
        return cls(workspace=getattr(ctx, "workspace", None), restrict_to_workspace=restrict)

    @property
    def name(self) -> str:
        return "execute_scaffold_plan"

    @property
    def description(self) -> str:
        return (
            "Execute a structured scaffold strategy returned by plan_product_surfaces. "
            "Uses scaffold_project for the actual scaffold calls."
        )

    async def execute(
        self,
        project_name: str,
        planner_result: dict[str, Any],
        force: bool = False,
        **_: Any,
    ) -> dict[str, Any] | str:
        if not isinstance(planner_result, dict):
            return "Error: planner_result must be an object returned by plan_product_surfaces."

        if planner_result.get("should_block_scaffolding"):
            questions = planner_result.get("clarification_questions") or []
            question_text = "\n".join(f"- {item}" for item in questions if isinstance(item, str))
            return (
                "Error: planner_result blocks scaffolding until clarifications are answered."
                + (f"\n{question_text}" if question_text else "")
            )

        scaffold_plan = planner_result.get("scaffold_plan")
        if not isinstance(scaffold_plan, list) or not scaffold_plan:
            platform = str(planner_result.get("recommended_scaffold_platform") or "").strip()
            if not platform:
                return "Error: planner_result does not include a scaffold_plan or recommended scaffold platform."
            scaffold_plan = [
                {
                    "platform": platform,
                    "template": planner_result.get("recommended_scaffold_template"),
                    "path": project_name,
                    "reason": "Fallback single scaffold inferred from planner_result.",
                }
            ]

        scaffold_tool = ScaffoldProjectTool(
            workspace=self._workspace,
            restrict_to_workspace=self._restrict_to_workspace,
        )
        executed_steps: list[dict[str, Any]] = []

        for index, raw_step in enumerate(scaffold_plan, start=1):
            if not isinstance(raw_step, dict):
                return f"Error: scaffold_plan step #{index} is not an object."
            platform = str(raw_step.get("platform") or "").strip()
            if not platform:
                return f"Error: scaffold_plan step #{index} is missing platform."
            target_path = str(raw_step.get("path") or "").strip() or project_name
            template = raw_step.get("template")
            if template is not None:
                template = str(template)

            result = await scaffold_tool.execute(
                project_name=target_path,
                platform=platform,
                template=template,
                planner_result=planner_result,
                force=force,
            )
            if isinstance(result, str) and result.startswith("Error"):
                return f"Error executing scaffold_plan step #{index} ({platform} -> {target_path}): {result}"

            executed_steps.append(
                {
                    "index": index,
                    "platform": platform,
                    "template": template,
                    "path": target_path,
                    "reason": raw_step.get("reason"),
                    "result": result,
                }
            )

        return {
            "project_name": project_name,
            "primary_platform": planner_result.get("primary_platform"),
            "scaffold_strategy": planner_result.get("scaffold_strategy"),
            "executed_steps": executed_steps,
            "step_count": len(executed_steps),
        }
