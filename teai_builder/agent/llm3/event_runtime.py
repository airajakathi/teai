"""Event emission helpers owned by llm3."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .event_emitter import OrchestrationEventEmitter


class LLM3EventRuntime:
    """Own local event recording and optional runtime event publishing."""

    def __init__(
        self,
        *,
        event_emitter: OrchestrationEventEmitter,
        publish_runtime_event: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._event_emitter = event_emitter
        self._publish_runtime_event = publish_runtime_event

    def emit(
        self,
        *,
        turn_id: str,
        session_key: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._event_emitter.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type=event_type,
            payload=payload,
        )

    async def record(
        self,
        *,
        turn_id: str,
        session_key: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.emit(
            turn_id=turn_id,
            session_key=session_key,
            event_type=event_type,
            payload=payload,
        )
        if (
            self._publish_runtime_event is None
            or channel is None
            or chat_id is None
        ):
            return
        await self._publish_runtime_event(
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
            metadata=metadata,
            event_type=event_type,
            payload=payload,
        )
