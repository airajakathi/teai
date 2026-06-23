"""Phase 1 deterministic orchestration-mode selection."""

from __future__ import annotations

from .types import OrchestrationMode, UnifiedTurn

_WORKFLOW_HINTS = (
    "build",
    "create app",
    "full project",
    "multi-step",
    "workflow",
    "architecture",
)
_ASSISTED_HINTS = (
    "implement",
    "fix",
    "refactor",
    "update",
    "analyze",
    "audit",
    "debug",
    "generate",
)


def select_mode(turn: UnifiedTurn) -> OrchestrationMode:
    """Select a phase 1 orchestration mode.

    Phase 1 keeps this deterministic and conservative. It only escalates to
    `workflow` when the request strongly signals a large build/planning task,
    otherwise it chooses `assisted` when attached media or action-oriented
    language is present, and falls back to `direct`.
    """

    if turn.message_kind != "user":
        return "direct"
    text = turn.user_message.lower()
    if turn.image_inputs or turn.audio_inputs or turn.video_inputs or turn.attachments:
        return "assisted"
    if any(hint in text for hint in _WORKFLOW_HINTS):
        return "workflow"
    if any(hint in text for hint in _ASSISTED_HINTS):
        return "assisted"
    return "direct"
