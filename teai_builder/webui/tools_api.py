"""Lightweight tool summaries for the WebUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from teai_builder.agent.tools.context import ToolContext
from teai_builder.agent.tools.loader import ToolLoader
from teai_builder.agent.tools.registry import ToolRegistry
from teai_builder.security.workspace_access import workspace_sandbox_status


def webui_tools_payload(
    *,
    workspace_path: Path,
    tools_config: Any,
    bus: Any = None,
    cron_service: Any = None,
    sessions: Any = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Return enabled runtime tools with safe metadata for the WebUI."""
    registry = ToolRegistry()
    ctx = ToolContext(
        config=tools_config,
        workspace=str(workspace_path.resolve()),
        bus=bus,
        cron_service=cron_service,
        sessions=sessions,
        timezone=timezone,
        workspace_sandbox=workspace_sandbox_status(
            restrict_to_workspace=tools_config.restrict_to_workspace,
            workspace=workspace_path,
            sandbox_backend=tools_config.exec.sandbox,
            strict_execution=tools_config.exec.strict_sandbox,
        ),
    )
    ToolLoader().load(ctx, registry)
    tools = []
    for schema in registry.get_definitions():
        fn = schema.get("function") if isinstance(schema, dict) else None
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            continue
        tool = registry.get(name)
        if tool is None:
            continue
        tools.append(
            {
                "name": name,
                "description": fn.get("description") or name,
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                "permission": registry.get_permission(name),
                "read_only": bool(tool.read_only),
                "concurrency_safe": bool(tool.concurrency_safe),
                "exclusive": bool(tool.exclusive),
                "source": "builtin" if not name.startswith("mcp_") else "mcp",
            }
        )
    return {"tools": tools}
