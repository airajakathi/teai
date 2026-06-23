"""Audio (text-to-speech) generation tool.

A distinct speech-synthesis model slot, independent of the text / image / video
models. Auto-called when the user wants narration, voiceovers, or spoken
replies. Configured via ``tools.audioGeneration`` (default model
``stepaudio-2.5-tts`` on StepFun). Degrades gracefully when unconfigured.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.schema import (
    NumberSchema,
    StringSchema,
    tool_parameters_schema,
)
from teai_builder.config.schema import Base
from teai_builder.providers.audio_generation import (
    AudioGenerationError,
    AudioGenerationProvider,
    get_audio_gen_provider,
)
from teai_builder.utils.artifacts import (
    ArtifactError,
    generated_audio_tool_result,
    store_generated_audio_artifact,
)

if TYPE_CHECKING:
    from teai_builder.config.schema import ProviderConfig


class AudioGenerationToolConfig(Base):
    """Audio (text-to-speech) tool configuration."""

    enabled: bool = False
    provider: str = "stepfun"
    model: str = "stepaudio-2.5-tts"
    default_voice: str = ""
    default_format: str = "mp3"
    save_dir: str = "generated/audio"


@tool_parameters(
    tool_parameters_schema(
        text=StringSchema(
            "The text to synthesize into speech.",
            min_length=1,
        ),
        voice=StringSchema(
            "Optional voice name/id supported by the configured provider.",
        ),
        response_format=StringSchema(
            "Optional audio format: mp3, wav, opus, aac, flac.",
        ),
        speed=NumberSchema(
            description="Optional speaking speed multiplier (e.g. 1.0 normal).",
            minimum=0.25,
            maximum=4.0,
        ),
        required=["text"],
    )
)
class AudioGenerationTool(Tool):
    """Synthesize speech from text and store it as a persistent audio artifact."""

    config_key = "audio_generation"

    @classmethod
    def config_cls(cls):
        return AudioGenerationToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.audio_generation.enabled

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(
            workspace=ctx.workspace,
            config=ctx.config.audio_generation,
            provider_configs=ctx.audio_generation_provider_configs,
        )

    def __init__(
        self,
        *,
        workspace: str | Path,
        config: AudioGenerationToolConfig,
        provider_configs: dict[str, ProviderConfig] | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser()
        self.config = config
        self.provider_configs = dict(provider_configs or {})

    @property
    def name(self) -> str:
        return "generate_speech"

    @property
    def description(self) -> str:
        return (
            "Synthesize natural speech from text (text-to-speech) and store it as a "
            "persistent audio artifact. Returns artifact ids and local paths; deliver "
            "with the message tool's media parameter."
        )

    def _provider_config(self) -> ProviderConfig | None:
        return self.provider_configs.get(self.config.provider)

    def _provider_client(self) -> AudioGenerationProvider | None:
        cls = get_audio_gen_provider(self.config.provider)
        if cls is None:
            return None
        provider = self._provider_config()
        return cls(
            api_key=provider.api_key if provider else None,
            api_base=provider.api_base if provider else None,
            extra_headers=provider.extra_headers if provider else None,
            extra_body=provider.extra_body if provider else None,
        )

    async def execute(
        self,
        text: str,
        voice: str | None = None,
        response_format: str | None = None,
        speed: float | None = None,
        **kwargs: Any,
    ) -> str:
        if not self.config.model:
            return (
                "Error: no audio model configured. Set tools.audioGeneration.model and a "
                "provider key, then retry."
            )
        client = self._provider_client()
        if client is None:
            return f"Error: unsupported audio generation provider '{self.config.provider}'"

        try:
            response = await client.synthesize(
                text=text,
                model=self.config.model,
                voice=voice or self.config.default_voice or None,
                response_format=response_format or self.config.default_format,
                speed=speed,
            )
            artifacts: list[dict[str, Any]] = []
            for clip in response.audio:
                artifact = store_generated_audio_artifact(
                    clip.data,
                    mime=clip.mime,
                    prompt=text,
                    model=self.config.model,
                    voice=voice or self.config.default_voice or None,
                    save_dir=self.config.save_dir,
                    provider=self.config.provider,
                )
                artifacts.append(artifact)
            if not artifacts:
                return "Error: audio provider returned no usable clips"
            return generated_audio_tool_result(artifacts)
        except (ArtifactError, AudioGenerationError, OSError) as exc:
            return f"Error: {exc}"
