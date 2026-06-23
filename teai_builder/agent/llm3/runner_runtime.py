"""Shared agent runner bridge owned by llm3."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from loguru import logger

from teai_builder.agent.hook import AgentHook, CompositeHook
from teai_builder.agent.progress_hook import AgentProgressHook
from teai_builder.agent.runner import _MAX_INJECTIONS_PER_TURN, AgentRunResult, AgentRunSpec
from teai_builder.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from teai_builder.agent.tools.file_state import bind_file_states, reset_file_states
from teai_builder.agent.tools.registry import ToolRegistry
from teai_builder.bus.events import InboundMessage
from teai_builder.security.workspace_access import bind_workspace_scope, reset_workspace_scope
from teai_builder.session import turn_continuation
from teai_builder.session.goal_state import (
    goal_state_runtime_lines,
    runner_wall_llm_timeout_s,
    sustained_goal_active,
)
from teai_builder.utils.runtime import SUSTAINED_GOAL_CONTINUE_PROMPT


class LLM3RunnerRuntime:
    """Own the shared llm runner invocation used by the loop."""

    async def execute(
        self,
        loop: Any,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
        *,
        session: Any | None = None,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
        pending_queue: asyncio.Queue | None = None,
        ephemeral: bool = False,
        tools: ToolRegistry | None = None,
    ) -> AgentRunResult:
        loop._sync_subagent_runtime_limits()

        loop_hook = AgentProgressHook(
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            metadata=metadata,
            session_key=session_key,
            tool_hint_max_length=loop.tool_hint_max_length,
            set_tool_context=loop._set_tool_context,
            on_iteration=lambda iteration: setattr(loop, "_current_iteration", iteration),
        )
        hook: AgentHook = loop_hook
        if not ephemeral and loop._extra_hooks:
            hook = CompositeHook([loop_hook] + loop._extra_hooks)

        async def _checkpoint(payload: dict[str, Any]) -> None:
            if session is None:
                return
            loop._set_runtime_checkpoint(session, payload)

        async def _drain_pending(*, limit: int = _MAX_INJECTIONS_PER_TURN) -> list[dict[str, Any]]:
            if pending_queue is None:
                return []

            def _to_user_message(pending_msg: InboundMessage) -> dict[str, Any]:
                content = pending_msg.content
                media = pending_msg.media if pending_msg.media else None
                if media:
                    content, media = loop._prepare_message_media(content, media)
                    media = media or None
                user_content = loop.context._build_user_content(content, media)
                return {"role": "user", "content": user_content}

            items: list[dict[str, Any]] = []
            while len(items) < limit:
                try:
                    items.append(_to_user_message(pending_queue.get_nowait()))
                except asyncio.QueueEmpty:
                    break

            if (
                not items
                and session is not None
                and loop.subagents.get_running_count_by_session(session.key) > 0
            ):
                try:
                    msg = await asyncio.wait_for(pending_queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Timeout waiting for sub-agent completion in session {}",
                        session.key,
                    )
                    return items
                items.append(_to_user_message(msg))
                while len(items) < limit:
                    try:
                        items.append(_to_user_message(pending_queue.get_nowait()))
                    except asyncio.QueueEmpty:
                        break

            return items

        active_session_key = session.key if session else session_key
        effective_scope = loop.workspace_scopes.for_turn(
            channel=channel,
            message_metadata=metadata,
            session_metadata=session.metadata if session is not None else None,
        )
        request_ctx = RequestContext(
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            session_key=active_session_key,
            metadata=dict(metadata or {}),
        )
        file_state_token = bind_file_states(loop._file_state_store.for_session(active_session_key))
        request_token = bind_request_context(request_ctx)
        workspace_token = bind_workspace_scope(effective_scope)
        goal_lines = goal_state_runtime_lines(session.metadata if session is not None else None)
        goal_continue = (
            "You have an active sustained goal:\n\n"
            + "\n".join(goal_lines)
            + "\n\nPlease continue working toward the objective using your tools, "
            "or call complete_goal if the work is truly finished."
        ) if goal_lines else SUSTAINED_GOAL_CONTINUE_PROMPT
        session_metadata = session.metadata if session is not None else None
        try:
            loop._last_run_tool_events = []
            result = await loop.runner.run(AgentRunSpec(
                initial_messages=initial_messages,
                tools=tools or loop.tools,
                model=loop.model,
                max_iterations=loop.max_iterations,
                max_tool_result_chars=loop.max_tool_result_chars,
                hook=hook,
                error_message="Sorry, I encountered an error calling the AI model.",
                concurrent_tools=True,
                workspace=effective_scope.project_path,
                session_key=session.key if session else None,
                context_window_tokens=loop.context_window_tokens,
                context_block_limit=loop.context_block_limit,
                provider_retry_mode=loop.provider_retry_mode,
                progress_callback=on_progress,
                stream_progress_deltas=on_stream is not None,
                retry_wait_callback=on_retry_wait,
                checkpoint_callback=_checkpoint,
                injection_callback=_drain_pending,
                llm_timeout_s=runner_wall_llm_timeout_s(
                    loop.sessions,
                    session.key if session is not None else session_key,
                    metadata=session_metadata,
                    message_metadata=metadata,
                ),
                goal_active_predicate=lambda: sustained_goal_active(session.metadata) if session is not None else False,
                goal_continue_message=goal_continue,
                finalize_on_max_iterations=turn_continuation.should_finalize_on_max_iterations(
                    pending_queue_available=pending_queue is not None and session is not None,
                    session_metadata=session_metadata,
                    message_metadata=metadata,
                ),
            ))
        finally:
            reset_workspace_scope(workspace_token)
            reset_request_context(request_token)
            reset_file_states(file_state_token)
        loop._last_usage = result.usage
        loop._last_run_tool_events = list(result.tool_events)
        if result.stop_reason == "max_iterations":
            logger.warning("Max iterations ({}) reached", loop.max_iterations)
            should_stream = turn_continuation.should_stream_budget_response(
                stop_reason=result.stop_reason,
                pending_queue_available=pending_queue is not None and session is not None,
                session_metadata=session_metadata,
                message_metadata=metadata,
            )
            if on_stream and on_stream_end and should_stream:
                await on_stream(result.final_content or "")
                await on_stream_end(resuming=False)
        elif result.stop_reason == "error":
            logger.error("LLM returned error: {}", (result.final_content or "")[:200])
        return result
