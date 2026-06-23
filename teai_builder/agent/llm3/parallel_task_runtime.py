"""Parallel task scheduling and worker execution owned by llm3."""

from __future__ import annotations

import asyncio
from typing import Any

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.llm3.worker_runtime import WorkerTaskSpec
from teai_builder.agent.task_execution_types import ParallelTask, TaskResult, TaskStatus


class LLM3ParallelTaskRuntime:
    """Own dependency-aware batching and worker task execution."""

    def __init__(self, *, executor: Any) -> None:
        self.executor = executor

    async def execute(self, goal: Goal, tasks: list[ParallelTask]) -> dict[str, TaskResult]:
        results: dict[str, TaskResult] = {}
        pending = {task.task_id: task for task in tasks}
        completed: set[str] = set()

        while pending:
            ready = [
                task
                for task in pending.values()
                if task.status == TaskStatus.PENDING
                and all(dep in completed for dep in task.depends_on)
            ]
            if not ready:
                blocked = [
                    task.task_id
                    for task in pending.values()
                    if task.status == TaskStatus.PENDING
                ]
                if blocked:
                    raise RuntimeError(
                        f"Deadlocked tasks with unmet dependencies: {blocked}"
                    )
                break

            selected = ready[: self.executor.max_parallel]
            running = []
            for task in selected:
                task.status = TaskStatus.RUNNING
                running.append(self.run_task(goal, task))

            batch = await asyncio.gather(*running, return_exceptions=True)
            for task, raw in zip(selected, batch):
                if isinstance(raw, Exception):
                    task.status = TaskStatus.FAILED
                    results[task.task_id] = TaskResult(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        error=str(raw),
                    )
                else:
                    results[task.task_id] = raw
                    task.status = raw.status
                pending.pop(task.task_id, None)
                if results[task.task_id].status == TaskStatus.COMPLETED:
                    completed.add(task.task_id)

        self.executor._results.update(results)
        return results

    async def run_task(self, goal: Goal, task: ParallelTask) -> TaskResult:
        started_at = asyncio.get_event_loop().time()
        status = TaskStatus.RUNNING
        output: dict[str, Any] = {}
        error: str | None = None
        await self.executor._emit_task_event(
            goal,
            task,
            "worker_task_started",
            {
                "task_id": task.task_id,
                "label": f"{goal.goal_id}:{task.task_id}",
                "attempt": task.metadata.get("attempt"),
                "total_attempts": task.metadata.get("total_attempts"),
                "retry_of_worker_id": task.metadata.get("retry_of_worker_id"),
                "depends_on": list(task.depends_on),
            },
        )
        try:
            if self.executor.worker_runtime is not None:
                result = await self.executor.worker_runtime.run(
                    WorkerTaskSpec(
                        task=task.prompt,
                        label=f"{goal.goal_id}:{task.task_id}",
                        role=(
                            str(task.metadata.get("role"))
                            if task.metadata.get("role")
                            else None
                        ),
                        model=self.executor._model_for(task),
                        model_preset=(
                            str(task.metadata.get("model_preset"))
                            if task.metadata.get("model_preset") is not None
                            else None
                        ),
                        origin_channel=str(goal.metadata.get("channel", "workflow")),
                        origin_chat_id=str(
                            goal.metadata.get("chat_id", goal.goal_id)
                        ),
                        session_key=(
                            str(goal.metadata.get("session_key"))
                            if goal.metadata.get("session_key") is not None
                            else None
                        ),
                    )
                )
                output = {
                    "worker_id": result.worker_id,
                    "label": result.label,
                    "output": result.final_output,
                    "stop_reason": result.stop_reason,
                    "tool_events": list(result.tool_events or []),
                }
                if result.error:
                    output["error"] = result.error
                await self.executor._emit_task_event(
                    goal,
                    task,
                    "worker_task_finished",
                    {
                        "task_id": task.task_id,
                        "worker_id": result.worker_id,
                        "label": result.label,
                        "status": result.status,
                        "stop_reason": result.stop_reason,
                        "error": result.error,
                        "attempt": task.metadata.get("attempt"),
                        "total_attempts": task.metadata.get("total_attempts"),
                        "retry_of_worker_id": task.metadata.get("retry_of_worker_id"),
                    },
                )
                if result.status != "completed":
                    status = TaskStatus.FAILED
                    error = result.error or result.final_output
                else:
                    status = TaskStatus.COMPLETED
            else:
                launch_message = await self.executor.subagent_manager.spawn(
                    task=task.prompt,
                    label=f"{goal.goal_id}:{task.task_id}",
                    model=self.executor._model_for(task),
                    session_key=(
                        str(goal.metadata.get("session_key"))
                        if goal.metadata.get("session_key") is not None
                        else None
                    ),
                )
                output = {"launch_message": launch_message}
                await self.executor._emit_task_event(
                    goal,
                    task,
                    "worker_task_finished",
                    {
                        "task_id": task.task_id,
                        "status": "completed",
                        "launch_message": launch_message,
                        "attempt": task.metadata.get("attempt"),
                        "total_attempts": task.metadata.get("total_attempts"),
                        "retry_of_worker_id": task.metadata.get("retry_of_worker_id"),
                    },
                )
                status = TaskStatus.COMPLETED
            if output.get("status") == "error":
                status = TaskStatus.FAILED
                error = str(output.get("error"))
        except Exception as exc:
            status = TaskStatus.FAILED
            error = str(exc)
            await self.executor._emit_task_event(
                goal,
                task,
                "worker_task_failed",
                {
                    "task_id": task.task_id,
                    "error": error,
                    "attempt": task.metadata.get("attempt"),
                    "total_attempts": task.metadata.get("total_attempts"),
                    "retry_of_worker_id": task.metadata.get("retry_of_worker_id"),
                },
            )
        finished_at = asyncio.get_event_loop().time()
        return TaskResult(
            task_id=task.task_id,
            status=status,
            output=output,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )
