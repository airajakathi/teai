"""Turn lifecycle helpers owned by llm3."""

from __future__ import annotations

from teai_builder.bus.events import InboundMessage

from .executive import ExecutiveOrchestrator, ExecutiveTurnPlan
from .state_store import InMemoryOrchestrationStateStore
from .types import ExecutionBrief


class LLM3TurnRuntime:
    """Own turn-start state transitions around the executive plan."""

    def __init__(
        self,
        *,
        executive: ExecutiveOrchestrator | None = None,
        state_store: InMemoryOrchestrationStateStore | None = None,
    ) -> None:
        self.executive = executive or ExecutiveOrchestrator()
        self.state_store = state_store or InMemoryOrchestrationStateStore()

    def start_turn(
        self,
        msg: InboundMessage,
        *,
        turn_id: str,
        session_key: str,
    ) -> ExecutiveTurnPlan:
        plan = self.executive.prepare_turn(
            msg,
            turn_id=turn_id,
            session_key=session_key,
        )
        self.state_store.start_turn(plan.turn)
        return plan

    def record_execution_brief(self, brief: ExecutionBrief) -> None:
        self.state_store.record_execution_brief(brief)

    def mark_completed(self, turn_id: str) -> None:
        self.state_store.mark_completed(turn_id)

    def snapshot(self, turn_id: str) -> dict[str, object] | None:
        return self.state_store.snapshot(turn_id)
