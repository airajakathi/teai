"""Workflow execution entrypoint owned by llm3."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class WorkflowLaunchHandle:
    run: Any
    task: asyncio.Task[Any]


class LLM3WorkflowExecutor:
    """Move workflow launch/resume ownership behind an llm3 runtime boundary."""

    def __init__(
        self,
        *,
        workflow_service: Any,
        dynamic_workflow: Any,
        schedule_background: Callable[[Awaitable[Any]], asyncio.Task[Any]],
        sync_task_graph: Callable[..., Any] | None = None,
        start_recovery: Callable[..., str] | None = None,
        complete_recovery: Callable[..., Any] | None = None,
    ) -> None:
        self._workflow_service = workflow_service
        self._dynamic_workflow = dynamic_workflow
        self._schedule_background = schedule_background
        self._sync_task_graph = sync_task_graph
        self._start_recovery = start_recovery
        self._complete_recovery = complete_recovery

    def start(
        self,
        *,
        workflow: Any,
        goal: Any,
        variables: dict[str, Any],
        on_completed: Callable[[Any, Any], Awaitable[None]],
    ) -> WorkflowLaunchHandle:
        run = self._workflow_service.create_run(workflow, goal, variables, executor="dynamic")
        if callable(self._sync_task_graph):
            self._sync_task_graph(workflow=workflow, run=run, goal=goal)

        async def _run_workflow() -> None:
            completed = await self._dynamic_workflow.execute(workflow, goal, variables, run=run)
            await on_completed(completed, workflow)

        task = self._schedule_background(_run_workflow())
        self._workflow_service.register_active_run(run.run_id, task)
        return WorkflowLaunchHandle(run=run, task=task)

    def resume(
        self,
        *,
        workflow: Any,
        run: Any,
        goal: Any,
        variables: dict[str, Any],
        on_completed: Callable[[Any, Any], Awaitable[None]],
    ) -> WorkflowLaunchHandle:
        async def _resume_workflow() -> None:
            recovery_id = None
            if callable(self._sync_task_graph):
                self._sync_task_graph(workflow=workflow, run=run, goal=goal)
            if callable(self._start_recovery):
                recovery_id = self._start_recovery(
                    run=run,
                    goal=goal,
                    reason="manual_restore",
                )
            try:
                resumed = await self._dynamic_workflow.execute(workflow, goal, variables, run=run)
                if recovery_id is not None and callable(self._complete_recovery):
                    self._complete_recovery(
                        recovery_id,
                        goal=goal,
                        run=resumed,
                        status=resumed.state,
                        summary=f"Workflow resume finished with state {resumed.state}",
                    )
                await on_completed(resumed, workflow)
            except Exception:
                if recovery_id is not None and callable(self._complete_recovery):
                    self._complete_recovery(
                        recovery_id,
                        goal=goal,
                        run=run,
                        status="failed",
                        summary="Workflow resume failed before completion",
                    )
                raise

        task = self._schedule_background(_resume_workflow())
        self._workflow_service.register_active_run(run.run_id, task)
        return WorkflowLaunchHandle(run=run, task=task)
