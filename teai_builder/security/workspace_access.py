"""Workspace access scope and sandbox capability helpers."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from loguru import logger

WorkspaceAccessMode = Literal["restricted", "full"]
WORKSPACE_SCOPE_METADATA_KEY = "workspace_scope"
_ACCESS_MODES = {"restricted", "full"}

_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", ""}
_PROVIDER_LABELS = {
    "none": "None",
    "unknown": "Unknown system sandbox",
    "macos_app_sandbox": "macOS App Sandbox",
    "bwrap": "Bubblewrap",
}

_CURRENT_WORKSPACE_SCOPE: ContextVar["WorkspaceScope | None"] = ContextVar(
    "teai_builder_workspace_scope",
    default=None,
)


class WorkspaceScopeError(ValueError):
    """Raised when a requested WebUI workspace scope is invalid."""

    status = 400

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class WorkspaceSandboxStatus:
    """Resolved workspace sandbox state for runtime display and tooling."""

    restrict_to_workspace: bool
    workspace_root: str
    level: str
    enforced: bool
    provider: str
    provider_label: str
    exec_backend: str
    exec_backend_available: bool
    exec_backend_required: bool
    summary: str

    def as_dict(self) -> dict[str, object]:
        return {
            "restrict_to_workspace": self.restrict_to_workspace,
            "workspace_root": self.workspace_root,
            "level": self.level,
            "enforced": self.enforced,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "exec_backend": self.exec_backend,
            "exec_backend_available": self.exec_backend_available,
            "exec_backend_required": self.exec_backend_required,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class WorkspaceScope:
    """Effective project root and access mode for one agent turn."""

    project_path: Path
    access_mode: WorkspaceAccessMode
    restrict_to_workspace: bool
    sandbox_status: WorkspaceSandboxStatus
    source_channel: str | None = None
    project_name_override: str | None = None

    @property
    def project_name(self) -> str:
        if isinstance(self.project_name_override, str):
            cleaned = self.project_name_override.strip()
            if cleaned:
                return cleaned
        return self.project_path.name or str(self.project_path)

    def metadata(self) -> dict[str, str]:
        data = {
            "project_path": str(self.project_path),
            "access_mode": self.access_mode,
        }
        if isinstance(self.project_name_override, str):
            cleaned = self.project_name_override.strip()
            if cleaned:
                data["project_name"] = cleaned
        return data

    def payload(self) -> dict[str, Any]:
        return {
            **self.metadata(),
            "project_name": self.project_name,
            "restrict_to_workspace": self.restrict_to_workspace,
            "sandbox_status": self.sandbox_status.as_dict(),
        }


@dataclass(frozen=True)
class ToolWorkspace:
    """Workspace policy resolved for a tool call."""

    project_path: Path | None
    restrict_to_workspace: bool
    scope: WorkspaceScope | None = None

    @property
    def allowed_root(self) -> Path | None:
        if self.restrict_to_workspace and self.project_path is not None:
            return self.project_path
        return None


@dataclass(frozen=True)
class WorkspaceScopeResolver:
    """Resolve the effective workspace scope at an agent turn boundary."""

    default_workspace: str | Path
    default_restrict_to_workspace: bool
    exec_sandbox_backend: str = ""
    exec_sandbox_strict: bool = True
    scoped_channel: str = "websocket"

    @property
    def sandbox_status(self) -> WorkspaceSandboxStatus:
        return self.default().sandbox_status

    def default(self) -> WorkspaceScope:
        return default_workspace_scope(
            self.default_workspace,
            self.default_restrict_to_workspace,
            sandbox_backend=self.exec_sandbox_backend,
            strict_execution=self.exec_sandbox_strict,
        )

    def for_message(
        self,
        msg: Any,
        session_metadata: Any,
    ) -> WorkspaceScope:
        return self.for_turn(
            channel=getattr(msg, "channel", None),
            message_metadata=getattr(msg, "metadata", None),
            session_metadata=session_metadata,
        )

    def for_turn(
        self,
        *,
        channel: str | None,
        message_metadata: Any,
        session_metadata: Any,
    ) -> WorkspaceScope:
        if channel != self.scoped_channel:
            return self.default()
        return resolve_effective_workspace_scope(
            message_metadata=message_metadata,
            session_metadata=session_metadata,
            default_workspace=self.default_workspace,
            default_restrict_to_workspace=self.default_restrict_to_workspace,
            source_channel=channel,
        )

    def persist_message_scope(self, session: Any, msg: Any) -> None:
        if getattr(msg, "channel", None) != self.scoped_channel:
            return
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            return
        raw = metadata.get(WORKSPACE_SCOPE_METADATA_KEY)
        if isinstance(raw, dict):
            session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = dict(raw)


def workspace_sandbox_status(
    *,
    restrict_to_workspace: bool,
    workspace: str | Path,
    sandbox_backend: str = "",
    strict_execution: bool = True,
    environ: dict[str, str] | None = None,
) -> WorkspaceSandboxStatus:
    """Return how workspace restriction is enforced in the current host."""

    workspace_root = str(Path(workspace).expanduser().resolve(strict=False))
    provider = _env_system_provider(environ)
    if not restrict_to_workspace:
        return WorkspaceSandboxStatus(
            restrict_to_workspace=False,
            workspace_root=workspace_root,
            level="off",
            enforced=False,
            provider="none",
            provider_label=_provider_label("none"),
            exec_backend="",
            exec_backend_available=False,
            exec_backend_required=False,
            summary="Workspace restriction is disabled.",
        )

    if provider:
        label = _provider_label(provider)
        return WorkspaceSandboxStatus(
            restrict_to_workspace=True,
            workspace_root=workspace_root,
            level="system",
            enforced=True,
            provider=provider,
            provider_label=label,
            exec_backend=sandbox_backend,
            exec_backend_available=bool(sandbox_backend),
            exec_backend_required=bool(sandbox_backend and strict_execution),
            summary=f"Workspace restriction is system-enforced by {label}.",
        )

    if sandbox_backend:
        from teai_builder.agent.tools.sandbox import sandbox_backend_status

        backend = sandbox_backend_status(sandbox_backend)
        if backend.available:
            return WorkspaceSandboxStatus(
                restrict_to_workspace=True,
                workspace_root=workspace_root,
                level="process",
                enforced=True,
                provider=backend.provider,
                provider_label=backend.provider_label,
                exec_backend=sandbox_backend,
                exec_backend_available=True,
                exec_backend_required=bool(strict_execution),
                summary=(
                    f"Workspace restriction is process-enforced for exec commands by "
                    f"{backend.provider_label}; application-level guards remain for non-exec tools."
                ),
            )
        if strict_execution:
            return WorkspaceSandboxStatus(
                restrict_to_workspace=True,
                workspace_root=workspace_root,
                level="degraded",
                enforced=False,
                provider="none",
                provider_label=_provider_label("none"),
                exec_backend=sandbox_backend,
                exec_backend_available=False,
                exec_backend_required=True,
                summary=(
                    f"Configured exec sandbox {backend.provider_label} is unavailable; "
                    "strict sandbox mode will block exec commands."
                ),
            )

    return WorkspaceSandboxStatus(
        restrict_to_workspace=True,
        workspace_root=workspace_root,
        level="application",
        enforced=False,
        provider="none",
        provider_label=_provider_label("none"),
        exec_backend=sandbox_backend,
        exec_backend_available=False,
        exec_backend_required=bool(sandbox_backend and strict_execution),
        summary=(
            "Workspace restriction uses teai_builder application-level guards."
            if not sandbox_backend
            else (
                f"Configured exec sandbox {_provider_label(sandbox_backend)} is unavailable; "
                "teai_builder is falling back to application-level guards."
            )
        ),
    )


def default_access_mode(restrict_to_workspace: bool) -> WorkspaceAccessMode:
    return "restricted" if restrict_to_workspace else "full"


def build_workspace_scope(
    project_path: str | Path,
    access_mode: str,
    *,
    source_channel: str | None = None,
    project_name: str | None = None,
    sandbox_backend: str = "",
    strict_execution: bool = True,
) -> WorkspaceScope:
    mode = _normalize_access_mode(access_mode)
    root = Path(project_path).expanduser().resolve(strict=False)
    restrict = mode == "restricted"
    return WorkspaceScope(
        project_path=root,
        access_mode=mode,
        restrict_to_workspace=restrict,
        sandbox_status=workspace_sandbox_status(
            restrict_to_workspace=restrict,
            workspace=root,
            sandbox_backend=sandbox_backend,
            strict_execution=strict_execution,
        ),
        source_channel=source_channel,
        project_name_override=project_name,
    )


def default_workspace_scope(
    workspace: str | Path,
    restrict_to_workspace: bool,
    *,
    source_channel: str | None = None,
    sandbox_backend: str = "",
    strict_execution: bool = True,
) -> WorkspaceScope:
    return build_workspace_scope(
        workspace,
        default_access_mode(restrict_to_workspace),
        source_channel=source_channel,
        sandbox_backend=sandbox_backend,
        strict_execution=strict_execution,
    )


def validate_workspace_scope_payload(
    raw: Any,
    *,
    default_workspace: str | Path,
    default_restrict_to_workspace: bool,
    source_channel: str | None = None,
    sandbox_backend: str = "",
    strict_execution: bool = True,
) -> WorkspaceScope:
    """Validate a client-requested workspace scope."""
    if raw is None:
        return default_workspace_scope(
            default_workspace,
            default_restrict_to_workspace,
            source_channel=source_channel,
            sandbox_backend=sandbox_backend,
            strict_execution=strict_execution,
        )
    if not isinstance(raw, dict):
        raise WorkspaceScopeError("workspace_scope must be an object")

    raw_path = raw.get("project_path") or raw.get("path")
    if raw_path is None or raw_path == "":
        raw_path = str(Path(default_workspace).expanduser().resolve(strict=False))
    if not isinstance(raw_path, str):
        raise WorkspaceScopeError("project_path must be a string")
    if "\0" in raw_path:
        raise WorkspaceScopeError("project_path contains invalid characters")

    project = Path(raw_path).expanduser()
    if not project.is_absolute():
        raise WorkspaceScopeError("project_path must be absolute")
    project = project.resolve(strict=False)
    if not project.is_dir():
        raise WorkspaceScopeError("project_path must be an existing directory")

    raw_mode = raw.get("access_mode")
    if raw_mode is None:
        raw_mode = default_access_mode(default_restrict_to_workspace)
    if not isinstance(raw_mode, str):
        raise WorkspaceScopeError("access_mode must be a string")
    raw_name = raw.get("project_name")
    if raw_name is not None and not isinstance(raw_name, str):
        raise WorkspaceScopeError("project_name must be a string")
    return build_workspace_scope(
        project,
        raw_mode,
        source_channel=source_channel,
        project_name=raw_name,
        sandbox_backend=sandbox_backend,
        strict_execution=strict_execution,
    )


def workspace_scope_from_metadata(
    metadata: Any,
    *,
    default_workspace: str | Path,
    default_restrict_to_workspace: bool,
    source_channel: str | None = None,
    sandbox_backend: str = "",
    strict_execution: bool = True,
) -> WorkspaceScope:
    """Resolve persisted metadata, falling back to a safe restricted default when invalid."""
    if not isinstance(metadata, dict):
        return default_workspace_scope(
            default_workspace,
            default_restrict_to_workspace,
            source_channel=source_channel,
            sandbox_backend=sandbox_backend,
            strict_execution=strict_execution,
        )
    try:
        return validate_workspace_scope_payload(
            metadata.get(WORKSPACE_SCOPE_METADATA_KEY),
            default_workspace=default_workspace,
            default_restrict_to_workspace=default_restrict_to_workspace,
            source_channel=source_channel,
            sandbox_backend=sandbox_backend,
            strict_execution=strict_execution,
        )
    except WorkspaceScopeError as e:
        logger.warning("invalid persisted workspace scope metadata; using restricted default: {}", e)
        return default_workspace_scope(
            default_workspace,
            True,
            source_channel=source_channel,
            sandbox_backend=sandbox_backend,
            strict_execution=strict_execution,
        )


def resolve_effective_workspace_scope(
    *,
    message_metadata: Any,
    session_metadata: Any,
    default_workspace: str | Path,
    default_restrict_to_workspace: bool,
    source_channel: str | None = None,
    sandbox_backend: str = "",
    strict_execution: bool = True,
) -> WorkspaceScope:
    if isinstance(message_metadata, dict) and WORKSPACE_SCOPE_METADATA_KEY in message_metadata:
        return workspace_scope_from_metadata(
            message_metadata,
            default_workspace=default_workspace,
            default_restrict_to_workspace=default_restrict_to_workspace,
            source_channel=source_channel,
            sandbox_backend=sandbox_backend,
            strict_execution=strict_execution,
        )
    return workspace_scope_from_metadata(
        session_metadata,
        default_workspace=default_workspace,
        default_restrict_to_workspace=default_restrict_to_workspace,
        source_channel=source_channel,
        sandbox_backend=sandbox_backend,
        strict_execution=strict_execution,
    )


def bind_workspace_scope(scope: WorkspaceScope) -> Token[WorkspaceScope | None]:
    return _CURRENT_WORKSPACE_SCOPE.set(scope)


def reset_workspace_scope(token: Token[WorkspaceScope | None]) -> None:
    _CURRENT_WORKSPACE_SCOPE.reset(token)


def current_workspace_scope() -> WorkspaceScope | None:
    return _CURRENT_WORKSPACE_SCOPE.get()


def current_tool_workspace(
    default_workspace: str | Path | None,
    *,
    restrict_to_workspace: bool = False,
    sandbox_restricts_workspace: bool = False,
) -> ToolWorkspace:
    """Return the workspace/access policy for the current tool call."""

    scope = current_workspace_scope()
    project_path = (
        scope.project_path
        if scope is not None
        else Path(default_workspace).expanduser() if default_workspace is not None else None
    )
    restrict = (
        scope.restrict_to_workspace
        if scope is not None
        else bool(restrict_to_workspace)
    ) or sandbox_restricts_workspace
    return ToolWorkspace(
        project_path=project_path,
        restrict_to_workspace=restrict,
        scope=scope,
    )


def current_scope_allows_loopback(*, enabled: bool) -> bool:
    """Return True when the current WebUI Full Access turn may touch loopback URLs."""

    scope = current_workspace_scope()
    return bool(
        enabled
        and scope is not None
        and scope.source_channel == "websocket"
        and scope.access_mode == "full"
        and not scope.restrict_to_workspace
    )


def _env_system_provider(environ: dict[str, str] | None = None) -> str | None:
    env = environ if environ is not None else os.environ
    explicit_provider = env.get("TEAI_BUILDER_WORKSPACE_SANDBOX_PROVIDER")
    enforced = env.get("TEAI_BUILDER_WORKSPACE_SANDBOX_ENFORCED")
    compatibility = env.get("TEAI_BUILDER_SANDBOX_ENFORCED")

    marker = enforced if enforced is not None else compatibility
    if marker is None:
        return None

    normalized_marker = marker.strip().lower()
    if normalized_marker in _FALSE_VALUES:
        return None
    if normalized_marker in _TRUE_VALUES:
        return _normalize_provider(explicit_provider)
    return _normalize_provider(marker)


def _normalize_provider(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or "unknown"


def _provider_label(provider: str) -> str:
    if provider in _PROVIDER_LABELS:
        return _PROVIDER_LABELS[provider]
    return provider.replace("_", " ").title()


def _normalize_access_mode(value: str) -> WorkspaceAccessMode:
    mode = value.strip().lower().replace("_", "-")
    if mode == "restrict":
        mode = "restricted"
    if mode == "full-access":
        mode = "full"
    if mode not in _ACCESS_MODES:
        raise WorkspaceScopeError("access_mode must be restricted or full")
    return mode  # type: ignore[return-value]
