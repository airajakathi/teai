"""Spawn tool for creating background subagents."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.context import ContextAware, RequestContext
from teai_builder.agent.tools.schema import NumberSchema, StringSchema, tool_parameters_schema
from teai_builder.security.workspace_access import current_workspace_scope

if TYPE_CHECKING:
    from teai_builder.agent.llm3.worker_runtime import WorkerRuntime
    from teai_builder.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the subagent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
        role=StringSchema(
            "AI employee role for this subagent. Loads a specialized expertise prompt "
            "with research and verification checklists. "
            "One of: architect, designer, frontend_engineer, backend_engineer, "
            "devops_engineer, qa_engineer."
        ),
        model_preset=StringSchema(
            "Named model preset from config modelPresets to use for this subagent. "
            "Defaults to the main agent preset. Recommended mapping: "
            "architect→reasoning, frontend_engineer/backend_engineer/devops_engineer/qa_engineer→coding, "
            "designer→primary."
        ),
        temperature=NumberSchema(
            description=(
                "Optional sampling temperature for the subagent "
                "(0.0 = deterministic, higher = more creative). "
                "Overrides the model preset temperature when set. "
                "Defaults to the preset or provider configured temperature."
            ),
            minimum=0.0,
            maximum=2.0,
        ),
        required=["task"],
    )
)
class SpawnTool(Tool, ContextAware):
    """Tool to spawn a subagent for background task execution."""

    def __init__(
        self,
        manager: "SubagentManager | None" = None,
        worker_runtime: "WorkerRuntime | None" = None,
    ):
        self._manager = manager
        self._worker_runtime = worker_runtime
        self._origin_channel: ContextVar[str] = ContextVar("spawn_origin_channel", default="cli")
        self._origin_chat_id: ContextVar[str] = ContextVar("spawn_origin_chat_id", default="direct")
        self._session_key: ContextVar[str] = ContextVar("spawn_session_key", default="cli:direct")
        self._origin_message_id: ContextVar[str | None] = ContextVar(
            "spawn_origin_message_id",
            default=None,
        )
        self._request_metadata: ContextVar[dict[str, Any]] = ContextVar(
            "spawn_request_metadata",
            default={},
        )

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(
            manager=ctx.subagent_manager,
            worker_runtime=getattr(ctx, "worker_runtime", None),
        )

    def set_context(self, ctx: RequestContext) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel.set(ctx.channel)
        self._origin_chat_id.set(ctx.chat_id)
        self._session_key.set(ctx.session_key or f"{ctx.channel}:{ctx.chat_id}")
        self._origin_message_id.set(ctx.message_id)
        self._request_metadata.set(dict(ctx.metadata or {}))

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "Use `role` to assign a specialized AI employee identity (architect, designer, "
            "frontend_engineer, backend_engineer, devops_engineer, qa_engineer). "
            "Use `model_preset` to run the subagent on a different model (e.g. reasoning, coding). "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    async def execute(
        self,
        task: str,
        label: str | None = None,
        role: str | None = None,
        model_preset: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to execute the given task."""
        runtime = self._worker_runtime
        manager = self._manager
        request_metadata = dict(self._request_metadata.get() or {})
        if request_metadata.get("_inline_subagents") and manager is not None:
            result = await manager.run_worker(
                task=task,
                label=label,
                role=role,
                model_preset=model_preset,
                origin_channel=self._origin_channel.get(),
                origin_chat_id=self._origin_chat_id.get(),
                session_key=self._session_key.get(),
                origin_message_id=self._origin_message_id.get(),
                temperature=temperature,
                workspace_scope=current_workspace_scope(),
            )
            final_output = str(result.get("final_output") or "").strip()
            return (
                f"Subagent [{label or task[:30]}] completed inline.\n\n{final_output}"
                if final_output
                else f"Subagent [{label or task[:30]}] completed inline with no output."
            )
        running = runtime.get_running_count() if runtime is not None else manager.get_running_count()
        limit = (
            runtime.max_concurrent_workers
            if runtime is not None
            else manager.max_concurrent_subagents
        )
        if running >= limit:
            return (
                f"Cannot spawn subagent: concurrency limit reached "
                f"({running}/{limit} running). Wait for a running subagent "
                f"to complete before spawning a new one."
            )
        if runtime is not None:
            from teai_builder.agent.llm3.worker_runtime import WorkerTaskSpec

            result = await runtime.spawn(
                WorkerTaskSpec(
                    task=task,
                    label=label,
                    role=role,
                    model_preset=model_preset,
                    origin_channel=self._origin_channel.get(),
                    origin_chat_id=self._origin_chat_id.get(),
                    session_key=self._session_key.get(),
                    origin_message_id=self._origin_message_id.get(),
                    temperature=temperature,
                    workspace_scope=current_workspace_scope(),
                    owner_turn_id=request_metadata.get("_llm3_turn_id"),
                    owner_request_id=request_metadata.get("_llm3_request_id"),
                )
            )
            return result.launch_message
        return await manager.spawn(
            task=task,
            label=label,
            role=role,
            model_preset=model_preset,
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get(),
            origin_message_id=self._origin_message_id.get(),
            temperature=temperature,
            workspace_scope=current_workspace_scope(),
        )
