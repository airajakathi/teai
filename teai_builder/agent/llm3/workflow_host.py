"""Workflow runtime host owned by llm3."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from teai_builder.agent.checkpoint import get_checkpoint_store
from teai_builder.agent.goal_validator import get_goal_validator
from teai_builder.agent.llm3.task_scheduler import LLM3TaskScheduler
from teai_builder.agent.llm3.workflow_models import WorkflowRun, WorkflowStep
from teai_builder.agent.llm3.workflow_support import SemanticCheckpointTrigger
from teai_builder.config.paths import get_runtime_subdir


class LLM3WorkflowHost:
    """Own storage, validators, active runs, and runtime callbacks for workflows."""

    def __init__(
        self,
        *,
        parallel_executor: Any,
        storage_dir: Path | None = None,
        on_run_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_step_event: Callable[[WorkflowRun, WorkflowStep | None, str, dict[str, Any]], Awaitable[None]] | None = None,
        execute_tool: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        task_scheduler: LLM3TaskScheduler | None = None,
        checkpoint_store: Any | None = None,
        goal_validator: Any | None = None,
        semantic_checkpoint_trigger: Any | None = None,
    ) -> None:
        self.parallel_executor = parallel_executor
        self.task_scheduler = task_scheduler or LLM3TaskScheduler(parallel_executor)
        self.checkpoint_store = checkpoint_store or get_checkpoint_store()
        self.goal_validator = goal_validator or get_goal_validator()
        self.semantic_checkpoint_trigger = semantic_checkpoint_trigger or SemanticCheckpointTrigger()
        self.active_runs: dict[str, asyncio.Task[WorkflowRun]] = {}
        self.on_run_update = on_run_update
        self.on_step_event = on_step_event
        self.execute_tool = execute_tool
        self.storage_dir = self._resolve_storage_dir(storage_dir)

    @staticmethod
    def _resolve_storage_dir(storage_dir: Path | None) -> Path:
        target = storage_dir or get_runtime_subdir("workflows")
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except OSError as e:
            raise RuntimeError(f"workflow storage directory is unavailable: {target}") from e

    def path_for(self, run_id: str) -> Path:
        return self.storage_dir / f"{run_id}.json"
