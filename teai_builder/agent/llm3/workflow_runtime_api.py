"""Primary workflow runtime API owned by llm3."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from teai_builder.agent.checkpoint import Checkpoint, get_checkpoint_store
from teai_builder.agent.goal_validator import Goal, get_goal_validator
from teai_builder.agent.parallel_executor import (
    ParallelExecutor,
    ParallelTask,
    TaskResult,
)

from .dynamic_workflow_executor import DynamicWorkflowExecutor
from .parallel_workflow_runtime import LLM3ParallelWorkflowRuntime
from .task_scheduler import LLM3TaskScheduler
from .workflow_completion_runtime import LLM3WorkflowCompletionRuntime
from .workflow_host import LLM3WorkflowHost
from .workflow_models import WorkflowDefinition, WorkflowRun, WorkflowStep, WorkflowStepRun
from .workflow_service import LLM3WorkflowService
from .workflow_support import SemanticCheckpointTrigger


class LLM3WorkflowRuntimeAPI:
    """Public workflow runtime surface owned by llm3."""

    def __init__(
        self,
        parallel_executor: ParallelExecutor,
        storage_dir: Path | None = None,
        on_run_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_step_event: Callable[[WorkflowRun, WorkflowStep | None, str, dict[str, Any]], Awaitable[None]] | None = None,
        execute_tool: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        task_scheduler: LLM3TaskScheduler | None = None,
        workflow_host: LLM3WorkflowHost | None = None,
        checkpoint_store: Any | None = None,
        goal_validator: Any | None = None,
        semantic_checkpoint_trigger: Any | None = None,
    ) -> None:
        self.workflow_host = workflow_host or LLM3WorkflowHost(
            parallel_executor=parallel_executor,
            storage_dir=storage_dir,
            on_run_update=on_run_update,
            on_step_event=on_step_event,
            execute_tool=execute_tool,
            task_scheduler=task_scheduler,
            checkpoint_store=checkpoint_store or get_checkpoint_store(),
            goal_validator=goal_validator or get_goal_validator(),
            semantic_checkpoint_trigger=semantic_checkpoint_trigger or SemanticCheckpointTrigger(),
        )
        self.parallel_executor = self.workflow_host.parallel_executor
        self.task_scheduler = self.workflow_host.task_scheduler
        self.checkpoint_store = self.workflow_host.checkpoint_store
        self.goal_validator = self.workflow_host.goal_validator
        self.semantic_checkpoint_trigger = self.workflow_host.semantic_checkpoint_trigger
        self._active_runs = self.workflow_host.active_runs
        self._on_run_update = self.workflow_host.on_run_update
        self._on_step_event = self.workflow_host.on_step_event
        self.storage_dir = self.workflow_host.storage_dir
        self.workflow_service = LLM3WorkflowService(self)
        self.completion_runtime = LLM3WorkflowCompletionRuntime(
            workflow_service=self.workflow_service,
            goal_validator=self.goal_validator,
        )
        self.parallel_runtime = LLM3ParallelWorkflowRuntime(workflow_engine=self)

    def _path_for(self, run_id: str) -> Path:
        return self.workflow_host.path_for(run_id)

    @staticmethod
    def _goal_to_dict(goal: Goal) -> dict[str, Any]:
        return LLM3WorkflowService.goal_to_dict(goal)

    @staticmethod
    def goal_from_run(run: WorkflowRun) -> Goal | None:
        return LLM3WorkflowService.goal_from_run(run)

    @staticmethod
    def variables_from_run(run: WorkflowRun) -> dict[str, Any]:
        return LLM3WorkflowService.variables_from_run(run)

    @staticmethod
    def _step_run_to_dict(step: WorkflowStepRun) -> dict[str, Any]:
        return LLM3WorkflowService.step_run_to_dict(step)

    @staticmethod
    def _step_run_from_dict(data: dict[str, Any]) -> WorkflowStepRun:
        return LLM3WorkflowService.step_run_from_dict(data)

    def _append_history(self, run: WorkflowRun, state: str, detail: str | None = None) -> None:
        self.workflow_service.append_history(run, state, detail)

    def _ensure_step_states(
        self,
        run: WorkflowRun,
        definition: WorkflowDefinition,
    ) -> dict[str, WorkflowStepRun]:
        return self.workflow_service.ensure_step_states(run, definition)

    def create_run(
        self,
        definition: WorkflowDefinition,
        goal: Goal,
        variables: dict[str, Any],
        *,
        executor: str = "dynamic",
    ) -> WorkflowRun:
        return self.workflow_service.create_run(
            definition,
            goal,
            variables,
            executor=executor,
        )

    def list_runs(self, workflow_id: str | None = None, limit: int = 10) -> list[WorkflowRun]:
        return self.workflow_service.list_runs(
            workflow_id=workflow_id,
            limit=limit,
        )

    def is_run_active(self, run_id: str) -> bool:
        return self.workflow_service.is_run_active(run_id)

    def register_active_run(self, run_id: str, task: asyncio.Task[WorkflowRun]) -> None:
        self.workflow_service.register_active_run(run_id, task)

    def request_cancel(self, run_id: str) -> bool:
        return self.workflow_service.request_cancel(run_id)

    def save_run(self, run: WorkflowRun) -> Path:
        return self.workflow_service.save_run(run)

    def load_run(self, run_id: str) -> WorkflowRun | None:
        return self.workflow_service.load_run(run_id)

    def _run_to_dict(self, run: WorkflowRun) -> dict[str, Any]:
        return LLM3WorkflowService.run_to_dict(run)

    def run_update_payload(self, run: WorkflowRun) -> dict[str, Any]:
        return self.workflow_service.run_update_payload(run)

    def _emit_run_update(self, payload: dict[str, Any]) -> None:
        self.workflow_service.emit_run_update(payload)

    async def _emit_step_event(
        self,
        run: WorkflowRun,
        step: WorkflowStep | None,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.workflow_service.emit_step_event(
            run,
            step,
            event_type,
            dict(payload or {}),
        )

    def _run_from_dict(self, data: dict[str, Any]) -> WorkflowRun:
        return LLM3WorkflowService.run_from_dict(data)

    async def run(self, definition: WorkflowDefinition, goal: Goal, variables: dict[str, Any]) -> WorkflowRun:
        return await self.parallel_runtime.execute(definition, goal, variables)

    def _build_task_map(
        self,
        definition: WorkflowDefinition,
        goal: Goal,
        variables: dict[str, Any],
    ) -> dict[str, ParallelTask]:
        return self.workflow_service.build_task_map(definition, goal, variables)

    @staticmethod
    def _task_result_from_step_run(step_id: str, step_run: WorkflowStepRun) -> TaskResult:
        return LLM3WorkflowService.task_result_from_step_run(step_id, step_run)

    def save_workflow_checkpoint(
        self,
        run: WorkflowRun,
        step: WorkflowStep,
        *,
        goal: Goal | None = None,
    ) -> Checkpoint | None:
        return self.workflow_service.save_workflow_checkpoint(
            run,
            step,
            goal=goal,
        )
