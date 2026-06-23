"""Screenshot tool — capture a URL or local page as a persistent image artifact.

Playwright-backed when available (headless Chromium), with a graceful fallback
to a system headless-Chromium CLI. Lets teai_builder "look at" web pages and live
deploys for autonomous look-judge-fix loops without manual MCP setup.
"""

from __future__ import annotations

import asyncio
import base64
import shutil
from pathlib import Path
from typing import Any

from loguru import logger

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from teai_builder.security.workspace_access import current_tool_workspace
from teai_builder.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from teai_builder.utils.artifacts import ArtifactError, store_generated_image_artifact

_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 800
_NAV_TIMEOUT_MS = 30_000
_CHROME_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "chrome",
)


@tool_parameters(
    tool_parameters_schema(
        url=StringSchema(
            "URL to capture (http(s)://...) or a workspace-relative path to a local "
            "HTML file (e.g. projects/app/index.html).",
            min_length=1,
        ),
        full_page=BooleanSchema(
            description="Capture the entire scrollable page instead of just the viewport.",
            default=False,
        ),
        width=IntegerSchema(
            description="Viewport width in pixels.",
            minimum=240,
            maximum=3840,
        ),
        height=IntegerSchema(
            description="Viewport height in pixels.",
            minimum=240,
            maximum=2160,
        ),
        wait_ms=IntegerSchema(
            description="Extra milliseconds to wait after load (for animations/late content).",
            minimum=0,
            maximum=15_000,
        ),
        required=["url"],
    )
)
class ScreenshotTool(Tool):
    """Capture a screenshot of a URL or local page and store it as an artifact."""

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(workspace=ctx.workspace)

    def __init__(self, *, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser()

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return (
            "Capture a screenshot of a web page (live URL) or a local HTML file and "
            "store it as a persistent image artifact. Use to visually verify deploys, "
            "review UI, and self-correct. Returns the artifact path; show it with "
            "canvas(type=\"image\", content=\"<path>\")."
        )

    def _resolve_target(self, url: str) -> str:
        value = url.strip()
        if value.startswith(("http://", "https://", "file://", "data:")):
            return value
        access = current_tool_workspace(self.workspace, restrict_to_workspace=True)
        workspace = access.project_path or self.workspace
        try:
            resolved = resolve_allowed_path(
                value,
                workspace=workspace,
                allowed_root=access.allowed_root,
                strict=True,
            )
        except WorkspaceBoundaryError as exc:
            raise ValueError(
                "local screenshot target must be inside the workspace"
            ) from exc
        except OSError as exc:
            raise ValueError(f"screenshot target not found: {value}") from exc
        if not resolved.is_file():
            raise ValueError(f"screenshot target is not a file: {value}")
        return resolved.as_uri()

    async def execute(
        self,
        url: str,
        full_page: bool | None = None,
        width: int | None = None,
        height: int | None = None,
        wait_ms: int | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            target = self._resolve_target(url)
        except ValueError as exc:
            return f"Error: {exc}"

        w = width or _DEFAULT_WIDTH
        h = height or _DEFAULT_HEIGHT
        full = bool(full_page)
        wait = wait_ms or 0

        png: bytes | None = None
        try:
            png = await self._capture_playwright(target, w, h, full, wait)
        except _PlaywrightUnavailable:
            png = await self._capture_chromium_cli(target, w, h)
            if png is None:
                return (
                    "Error: no screenshot backend available. Install Playwright "
                    "(`pip install playwright && playwright install chromium`) or a "
                    "headless Chromium/Chrome binary."
                )
        except Exception as exc:  # noqa: BLE001 — surface capture failures to the model
            logger.exception("Screenshot capture failed")
            return f"Error: screenshot failed: {exc}"

        if not png:
            return "Error: screenshot produced no image data"

        try:
            data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
            artifact = store_generated_image_artifact(
                data_url,
                prompt=f"screenshot of {url}",
                model="screenshot",
                save_dir="generated/screenshots",
                provider="screenshot",
            )
        except (ArtifactError, OSError) as exc:
            return f"Error: failed to store screenshot: {exc}"

        import json

        return json.dumps(
            {
                "artifact": artifact,
                "next_step": (
                    "Show it with canvas(type=\"image\", content=\"<path>\") and review "
                    "it. If something is wrong, fix the code and re-screenshot."
                ),
            },
            ensure_ascii=False,
        )

    async def _capture_playwright(
        self,
        target: str,
        width: int,
        height: int,
        full_page: bool,
        wait_ms: int,
    ) -> bytes:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise _PlaywrightUnavailable from exc

        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            try:
                page = await browser.new_page(viewport={"width": width, "height": height})
                await page.goto(target, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
                if wait_ms:
                    await page.wait_for_timeout(wait_ms)
                return await page.screenshot(full_page=full_page, type="png")
            finally:
                await browser.close()

    async def _capture_chromium_cli(
        self,
        target: str,
        width: int,
        height: int,
    ) -> bytes | None:
        binary = next((b for b in _CHROME_CANDIDATES if shutil.which(b)), None)
        if binary is None:
            return None
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "shot.png"
            cmd = [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                f"--window-size={width},{height}",
                f"--screenshot={out}",
                target,
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            except (asyncio.TimeoutError, OSError) as exc:
                logger.warning("Headless Chromium screenshot failed: {}", exc)
                return None
            if out.is_file() and out.stat().st_size > 0:
                return out.read_bytes()
            logger.warning(
                "Headless Chromium produced no screenshot: {}",
                (stderr or b"").decode("utf-8", "replace")[:300],
            )
            return None


class _PlaywrightUnavailable(RuntimeError):
    """Raised internally when Playwright is not importable."""
