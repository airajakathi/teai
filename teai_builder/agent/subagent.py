"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from teai_builder.agent.hook import AgentHook, AgentHookContext
from teai_builder.agent.runner import AgentRunner, AgentRunSpec
from teai_builder.agent.tools.context import ToolContext
from teai_builder.agent.tools.file_state import FileStates
from teai_builder.agent.tools.loader import ToolLoader
from teai_builder.agent.tools.registry import ToolRegistry
from teai_builder.security.workspace_access import (
    WorkspaceScope,
    bind_workspace_scope,
    reset_workspace_scope,
    workspace_sandbox_status,
)
from teai_builder.bus.events import InboundMessage
from teai_builder.bus.queue import MessageBus
from teai_builder.config.schema import AgentDefaults, ToolsConfig
from teai_builder.providers.base import LLMProvider
from teai_builder.utils.prompt_templates import render_template


@dataclass(slots=True)
class SubagentStatus:
    """Real-time status of a running subagent."""

    task_id: str
    label: str
    task_description: str
    started_at: float          # time.monotonic()
    phase: str = "initializing"  # initializing | awaiting_tools | tools_completed | final_response | done | error
    iteration: int = 0
    tool_events: list = field(default_factory=list)   # [{name, status, detail}, ...]
    usage: dict = field(default_factory=dict)          # token usage
    stop_reason: str | None = None
    error: str | None = None


class _SubagentHook(AgentHook):
    """Hook for subagent execution — logs tool calls and updates status."""

    def __init__(self, task_id: str, status: SubagentStatus | None = None) -> None:
        super().__init__()
        self._task_id = task_id
        self._status = status

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Subagent [{}] executing: {} with arguments: {}",
                self._task_id, tool_call.name, args_str,
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is None:
            return
        self._status.iteration = context.iteration
        self._status.tool_events = list(context.tool_events)
        self._status.usage = dict(context.usage)
        if context.error:
            self._status.error = str(context.error)


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        max_tool_result_chars: int,
        model: str | None = None,
        tools_config: ToolsConfig | None = None,
        restrict_to_workspace: bool = False,
        disabled_skills: list[str] | None = None,
        max_iterations: int | None = None,
        max_concurrent_subagents: int | None = None,
        llm_wall_timeout_for_session: Callable[[str | None], float | None] | None = None,
        preset_snapshot_loader: "Callable[[str], Any] | None" = None,
    ):
        defaults = AgentDefaults()
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.tools_config = tools_config or ToolsConfig()
        self.max_tool_result_chars = max_tool_result_chars
        self.restrict_to_workspace = restrict_to_workspace
        self.disabled_skills = set(disabled_skills or [])
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else defaults.max_tool_iterations
        )
        self.max_concurrent_subagents = (
            max_concurrent_subagents
            if max_concurrent_subagents is not None
            else defaults.max_concurrent_subagents
        )
        self.runner = AgentRunner(provider)
        self._preset_snapshot_loader = preset_snapshot_loader
        self._llm_wall_timeout_for_session = llm_wall_timeout_for_session
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_statuses: dict[str, SubagentStatus] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    def _subagent_tools_config(self) -> ToolsConfig:
        """Build a ToolsConfig scoped for subagent use."""
        return ToolsConfig(
            exec=self.tools_config.exec,
            web=self.tools_config.web,
            restrict_to_workspace=self.restrict_to_workspace,
            governance=self.tools_config.governance,
        )

    def _build_tools(
        self,
        workspace: Path | None = None,
        tools_config: ToolsConfig | None = None,
    ) -> ToolRegistry:
        """Build an isolated subagent tool registry via ToolLoader."""
        root = self.workspace if workspace is None else workspace
        registry = ToolRegistry()
        cfg = tools_config if tools_config is not None else self._subagent_tools_config()
        ctx = ToolContext(
            config=cfg,
            workspace=str(root.resolve()),
            file_state_store=FileStates(),
            worker_runtime=None,
            workspace_sandbox=workspace_sandbox_status(
                restrict_to_workspace=cfg.restrict_to_workspace,
                workspace=root,
                sandbox_backend=cfg.exec.sandbox,
                strict_execution=cfg.exec.strict_sandbox,
            ),
        )
        ToolLoader().load(ctx, registry, scope="subagent")
        return registry

    def set_provider(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model
        self.runner.provider = provider

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        role: str | None = None,
        model: str | None = None,
        model_preset: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
        temperature: float | None = None,
        workspace_scope: WorkspaceScope | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        record = await self.spawn_worker(
            task=task,
            label=label,
            role=role,
            model=model,
            model_preset=model_preset,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            origin_message_id=origin_message_id,
            temperature=temperature,
            workspace_scope=workspace_scope,
        )
        return record["launch_message"]

    async def spawn_worker(
        self,
        task: str,
        label: str | None = None,
        role: str | None = None,
        model: str | None = None,
        model_preset: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
        temperature: float | None = None,
        workspace_scope: WorkspaceScope | None = None,
        owner_turn_id: str | None = None,
        owner_request_id: str | None = None,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, str]:
        """Spawn a subagent and return a typed worker launch record."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id, "session_key": session_key}

        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
        )
        self._task_statuses[task_id] = status

        bg_task = asyncio.create_task(
            self._run_subagent(
                task_id,
                task,
                display_label,
                origin,
                status,
                origin_message_id,
                temperature,
                workspace_scope,
                owner_turn_id=owner_turn_id,
                owner_request_id=owner_request_id,
                on_event=on_event,
                role=role,
                model=model,
                model_preset=model_preset,
            )
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            self._task_statuses.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        launch_message = (
            f"Subagent [{display_label}] started (id: {task_id}). "
            "I'll notify you when it completes."
        )
        if on_event is not None:
            await on_event(
                "worker_task_started",
                {
                    "worker_id": task_id,
                    "label": display_label,
                    "status": "running",
                    "task": task,
                    "origin_channel": origin_channel,
                    "origin_chat_id": origin_chat_id,
                    "session_key": session_key,
                    "owner_turn_id": owner_turn_id,
                    "owner_request_id": owner_request_id,
                },
            )
        return {
            "worker_id": task_id,
            "label": display_label,
            "launch_message": launch_message,
        }

    async def run_worker(
        self,
        task: str,
        label: str | None = None,
        role: str | None = None,
        model: str | None = None,
        model_preset: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
        temperature: float | None = None,
        workspace_scope: WorkspaceScope | None = None,
    ) -> dict[str, Any]:
        """Execute a worker inline and return a typed execution result."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
        )
        self._task_statuses[task_id] = status
        try:
            return await self._execute_subagent(
                task_id=task_id,
                task=task,
                label=display_label,
                origin={
                    "channel": origin_channel,
                    "chat_id": origin_chat_id,
                    "session_key": session_key,
                },
                status=status,
                origin_message_id=origin_message_id,
                temperature=temperature,
                workspace_scope=workspace_scope,
                role=role,
                model=model,
                model_preset=model_preset,
            )
        finally:
            self._task_statuses.pop(task_id, None)

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        status: SubagentStatus,
        origin_message_id: str | None = None,
        temperature: float | None = None,
        workspace_scope: WorkspaceScope | None = None,
        owner_turn_id: str | None = None,
        owner_request_id: str | None = None,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        *,
        role: str | None = None,
        model: str | None = None,
        model_preset: str | None = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        outcome = await self._execute_subagent(
            task_id=task_id,
            task=task,
            label=label,
            origin=origin,
            status=status,
            origin_message_id=origin_message_id,
            temperature=temperature,
            workspace_scope=workspace_scope,
            role=role,
            model=model,
            model_preset=model_preset,
        )
        if on_event is not None:
            await on_event(
                "worker_task_finished",
                {
                    "worker_id": task_id,
                    "label": label,
                    "status": outcome["status"],
                    "error": outcome.get("error"),
                    "stop_reason": outcome.get("stop_reason"),
                    "task": task,
                    "origin_channel": origin.get("channel"),
                    "origin_chat_id": origin.get("chat_id"),
                    "session_key": origin.get("session_key"),
                    "owner_turn_id": owner_turn_id,
                    "owner_request_id": owner_request_id,
                },
            )
        await self._announce_result(
            task_id,
            label,
            task,
            outcome["final_output"],
            origin,
            "ok" if outcome["status"] == "completed" else "error",
            origin_message_id,
            owner_turn_id=owner_turn_id,
            owner_request_id=owner_request_id,
        )

    async def _execute_subagent(
        self,
        *,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        status: SubagentStatus,
        origin_message_id: str | None = None,
        temperature: float | None = None,
        workspace_scope: WorkspaceScope | None = None,
        role: str | None = None,
        model: str | None = None,
        model_preset: str | None = None,
    ) -> dict[str, Any]:
        """Execute a worker task and return a structured outcome."""

        async def _on_checkpoint(payload: dict) -> None:
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)

        # Resolve model and runner for this spawn.
        # If a model_preset is set and we have a loader, resolve it to get the
        # correct provider snapshot. Create a fresh runner when the provider
        # differs from the shared one (safe for concurrent spawns on different
        # providers). Explicit temperature argument always wins over preset default.
        run_model = model or self.model
        run_runner = self.runner
        run_temperature = temperature

        if model_preset and self._preset_snapshot_loader:
            try:
                snapshot = self._preset_snapshot_loader(model_preset)
                run_model = snapshot.model
                if snapshot.provider is not self.runner.provider:
                    run_runner = AgentRunner(snapshot.provider)
                if run_temperature is None and hasattr(snapshot, "provider"):
                    gen = getattr(snapshot.provider, "generation", None)
                    if gen is not None:
                        run_temperature = getattr(gen, "temperature", None)
            except Exception as e:
                logger.warning(
                    "Subagent [{}] could not resolve model_preset {!r}: {}. "
                    "Falling back to default model.",
                    task_id, model_preset, e,
                )

        try:
            root = workspace_scope.project_path if workspace_scope is not None else self.workspace
            cfg = None
            if workspace_scope is not None:
                cfg = self._subagent_tools_config()
                cfg.restrict_to_workspace = workspace_scope.restrict_to_workspace
            tools = self._build_tools(workspace=root, tools_config=cfg)
            system_prompt = self._build_subagent_prompt(workspace=root, role=role)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            sess_key = origin.get("session_key")
            llm_timeout = (
                self._llm_wall_timeout_for_session(sess_key)
                if self._llm_wall_timeout_for_session
                else None
            )
            token = bind_workspace_scope(workspace_scope) if workspace_scope is not None else None
            try:
                result = await run_runner.run(AgentRunSpec(
                    initial_messages=messages,
                    tools=tools,
                    model=run_model,
                    temperature=run_temperature,
                    max_iterations=self.max_iterations,
                    max_tool_result_chars=self.max_tool_result_chars,
                    hook=_SubagentHook(task_id, status),
                    max_iterations_message="Task completed but no final response was generated.",
                    finalize_on_max_iterations=False,
                    error_message=None,
                    fail_on_tool_error=True,
                    checkpoint_callback=_on_checkpoint,
                    session_key=sess_key,
                    workspace=root,
                    llm_timeout_s=llm_timeout,
                ))
            finally:
                if token is not None:
                    reset_workspace_scope(token)
            status.phase = "done"
            status.stop_reason = result.stop_reason
            status.tool_events = list(result.tool_events)

            if result.stop_reason == "tool_error":
                final_output = self._format_partial_progress(result)
                return {
                    "worker_id": task_id,
                    "label": label,
                    "status": "failed",
                    "final_output": final_output,
                    "stop_reason": result.stop_reason,
                    "error": result.error or "Tool execution failed.",
                    "tool_events": list(result.tool_events),
                    "usage": dict(status.usage),
                }
            if result.stop_reason == "error":
                return {
                    "worker_id": task_id,
                    "label": label,
                    "status": "failed",
                    "final_output": result.error or "Error: subagent execution failed.",
                    "stop_reason": result.stop_reason,
                    "error": result.error or "Error: subagent execution failed.",
                    "tool_events": list(result.tool_events),
                    "usage": dict(status.usage),
                }

            final_result = result.final_content or "Task completed but no final response was generated."
            logger.info("Subagent [{}] completed successfully", task_id)
            return {
                "worker_id": task_id,
                "label": label,
                "status": "completed",
                "final_output": final_result,
                "stop_reason": result.stop_reason,
                "error": None,
                "tool_events": list(result.tool_events),
                "usage": dict(status.usage),
            }

        except Exception as e:
            status.phase = "error"
            status.error = str(e)
            logger.exception("Subagent [{}] failed", task_id)
            return {
                "worker_id": task_id,
                "label": label,
                "status": "failed",
                "final_output": f"Error: {e}",
                "stop_reason": "error",
                "error": str(e),
                "tool_events": list(status.tool_events),
                "usage": dict(status.usage),
            }

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
        origin_message_id: str | None = None,
        *,
        owner_turn_id: str | None = None,
        owner_request_id: str | None = None,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = render_template(
            "agent/subagent_announce.md",
            label=label,
            status_text=status_text,
            task=task,
            result=result,
        )

        # Inject as system message to trigger main agent.
        # Use session_key_override to align with the main agent's effective
        # session key (which accounts for unified sessions) so the result is
        # routed to the correct pending queue (mid-turn injection) instead of
        # being dispatched as a competing independent task.
        override = origin.get("session_key") or f"{origin['channel']}:{origin['chat_id']}"
        metadata: dict[str, Any] = {
            "injected_event": "subagent_result",
            "subagent_task_id": task_id,
            "origin_channel": origin.get("channel"),
            "origin_chat_id": origin.get("chat_id"),
        }
        if origin_message_id:
            metadata["origin_message_id"] = origin_message_id
        if owner_turn_id is not None:
            metadata["owner_turn_id"] = owner_turn_id
        if owner_request_id is not None:
            metadata["owner_request_id"] = owner_request_id
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
            session_key_override=override,
            metadata=metadata,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    @staticmethod
    def _format_partial_progress(result) -> str:
        completed = [e for e in result.tool_events if e["status"] == "ok"]
        failure = next((e for e in reversed(result.tool_events) if e["status"] == "error"), None)
        lines: list[str] = []
        if completed:
            lines.append("Completed steps:")
            for event in completed[-3:]:
                lines.append(f"- {event['name']}: {event['detail']}")
        if failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {failure['name']}: {failure['detail']}")
        if result.error and not failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {result.error}")
        return "\n".join(lines) or (result.error or "Error: subagent execution failed.")

    def _build_subagent_prompt(self, workspace: Path | None = None, role: str | None = None) -> str:
        """Build a focused system prompt for the subagent."""
        from teai_builder.agent.context import ContextBuilder
        from teai_builder.agent.skills import SkillsLoader
        from teai_builder.utils.prompt_templates import _TEMPLATES_ROOT

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        root = workspace or self.workspace
        skills_summary = SkillsLoader(
            root,
            disabled_skills=self.disabled_skills,
        ).build_skills_summary()

        role_content: str | None = None
        if role:
            safe_role = role.replace("/", "").replace("..", "").replace("\\", "")
            role_file = _TEMPLATES_ROOT / "agent" / "roles" / f"{safe_role}.md"
            if role_file.is_file():
                role_content = role_file.read_text(encoding="utf-8")
            else:
                logger.warning("Subagent role template not found: {}", role_file)

        return render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(root),
            skills_summary=skills_summary or "",
            role_content=role_content or "",
        )

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    def get_running_count_by_session(self, session_key: str) -> int:
        """Return the number of currently running subagents for a session."""
        tids = self._session_tasks.get(session_key, set())
        return sum(
            1 for tid in tids
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        )
