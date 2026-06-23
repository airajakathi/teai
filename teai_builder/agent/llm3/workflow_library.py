"""Workflow definition registry owned by llm3."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from .workflow_models import WorkflowDefinition, WorkflowStep

_BUILTIN_WORKFLOWS: dict[str, WorkflowDefinition] = {}


def register_workflow(definition: WorkflowDefinition) -> None:
    _BUILTIN_WORKFLOWS[definition.workflow_id] = definition


def get_workflow(workflow_id: str) -> WorkflowDefinition | None:
    return _BUILTIN_WORKFLOWS.get(workflow_id)


def list_workflows() -> list[WorkflowDefinition]:
    return [_BUILTIN_WORKFLOWS[key] for key in sorted(_BUILTIN_WORKFLOWS)]


def load_workflows_from_dir(workflows_dir: Path) -> None:
    if not workflows_dir.exists():
        return
    for path in workflows_dir.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                steps = []
                for step in data.get("steps", []):
                    steps.append(
                        WorkflowStep(
                            step_id=step["step_id"],
                            name=step["name"],
                            prompt_template=step["prompt_template"],
                            depends_on=step.get("depends_on", []),
                            max_retries=step.get("max_retries", 0),
                            checkpoint_after=step.get("checkpoint_after", False),
                            continue_on_error=step.get("continue_on_error", False),
                            run_if=step.get("run_if"),
                            timeout_seconds=step.get("timeout_seconds"),
                            metadata=dict(step.get("metadata", {})),
                        )
                    )
            definition = WorkflowDefinition(
                workflow_id=data["workflow_id"],
                name=data["name"],
                description=data.get("description", ""),
                steps=steps,
            )
            register_workflow(definition)
        except Exception as exc:
            logger.warning("Failed to load workflow from {}: {}", path, exc)
