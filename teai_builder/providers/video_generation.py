"""Video generation provider seam.

Mirrors :mod:`teai_builder.providers.image_generation` so that a distinct
text-to-video / image-to-video model slot can be configured independently of
the text and image models. Providers register themselves at import time and
are resolved lazily, exactly like the image-generation registry.

Most video APIs are asynchronous (submit a job, then poll a task id). The base
class implements a generic submit+poll loop; concrete providers only describe
how to build the request and how to read the task/result payloads. The seam is
intentionally provider-agnostic so adding a real key (StepFun, a custom
OpenAI-compatible endpoint, etc.) "just works" without touching the agent loop.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from teai_builder.providers.registry import find_by_name

_DEFAULT_TIMEOUT_S = 120.0
_DEFAULT_POLL_INTERVAL_S = 5.0
_DEFAULT_POLL_TIMEOUT_S = 600.0

_DATA_VIDEO_RE = re.compile(r"^data:(video/[A-Za-z0-9.+-]+);base64,(.*)$", re.DOTALL)


class VideoGenerationError(RuntimeError):
    """Raised when the video generation provider cannot return a video."""


@dataclass(frozen=True)
class GeneratedVideo:
    """A single decoded video clip."""

    data: bytes
    mime: str


@dataclass(frozen=True)
class GeneratedVideoResponse:
    """Videos and optional text returned by the provider."""

    videos: list[GeneratedVideo]
    content: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def decode_video_payload(value: str) -> GeneratedVideo:
    """Decode a base64 ``data:video/...`` URL into a :class:`GeneratedVideo`."""
    match = _DATA_VIDEO_RE.match(value.strip())
    if match is None:
        raise VideoGenerationError("expected a base64 video data URL")
    mime, encoded = match.groups()
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except binascii.Error as exc:
        raise VideoGenerationError("invalid base64 video payload") from exc
    return GeneratedVideo(data=raw, mime=mime)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_VIDEO_GEN_PROVIDERS: dict[str, type["VideoGenerationProvider"]] = {}


def register_video_gen_provider(cls: type["VideoGenerationProvider"]) -> None:
    name = cls.provider_name
    if not name:
        raise ValueError(f"{cls.__name__} must set provider_name")
    _VIDEO_GEN_PROVIDERS[name] = cls


def get_video_gen_provider(name: str) -> type["VideoGenerationProvider"] | None:
    return _VIDEO_GEN_PROVIDERS.get(name)


def video_gen_provider_names() -> tuple[str, ...]:
    return tuple(_VIDEO_GEN_PROVIDERS)


def video_gen_provider_configs(config: Any) -> dict[str, Any]:
    providers_cfg = config.providers
    return {
        name: pc
        for name in _VIDEO_GEN_PROVIDERS
        if (pc := getattr(providers_cfg, name, None)) is not None
    }


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class VideoGenerationProvider(ABC):
    """Base class for video generation provider clients."""

    provider_name: str = ""
    missing_key_message: str = ""
    default_timeout: float = _DEFAULT_TIMEOUT_S
    poll_interval: float = _DEFAULT_POLL_INTERVAL_S
    poll_timeout: float = _DEFAULT_POLL_TIMEOUT_S

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
    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_image: str | None = None,
        duration_seconds: int | None = None,
        aspect_ratio: str | None = None,
    ) -> GeneratedVideoResponse: ...

    # -- shared HTTP helpers -------------------------------------------------

    async def _http_post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        client: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        if client is not None:
            return await client.post(url, headers=headers, json=body)
        if self._client is not None:
            return await self._client.post(url, headers=headers, json=body)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            return await c.post(url, headers=headers, json=body)

    async def _http_get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        client: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        if client is not None:
            return await client.get(url, headers=headers)
        if self._client is not None:
            return await self._client.get(url, headers=headers)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            return await c.get(url, headers=headers)

    async def _download_video(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> GeneratedVideo:
        response = await client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise VideoGenerationError(
                f"failed to download generated video: {response.text[:300]}"
            ) from exc
        mime = response.headers.get("content-type", "video/mp4").split(";", 1)[0].strip()
        if not mime.startswith("video/") and mime != "image/gif":
            mime = "video/mp4"
        return GeneratedVideo(data=response.content, mime=mime)


# ---------------------------------------------------------------------------
# Generic OpenAI-compatible / custom video client
# ---------------------------------------------------------------------------


class CustomVideoGenerationClient(VideoGenerationProvider):
    """OpenAI-compatible video generations endpoint for custom providers.

    Posts to ``{api_base}/video/generations`` and supports both synchronous
    responses (``data[].url`` or ``data[].b64_json``) and the common
    submit-then-poll pattern (``id`` returned, then ``GET {base}/video/
    generations/{id}`` until ``status == "succeeded"``).
    """

    provider_name = "custom"
    missing_base_message = (
        "Custom video generation API base is not configured. Set providers.custom.apiBase."
    )

    def _default_base_url(self) -> str:
        return ""

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_image: str | None = None,
        duration_seconds: int | None = None,
        aspect_ratio: str | None = None,
    ) -> GeneratedVideoResponse:
        if not self.api_base:
            raise VideoGenerationError(self.missing_base_message)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)

        body: dict[str, Any] = {"model": model, "prompt": prompt}
        if duration_seconds:
            body["seconds"] = duration_seconds
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        body.update(self.extra_body)

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await self._http_post(
                f"{self.api_base}/video/generations",
                headers=headers,
                body=body,
                client=client,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise VideoGenerationError(
                    f"video generation failed (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                ) from exc

            payload = response.json()
            videos = await self._resolve_payload(client, headers, payload)
            if not videos:
                raise VideoGenerationError("provider returned no video for this request")
            return GeneratedVideoResponse(videos=videos, raw=payload)
        finally:
            if owns_client:
                await client.aclose()

    async def _resolve_payload(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> list[GeneratedVideo]:
        videos = self._videos_from_payload(payload)
        if videos:
            return await self._materialize(client, videos)

        task_id = payload.get("id") or payload.get("task_id")
        status = payload.get("status")
        if not task_id:
            return []

        deadline = asyncio.get_event_loop().time() + self.poll_timeout
        while asyncio.get_event_loop().time() < deadline:
            if status in ("succeeded", "completed", "success"):
                break
            if status in ("failed", "error", "cancelled"):
                raise VideoGenerationError(f"video task {task_id} failed: {payload}")
            await asyncio.sleep(self.poll_interval)
            poll = await self._http_get(
                f"{self.api_base}/video/generations/{task_id}",
                headers=headers,
                client=client,
            )
            try:
                poll.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise VideoGenerationError(
                    f"polling video task {task_id} failed: {poll.text[:300]}"
                ) from exc
            payload = poll.json()
            status = payload.get("status")
            videos = self._videos_from_payload(payload)
            if videos:
                return await self._materialize(client, videos)
        raise VideoGenerationError(f"video task {task_id} did not complete in time")

    @staticmethod
    def _videos_from_payload(payload: dict[str, Any]) -> list[str]:
        out: list[str] = []
        items: list[Any] = []
        for key in ("data", "output", "videos", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                items.extend(value)
            elif isinstance(value, (str, dict)):
                items.append(value)
        for item in items:
            if isinstance(item, str) and item:
                out.append(item)
            elif isinstance(item, dict):
                for k in ("url", "video_url", "b64_json", "video"):
                    v = item.get(k)
                    if isinstance(v, str) and v:
                        out.append(v)
                        break
        return out

    async def _materialize(
        self,
        client: httpx.AsyncClient,
        values: list[str],
    ) -> list[GeneratedVideo]:
        videos: list[GeneratedVideo] = []
        for value in values:
            if value.startswith("data:video/"):
                videos.append(decode_video_payload(value))
            elif value.startswith(("http://", "https://")):
                videos.append(await self._download_video(client, value))
            else:
                # Bare base64 — assume mp4.
                try:
                    raw = base64.b64decode("".join(value.split()), validate=True)
                except binascii.Error:
                    logger.warning("Skipping unrecognized video payload value")
                    continue
                videos.append(GeneratedVideo(data=raw, mime="video/mp4"))
        return videos


# ---------------------------------------------------------------------------
# Provider registration
# ---------------------------------------------------------------------------

register_video_gen_provider(CustomVideoGenerationClient)
