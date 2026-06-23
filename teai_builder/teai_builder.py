"""High-level programmatic interface to teai_builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from teai_builder.agent.hook import AgentHook, SDKCaptureHook
from teai_builder.agent.loop import AgentLoop
from teai_builder.providers.audio_generation import audio_gen_provider_configs
from teai_builder.providers.image_generation import image_gen_provider_configs
from teai_builder.providers.video_generation import video_gen_provider_configs


@dataclass(slots=True)
class RunResult:
    """Result of a single agent run."""

    content: str
    tools_used: list[str]
    messages: list[dict[str, Any]]


class TeaiBuilder:
    """Programmatic facade for running the teai_builder agent.

    Usage::

        bot = TeaiBuilder.from_config()
        result = await bot.run("Summarize this repo", hooks=[MyHook()])
        print(result.content)
    """

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        workspace: str | Path | None = None,
    ) -> TeaiBuilder:
        """Create a TeaiBuilder instance from a config file.

        Args:
            config_path: Path to ``config.json``.  Defaults to
                ``~/.teai_builder/config.json``.
            workspace: Override the workspace directory from config.
        """
        from teai_builder.config.loader import load_config, resolve_config_env_vars
        from teai_builder.config.schema import Config

        resolved: Path | None = None
        if config_path is not None:
            resolved = Path(config_path).expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Config not found: {resolved}")

        config: Config = resolve_config_env_vars(load_config(resolved))
        if workspace is not None:
            config.agents.defaults.workspace = str(
                Path(workspace).expanduser().resolve()
            )

        loop = AgentLoop.from_config(
            config,
            image_generation_provider_configs=image_gen_provider_configs(config),
            video_generation_provider_configs=video_gen_provider_configs(config),
            audio_generation_provider_configs=audio_gen_provider_configs(config),
        )
        return cls(loop)

    async def run(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        hooks: list[AgentHook] | None = None,
    ) -> RunResult:
        """Run the agent once and return the result.

        Args:
            message: The user message to process.
            session_key: Session identifier for conversation isolation.
                Different keys get independent history.
            hooks: Optional lifecycle hooks for this run.
        """
        capture = SDKCaptureHook()
        prev = self._loop._extra_hooks
        base_hooks = list(hooks) if hooks is not None else list(prev or [])
        self._loop._extra_hooks = [capture, *base_hooks]
        try:
            response = await self._loop.process_direct(
                message, session_key=session_key,
            )
        finally:
            self._loop._extra_hooks = prev

        content = (response.content if response else None) or ""
        return RunResult(
            content=content,
            tools_used=capture.tools_used,
            messages=capture.messages,
        )

    async def aclose(self) -> None:
        """Release resources held by this instance (MCP connections, etc.)."""
        await self._loop.close_mcp()

    async def __aenter__(self) -> TeaiBuilder:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

