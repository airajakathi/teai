"""Parallel execution engine compatibility wrapper for llm3 task orchestration."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from teai_builder.agent.goal_validator import Goal, get_goal_validator
from teai_builder.agent.llm3.parallel_task_runtime import LLM3ParallelTaskRuntime
from teai_builder.agent.llm3.worker_runtime import WorkerRuntime
from teai_builder.agent.subagent import SubagentManager
from teai_builder.agent.task_execution_types import ParallelTask, TaskResult, TaskStatus
from teai_builder.bus.queue import MessageBus


class ParallelExecutor:
    def __init__(
        self,
        subagent_manager: SubagentManager,
        bus: MessageBus,
        max_parallel: int = 3,
        worker_runtime: WorkerRuntime | None = None,
        on_task_event: Callable[[Goal, ParallelTask, str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self.subagent_manager = subagent_manager
        self.bus = bus
        self.max_parallel = max_parallel
        self.worker_runtime = worker_runtime
        self._on_task_event = on_task_event
        self.goal_validator = get_goal_validator()
        self._results: dict[str, TaskResult] = {}
        self.runtime = LLM3ParallelTaskRuntime(executor=self)

    def _model_for(self, task: ParallelTask) -> str:
        return task.model or self.subagent_manager.model

    async def _emit_task_event(
        self,
        goal: Goal,
        task: ParallelTask,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._on_task_event is None:
            return
        result = self._on_task_event(goal, task, event_type, dict(payload or {}))
        if asyncio.iscoroutine(result):
            await result

    async def execute(self, goal: Goal, tasks: list[ParallelTask]) -> dict[str, TaskResult]:
        return await self.runtime.execute(goal, tasks)

    async def _run_task(self, goal: Goal, task: ParallelTask) -> TaskResult:
        return await self.runtime.run_task(goal, task)
