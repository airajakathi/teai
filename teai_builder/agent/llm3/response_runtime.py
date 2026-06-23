"""Response finalization helpers owned by llm3."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from teai_builder.bus.events import OutboundMessage

from .event_emitter import OrchestrationEventEmitter
from .turn_runtime import LLM3TurnRuntime
from .types import (
    ExecutionBrief,
    ExecutionResult,
    ReviewDecision,
    UnifiedTurn,
    llm3_metadata_payload,
)


class LLM3ResponseRuntime:
    """Own response-ready lifecycle and llm3 metadata packaging."""

    def __init__(
        self,
        *,
        turn_runtime: LLM3TurnRuntime,
        event_emitter: OrchestrationEventEmitter,
    ) -> None:
        self.turn_runtime = turn_runtime
        self.event_emitter = event_emitter

    async def finalize_response(
        self,
        outbound: OutboundMessage,
        *,
        turn_id: str,
        turn: UnifiedTurn,
        mode: str | None,
        brief: ExecutionBrief | None,
        result: ExecutionResult | None,
        review: ReviewDecision | None,
        stop_reason: str,
        ephemeral: bool = False,
        on_response_ready: Callable[[], Awaitable[None] | None] | None = None,
    ) -> OutboundMessage:
        self.turn_runtime.mark_completed(turn_id)
        if on_response_ready is not None:
            maybe_awaitable = on_response_ready()
            if maybe_awaitable is not None:
                await maybe_awaitable
        self.event_emitter.emit(
            turn_id=turn.turn_id,
            session_key=turn.session_key,
            event_type="response_ready",
            payload={"stop_reason": stop_reason or "ok"},
        )
        outbound.metadata["_llm3"] = llm3_metadata_payload(
            turn=turn,
            mode=mode,
            brief=brief,
            result=result,
            review=review,
        )
        outbound.metadata["_llm3_state"] = self.turn_runtime.snapshot(turn_id)
        outbound.metadata["_llm3_events"] = self.event_emitter.summary(turn_id)
        if ephemeral:
            outbound.metadata["_stop_reason"] = stop_reason
        return outbound
