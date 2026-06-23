"""Media gateway services shared by WebUI HTTP routes and WebSocket frames."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from teai_builder.config.paths import get_media_dir
from teai_builder.webui.files_api import serve_signed_workspace_file, sign_workspace_file
from teai_builder.webui.media_api import (
    attach_signed_media_urls,
    serve_signed_media,
    sign_media_path,
    sign_or_stage_media_path,
    signed_media_attachments,
)
from teai_builder.webui.transcript import rewrite_local_markdown_images


class WebUIMediaGateway:
    """Own media URL signing and WebUI markdown/media augmentation."""

    def __init__(
        self,
        *,
        workspace_path: Path,
        logger: Any,
        media_dir: Callable[[str | None], Path] | None = None,
        secret: bytes | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.logger = logger
        self._media_dir = media_dir or (lambda channel=None: get_media_dir(channel))
        self.secret = secret or secrets.token_bytes(32)

    def serve_signed_media(
        self,
        sig: str,
        payload: str,
        *,
        request: WsRequest | None = None,
    ) -> Response:
        return serve_signed_media(
            sig,
            payload,
            secret=self.secret,
            request=request,
            media_dir=self._media_dir,
        )

    def sign_media_path(self, abs_path: Path) -> str | None:
        return sign_media_path(
            abs_path,
            secret=self.secret,
            media_dir=self._media_dir,
        )

    def sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        return sign_or_stage_media_path(
            path,
            secret=self.secret,
            media_dir=self._media_dir,
            logger=self.logger,
        )

    def sign_workspace_file(self, path: Path) -> str | None:
        """Sign a workspace file path (HTML/CSS/JS/...) for canvas file previews."""
        return sign_workspace_file(
            path,
            secret=self.secret,
            workspace_root=self.workspace_path,
        )

    def serve_workspace_file(
        self,
        sig: str,
        payload: str,
        *,
        request: WsRequest | None = None,
    ) -> Response:
        return serve_signed_workspace_file(
            sig,
            payload,
            secret=self.secret,
            workspace_root=self.workspace_path,
            request=request,
        )

    def sign_canvas_content(self, ctype: str, content: str) -> str | None:
        """Return a browser-loadable URL for a canvas item, or None to keep as-is.

        Used both for live frames (websocket channel) and history replay
        (thread response) so canvas previews survive a gateway restart: the
        transcript stores the raw filesystem path and we re-sign on demand.
        """
        if not content or content.startswith(("http://", "https://", "data:", "/api/")):
            return None
        if ctype in ("image", "video"):
            signed = self.sign_or_stage_media_path(Path(content))
            return signed.get("url") if signed else None
        if ctype == "html" and not content.lstrip().startswith("<"):
            return self.sign_workspace_file(Path(content))
        return None

    def rewrite_local_markdown_images(
        self,
        text: str,
        *,
        workspace_path: Path | None = None,
    ) -> str:
        return rewrite_local_markdown_images(
            text,
            workspace_path=workspace_path or self.workspace_path,
            sign_path=self.sign_or_stage_media_path,
        )

    def augment_media_urls(self, payload: dict[str, Any]) -> None:
        attach_signed_media_urls(payload, sign_path=self.sign_media_path)

    def augment_transcript_media(self, paths: list[str]) -> list[dict[str, Any]]:
        return signed_media_attachments(
            paths,
            sign_path=self.sign_or_stage_media_path,
        )

    def augment_transcript_user_media(self, paths: list[str]) -> list[dict[str, Any]]:
        return self.augment_transcript_media(paths)
