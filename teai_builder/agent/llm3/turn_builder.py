"""Phase 1 helpers for canonical turn and execution brief construction."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from teai_builder.bus.events import InboundMessage
from teai_builder.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY

from .types import AttachmentRef, CapabilityRequest, ExecutionBrief, MediaInput, UnifiedTurn

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".gif"}


def _attachment_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    return "file"


def _capability_requests(msg: InboundMessage, attachments: list[AttachmentRef]) -> list[CapabilityRequest]:
    requested: list[CapabilityRequest] = []
    if attachments:
        requested.append(
            CapabilityRequest(capability="multimodal_input", source="inferred", required=False)
        )
    image_generation = (msg.metadata or {}).get("image_generation")
    if isinstance(image_generation, dict) and image_generation.get("enabled") is True:
        requested.append(
            CapabilityRequest(capability="image_generation", source="ui", required=True)
        )
    return requested


def build_unified_turn(
    msg: InboundMessage,
    *,
    turn_id: str,
    session_key: str,
) -> UnifiedTurn:
    """Build a canonical phase 1 turn object from the current inbound message."""

    attachments: list[AttachmentRef] = []
    image_inputs: list[MediaInput] = []
    audio_inputs: list[MediaInput] = []
    video_inputs: list[MediaInput] = []
    for index, path in enumerate(msg.media or []):
        attachment_id = f"att-{index}"
        kind = _attachment_kind(path)
        attachments.append(
            AttachmentRef(
                attachment_id=attachment_id,
                kind=kind,
                name=Path(path).name or path,
                path=path,
            )
        )
        media = MediaInput(
            media_id=f"media-{index}",
            kind=kind,
            path=path,
            attachment_id=attachment_id,
        )
        if kind == "image":
            image_inputs.append(media)
        elif kind == "audio":
            audio_inputs.append(media)
        elif kind == "video":
            video_inputs.append(media)
    metadata = dict(msg.metadata or {})
    workspace_scope = metadata.get(WORKSPACE_SCOPE_METADATA_KEY)
    return UnifiedTurn(
        turn_id=turn_id,
        session_key=session_key,
        channel=msg.channel,
        created_at=int(msg.timestamp.timestamp() * 1000),
        user_message=msg.content,
        message_kind="system" if msg.channel == "system" else "user",
        attachments=attachments,
        image_inputs=image_inputs,
        audio_inputs=audio_inputs,
        video_inputs=video_inputs,
        requested_capabilities=_capability_requests(msg, attachments),
        workspace_scope=dict(workspace_scope) if isinstance(workspace_scope, dict) else {},
        metadata=metadata,
    )


def build_execution_brief(
    turn: UnifiedTurn,
    *,
    mode: str,
) -> ExecutionBrief:
    """Build a bounded phase 1 execution brief from the canonical turn."""

    objective = turn.user_message.strip() or "Process the attached user input."
    constraints = ["Respect the active workspace scope."]
    if turn.workspace_scope:
        constraints.append("Do not operate outside the resolved workspace scope.")
    if turn.image_inputs or turn.audio_inputs or turn.video_inputs:
        constraints.append("Use attached media as part of the current user request.")
    allowed_capabilities = sorted(
        {
            "chat",
            *[item.capability for item in turn.requested_capabilities],
        }
    )
    return ExecutionBrief(
        request_id=f"req-{uuid.uuid4().hex[:10]}",
        turn_id=turn.turn_id,
        session_key=turn.session_key,
        mode=mode,
        created_at=int(time.time() * 1000),
        objective=objective,
        user_intent_summary=objective,
        success_criteria=[
            "Return a complete user-facing response for the current request.",
        ],
        constraints=constraints,
        allowed_capabilities=allowed_capabilities,
        workspace_scope=dict(turn.workspace_scope),
        metadata={
            "attachment_count": len(turn.attachments),
            "has_media": bool(turn.image_inputs or turn.audio_inputs or turn.video_inputs),
        },
    )
