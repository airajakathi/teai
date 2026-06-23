"""Machine-readable project phase state for the teai_builder software-company flow.

Each project tracked by the CEO/employee workflow gets a state file at
``<project>/.teai_builder/state.json`` recording its platform, the current phase,
per-phase gate results, and the latest independent verification result. The
``project_gate`` tool advances phases (refusing to reach deliver/deploy until
gates pass) and ``run_verification`` writes structured check results here so the
gate consumes real evidence instead of the agent's self-report.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from teai_builder.security.workspace_access import current_tool_workspace

STATE_VERSION = 1

# Ordered software-company lifecycle. ``project_gate`` walks these in order and
# enforces prerequisites before the two terminal phases.
PHASE_ORDER: list[str] = [
    "research",
    "architecture",
    "design",
    "build",
    "qa",
    "deliver",
    "deploy",
]

# Phases that may not be entered until independent verification passes.
VERIFIED_PHASES: frozenset[str] = frozenset({"deliver", "deploy"})

VALID_PLATFORMS: frozenset[str] = frozenset(
    {"web", "mobile", "desktop", "cli", "backend", "extension", "bot", "solution", "unknown"}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_workspace_base(default_workspace: str | Path | None) -> Path:
    """Return the effective workspace/project root for the current turn."""
    access = current_tool_workspace(default_workspace)
    if access.project_path is not None:
        return Path(access.project_path)
    if default_workspace is not None:
        return Path(default_workspace).expanduser()
    return Path.cwd()


def _looks_like_project(path: Path) -> bool:
    if not path.is_dir():
        return False
    markers = ("package.json", "PROJECT.md", "app.json", "pyproject.toml", ".teai_builder")
    return any((path / marker).exists() for marker in markers)


def resolve_project_dir(
    default_workspace: str | Path | None,
    project: str | None,
) -> tuple[Path | None, str | None]:
    """Resolve the project directory.

    Returns ``(path, error)``. ``error`` is a human-readable string when the
    project could not be located unambiguously.
    """
    base = resolve_workspace_base(default_workspace).resolve()
    projects_dir = base / "projects"

    if project:
        candidate = Path(project).expanduser()
        candidates: list[Path] = []
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            candidates.extend([base / project, projects_dir / project, candidate.resolve()])
        for cand in candidates:
            try:
                resolved = cand.resolve()
            except OSError:
                continue
            if resolved.is_dir():
                return resolved, None
        return None, (
            f"project '{project}' not found. Looked under {base} and {projects_dir}."
        )

    # No explicit project: prefer a single project under projects/.
    if projects_dir.is_dir():
        subdirs = [p for p in projects_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(subdirs) == 1:
            return subdirs[0].resolve(), None
        if len(subdirs) > 1:
            names = ", ".join(sorted(p.name for p in subdirs))
            return None, f"multiple projects found ({names}); pass project=<name>."
    if _looks_like_project(base):
        return base, None
    return None, (
        "no project found. Create one under projects/<name>/ or pass project=<name>."
    )


def state_path(project_dir: Path) -> Path:
    return project_dir / ".teai_builder" / "state.json"


def default_state(name: str, platform: str = "unknown") -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "project": name,
        "platform": platform if platform in VALID_PLATFORMS else "unknown",
        "phase": "research",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "phases": {},
        "artifacts": {},
        "verification": None,
    }


def load_state(project_dir: Path) -> dict[str, Any]:
    path = state_path(project_dir)
    if not path.is_file():
        return default_state(project_dir.name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state(project_dir.name)
    if not isinstance(data, dict):
        return default_state(project_dir.name)
    # Backfill required keys for forward compatibility.
    base = default_state(data.get("project") or project_dir.name)
    base.update(data)
    for key in ("phases", "artifacts"):
        if not isinstance(base.get(key), dict):
            base[key] = {}
    return base


def save_state(project_dir: Path, state: dict[str, Any]) -> None:
    state["version"] = STATE_VERSION
    state["updated_at"] = _now_iso()
    path = state_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_verification_result(project_dir: Path, result: dict[str, Any]) -> None:
    """Persist the latest verification result on the project state file."""
    state = load_state(project_dir)
    state["verification"] = {**result, "recorded_at": _now_iso(), "epoch": time.time()}
    save_state(project_dir, state)


def record_artifact_value(project_dir: Path, artifact: str, value: str) -> None:
    """Persist a recorded artifact on the project state file."""
    state = load_state(project_dir)
    artifacts = state.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        state["artifacts"] = artifacts
    artifacts[artifact] = value
    save_state(project_dir, state)


def latest_verification_passed(state: dict[str, Any]) -> bool:
    ver = state.get("verification")
    return isinstance(ver, dict) and ver.get("status") == "pass"
