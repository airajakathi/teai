"""Phase 2 executive wrapper for the LLM3 orchestration runtime."""

from __future__ import annotations

from dataclasses import dataclass

from teai_builder.bus.events import InboundMessage

from .mode_selector import select_mode
from .turn_builder import build_execution_brief, build_unified_turn
from .types import ExecutionBrief, OrchestrationMode, UnifiedTurn


@dataclass(frozen=True)
class ExecutiveTurnPlan:
    """Minimal phase 2 executive plan for one turn."""

    turn: UnifiedTurn
    mode: OrchestrationMode
    brief: ExecutionBrief


class ExecutiveOrchestrator:
    """Prepare canonical turn contracts before the legacy executor runs."""

    def prepare_turn(
        self,
        msg: InboundMessage,
        *,
        turn_id: str,
        session_key: str,
    ) -> ExecutiveTurnPlan:
        turn = build_unified_turn(
            msg,
            turn_id=turn_id,
            session_key=session_key,
        )
        mode = select_mode(turn)
        brief = build_execution_brief(turn, mode=mode)
        return ExecutiveTurnPlan(turn=turn, mode=mode, brief=brief)
