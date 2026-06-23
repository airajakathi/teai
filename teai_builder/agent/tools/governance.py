"""Tool availability and approval policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any


@dataclass(frozen=True)
class ToolPolicy:
    """Resolved governance policy for one tool."""

    name: str
    available: bool
    permission: str
    profile: str


class ToolGovernance:
    """Resolve profile-based tool availability and approval policy."""

    def __init__(
        self,
        *,
        profile: str = "default",
        enabled_tools: list[str] | None = None,
        disabled_tools: list[str] | None = None,
        permissions: dict[str, str] | None = None,
    ) -> None:
        self.profile = profile
        self.enabled_tools = list(enabled_tools or ["*"])
        self.disabled_tools = list(disabled_tools or [])
        self.permissions = dict(permissions or {})

    @classmethod
    def from_config(cls, config: Any) -> "ToolGovernance":
        governance = getattr(config, "governance", None)
        if governance is None:
            return cls()
        profile_name = getattr(governance, "active_profile", "default") or "default"
        profile = getattr(governance, "profiles", {}).get(profile_name)
        enabled_tools = list(getattr(profile, "enabled_tools", ["*"])) if profile is not None else ["*"]
        disabled_tools = list(getattr(profile, "disabled_tools", [])) if profile is not None else []
        permissions = dict(getattr(governance, "permissions", {}) or {})
        return cls(
            profile=profile_name,
            enabled_tools=enabled_tools,
            disabled_tools=disabled_tools,
            permissions=permissions,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip()

    @classmethod
    def _matches(cls, name: str, pattern: str) -> bool:
        normalized_name = cls._normalize(name)
        normalized_pattern = cls._normalize(pattern)
        if not normalized_pattern:
            return False
        if normalized_pattern == "*":
            return True
        if normalized_pattern == normalized_name:
            return True
        return fnmatchcase(normalized_name, normalized_pattern)

    def is_available(self, name: str) -> bool:
        normalized = self._normalize(name)
        if not normalized:
            return False
        enabled = any(self._matches(normalized, pattern) for pattern in self.enabled_tools)
        if not enabled:
            return False
        if any(self._matches(normalized, pattern) for pattern in self.disabled_tools):
            return False
        return True

    def permission_for(self, name: str) -> str:
        normalized = self._normalize(name)
        if normalized in self.permissions:
            return self.permissions[normalized]
        for pattern, mode in self.permissions.items():
            if self._matches(normalized, pattern):
                return mode
        return "allow"

    def policy_for(self, name: str) -> ToolPolicy:
        return ToolPolicy(
            name=name,
            available=self.is_available(name),
            permission=self.permission_for(name),
            profile=self.profile,
        )
