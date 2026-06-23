"""Workspace-scoped source preview payloads for the WebUI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from teai_builder.security.workspace_access import WorkspaceScope
from teai_builder.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from teai_builder.utils.helpers import write_text_atomic

MAX_FILE_PREVIEW_BYTES = 384 * 1024
MAX_FILE_SAVE_BYTES = MAX_FILE_PREVIEW_BYTES


class WebUIFilePreviewError(ValueError):
    """Raised when a file cannot be previewed through the WebUI."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def file_preview_payload(
    raw_path: str | None,
    *,
    scope: WorkspaceScope,
    max_bytes: int = MAX_FILE_PREVIEW_BYTES,
) -> dict[str, Any]:
    """Return a text preview for a file inside the session workspace."""

    path = _clean_preview_path(raw_path)
    if not path:
        raise WebUIFilePreviewError(400, "missing path")
    if len(path) > 4096:
        raise WebUIFilePreviewError(400, "path is too long")

    try:
        resolved = resolve_allowed_path(
            path,
            workspace=scope.project_path,
            allowed_root=scope.project_path,
            strict=True,
        )
    except FileNotFoundError as e:
        raise WebUIFilePreviewError(404, "file not found") from e
    except WorkspaceBoundaryError as e:
        raise WebUIFilePreviewError(403, "file is outside the current workspace") from e
    except OSError as e:
        raise WebUIFilePreviewError(400, "invalid path") from e

    if not resolved.is_file():
        raise WebUIFilePreviewError(404, "file not found")

    try:
        with open(resolved, "rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError as e:
        raise WebUIFilePreviewError(500, "failed to read file") from e

    if b"\0" in raw[:4096]:
        raise WebUIFilePreviewError(415, "binary files cannot be previewed")

    truncated = len(raw) > max_bytes
    preview_bytes = raw[:max_bytes]
    try:
        content = preview_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = preview_bytes.decode("utf-8", errors="replace")

    display_path = _display_path(resolved, scope.project_path)
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "display_path": display_path,
        "project_path": str(scope.project_path),
        "language": _language_for_path(resolved),
        "content": content,
        "size": stat.st_size,
        "revision": _file_revision(stat),
        "truncated": truncated,
    }


def file_symbol_payload(
    raw_path: str | None,
    *,
    scope: WorkspaceScope,
) -> dict[str, Any]:
    """Return extracted symbols for a file inside the session workspace."""

    path = _clean_preview_path(raw_path)
    if not path:
        raise WebUIFilePreviewError(400, "missing path")
    if len(path) > 4096:
        raise WebUIFilePreviewError(400, "path is too long")

    try:
        resolved = resolve_allowed_path(
            path,
            workspace=scope.project_path,
            allowed_root=scope.project_path,
            strict=True,
        )
    except FileNotFoundError as e:
        raise WebUIFilePreviewError(404, "file not found") from e
    except WorkspaceBoundaryError as e:
        raise WebUIFilePreviewError(403, "file is outside the current workspace") from e
    except OSError as e:
        raise WebUIFilePreviewError(400, "invalid path") from e

    if not resolved.is_file():
        raise WebUIFilePreviewError(404, "file not found")

    from teai_builder.webui.workspace_search import _symbols_for_file

    display_path = _display_path(resolved, scope.project_path)
    items = _symbols_for_file(resolved, display_path, resolved.name)
    items.sort(key=lambda item: (item["line"], item["column"], item["name"].lower()))
    return {
        "path": str(resolved),
        "display_path": display_path,
        "project_path": str(scope.project_path),
        "items": items,
    }


def save_file_preview(
    raw_path: str | None,
    *,
    content: str,
    scope: WorkspaceScope,
    base_revision: str | None = None,
    max_bytes: int = MAX_FILE_SAVE_BYTES,
) -> dict[str, Any]:
    """Persist text content for a workspace file and return the refreshed preview."""

    path = _clean_preview_path(raw_path)
    if not path:
        raise WebUIFilePreviewError(400, "missing path")
    if len(path) > 4096:
        raise WebUIFilePreviewError(400, "path is too long")
    if not isinstance(content, str):
        raise WebUIFilePreviewError(400, "missing content")
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise WebUIFilePreviewError(413, "file content is too large to save")

    try:
        resolved = resolve_allowed_path(
            path,
            workspace=scope.project_path,
            allowed_root=scope.project_path,
            strict=True,
        )
    except FileNotFoundError as e:
        raise WebUIFilePreviewError(404, "file not found") from e
    except WorkspaceBoundaryError as e:
        raise WebUIFilePreviewError(403, "file is outside the current workspace") from e
    except OSError as e:
        raise WebUIFilePreviewError(400, "invalid path") from e

    if not resolved.is_file():
        raise WebUIFilePreviewError(404, "file not found")

    current_revision = _file_revision(resolved.stat())
    expected_revision = base_revision.strip() if isinstance(base_revision, str) else ""
    if expected_revision and expected_revision != current_revision:
        raise WebUIFilePreviewError(409, "file changed on disk")

    try:
        write_text_atomic(resolved, content)
    except OSError as e:
        raise WebUIFilePreviewError(500, "failed to save file") from e
    return file_preview_payload(str(resolved), scope=scope, max_bytes=max_bytes)


def _clean_preview_path(raw_path: str | None) -> str:
    if raw_path is None:
        return ""
    value = raw_path.strip()
    if not value:
        return ""
    if value.startswith("file://"):
        parsed = urlparse(value)
        value = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:[\\/]", value):
            value = value[1:]
    else:
        value = unquote(value)
    value = value.split("?", 1)[0].split("#", 1)[0].strip()
    if not re.match(r"^[A-Za-z]:[\\/]", value):
        value = re.sub(r":\d+(?::\d+)?$", "", value)
    return value


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _language_for_path(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower().lstrip(".")
    if name == "dockerfile":
        return "dockerfile"
    return {
        "cjs": "javascript",
        "css": "css",
        "cts": "typescript",
        "html": "html",
        "js": "javascript",
        "json": "json",
        "jsonl": "json",
        "jsx": "jsx",
        "md": "markdown",
        "mdx": "markdown",
        "mjs": "javascript",
        "mts": "typescript",
        "py": "python",
        "pyi": "python",
        "scss": "scss",
        "sh": "bash",
        "toml": "toml",
        "ts": "typescript",
        "tsx": "tsx",
        "yaml": "yaml",
        "yml": "yaml",
    }.get(ext, ext or "text")


def _file_revision(stat: Any) -> str:
    return f"{int(stat.st_mtime_ns)}:{int(stat.st_size)}"
