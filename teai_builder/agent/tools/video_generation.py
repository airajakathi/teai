"""Video generation tool.

A distinct text-to-video / image-to-video model slot, independent of the text
and image models. Disabled by default; enable via ``tools.videoGeneration`` and
configure a provider key. Degrades gracefully when no provider is configured.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.schema import (
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from teai_builder.config.paths import get_media_dir
from teai_builder.config.schema import Base
from teai_builder.providers.video_generation import (
    VideoGenerationError,
    VideoGenerationProvider,
    get_video_gen_provider,
)
from teai_builder.security.workspace_access import current_tool_workspace
from teai_builder.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from teai_builder.utils.artifacts import (
    ArtifactError,
    generated_video_tool_result,
    store_generated_video_artifact,
)
from teai_builder.utils.helpers import detect_image_mime

if TYPE_CHECKING:
    from teai_builder.config.schema import ProviderConfig


class VideoGenerationToolConfig(Base):
    """Video generation tool configuration."""

    enabled: bool = False
    provider: str = "custom"
    model: str = ""
    default_duration_seconds: int = 5
    default_aspect_ratio: str = "16:9"
    save_dir: str = "generated/video"


@tool_parameters(
    tool_parameters_schema(
        prompt=StringSchema(
            "Detailed text-to-video prompt. Include subject, motion, camera, style, and pacing.",
            min_length=1,
        ),
        reference_image=StringSchema(
            "Optional local image path to animate (image-to-video).",
        ),
        duration_seconds=IntegerSchema(
            description="Desired clip length in seconds.",
            minimum=1,
            maximum=60,
        ),
        aspect_ratio=StringSchema(
            "Optional output aspect ratio, e.g. 16:9, 9:16, 1:1.",
        ),
        required=["prompt"],
    )
)
class VideoGenerationTool(Tool):
    """Generate persistent video artifacts through the configured video provider."""

    config_key = "video_generation"

    @classmethod
    def config_cls(cls):
        return VideoGenerationToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.video_generation.enabled

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(
            workspace=ctx.workspace,
            config=ctx.config.video_generation,
            provider_configs=ctx.video_generation_provider_configs,
        )

    def __init__(
        self,
        *,
        workspace: str | Path,
        config: VideoGenerationToolConfig,
        provider_configs: dict[str, ProviderConfig] | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser()
        self.config = config
        self.provider_configs = dict(provider_configs or {})

    @property
    def name(self) -> str:
        return "generate_video"

    @property
    def description(self) -> str:
        return (
            "Generate a short video clip from a text prompt (optionally animating a "
            "reference image) and store it as a persistent artifact. Returns artifact "
            "ids and local paths."
        )

    def _provider_config(self) -> ProviderConfig | None:
        return self.provider_configs.get(self.config.provider)

    def _provider_client(self) -> VideoGenerationProvider | None:
        cls = get_video_gen_provider(self.config.provider)
        if cls is None:
            return None
        provider = self._provider_config()
        return cls(
            api_key=provider.api_key if provider else None,
            api_base=provider.api_base if provider else None,
            extra_headers=provider.extra_headers if provider else None,
            extra_body=provider.extra_body if provider else None,
        )

    def _resolve_reference_image(self, value: str) -> str:
        access = current_tool_workspace(self.workspace, restrict_to_workspace=True)
        workspace = access.project_path or self.workspace
        try:
            resolved = resolve_allowed_path(
                value,
                workspace=workspace,
                allowed_root=access.allowed_root,
                extra_allowed_roots=[get_media_dir()] if access.allowed_root is not None else None,
                strict=True,
            )
        except WorkspaceBoundaryError as exc:
            raise VideoGenerationError(
                "reference_image must be inside the workspace or teai_builder media directory"
            ) from exc
        except OSError as exc:
            raise VideoGenerationError(f"reference image not found: {value}") from exc
        if not resolved.is_file() or detect_image_mime(resolved.read_bytes()) is None:
            raise VideoGenerationError(f"unsupported reference image: {value}")
        return str(resolved)

    async def execute(
        self,
        prompt: str,
        reference_image: str | None = None,
        duration_seconds: int | None = None,
        aspect_ratio: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not self.config.model:
            return (
                "Error: no video model configured. Set tools.videoGeneration.model and a "
                "provider key, then retry."
            )
        client = self._provider_client()
        if client is None:
            return f"Error: unsupported video generation provider '{self.config.provider}'"

        try:
            ref = self._resolve_reference_image(reference_image) if reference_image else None
            response = await client.generate(
                prompt=prompt,
                model=self.config.model,
                reference_image=ref,
                duration_seconds=duration_seconds or self.config.default_duration_seconds,
                aspect_ratio=aspect_ratio or self.config.default_aspect_ratio,
            )
            artifacts: list[dict[str, Any]] = []
            for video in response.videos:
                artifact = store_generated_video_artifact(
                    video.data,
                    mime=video.mime,
                    prompt=prompt,
                    model=self.config.model,
                    source_images=[ref] if ref else None,
                    save_dir=self.config.save_dir,
                    provider=self.config.provider,
                )
                artifacts.append(artifact)
            if not artifacts:
                return "Error: video provider returned no usable clips"
            return generated_video_tool_result(artifacts)
        except (ArtifactError, VideoGenerationError, OSError) as exc:
            return f"Error: {exc}"
