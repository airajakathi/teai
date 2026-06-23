"""Parallel workflow execution runtime owned by llm3."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.parallel_executor import TaskStatus

from .workflow_completion_runtime import LLM3WorkflowCompletionRuntime


class LLM3ParallelWorkflowRuntime:
    """Own parallel workflow progression and completion policy."""

    def __init__(self, *, workflow_engine: Any) -> None:
        self.workflow_engine = workflow_engine
        self.workflow_host = getattr(workflow_engine, "workflow_host", workflow_engine)
        self.workflow_service = getattr(workflow_engine, "workflow_service", None)
        self.completion_runtime = getattr(
            workflow_engine,
            "completion_runtime",
            LLM3WorkflowCompletionRuntime(
                workflow_service=self.workflow_service,
                goal_validator=self.workflow_host.goal_validator,
            ),
        )

    @staticmethod
    def _has_auto_tool_steps(definition: Any) -> bool:
        return any(
            isinstance(getattr(step, "metadata", None), dict) and step.metadata.get("auto_tool")
            for step in getattr(definition, "steps", [])
        )

    async def execute(
        self,
        definition: Any,
        goal: Goal,
        variables: dict[str, Any],
    ) -> Any:
        workflow_service = self.workflow_service or getattr(
            self.workflow_engine,
            "workflow_service",
            None,
        )
        if self._has_auto_tool_steps(definition):
            dynamic_runtime = getattr(self.workflow_engine, "dynamic_runtime", None)
            if dynamic_runtime is None:
                from .dynamic_workflow_runtime import LLM3DynamicWorkflowRuntime

                dynamic_runtime = LLM3DynamicWorkflowRuntime(
                    workflow_engine=self.workflow_engine,
                    workflow_service=workflow_service,
                )
            return await dynamic_runtime.execute(definition, goal, variables)
        run = workflow_service.create_run(
            definition,
            goal,
            variables,
            executor="parallel",
        )
        self.workflow_service = workflow_service
        self.workflow_service.begin_execution(
            run,
            definition,
            goal,
            variables,
            executor="parallel",
            detail="Parallel workflow started",
        )

        try:
            task_map = self.workflow_service.build_task_map(definition, goal, variables)
            results = await self.workflow_host.task_scheduler.execute(goal, list(task_map.values()))
            for step in definition.steps:
                step_run = run.step_states[step.step_id]
                result = results.get(step.step_id)
                if result and result.status == TaskStatus.COMPLETED:
                    run.step_results[step.step_id] = result.output
                    step_run.state = "completed"
                    step_run.output = result.output
                    step_run.finished_at = time.time()
                else:
                    step_run.state = "failed"
                    step_run.error = result.error if result else "Unknown task failure"
                    step_run.finished_at = time.time()
                    if step.continue_on_error:
                        run.step_results[step.step_id] = {"error": step_run.error}
                        continue
                    self.workflow_service.append_history(run, "failed", f"Step {step.step_id} failed")
                    run.error = step_run.error
                    self.workflow_service.save_run(run)
                    return run
            validation = await self.completion_runtime.validate_goal(run, goal)
            if validation.is_complete is False:
                self.completion_runtime.fail_goal_validation(run, validation)
                self.workflow_service.save_run(run)
                return run
            self.completion_runtime.complete_run(run)
        except asyncio.CancelledError:
            self.completion_runtime.cancel_run(run)
            raise
        except Exception as exc:
            self.completion_runtime.fail_run(
                run,
                detail=f"Workflow failed: {exc}",
                error=str(exc),
            )
            logger.exception("Workflow {} failed", run.run_id)
        finally:
            run.finished_at = time.time()
            self.workflow_service.save_run(run)
        return run
