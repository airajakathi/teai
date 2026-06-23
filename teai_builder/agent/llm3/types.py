"""Shared phase 1 orchestration types for the LLM3 runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

OrchestrationMode = Literal["direct", "assisted", "delegated", "workflow"]
ExecutionStatus = Literal["completed", "partial", "failed", "cancelled"]
ReviewAction = Literal["accept", "continue", "retry", "revise", "ask_user", "escalate"]


@dataclass(frozen=True)
class AttachmentRef:
    attachment_id: str
    kind: str
    name: str
    path: str
    source: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaInput:
    media_id: str
    kind: str
    path: str
    attachment_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityRequest:
    capability: str
    source: str
    required: bool = False


@dataclass(frozen=True)
class UnifiedTurn:
    turn_id: str
    session_key: str
    channel: str
    created_at: int
    user_message: str
    message_kind: str
    attachments: list[AttachmentRef] = field(default_factory=list)
    image_inputs: list[MediaInput] = field(default_factory=list)
    audio_inputs: list[MediaInput] = field(default_factory=list)
    video_inputs: list[MediaInput] = field(default_factory=list)
    requested_capabilities: list[CapabilityRequest] = field(default_factory=list)
    workspace_scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionBrief:
    request_id: str
    turn_id: str
    session_key: str
    mode: OrchestrationMode
    created_at: int
    objective: str
    user_intent_summary: str
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    allowed_capabilities: list[str] = field(default_factory=list)
    workspace_scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    turn_id: str
    session_key: str
    status: ExecutionStatus
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    final_user_safe_answer_candidate: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewDecision:
    review_id: str
    turn_id: str
    request_id: str
    decision: ReviewAction
    rationale: str
    unmet_criteria: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def llm3_metadata_payload(
    *,
    turn: UnifiedTurn | None = None,
    mode: OrchestrationMode | None = None,
    brief: ExecutionBrief | None = None,
    result: ExecutionResult | None = None,
    review: ReviewDecision | None = None,
) -> dict[str, Any]:
    """Build a concise metadata payload for debugging and WebUI consumers."""

    payload: dict[str, Any] = {}
    if turn is not None:
        payload["turn_id"] = turn.turn_id
    if mode is not None:
        payload["mode"] = mode
    if brief is not None:
        payload["request_id"] = brief.request_id
        payload["objective"] = brief.objective
    if result is not None:
        payload["status"] = result.status
    if review is not None:
        payload["review"] = review.decision
    return payload
