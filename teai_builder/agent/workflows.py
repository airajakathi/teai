"""Built-in workflow templates for common development pipelines."""

from __future__ import annotations

from teai_builder.agent.llm3.workflow_library import register_workflow
from teai_builder.agent.llm3.workflow_models import WorkflowDefinition, WorkflowStep


def _register_builtins() -> None:
    register_workflow(
        WorkflowDefinition(
            workflow_id="app_build_v1",
            name="App Build Pipeline",
            description="Research, plan, scaffold, and preview an application.",
            input_schema={
                "type": "object",
                "properties": {
                    "project_name": {"type": "string"},
                    "user_request": {"type": "string"},
                    "platform": {
                        "type": "string",
                        "enum": ["web", "mobile", "desktop", "cli", "backend", "extension", "bot", "solution"],
                    },
                },
                "required": ["project_name", "platform", "user_request"],
            },
            steps=[
                WorkflowStep(
                    step_id="surface_plan",
                    name="Plan product surfaces.",
                    prompt_template=(
                        "Auto-run the structured product surface planner and capture its typed result before research or code."
                    ),
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
                    step_id="brief",
                    name="Expand rough idea into product brief.",
                    prompt_template=(
                        "Use the typed output of `plan_product_surfaces` as the source of truth.\n"
                        "Expand the user's rough idea into a detailed product brief before implementation.\n"
                        "Define the product summary, target users, core workflow, required UI states, color/theme direction, backend/auth scope, data entities, and release-quality bar.\n"
                        "If clarification questions exist, surface them explicitly before code."
                    ),
                    depends_on=["surface_plan"],
                ),
                WorkflowStep(
                    step_id="research",
                    name="Research latest stack and project requirements.",
                    prompt_template=(
                        "Research the latest recommended libraries, SDKs, architecture patterns, auth approaches, deployment options, and reference products for '{project_name}'.\n"
                        "Start from the brief and `plan_product_surfaces` output.\n"
                        "Focus on the real product shape: UI system, theme consistency, backend boundaries, auth/account flows, data models, and release requirements."
                    ),
                    depends_on=["brief"],
                ),
                WorkflowStep(
                    step_id="plan",
                    name="Create implementation plan.",
                    prompt_template=(
                        "Update the implementation plan using the research findings and the typed planner output.\n"
                        "Break the work into phases, acceptance criteria, UX/UI deliverables, backend/data work, auth/billing requirements, and verification gates.\n"
                        "Keep the plan production-ready and aligned with every required delivery surface."
                    ),
                    depends_on=["research"],
                ),
                WorkflowStep(
                    step_id="tasks",
                    name="Create executable task board.",
                    prompt_template=(
                        "Turn the approved plan into an ordered task board.\n"
                        "Assign owners, dependencies, subtasks, and verification expectations for frontend, backend, design, devops, and QA work.\n"
                        "Make the tasks concrete enough that subagents can execute them directly."
                    ),
                    depends_on=["plan"],
                ),
                WorkflowStep(
                    step_id="scaffold",
                    name="Scaffold project files.",
                    prompt_template=(
                        "Execute the scaffold plan produced by the structured planner result."
                    ),
                    depends_on=["tasks"],
                    checkpoint_after=True,
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
                WorkflowStep(
                    step_id="verify",
                    name="Verify build and preview.",
                    prompt_template=(
                        "Verify the '{project_name}' scaffold builds cleanly and the preview renders. "
                        "Fix any issues found."
                    ),
                    depends_on=["scaffold"],
                    checkpoint_after=True,
                ),
            ],
        )
    )


_register_builtins()
