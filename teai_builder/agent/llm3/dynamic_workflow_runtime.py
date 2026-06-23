"""Dynamic workflow execution runtime owned by llm3."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Any

from loguru import logger

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.parallel_executor import ParallelTask, TaskResult, TaskStatus

from .workflow_completion_runtime import LLM3WorkflowCompletionRuntime


class LLM3DynamicWorkflowRuntime:
    """Own dynamic workflow progression, retry policy, and completion logic."""

    def __init__(
        self,
        *,
        workflow_engine: Any,
        workflow_service: Any | None = None,
        max_retries: int = 2,
        fallback_prompt: str | None = None,
    ) -> None:
        self.workflow_engine = workflow_engine
        self.workflow_host = getattr(workflow_engine, "workflow_host", workflow_engine)
        self.workflow_service = (
            workflow_service
            or getattr(workflow_engine, "workflow_service", None)
        )
        self.completion_runtime = getattr(
            workflow_engine,
            "completion_runtime",
            LLM3WorkflowCompletionRuntime(
                workflow_service=self.workflow_service,
                goal_validator=self.workflow_host.goal_validator,
            ),
        )
        self.max_retries = max_retries
        self.fallback_prompt = fallback_prompt or (
            "The previous attempt failed. Analyze the error, adjust the plan, "
            "and continue toward the goal."
        )

    async def execute(
        self,
        definition: Any,
        goal: Goal,
        variables: dict[str, Any],
        *,
        run: Any | None = None,
    ) -> Any:
        run = run or self.workflow_service.create_run(
            definition,
            goal,
            variables,
            executor="dynamic",
        )
        self.workflow_service.begin_execution(
            run,
            definition,
            goal,
            variables,
            executor="dynamic",
            detail="Dynamic workflow started",
        )

        try:
            task_map = self.workflow_service.build_task_map(definition, goal, variables)
            results: dict[str, TaskResult] = {
                step_id: self.workflow_service.task_result_from_step_run(step_id, step_run)
                for step_id, step_run in run.step_states.items()
                if step_run.state in {"completed", "failed", "cancelled", "skipped"}
            }

            for step in definition.steps:
                step_run = run.step_states[step.step_id]
                if step.step_id in run.step_results and step_run.state == "completed":
                    continue
                if run.cancel_requested:
                    step_run.state = "cancelled"
                    step_run.finished_at = time.time()
                    self.workflow_service.append_history(run, "cancelled", "Workflow cancelled")
                    run.error = "Workflow cancelled"
                    self.workflow_service.save_run(run)
                    return run
                should_run, reason = self._should_run_step(step, variables, run)
                if not should_run:
                    step_run.state = "skipped"
                    step_run.skipped_reason = reason
                    step_run.finished_at = time.time()
                    step_run.output = {"skipped": True, "reason": reason}
                    run.step_results[step.step_id] = step_run.output
                    results[step.step_id] = self.workflow_service.task_result_from_step_run(step.step_id, step_run)
                    self.workflow_service.save_run(run)
                    continue
                step_run.state = "running"
                step_run.error = None
                step_run.skipped_reason = None
                if step_run.started_at is None:
                    step_run.started_at = time.time()
                step_run.finished_at = None
                run.current_step = step.step_id
                self.workflow_service.save_run(run)
                auto_result = await self.workflow_service.execute_auto_tool_step(step, variables, run)
                if auto_result is not None:
                    result = auto_result
                else:
                    task = task_map[step.step_id]
                    result = await self._run_step_with_retries(goal, task, step, results, run, step_run)
                results[step.step_id] = result
                if result.status == TaskStatus.COMPLETED:
                    run.step_results[step.step_id] = result.output
                    step_run.state = "completed"
                    step_run.output = result.output
                    step_run.error = None
                    step_run.finished_at = time.time()
                    if step.checkpoint_after or self.workflow_host.semantic_checkpoint_trigger.should_checkpoint(step):
                        checkpoints = run.metadata.setdefault("checkpoints", [])
                        if isinstance(checkpoints, list):
                            checkpoint = self.workflow_service.save_workflow_checkpoint(run, step, goal=goal)
                            checkpoints.append(
                                {
                                    "step_id": step.step_id,
                                    "saved_at": time.time(),
                                    "result_keys": sorted(run.step_results.keys()),
                                    "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
                                    "context_budget_pct": (
                                        checkpoint.context_budget_pct if checkpoint is not None else None
                                    ),
                                }
                            )
                            if checkpoint is not None:
                                await self.workflow_service.emit_step_event(
                                    run,
                                    step,
                                    "workflow_checkpoint_created",
                                    {
                                        "run_id": run.run_id,
                                        "step_id": step.step_id,
                                        "checkpoint_id": checkpoint.checkpoint_id,
                                        "result_keys": sorted(run.step_results.keys()),
                                        "context_budget_pct": checkpoint.context_budget_pct,
                                    },
                                )
                else:
                    step_run.state = "cancelled" if result.status == TaskStatus.CANCELLED else "failed"
                    step_run.error = result.error or "Dynamic workflow step failed"
                    step_run.finished_at = time.time()
                    step_run.output = result.output
                    if result.output:
                        run.step_results[step.step_id] = result.output
                    if result.status == TaskStatus.CANCELLED:
                        self.workflow_service.append_history(run, "cancelled", f"Step {step.step_id} cancelled")
                        run.error = step_run.error
                    elif step.continue_on_error:
                        run.step_results[step.step_id] = {
                            "error": step_run.error,
                            "continued": True,
                        }
                        self.workflow_service.save_run(run)
                        continue
                    else:
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
            if run.current_step and run.current_step in run.step_states:
                step_run = run.step_states[run.current_step]
                step_run.state = "cancelled"
                step_run.error = "Workflow cancelled"
                step_run.finished_at = time.time()
            self.completion_runtime.cancel_run(run)
        except Exception as exc:
            self.completion_runtime.fail_run(
                run,
                detail=f"Dynamic workflow failed: {exc}",
                error=str(exc),
            )
            logger.exception("Dynamic workflow {} failed", run.run_id)
        finally:
            run.finished_at = time.time()
            self.workflow_service.save_run(run)
        return run

    async def _run_step_with_retries(
        self,
        goal: Goal,
        task: ParallelTask,
        step: Any,
        prior_results: dict[str, TaskResult],
        run: Any,
        step_run: Any,
    ) -> TaskResult:
        last_result: TaskResult | None = None
        total_attempts = max(step.max_retries, 0) + 1
        for attempt in range(1, total_attempts + 1):
            step_run.attempts = attempt
            self.workflow_service.save_run(run)
            if attempt > 1:
                retry_of_worker_id = None
                if last_result is not None and isinstance(last_result.output, dict):
                    retry_of_worker_id = last_result.output.get("worker_id")
                await self.workflow_service.emit_step_event(
                    run,
                    step,
                    "workflow_step_retry_started",
                    {
                        "run_id": run.run_id,
                        "step_id": step.step_id,
                        "attempt": attempt,
                        "total_attempts": total_attempts,
                        "retry_of_worker_id": retry_of_worker_id,
                        "prior_error": last_result.error if last_result is not None else None,
                    },
                )
                enriched_prompt = self._enrich_prompt_with_failure(task.prompt, last_result, prior_results)
                task = dataclasses.replace(task, prompt=enriched_prompt)
            task = dataclasses.replace(
                task,
                metadata={
                    **task.metadata,
                    "attempt": attempt,
                    "total_attempts": total_attempts,
                    "retry_of_worker_id": (
                        last_result.output.get("worker_id")
                        if last_result is not None and isinstance(last_result.output, dict)
                        else None
                    ),
                },
            )
            try:
                coro = self.workflow_host.task_scheduler.run_task(goal, task)
                if step.timeout_seconds is not None and step.timeout_seconds > 0:
                    last_result = await asyncio.wait_for(coro, timeout=step.timeout_seconds)
                else:
                    last_result = await coro
            except asyncio.CancelledError:
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.CANCELLED,
                    error="Workflow cancelled",
                )
            except asyncio.TimeoutError:
                last_result = TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    error=f"Timed out after {step.timeout_seconds} second(s)",
                )
            if last_result.status == TaskStatus.COMPLETED:
                return last_result
            if last_result.status == TaskStatus.CANCELLED:
                return last_result
            if attempt < total_attempts:
                await asyncio.sleep(min(2 ** attempt, 10))

        return last_result or TaskResult(task_id=task.task_id, status=TaskStatus.FAILED, error="Unknown task failure")

    def _enrich_prompt_with_failure(
        self,
        prompt: str,
        last_result: TaskResult | None,
        prior_results: dict[str, TaskResult],
    ) -> str:
        context_lines = [prompt, "", "Previous attempt failed."]
        if last_result and last_result.error:
            context_lines.append(f"Failure reason: {last_result.error}")
        if prior_results:
            context_lines.append("Prior step outputs:")
            for step_id, result in prior_results.items():
                output = result.output.get("output") if isinstance(result.output, dict) else result.output
                context_lines.append(f"- {step_id}: {output}")
        context_lines.append(self.fallback_prompt)
        return "\n".join(context_lines)

    @staticmethod
    def _should_run_step(
        step: Any,
        variables: dict[str, Any],
        run: Any,
    ) -> tuple[bool, str | None]:
        predicate = (step.run_if or "").strip()
        if not predicate or predicate == "always":
            return True, None
        if predicate == "never":
            return False, "run_if=never"
        if predicate.startswith("step:"):
            dependency_id = predicate.split(":", 1)[1]
            if dependency_id in run.step_results:
                return True, None
            return False, f"missing step result `{dependency_id}`"
        value = variables.get(predicate)
        if bool(value):
            return True, None
        return False, f"condition `{predicate}` evaluated false"
