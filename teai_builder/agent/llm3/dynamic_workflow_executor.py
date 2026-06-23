"""Compatibility dynamic workflow executor rehomed under llm3."""

from __future__ import annotations

from typing import Any

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.parallel_executor import ParallelTask, TaskResult

from .dynamic_workflow_runtime import LLM3DynamicWorkflowRuntime
from .workflow_models import WorkflowDefinition, WorkflowRun, WorkflowStep, WorkflowStepRun


class DynamicWorkflowExecutor:
    """Compatibility wrapper over the llm3 dynamic workflow runtime."""

    def __init__(
        self,
        workflow_engine: Any,
        max_retries: int = 2,
        fallback_prompt: str | None = None,
    ) -> None:
        self.workflow_engine = workflow_engine
        self.max_retries = max_retries
        self.fallback_prompt = fallback_prompt or (
            "The previous attempt failed. Analyze the error, adjust the plan, "
            "and continue toward the goal."
        )
        self.runtime = LLM3DynamicWorkflowRuntime(
            workflow_engine=workflow_engine,
            max_retries=max_retries,
            fallback_prompt=self.fallback_prompt,
        )

    async def execute(
        self,
        definition: WorkflowDefinition,
        goal: Goal,
        variables: dict[str, Any],
        *,
        run: WorkflowRun | None = None,
    ) -> WorkflowRun:
        return await self.runtime.execute(
            definition,
            goal,
            variables,
            run=run,
        )

    async def _run_step_with_retries(
        self,
        goal: Goal,
        task: ParallelTask,
        step: WorkflowStep,
        prior_results: dict[str, TaskResult],
        run: WorkflowRun,
        step_run: WorkflowStepRun,
    ) -> TaskResult:
        return await self.runtime._run_step_with_retries(
            goal,
            task,
            step,
            prior_results,
            run,
            step_run,
        )

    def _enrich_prompt_with_failure(
        self,
        prompt: str,
        last_result: TaskResult | None,
        prior_results: dict[str, TaskResult],
    ) -> str:
        return self.runtime._enrich_prompt_with_failure(prompt, last_result, prior_results)

    @staticmethod
    def _should_run_step(
        step: WorkflowStep,
        variables: dict[str, Any],
        run: WorkflowRun,
    ) -> tuple[bool, str | None]:
        return LLM3DynamicWorkflowRuntime._should_run_step(step, variables, run)
