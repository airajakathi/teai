"""Phase-gate tool: the CEO must call this to advance a project's lifecycle.

Quality used to be aspirational prose. This makes it real: the gate refuses to
mark a project ``deliver``/``deploy`` until independent verification has passed
and the required artifacts exist. State lives in ``<project>/.teai_builder/state.json``
and is updated atomically here so a half-built project can never be reported as
"done and deployed".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.project_state import (
    PHASE_ORDER,
    VALID_PLATFORMS,
    VERIFIED_PHASES,
    latest_verification_passed,
    load_state,
    record_artifact_value,
    resolve_project_dir,
    save_state,
)
from teai_builder.agent.tools.schema import StringSchema, tool_parameters_schema

_ACTIONS = ("status", "init", "set_platform", "record_artifact", "advance")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "One of: status, init, set_platform, record_artifact, advance.",
        ),
        project=StringSchema(
            "Project name under projects/ or absolute path. Optional with one project.",
            nullable=True,
        ),
        to=StringSchema(
            "Target phase for 'advance': research, architecture, design, build, "
            "qa, deliver, deploy. Omit to advance to the next phase.",
            nullable=True,
        ),
        platform=StringSchema(
            "Platform for 'init'/'set_platform': web, mobile, desktop, cli, backend, extension, bot, solution.",
            nullable=True,
        ),
        artifact=StringSchema(
            "Artifact key for 'record_artifact' (e.g. architecture, design, build).",
            nullable=True,
        ),
        path=StringSchema(
            "File path or preview URL for 'record_artifact' (relative to the project, absolute, http(s)://, or exp://).",
            nullable=True,
        ),
        required=["action"],
    )
)
class ProjectGateTool(Tool):
    """Validate and advance a project's lifecycle phases with hard quality gates."""

    _scopes = {"core"}

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    @classmethod
    def create(cls, ctx: Any) -> "ProjectGateTool":
        return cls(workspace=getattr(ctx, "workspace", None))

    @property
    def name(self) -> str:
        return "project_gate"

    @property
    def description(self) -> str:
        return (
            "Authoritative project phase gate for the software-company workflow. "
            "The CEO must use this to move a project through research -> "
            "architecture -> design -> build -> qa -> deliver -> deploy. It "
            "REFUSES to enter 'deliver' or 'deploy' until run_verification has "
            "passed and required artifacts exist — so a broken build can never be "
            "reported as done. Actions: status (inspect), init (create state + "
            "platform), set_platform, record_artifact (register a produced file), "
            "advance (move phase, validating prerequisites). Supports product "
            "surfaces such as backend services, extensions, bots, and multi-platform solutions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters_schema  # type: ignore[attr-defined]

    async def execute(
        self,
        action: str,
        project: str | None = None,
        to: str | None = None,  # noqa: A002
        platform: str | None = None,
        artifact: str | None = None,
        path: str | None = None,
        **_: Any,
    ) -> str:
        if action not in _ACTIONS:
            return f"project_gate error: unknown action '{action}'. Use one of {', '.join(_ACTIONS)}."
        project_dir, error = resolve_project_dir(self._workspace, project)
        if project_dir is None:
            return f"project_gate error: {error}"
        state = load_state(project_dir)

        if action == "status":
            return self._render(state, project_dir)
        if action == "init":
            return self._init(state, project_dir, platform)
        if action == "set_platform":
            return self._set_platform(state, project_dir, platform)
        if action == "record_artifact":
            return self._record_artifact(state, project_dir, artifact, path)
        if action == "advance":
            return self._advance(state, project_dir, to)
        return f"project_gate error: unhandled action '{action}'."

    # ── actions ──────────────────────────────────────────────────────────

    def _init(self, state: dict[str, Any], project_dir: Path, platform: str | None) -> str:
        if platform:
            normalized = platform.strip().lower()
            if normalized not in VALID_PLATFORMS:
                return f"project_gate error: platform must be one of {', '.join(sorted(VALID_PLATFORMS))}."
            state["platform"] = normalized
        save_state(project_dir, state)
        return "project_gate: initialized.\n" + self._render(state, project_dir)

    def _set_platform(self, state: dict[str, Any], project_dir: Path, platform: str | None) -> str:
        if not platform:
            return "project_gate error: set_platform requires platform."
        normalized = platform.strip().lower()
        if normalized not in VALID_PLATFORMS:
            return f"project_gate error: platform must be one of {', '.join(sorted(VALID_PLATFORMS))}."
        state["platform"] = normalized
        save_state(project_dir, state)
        return f"project_gate: platform set to {normalized}."

    def _record_artifact(
        self,
        state: dict[str, Any],
        project_dir: Path,
        artifact: str | None,
        path: str | None,
    ) -> str:
        if not artifact or not path:
            return "project_gate error: record_artifact requires artifact and path."
        if self._is_preview_reference(path):
            record_artifact_value(project_dir, artifact, path)
            return f"project_gate: recorded artifact '{artifact}' -> {path}."
        candidate = Path(path)
        resolved = candidate if candidate.is_absolute() else project_dir / path
        if not resolved.exists():
            return (
                f"project_gate error: artifact path does not exist: {resolved}. "
                "Create the file before recording it."
            )
        rel = self._rel(resolved, project_dir)
        record_artifact_value(project_dir, artifact, rel)
        return f"project_gate: recorded artifact '{artifact}' -> {rel}."

    def _advance(self, state: dict[str, Any], project_dir: Path, to: str | None) -> str:
        current = state.get("phase", "research")
        if to:
            target = to.strip().lower()
            if target not in PHASE_ORDER:
                return f"project_gate error: unknown phase '{to}'. Valid: {', '.join(PHASE_ORDER)}."
        else:
            try:
                idx = PHASE_ORDER.index(current)
            except ValueError:
                idx = 0
            if idx >= len(PHASE_ORDER) - 1:
                return f"project_gate: already at final phase '{current}'."
            target = PHASE_ORDER[idx + 1]

        ok, reason = self._can_enter(state, project_dir, target)
        if not ok:
            return f"project_gate: BLOCKED — cannot enter '{target}'. {reason}"

        state["phase"] = target
        state.setdefault("phases", {})[target] = {
            "status": "entered",
            "at": _now_iso(),
            "from": current,
        }
        save_state(project_dir, state)
        return f"project_gate: advanced {current} -> {target}.\n" + self._render(state, project_dir)

    # ── gate logic ───────────────────────────────────────────────────────

    def _can_enter(
        self,
        state: dict[str, Any],
        project_dir: Path,
        target: str,
    ) -> tuple[bool, str]:
        artifacts = state.get("artifacts", {}) if isinstance(state.get("artifacts"), dict) else {}

        if target == "design":
            if "architecture" not in artifacts and not (project_dir / "docs" / "architecture.md").exists():
                return False, (
                    "Record an architecture artifact first "
                    "(project_gate record_artifact artifact=architecture path=docs/architecture.md)."
                )
        if target == "qa":
            if not self._has_source(project_dir):
                return False, "No source files found — build something before QA."
        if target in VERIFIED_PHASES:
            if not latest_verification_passed(state):
                ver = state.get("verification")
                detail = "run_verification has not passed"
                if isinstance(ver, dict):
                    detail = f"latest verification status = {ver.get('status')!r}: {ver.get('summary', '')}"
                return False, (
                    f"Independent verification must pass first ({detail}). "
                    "Run the run_verification tool and fix any failing checks."
                )
            if "architecture" not in artifacts and not (project_dir / "docs" / "architecture.md").exists():
                return False, "Missing architecture artifact required before delivery."
            if state.get("platform") == "mobile":
                ok, detail = self._mobile_preview_requirements(artifacts)
                if not ok:
                    return False, detail
        return True, ""

    @staticmethod
    def _has_source(project_dir: Path) -> bool:
        patterns = ("*.html", "*.js", "*.jsx", "*.ts", "*.tsx", "*.py", "*.go", "*.rs", "*.swift")
        for pattern in patterns:
            for p in project_dir.rglob(pattern):
                if any(part in {"node_modules", ".git", ".teai_builder", "dist", "build"} for part in p.parts):
                    continue
                return True
        return False

    # ── rendering ────────────────────────────────────────────────────────

    def _render(self, state: dict[str, Any], project_dir: Path) -> str:
        ver = state.get("verification")
        ver_line = "none"
        if isinstance(ver, dict):
            ver_line = f"{ver.get('status', 'unknown')} — {ver.get('summary', '')}"
        view = {
            "project": state.get("project"),
            "platform": state.get("platform"),
            "phase": state.get("phase"),
            "next_phase": self._next_phase(state.get("phase", "research")),
            "artifacts": state.get("artifacts", {}),
            "verification": ver_line,
            "state_file": str(project_dir / ".teai_builder" / "state.json"),
        }
        return json.dumps(view, ensure_ascii=False, indent=2)

    @staticmethod
    def _next_phase(current: str) -> str | None:
        try:
            idx = PHASE_ORDER.index(current)
        except ValueError:
            return PHASE_ORDER[0]
        return PHASE_ORDER[idx + 1] if idx < len(PHASE_ORDER) - 1 else None

    @staticmethod
    def _rel(path: Path, project_dir: Path) -> str:
        try:
            return str(path.resolve().relative_to(project_dir.resolve()))
        except (OSError, ValueError):
            return str(path)

    @staticmethod
    def _is_preview_reference(value: str) -> bool:
        lowered = value.strip().lower()
        return lowered.startswith(("http://", "https://", "exp://", "exp+"))

    @classmethod
    def _mobile_preview_requirements(cls, artifacts: dict[str, Any]) -> tuple[bool, str]:
        native_ref = artifacts.get("expo_native_preview") or artifacts.get("mobile_preview")
        web_ref = artifacts.get("expo_web_preview") or artifacts.get("web_preview")
        if not isinstance(native_ref, str) or not native_ref.startswith(("exp://", "exp+")):
            return (
                False,
                "Mobile delivery requires a recorded Expo native handoff first "
                "(project_gate record_artifact artifact=expo_native_preview path=exp://<lan-ip>:<port>).",
            )
        if not isinstance(web_ref, str) or not web_ref.startswith(("http://", "https://")):
            return (
                False,
                "Mobile delivery requires a recorded verified Expo web mirror "
                "(project_gate record_artifact artifact=expo_web_preview path=http://127.0.0.1:<port>).",
            )
        return True, ""
