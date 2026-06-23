"""Audio (text-to-speech) generation provider seam.

A distinct speech-synthesis model slot, independent of the text / image / video
models — mirroring :mod:`teai_builder.providers.image_generation` and
:mod:`teai_builder.providers.video_generation`. Providers register at import time and
resolve lazily so adding a key (StepFun, OpenAI, a custom OpenAI-compatible
``/audio/speech`` endpoint) "just works" with no agent-loop change.

This is the opposite direction of transcription (speech-to-text), which lives in
``teai_builder.audio`` / ``teai_builder.providers.transcription``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from teai_builder.providers.registry import find_by_name

_DEFAULT_TIMEOUT_S = 120.0

# Map OpenAI-style response_format hints to MIME types.
_FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/wav",
}


class AudioGenerationError(RuntimeError):
    """Raised when the audio/TTS provider cannot return audio."""


@dataclass(frozen=True)
class GeneratedAudio:
    """A single synthesized audio clip."""

    data: bytes
    mime: str


@dataclass(frozen=True)
class GeneratedAudioResponse:
    """Audio clips and optional text returned by the provider."""

    audio: list[GeneratedAudio]
    content: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _mime_for_format(fmt: str | None, content_type: str | None) -> str:
    if content_type:
        ct = content_type.split(";", 1)[0].strip().lower()
        if ct.startswith("audio/"):
            return ct
    if fmt:
        return _FORMAT_MIME.get(fmt.lower(), "audio/mpeg")
    return "audio/mpeg"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_AUDIO_GEN_PROVIDERS: dict[str, type["AudioGenerationProvider"]] = {}


def register_audio_gen_provider(cls: type["AudioGenerationProvider"]) -> None:
    name = cls.provider_name
    if not name:
        raise ValueError(f"{cls.__name__} must set provider_name")
    _AUDIO_GEN_PROVIDERS[name] = cls


def get_audio_gen_provider(name: str) -> type["AudioGenerationProvider"] | None:
    return _AUDIO_GEN_PROVIDERS.get(name)


def audio_gen_provider_names() -> tuple[str, ...]:
    return tuple(_AUDIO_GEN_PROVIDERS)


def audio_gen_provider_configs(config: Any) -> dict[str, Any]:
    providers_cfg = config.providers
    return {
        name: pc
        for name in _AUDIO_GEN_PROVIDERS
        if (pc := getattr(providers_cfg, name, None)) is not None
    }


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class AudioGenerationProvider(ABC):
    """Base class for text-to-speech provider clients."""

    provider_name: str = ""
    missing_key_message: str = ""
    default_timeout: float = _DEFAULT_TIMEOUT_S

    def __init__(
        self,
        *,
        api_key: str | None,
        api_base: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = self._resolve_base_url(api_base)
        self.extra_headers = extra_headers or {}
        self.extra_body = extra_body or {}
        self.timeout = timeout if timeout is not None else self.default_timeout
        self._client = client

    def _resolve_base_url(self, api_base: str | None) -> str:
        if api_base:
            return api_base.rstrip("/")
        spec = find_by_name(self.provider_name)
        if spec and spec.default_api_base:
            return spec.default_api_base.rstrip("/")
        return self._default_base_url()

    def _default_base_url(self) -> str:
        return ""

    @abstractmethod
    async def synthesize(
        self,
        *,
        text: str,
        model: str,
        voice: str | None = None,
        response_format: str | None = None,
        speed: float | None = None,
    ) -> GeneratedAudioResponse: ...

    async def _http_post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, headers=headers, json=body)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            return await c.post(url, headers=headers, json=body)


class _OpenAISpeechBase(AudioGenerationProvider):
    """Shared implementation for OpenAI-compatible ``/audio/speech`` endpoints.

    Returns raw audio bytes (not JSON). Used by OpenAI, StepFun, and custom
    OpenAI-compatible providers.
    """

    def _speech_url(self) -> str:
        return f"{self.api_base}/audio/speech"

    def _require_key(self) -> None:
        if not self.api_key:
            raise AudioGenerationError(
                self.missing_key_message
                or f"{self.provider_name} API key is not configured."
            )

    async def synthesize(
        self,
        *,
        text: str,
        model: str,
        voice: str | None = None,
        response_format: str | None = None,
        speed: float | None = None,
    ) -> GeneratedAudioResponse:
        self._require_key()
        if not self.api_base:
            raise AudioGenerationError(
                f"{self.provider_name} audio API base is not configured."
            )

        fmt = (response_format or "mp3").lower()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        body: dict[str, Any] = {
            "model": model,
            "input": text,
            "response_format": fmt,
        }
        if voice:
            body["voice"] = voice
        if speed is not None:
            body["speed"] = speed
        body.update(self.extra_body)

        try:
            response = await self._http_post(self._speech_url(), headers=headers, body=body)
        except httpx.TimeoutException as exc:
            raise AudioGenerationError(f"{self.provider_name} TTS request timed out") from exc
        except httpx.RequestError as exc:
            raise AudioGenerationError(f"{self.provider_name} TTS request failed: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise AudioGenerationError(
                f"{self.provider_name} TTS failed (HTTP {response.status_code}): {detail}"
            ) from exc

        content_type = response.headers.get("content-type", "")
        raw = response.content
        # Some gateways return JSON with a base64 field instead of raw audio.
        if content_type.startswith("application/json") or (raw[:1] in (b"{", b"[")):
            return self._from_json(response.json(), fmt)
        if not raw:
            raise AudioGenerationError(f"{self.provider_name} TTS returned no audio data")
        mime = _mime_for_format(fmt, content_type)
        return GeneratedAudioResponse(audio=[GeneratedAudio(data=raw, mime=mime)])

    def _from_json(self, payload: dict[str, Any], fmt: str) -> GeneratedAudioResponse:
        import base64
        import binascii

        candidates: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, str) and value:
                candidates.append(value)
            elif isinstance(value, dict):
                for key in ("audio", "data", "b64_json", "audio_base64", "speech"):
                    if key in value:
                        collect(value[key])
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        for value in candidates:
            cleaned = value.split(",", 1)[1] if value.startswith("data:") else value
            try:
                raw = base64.b64decode("".join(cleaned.split()), validate=True)
            except (binascii.Error, ValueError):
                continue
            if raw:
                return GeneratedAudioResponse(
                    audio=[GeneratedAudio(data=raw, mime=_mime_for_format(fmt, None))],
                    raw=payload,
                )
        raise AudioGenerationError(f"{self.provider_name} TTS returned no decodable audio")


class OpenAISpeechClient(_OpenAISpeechBase):
    provider_name = "openai"
    missing_key_message = "OpenAI API key is not configured. Set providers.openai.apiKey."

    def _default_base_url(self) -> str:
        return "https://api.openai.com/v1"


class StepFunSpeechClient(_OpenAISpeechBase):
    """StepFun (阶跃星辰) text-to-speech via the OpenAI-compatible speech API.

    Default model is ``stepaudio-2.5-tts``. Honors the configured
    ``providers.stepfun.apiBase`` (the same key/base used for chat), and falls
    back to the canonical ``api.stepfun.com`` speech base only when no base is
    configured. If your StepFun key is scoped to a plan proxy that does not
    expose ``/audio/speech``, set ``providers.stepfun.apiBase`` to the speech
    base that your key is authorized for.
    """

    provider_name = "stepfun"
    missing_key_message = "StepFun API key is not configured. Set providers.stepfun.apiKey."

    def _default_base_url(self) -> str:
        return "https://api.stepfun.com/v1"


class CustomSpeechClient(_OpenAISpeechBase):
    provider_name = "custom"
    missing_key_message = ""

    def _require_key(self) -> None:  # custom endpoints may be keyless
        return

    def _default_base_url(self) -> str:
        return ""


register_audio_gen_provider(OpenAISpeechClient)
register_audio_gen_provider(StepFunSpeechClient)
register_audio_gen_provider(CustomSpeechClient)
