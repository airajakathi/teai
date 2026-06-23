"""Shared workflow completion helpers owned by llm3."""

from __future__ import annotations

import uuid
from typing import Any


class LLM3WorkflowCompletionRuntime:
    """Own goal validation and terminal workflow state transitions."""

    def __init__(
        self,
        *,
        workflow_service: Any,
        goal_validator: Any,
    ) -> None:
        self.workflow_service = workflow_service
        self.goal_validator = goal_validator

    async def validate_goal(self, run: Any, goal: Any) -> Any:
        validation = self.goal_validator.validate(goal, run.step_results)
        await self.workflow_service.emit_step_event(
            run,
            None,
            "workflow_goal_validated",
            {
                "run_id": run.run_id,
                "merge_id": "workflow-results",
                "merge_summary": f"Merged {len(run.step_results)} workflow result(s)",
                "result_keys": sorted(run.step_results.keys()),
                "validation_id": f"val-{uuid.uuid4().hex[:10]}",
                "is_complete": validation.is_complete,
                "confidence": validation.confidence,
                "reasoning": validation.reasoning,
                "failed_criteria": list(validation.failed_criteria),
                "suggestions": list(validation.suggestions),
            },
        )
        return validation

    def fail_goal_validation(self, run: Any, validation: Any) -> None:
        self.workflow_service.append_history(run, "failed", "Goal validation failed")
        run.error = "Goal validation failed: " + ", ".join(
            validation.failed_criteria or ["unknown failure"]
        )

    def complete_run(self, run: Any, *, detail: str = "Workflow completed") -> None:
        run.current_step = None
        self.workflow_service.append_history(run, "completed", detail)

    def cancel_run(self, run: Any, *, detail: str = "Workflow cancelled") -> None:
        run.current_step = None
        run.error = detail
        self.workflow_service.append_history(run, "cancelled", detail)

    def fail_run(self, run: Any, *, detail: str, error: str | None = None) -> None:
        run.current_step = None
        run.error = error or detail
        self.workflow_service.append_history(run, "failed", detail)
