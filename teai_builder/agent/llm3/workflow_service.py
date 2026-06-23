"""Durable workflow state service owned by llm3."""

from __future__ import annotations

import json
import asyncio
import time
import string
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loguru import logger

from teai_builder.agent.checkpoint import Checkpoint
from teai_builder.agent.goal_validator import Goal
from teai_builder.agent.task_execution_types import ParallelTask, TaskResult, TaskStatus
from teai_builder.agent.llm3.workflow_models import (
    WorkflowRun,
    WorkflowState,
    WorkflowStepRun,
)


class LLM3WorkflowService:
    """Own workflow state mutation, persistence, and active-run bookkeeping."""

    def __init__(self, workflow_engine: Any) -> None:
        self._workflow_engine = workflow_engine
        self._workflow_host = getattr(workflow_engine, "workflow_host", workflow_engine)

    def append_history(self, run: Any, state: str, detail: str | None = None) -> None:
        timestamp = time.time()
        run.state = state
        run.updated_at = timestamp
        run.status_history.append(
            {
                "state": state,
                "detail": detail,
                "timestamp": timestamp,
            }
        )

    @staticmethod
    def step_run_to_dict(step: Any) -> dict[str, Any]:
        return {
            "step_id": step.step_id,
            "name": step.name,
            "state": step.state,
            "attempts": step.attempts,
            "started_at": step.started_at,
            "finished_at": step.finished_at,
            "error": step.error,
            "output": step.output,
            "skipped_reason": step.skipped_reason,
            "metadata": step.metadata,
        }

    @staticmethod
    def step_run_from_dict(data: dict[str, Any]) -> Any:
        return WorkflowStepRun(
            step_id=data["step_id"],
            name=data.get("name", data["step_id"]),
            state=data.get("state", WorkflowState.PENDING),
            attempts=int(data.get("attempts", 0)),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
            output=data.get("output"),
            skipped_reason=data.get("skipped_reason"),
            metadata=dict(data.get("metadata", {})),
        )

    def ensure_step_states(
        self,
        run: Any,
        definition: Any,
    ) -> dict[str, Any]:
        for step in definition.steps:
            run.step_states.setdefault(
                step.step_id,
                WorkflowStepRun(step_id=step.step_id, name=step.name),
            )
        return run.step_states

    def create_run(
        self,
        workflow: Any,
        goal: Any,
        variables: dict[str, Any],
        *,
        executor: str = "dynamic",
    ) -> Any:
        run = WorkflowRun(
            run_id=f"{workflow.workflow_id}:{int(time.time())}",
            workflow_id=workflow.workflow_id,
            goal_id=goal.goal_id,
            metadata={
                "executor": executor,
                "variables": dict(variables),
                "goal": self.goal_to_dict(goal),
                "session_key": goal.metadata.get("session_key"),
            },
        )
        self.ensure_step_states(run, workflow)
        self.append_history(run, WorkflowState.PENDING, "Run created")
        self.save_run(run)
        return run

    @staticmethod
    def goal_to_dict(goal: Goal) -> dict[str, Any]:
        return {
            "goal_id": goal.goal_id,
            "description": goal.description,
            "success_criteria": list(goal.success_criteria),
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
            "status": goal.status,
            "metadata": dict(goal.metadata),
        }

    @staticmethod
    def goal_from_run(run: Any) -> Any | None:
        raw = run.metadata.get("goal")
        if not isinstance(raw, dict):
            return None
        return Goal(
            goal_id=raw.get("goal_id", run.goal_id),
            description=raw.get("description", ""),
            success_criteria=list(raw.get("success_criteria", [])),
            created_at=raw.get("created_at", time.time()),
            updated_at=raw.get("updated_at", time.time()),
            status=raw.get("status", "active"),
            metadata=dict(raw.get("metadata", {})),
        )

    @staticmethod
    def variables_from_run(run: Any) -> dict[str, Any]:
        raw = run.metadata.get("variables", {})
        return dict(raw) if isinstance(raw, dict) else {}

    def begin_execution(
        self,
        run: Any,
        definition: Any,
        goal: Any,
        variables: dict[str, Any],
        *,
        executor: str,
        detail: str,
    ) -> Any:
        self.ensure_step_states(run, definition)
        run.metadata.setdefault("executor", executor)
        run.metadata["variables"] = dict(variables)
        run.metadata["goal"] = self.goal_to_dict(goal)
        run.current_step = None
        run.error = None
        run.finished_at = None
        run.cancel_requested = False
        self.append_history(run, "running", detail)
        self.save_run(run)
        return run

    @staticmethod
    def run_update_payload(run: Any) -> dict[str, Any]:
        return {
            "version": 1,
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "goal_id": run.goal_id,
            "session_key": run.metadata.get("session_key"),
            "state": run.state,
            "current_step": run.current_step,
            "started_at": run.started_at,
            "updated_at": run.updated_at,
            "finished_at": run.finished_at,
            "error": run.error,
            "cancel_requested": run.cancel_requested,
            "step_count": len(run.step_states),
            "completed_steps": sum(
                1
                for step in run.step_states.values()
                if step.state == WorkflowState.COMPLETED
            ),
            "status_history": [
                {
                    "state": item.get("state"),
                    "detail": item.get("detail"),
                    "at": item.get("at", item.get("timestamp")),
                }
                for item in run.status_history
                if isinstance(item, dict)
            ],
            "checkpoints": list(run.metadata.get("checkpoints", []))
            if isinstance(run.metadata.get("checkpoints"), list)
            else [],
            "step_states": [
                {
                    "step_id": step_id,
                    "name": step_run.name,
                    "state": step_run.state,
                    "attempts": step_run.attempts,
                    "started_at": step_run.started_at,
                    "finished_at": step_run.finished_at,
                    "error": step_run.error,
                    "output": step_run.output,
                    "skipped_reason": step_run.skipped_reason,
                }
                for step_id, step_run in run.step_states.items()
            ],
        }

    @staticmethod
    def build_task_map(
        definition: Any,
        goal: Goal,
        variables: dict[str, Any],
    ) -> dict[str, ParallelTask]:
        task_map: dict[str, ParallelTask] = {}
        for step in definition.steps:
            prompt = step.prompt_template.format(**variables)
            task_map[step.step_id] = ParallelTask(
                goal_id=goal.goal_id,
                task_id=step.step_id,
                description=step.name,
                prompt=prompt,
                depends_on=step.depends_on,
                metadata={
                    "workflow_step": True,
                    "continue_on_error": step.continue_on_error,
                    "run_if": step.run_if,
                    **step.metadata,
                },
            )
        return task_map

    @staticmethod
    def _stringify_missing_mapping(variables: dict[str, Any]) -> dict[str, str]:
        class _SafeMapping(dict[str, str]):
            def __missing__(self, key: str) -> str:
                return ""

        return _SafeMapping({key: "" if value is None else str(value) for key, value in variables.items()})

    @classmethod
    def _resolve_auto_value(cls, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            formatter = string.Formatter()
            fields = [name for _, name, _, _ in formatter.parse(value) if name]
            if fields:
                return value.format_map(cls._stringify_missing_mapping(variables))
            return value
        if isinstance(value, list):
            return [cls._resolve_auto_value(item, variables) for item in value]
        if isinstance(value, dict):
            return {key: cls._resolve_auto_value(item, variables) for key, item in value.items()}
        return value

    @classmethod
    def resolve_auto_tool_call(
        cls,
        step: Any,
        variables: dict[str, Any],
        run: Any,
    ) -> tuple[str | None, dict[str, Any]]:
        metadata = getattr(step, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            return None, {}
        tool_name = metadata.get("auto_tool")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return None, {}

        params: dict[str, Any] = {}
        raw_args = metadata.get("auto_tool_args", {})
        if isinstance(raw_args, dict):
            params.update({key: cls._resolve_auto_value(value, variables) for key, value in raw_args.items()})

        from_variables = metadata.get("auto_tool_args_from_variables", {})
        if isinstance(from_variables, dict):
            for param_name, variable_name in from_variables.items():
                if not isinstance(variable_name, str):
                    continue
                if variable_name in variables and variables[variable_name] is not None:
                    params[str(param_name)] = variables[variable_name]

        defaults = metadata.get("auto_tool_defaults", {})
        if isinstance(defaults, dict):
            for param_name, default_value in defaults.items():
                current = params.get(str(param_name))
                if current in (None, ""):
                    params[str(param_name)] = cls._resolve_auto_value(default_value, variables)

        from_results = metadata.get("auto_tool_args_from_results", {})
        if isinstance(from_results, dict):
            for param_name, step_id in from_results.items():
                if not isinstance(step_id, str):
                    continue
                if step_id in run.step_results:
                    params[str(param_name)] = run.step_results[step_id]

        return tool_name.strip(), params

    async def execute_auto_tool_step(
        self,
        step: Any,
        variables: dict[str, Any],
        run: Any,
    ) -> TaskResult | None:
        execute_tool = getattr(self._workflow_host, "execute_tool", None)
        if execute_tool is None:
            return None
        tool_name, params = self.resolve_auto_tool_call(step, variables, run)
        if not tool_name:
            return None

        started_at = time.time()
        result = await execute_tool(tool_name, params)
        finished_at = time.time()
        if isinstance(result, str) and result.startswith("Error"):
            return TaskResult(
                task_id=step.step_id,
                status=TaskStatus.FAILED,
                error=result,
                output={},
                started_at=started_at,
                finished_at=finished_at,
            )
        payload = result if isinstance(result, dict) else {"output": result}
        return TaskResult(
            task_id=step.step_id,
            status=TaskStatus.COMPLETED,
            output=payload,
            started_at=started_at,
            finished_at=finished_at,
        )

    @staticmethod
    def task_result_from_step_run(step_id: str, step_run: Any) -> TaskResult:
        state_to_status = {
            WorkflowState.COMPLETED: TaskStatus.COMPLETED,
            WorkflowState.FAILED: TaskStatus.FAILED,
            WorkflowState.CANCELLED: TaskStatus.CANCELLED,
            WorkflowState.SKIPPED: TaskStatus.BLOCKED,
        }
        return TaskResult(
            task_id=step_id,
            status=state_to_status.get(step_run.state, TaskStatus.PENDING),
            output=step_run.output if isinstance(step_run.output, dict) else {},
            error=step_run.error,
            started_at=step_run.started_at or 0.0,
            finished_at=step_run.finished_at or 0.0,
        )

    def save_workflow_checkpoint(
        self,
        run: Any,
        step: Any,
        *,
        goal: Goal | None = None,
    ) -> Checkpoint | None:
        session_key = (
            run.metadata.get("session_key")
            or (goal.metadata.get("session_key") if goal is not None else None)
            or "workflow"
        )
        result_keys = sorted(run.step_results.keys())
        checkpoint = Checkpoint(
            checkpoint_id=f"{run.run_id}:{step.step_id}:{int(time.time())}",
            session_key=str(session_key),
            created_at=time.time(),
            context_budget_pct=(len(result_keys) / max(len(run.step_states), 1)),
            state={
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "step_id": step.step_id,
                "goal_id": run.goal_id,
                "current_step": run.current_step,
                "step_results": dict(run.step_results),
            },
            messages=[],
            metadata={
                "kind": "workflow",
                "workflow_id": run.workflow_id,
                "run_id": run.run_id,
                "step_id": step.step_id,
                "step_name": step.name,
                "goal_id": run.goal_id,
                "result_keys": result_keys,
                "executor": run.metadata.get("executor"),
            },
        )
        self._workflow_host.checkpoint_store.save(checkpoint)
        return checkpoint

    @staticmethod
    def run_to_dict(run: Any) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "goal_id": run.goal_id,
            "state": run.state,
            "current_step": run.current_step,
            "step_results": run.step_results,
            "started_at": run.started_at,
            "updated_at": run.updated_at,
            "finished_at": run.finished_at,
            "error": run.error,
            "cancel_requested": run.cancel_requested,
            "status_history": run.status_history,
            "step_states": {
                step_id: LLM3WorkflowService.step_run_to_dict(step_run)
                for step_id, step_run in run.step_states.items()
            },
            "metadata": run.metadata,
        }

    @staticmethod
    def run_from_dict(data: dict[str, Any]) -> Any:
        return WorkflowRun(
            run_id=data["run_id"],
            workflow_id=data["workflow_id"],
            goal_id=data["goal_id"],
            state=data.get("state", WorkflowState.PENDING),
            current_step=data.get("current_step"),
            step_results=data.get("step_results", {}),
            started_at=data.get("started_at", time.time()),
            updated_at=data.get("updated_at", data.get("started_at", time.time())),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
            cancel_requested=bool(data.get("cancel_requested", False)),
            status_history=list(data.get("status_history", [])),
            step_states={
                step_id: LLM3WorkflowService.step_run_from_dict(step_data)
                for step_id, step_data in (data.get("step_states") or {}).items()
                if isinstance(step_data, dict)
            },
            metadata=data.get("metadata", {}),
        )

    def register_active_run(self, run_id: str, task: Any) -> None:
        self._workflow_host.active_runs[run_id] = task

        def _cleanup(done_task: Any) -> None:
            current = self._workflow_host.active_runs.get(run_id)
            if current is done_task:
                self._workflow_host.active_runs.pop(run_id, None)

        task.add_done_callback(_cleanup)

    def is_run_active(self, run_id: str) -> bool:
        task = self._workflow_host.active_runs.get(run_id)
        return task is not None and not task.done()

    def request_cancel(self, run_id: str) -> bool:
        run = self.load_run(run_id)
        if run is None:
            return False
        if run.state in {WorkflowState.COMPLETED, WorkflowState.CANCELLED}:
            return False
        run.cancel_requested = True
        self.append_history(run, run.state, "Cancellation requested")
        self.save_run(run)
        task = self._workflow_host.active_runs.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        return True

    def load_run(self, run_id: str) -> Any | None:
        path = self._workflow_host.path_for(run_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.run_from_dict(data)

    def list_runs(
        self,
        *,
        workflow_id: str | None = None,
        limit: int = 10,
    ) -> list[Any]:
        runs: list[Any] = []
        for path in self._workflow_host.storage_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                run = self.run_from_dict(data)
            except Exception:
                logger.exception(
                    "Failed to load workflow run metadata from {}",
                    path,
                )
                continue
            if workflow_id is not None and run.workflow_id != workflow_id:
                continue
            runs.append(run)
        runs.sort(key=lambda item: item.started_at, reverse=True)
        return runs[:limit]

    def save_run(self, run: Any) -> Path:
        path = self._workflow_host.path_for(run.run_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.run_to_dict(run), f, indent=2)
        tmp.replace(path)
        self.emit_run_update(self.run_update_payload(run))
        return path

    def emit_run_update(self, payload: dict[str, Any]) -> None:
        callback = self._workflow_host.on_run_update
        if callback is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(callback(dict(payload)))

    async def emit_step_event(
        self,
        run: Any,
        step: Any,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        callback = self._workflow_host.on_step_event
        if callback is None:
            return
        await callback(
            run,
            step,
            event_type,
            dict(payload or {}),
        )

    @classmethod
    def load_run_from_storage(
        cls,
        run_id: str,
        *,
        storage_dir: Path | None = None,
    ) -> Any | None:
        from teai_builder.agent.llm3.workflow_host import LLM3WorkflowHost

        service = cls(
            SimpleNamespace(
                workflow_host=LLM3WorkflowHost(
                    parallel_executor=SimpleNamespace(),
                    storage_dir=storage_dir,
                ),
                checkpoint_store=None,
            )
        )
        return service.load_run(run_id)

    @classmethod
    def list_runs_from_storage(
        cls,
        *,
        workflow_id: str | None = None,
        limit: int = 10,
        storage_dir: Path | None = None,
    ) -> list[Any]:
        from teai_builder.agent.llm3.workflow_host import LLM3WorkflowHost

        service = cls(
            SimpleNamespace(
                workflow_host=LLM3WorkflowHost(
                    parallel_executor=SimpleNamespace(),
                    storage_dir=storage_dir,
                ),
                checkpoint_store=None,
            )
        )
        return service.list_runs(workflow_id=workflow_id, limit=limit)
