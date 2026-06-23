from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teai_builder.agent.tools.base import Tool
from teai_builder.agent.tools.governance import ToolGovernance
from teai_builder.agent.tools.loader import ToolLoader
from teai_builder.agent.tools.registry import ToolRegistry
from teai_builder.config.schema import ToolGovernanceConfig, ToolProfileConfig, ToolsConfig


class _EchoTool(Tool):
    _scopes = {"core"}

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo"

    @property
    def parameters(self) -> dict:
        return {"type": "object"}

    @classmethod
    def enabled(cls, _ctx):
        return True

    @classmethod
    def create(cls, _ctx):
        return cls()

    async def execute(self, **_kwargs):
        return "ok"


class _ExecTool(_EchoTool):
    @property
    def name(self) -> str:
        return "exec"


def test_tool_governance_matches_profiles_and_permissions():
    cfg = ToolsConfig(
        governance=ToolGovernanceConfig(
            active_profile="safe",
            profiles={
                "safe": ToolProfileConfig(
                    enabled_tools=["read_*", "exec", "mcp_*"],
                    disabled_tools=["exec"],
                )
            },
            permissions={"read_*": "allow", "exec": "confirm", "mcp_private_*": "deny"},
        )
    )

    governance = ToolGovernance.from_config(cfg)

    assert governance.profile == "safe"
    assert governance.is_available("read_file") is True
    assert governance.is_available("exec") is False
    assert governance.permission_for("read_file") == "allow"
    assert governance.permission_for("mcp_private_secret") == "deny"
    assert governance.permission_for("unknown") == "allow"


def test_loader_skips_tools_not_available_in_active_profile():
    registry = ToolRegistry()
    cfg = ToolsConfig(
        governance=ToolGovernanceConfig(
            active_profile="readonly",
            profiles={"readonly": ToolProfileConfig(enabled_tools=["echo"], disabled_tools=["exec"])},
        )
    )
    ctx = SimpleNamespace(config=cfg)

    loader = ToolLoader(test_classes=[_EchoTool, _ExecTool])
    registered = loader.load(ctx, registry)

    assert registered == ["echo"]
    assert registry.has("echo")
    assert not registry.has("exec")


@pytest.mark.asyncio
async def test_registry_blocks_confirm_and_deny_permissions():
    registry = ToolRegistry()
    registry.register(_EchoTool(), permission="confirm")

    result = await registry.execute("echo", {})
    assert "requires approval" in result

    registry.unregister("echo")
    registry.register(_EchoTool(), permission="deny")

    result = await registry.execute("echo", {})
    assert "is denied" in result


def test_registry_exposes_tool_permission():
    registry = ToolRegistry()
    registry.register(_EchoTool(), permission="confirm")

    assert registry.get_permission("echo") == "confirm"
    assert registry.get_permission("missing") == "allow"
