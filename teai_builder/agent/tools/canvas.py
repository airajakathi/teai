"""Canvas tool – push live content to the WebUI canvas workspace panel.

The canvas is the right-side panel in the WebUI that acts as a mini-computer
display for teai_builder. It can render web apps, mobile previews, images, video,
code, terminal output, HTML documents, and more – all auto-detected from the
type parameter.

Supported types
---------------
url           Open a URL (local or remote) in a full browser iframe.
mobile_url    Same as url but rendered inside a phone-mockup frame + QR code
              so the user can open it on a real mobile device.
html          Render an HTML string or file path as a sandboxed page.
image         Display an image file (path or data URL).
video         Play a video file (path or URL).
code          Show syntax-highlighted source code.
terminal      Show terminal/shell output with ANSI styling.
document      Render a Markdown or plain-text document.
screenshot    Request the frontend to capture the current canvas view and
              send it back as an image for teai_builder to analyse.
"""
from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.context import ContextAware, RequestContext
from teai_builder.agent.tools.project_state import load_state, record_artifact_value, resolve_project_dir
from teai_builder.agent.tools.schema import StringSchema, tool_parameters_schema
from teai_builder.bus.events import OUTBOUND_META_AGENT_UI, OutboundMessage

_SUPPORTED_TYPES = (
    "url", "mobile_url", "html", "image", "video",
    "code", "terminal", "document", "screenshot",
)


@tool_parameters(
    tool_parameters_schema(
        type=StringSchema(
            "Content type to show. One of: url, mobile_url, html, image, video, "
            "code, terminal, document, screenshot."
        ),
        content=StringSchema(
            "The payload: a URL, HTML string, file path, source-code string, "
            "terminal output, or Markdown text. Leave empty for screenshot."
        ),
        title=StringSchema("Short title shown in the canvas navigation bar."),
        lang=StringSchema(
            "Language for code syntax highlighting, e.g. python, javascript, bash."
        ),
        required=["type"],
    )
)
class CanvasTool(Tool, ContextAware):
    """Push content to the WebUI canvas workspace panel for live preview."""

    _scopes = {"core"}

    def __init__(self, send_callback: Any | None = None, workspace: str | Path | None = None) -> None:
        self._send_callback = send_callback
        self._workspace = str(workspace) if workspace is not None else None
        self._ctx: ContextVar[RequestContext | None] = ContextVar(
            "canvas_tool_ctx", default=None
        )

    @classmethod
    def create(cls, ctx: Any) -> "CanvasTool":
        callback = ctx.bus.publish_outbound if ctx.bus else None
        return cls(send_callback=callback, workspace=getattr(ctx, "workspace", None))

    def set_context(self, ctx: RequestContext) -> None:
        self._ctx.set(ctx)

    # ── Tool identity ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "canvas"

    @property
    def description(self) -> str:
        return (
            "Push content to the WebUI canvas workspace panel.\n"
            "The canvas is a live right-side panel visible to the user.\n"
            "Use it to:\n"
            "  • Show a running web app:           canvas(type='url', content='http://localhost:3000')\n"
            "  • Mobile preview + QR code:         canvas(type='mobile_url', content='http://localhost:3000')\n"
            "  • Render raw HTML:                  canvas(type='html', content='<h1>Hello</h1>')\n"
            "  • Display a generated image:        canvas(type='image', content='/path/to/img.png')\n"
            "  • Play a video:                     canvas(type='video', content='/path/to/clip.mp4')\n"
            "  • Show source code:                 canvas(type='code', content='...', lang='python')\n"
            "  • Stream terminal output:           canvas(type='terminal', content='...')\n"
            "  • Render a Markdown doc:            canvas(type='document', content='# My Doc\\n...')\n"
            "  • Capture current canvas screenshot: canvas(type='screenshot', content='')\n"
            "After a screenshot request the user will see the canvas, optionally sending it back for analysis."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters_schema  # type: ignore[attr-defined]

    # ── Execution ──────────────────────────────────────────────────────────

    async def execute(
        self,
        type: str,  # noqa: A002
        content: str = "",
        title: str = "",
        lang: str = "",
        **_: Any,
    ) -> str:
        if type not in _SUPPORTED_TYPES:
            supported = ", ".join(_SUPPORTED_TYPES)
            return f"Error: unsupported canvas type '{type}'. Supported: {supported}"

        ctx = self._ctx.get()
        if not ctx or not self._send_callback:
            # Running outside WebUI – degrade gracefully
            return f"canvas({type}): no WebUI canvas connected"

        data: dict[str, Any] = {"type": type, "content": content}
        if title:
            data["title"] = title
        if lang:
            data["lang"] = lang

        msg = OutboundMessage(
            channel=ctx.channel,
            chat_id=ctx.chat_id,
            content="",
            metadata={
                "_progress": True,
                OUTBOUND_META_AGENT_UI: {"kind": "canvas", "data": data},
            },
        )
        try:
            await self._send_callback(msg)
        except Exception as exc:
            return f"canvas({type}): failed to push to WebUI – {exc}"

        self._record_preview_artifact(type=type, content=content)

        label = f" '{title}'" if title else ""
        return f"canvas: pushed {type} content{label} to WebUI workspace panel"

    def _record_preview_artifact(self, *, type: str, content: str) -> None:  # noqa: A002
        if not content:
            return
        project_dir, error = resolve_project_dir(self._workspace, None)
        if project_dir is None or error:
            return
        state = load_state(project_dir)
        artifact = self._artifact_name_for_preview(
            platform=str(state.get("platform") or "unknown"),
            preview_type=type,
            content=content,
        )
        if artifact is None:
            return
        try:
            record_artifact_value(project_dir, artifact, content)
        except OSError:
            return

    @staticmethod
    def _artifact_name_for_preview(*, platform: str, preview_type: str, content: str) -> str | None:
        lowered = content.strip().lower()
        normalized_platform = platform.strip().lower()
        if preview_type == "mobile_url":
            if lowered.startswith(("exp://", "exp+")):
                return "expo_native_preview"
            if lowered.startswith(("http://", "https://")):
                return "mobile_preview"
            return None
        if preview_type != "url":
            return None
        if not lowered.startswith(("http://", "https://")):
            return None
        if normalized_platform == "mobile":
            return "expo_web_preview"
        return "web_preview"
