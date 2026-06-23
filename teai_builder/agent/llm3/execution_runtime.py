"""Execution and review lifecycle helpers owned by llm3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from .execution_bridge import BridgeExecutionOutcome, ExecutionBridge
from .review import build_review_decision
from .state_store import InMemoryOrchestrationStateStore
from .types import ExecutionBrief, ReviewDecision


@dataclass(frozen=True)
class LLM3ExecutionRuntimeOutcome:
    execution: BridgeExecutionOutcome
    review: ReviewDecision


class LLM3ExecutionRuntime:
    """Own bridged execution, review derivation, and state recording."""

    def __init__(
        self,
        *,
        execution_bridge: ExecutionBridge | None = None,
        state_store: InMemoryOrchestrationStateStore | None = None,
        review_builder: Callable[[object], ReviewDecision] | None = None,
    ) -> None:
        self.execution_bridge = execution_bridge or ExecutionBridge()
        self.state_store = state_store or InMemoryOrchestrationStateStore()
        self.review_builder = review_builder or build_review_decision

    async def execute(
        self,
        brief: ExecutionBrief,
        executor: Callable[[], Awaitable[tuple[str, list[str], list[dict], str, bool]]],
        *,
        tool_events_supplier: Callable[[], list[dict[str, str]]] | None = None,
    ) -> LLM3ExecutionRuntimeOutcome:
        execution = await self.execution_bridge.execute(
            brief,
            executor,
            tool_events_supplier=tool_events_supplier,
        )
        self.state_store.record_execution_result(execution.result)
        review = self.review_builder(execution.result)
        self.state_store.record_review(review)
        return LLM3ExecutionRuntimeOutcome(
            execution=execution,
            review=review,
        )
