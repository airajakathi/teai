"""Workspace-scoped file tree payloads for the WebUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from teai_builder.security.workspace_access import WorkspaceScope

_IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}

MAX_WORKSPACE_TREE_ENTRIES = 1000
MAX_WORKSPACE_TREE_DEPTH = 5


def workspace_tree_payload(
    *,
    scope: WorkspaceScope,
    max_entries: int = MAX_WORKSPACE_TREE_ENTRIES,
    max_depth: int = MAX_WORKSPACE_TREE_DEPTH,
) -> dict[str, Any]:
    """Return a trimmed directory tree for the current workspace scope."""

    workspace_root = scope.project_path.resolve(strict=False)
    remaining_entries = max(1, max_entries)
    truncated = False

    def build_directory(path: Path, depth: int) -> dict[str, Any]:
        nonlocal remaining_entries, truncated

        remaining_entries -= 1
        node = {
            "path": str(path),
            "display_path": _display_path(path, workspace_root),
            "name": path.name or path.as_posix(),
            "kind": "directory",
            "children": [],
        }
        if depth >= max_depth:
            return node

        try:
            entries = sorted(
                path.iterdir(),
                key=lambda entry: (not entry.is_dir(), entry.name.lower()),
            )
        except OSError:
            return node

        children: list[dict[str, Any]] = []
        for entry in entries:
            if remaining_entries <= 0:
                truncated = True
                break
            if entry.is_dir():
                if entry.name in _IGNORED_DIR_NAMES:
                    continue
                children.append(build_directory(entry, depth + 1))
                continue
            remaining_entries -= 1
            children.append(
                {
                    "path": str(entry),
                    "display_path": _display_path(entry, workspace_root),
                    "name": entry.name,
                    "kind": "file",
                }
            )
        node["children"] = children
        return node

    root = build_directory(workspace_root, depth=0)
    return {
        "root": root,
        "truncated": truncated,
    }


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
