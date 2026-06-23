"""Typed worker runtime wrapper for phase 3 llm3 orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkerTaskSpec:
    task: str
    label: str | None = None
    role: str | None = None
    model: str | None = None
    model_preset: str | None = None
    origin_channel: str = "cli"
    origin_chat_id: str = "direct"
    session_key: str | None = None
    origin_message_id: str | None = None
    temperature: float | None = None
    workspace_scope: Any | None = None
    owner_turn_id: str | None = None
    owner_request_id: str | None = None


@dataclass(frozen=True)
class WorkerLaunchResult:
    worker_id: str
    label: str
    launch_message: str


@dataclass(frozen=True)
class WorkerExecutionResult:
    worker_id: str
    label: str
    status: str
    final_output: str
    stop_reason: str | None = None
    error: str | None = None
    tool_events: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None


class WorkerRuntime:
    """Wrap the legacy subagent manager with typed worker contracts."""

    def __init__(
        self,
        manager: Any,
        on_background_worker_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._manager = manager
        self._on_background_worker_event = on_background_worker_event

    @property
    def max_concurrent_workers(self) -> int:
        return self._manager.max_concurrent_subagents

    def get_running_count(self) -> int:
        return self._manager.get_running_count()

    async def spawn(self, spec: WorkerTaskSpec) -> WorkerLaunchResult:
        record = await self._manager.spawn_worker(
            task=spec.task,
            label=spec.label,
            role=spec.role,
            model=getattr(spec, "model", None),
            model_preset=spec.model_preset,
            origin_channel=spec.origin_channel,
            origin_chat_id=spec.origin_chat_id,
            session_key=spec.session_key,
            origin_message_id=spec.origin_message_id,
            temperature=spec.temperature,
            workspace_scope=spec.workspace_scope,
            owner_turn_id=spec.owner_turn_id,
            owner_request_id=spec.owner_request_id,
            on_event=self._on_background_worker_event,
        )
        return WorkerLaunchResult(
            worker_id=record["worker_id"],
            label=record["label"],
            launch_message=record["launch_message"],
        )

    async def run(self, spec: WorkerTaskSpec) -> WorkerExecutionResult:
        record = await self._manager.run_worker(
            task=spec.task,
            label=spec.label,
            role=spec.role,
            model=getattr(spec, "model", None),
            model_preset=spec.model_preset,
            origin_channel=spec.origin_channel,
            origin_chat_id=spec.origin_chat_id,
            session_key=spec.session_key,
            origin_message_id=spec.origin_message_id,
            temperature=spec.temperature,
            workspace_scope=spec.workspace_scope,
        )
        return WorkerExecutionResult(
            worker_id=record["worker_id"],
            label=record["label"],
            status=record["status"],
            final_output=record["final_output"],
            stop_reason=record.get("stop_reason"),
            error=record.get("error"),
            tool_events=list(record.get("tool_events", [])),
            usage=dict(record.get("usage", {})),
        )
