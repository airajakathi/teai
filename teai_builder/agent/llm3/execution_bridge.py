"""Phase 1 bridge from LLM3 contracts to the current execution runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .types import ExecutionBrief, ExecutionResult


@dataclass(frozen=True)
class BridgeExecutionOutcome:
    """Structured execution result plus the raw phase 1 loop payload."""

    result: ExecutionResult
    final_content: str
    tools_used: list[str] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    all_messages: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    had_injections: bool = False


class ExecutionBridge:
    """Adapt the current loop executor to the phase 1 execution contract."""

    async def execute(
        self,
        brief: ExecutionBrief,
        executor: Callable[[], Awaitable[tuple[str, list[str], list[dict[str, Any]], str, bool]]],
        tool_events_supplier: Callable[[], list[dict[str, str]]] | None = None,
    ) -> BridgeExecutionOutcome:
        final_content, tools_used, all_messages, stop_reason, had_injections = await executor()
        tool_events = list(tool_events_supplier() if tool_events_supplier is not None else [])
        status = "completed"
        if stop_reason in {"error", "tool_error"}:
            status = "failed"
        elif stop_reason in {"max_iterations", "cancelled"}:
            status = "partial" if stop_reason == "max_iterations" else "cancelled"
        summary = (
            f"Execution completed with stop_reason={stop_reason or 'ok'} "
            f"and {len(tools_used)} tool call(s)."
        )
        result = ExecutionResult(
            request_id=brief.request_id,
            turn_id=brief.turn_id,
            session_key=brief.session_key,
            status=status,
            summary=summary,
            evidence=[
                {"kind": "stop_reason", "value": stop_reason or "ok"},
                {"kind": "tools_used", "value": list(tools_used)},
                {"kind": "tool_event_count", "value": len(tool_events)},
                {"kind": "message_count", "value": len(all_messages)},
            ],
            final_user_safe_answer_candidate=final_content,
            metadata={
                "mode": brief.mode,
                "had_injections": had_injections,
                "tool_event_count": len(tool_events),
            },
        )
        return BridgeExecutionOutcome(
            result=result,
            final_content=final_content,
            tools_used=list(tools_used),
            tool_events=list(tool_events),
            all_messages=list(all_messages),
            stop_reason=stop_reason,
            had_injections=had_injections,
        )
