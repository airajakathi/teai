"""Compatibility workflow engine forwarding to llm3-owned workflow runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from teai_builder.agent.parallel_executor import ParallelExecutor
from teai_builder.agent.checkpoint import get_checkpoint_store
from teai_builder.agent.goal_validator import Goal, get_goal_validator
from teai_builder.agent.llm3.dynamic_workflow_executor import DynamicWorkflowExecutor
from teai_builder.agent.llm3.workflow_runtime_api import LLM3WorkflowRuntimeAPI
from teai_builder.agent.llm3.task_scheduler import LLM3TaskScheduler
from teai_builder.agent.llm3.workflow_host import LLM3WorkflowHost
from teai_builder.agent.llm3.workflow_library import (
    get_workflow as llm3_get_workflow,
    list_workflows as llm3_list_workflows,
    load_workflows_from_dir as llm3_load_workflows_from_dir,
    register_workflow as llm3_register_workflow,
)
from teai_builder.agent.llm3.workflow_models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowState,
    WorkflowStep,
    WorkflowStepRun,
)
from teai_builder.agent.llm3.workflow_service import LLM3WorkflowService
from teai_builder.agent.llm3.workflow_support import ContextCompactor, SemanticCheckpointTrigger


class WorkflowEngine(LLM3WorkflowRuntimeAPI):
    """Compatibility shell over the llm3 workflow runtime API."""

    def __init__(
        self,
        parallel_executor: ParallelExecutor,
        storage_dir: Path | None = None,
        on_run_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_step_event: Callable[[WorkflowRun, WorkflowStep | None, str, dict[str, Any]], Awaitable[None]] | None = None,
        execute_tool: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        task_scheduler: LLM3TaskScheduler | None = None,
        workflow_host: LLM3WorkflowHost | None = None,
    ) -> None:
        if workflow_host is None:
            workflow_host = LLM3WorkflowHost(
                parallel_executor=parallel_executor,
                storage_dir=storage_dir,
                on_run_update=on_run_update,
                on_step_event=on_step_event,
                execute_tool=execute_tool,
                task_scheduler=task_scheduler,
                checkpoint_store=get_checkpoint_store(),
                goal_validator=get_goal_validator(),
                semantic_checkpoint_trigger=SemanticCheckpointTrigger(),
            )
        super().__init__(
            parallel_executor=parallel_executor,
            storage_dir=storage_dir,
            on_run_update=on_run_update,
            on_step_event=on_step_event,
            execute_tool=execute_tool,
            task_scheduler=task_scheduler,
            workflow_host=workflow_host,
        )


def register_workflow(definition: WorkflowDefinition) -> None:
    llm3_register_workflow(definition)


def get_workflow(workflow_id: str) -> WorkflowDefinition | None:
    return llm3_get_workflow(workflow_id)


def list_workflows() -> list[WorkflowDefinition]:
    return llm3_list_workflows()


def list_saved_runs(
    *,
    workflow_id: str | None = None,
    session_key: str | None = None,
    limit: int = 10,
    storage_dir: Path | None = None,
) -> list[WorkflowRun]:
    runs = LLM3WorkflowService.list_runs_from_storage(
        workflow_id=workflow_id,
        limit=max(limit * 5, limit),
        storage_dir=storage_dir,
    )
    if session_key is not None:
        runs = [
            run
            for run in runs
            if run.metadata.get("session_key") == session_key
        ]
    return runs[:limit]


def load_workflows_from_dir(workflows_dir: Path) -> None:
    llm3_load_workflows_from_dir(workflows_dir)
