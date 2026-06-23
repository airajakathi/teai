"""Loop-level llm3 runtime bundle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .event_emitter import OrchestrationEventEmitter
from .event_runtime import LLM3EventRuntime
from .execution_runtime import LLM3ExecutionRuntime
from .response_runtime import LLM3ResponseRuntime
from .runner_runtime import LLM3RunnerRuntime
from .state_store import InMemoryOrchestrationStateStore
from .task_graph_runtime import LLM3TaskGraphRuntime
from .turn_runtime import LLM3TurnRuntime
from .workflow_runtime import WorkflowGraphRuntime


@dataclass(frozen=True)
class LLM3LoopRuntime:
    event_emitter: OrchestrationEventEmitter
    event_runtime: LLM3EventRuntime
    state_store: InMemoryOrchestrationStateStore
    turn_runtime: LLM3TurnRuntime
    execution_runtime: LLM3ExecutionRuntime
    response_runtime: LLM3ResponseRuntime
    workflow_runtime: WorkflowGraphRuntime
    task_graph_runtime: LLM3TaskGraphRuntime
    runner_runtime: LLM3RunnerRuntime

    @classmethod
    def build(
        cls,
        *,
        workspace: Path,
        publish_runtime_event: Callable[..., Awaitable[None]],
        run_payload_builder: Callable[[Any], dict[str, Any]],
    ) -> "LLM3LoopRuntime":
        llm3_runtime_dir = workspace / ".teai_builder" / "llm3"
        event_emitter = OrchestrationEventEmitter(
            storage_dir=llm3_runtime_dir / "events",
        )
        state_store = InMemoryOrchestrationStateStore(
            storage_dir=llm3_runtime_dir / "state",
        )
        event_runtime = LLM3EventRuntime(
            event_emitter=event_emitter,
            publish_runtime_event=publish_runtime_event,
        )
        turn_runtime = LLM3TurnRuntime(
            state_store=state_store,
        )
        execution_runtime = LLM3ExecutionRuntime(
            state_store=state_store,
        )
        response_runtime = LLM3ResponseRuntime(
            turn_runtime=turn_runtime,
            event_emitter=event_emitter,
        )
        workflow_runtime = WorkflowGraphRuntime(
            state_store=state_store,
            run_payload_builder=run_payload_builder,
        )
        return cls(
            event_emitter=event_emitter,
            event_runtime=event_runtime,
            state_store=state_store,
            turn_runtime=turn_runtime,
            execution_runtime=execution_runtime,
            response_runtime=response_runtime,
            workflow_runtime=workflow_runtime,
            task_graph_runtime=LLM3TaskGraphRuntime(
                state_store=state_store,
                event_runtime=event_runtime,
                workflow_runtime=workflow_runtime,
            ),
            runner_runtime=LLM3RunnerRuntime(),
        )
