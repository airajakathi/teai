"""Task scheduling adapter for moving workflow execution ownership under llm3."""

from __future__ import annotations

from typing import Any

from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.parallel_executor import ParallelExecutor, ParallelTask, TaskResult


class LLM3TaskScheduler:
    """Wrap legacy task execution primitives behind an llm3-owned contract."""

    def __init__(self, executor: ParallelExecutor | Any) -> None:
        self._executor = executor

    async def execute(self, goal: Goal, tasks: list[ParallelTask]) -> dict[str, TaskResult]:
        return await self._executor.execute(goal, tasks)

    async def run_task(self, goal: Goal, task: ParallelTask) -> TaskResult:
        return await self._executor._run_task(goal, task)
