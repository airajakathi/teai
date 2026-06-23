"""Project registry and progress helpers for the WebUI."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from teai_builder.config.paths import get_webui_dir
from teai_builder.security.workspace_access import WorkspaceScope, build_workspace_scope
from teai_builder.utils.helpers import write_bytes_atomic

PROJECT_REGISTRY_SCHEMA_VERSION = 1
PROJECT_METADATA_KEY = "project"
_MAX_REGISTRY_FILE_BYTES = 256 * 1024
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[(?P<state>[ xX~!])\]")
_RESERVED_PROJECT_DIR_NAMES = {"sessions", "cron", "memory", "webui"}


def project_registry_path() -> Path:
    return get_webui_dir() / "projects-index.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "project"


def _default_registry() -> dict[str, Any]:
    return {
        "schema_version": PROJECT_REGISTRY_SCHEMA_VERSION,
        "projects": [],
        "updated_at": None,
    }


def _normalize_record(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    project_id = raw.get("id")
    root_path = raw.get("root_path")
    name = raw.get("name")
    slug = raw.get("slug")
    if not all(isinstance(v, str) and v.strip() for v in (project_id, root_path, name, slug)):
        return None
    return {
        "id": project_id.strip(),
        "name": name.strip(),
        "slug": slug.strip(),
        "root_path": str(Path(root_path).expanduser().resolve(strict=False)),
        "created_at": raw.get("created_at") if isinstance(raw.get("created_at"), str) else _now_iso(),
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else _now_iso(),
    }


def _read_registry() -> dict[str, Any]:
    path = project_registry_path()
    if not path.is_file():
        return _default_registry()
    try:
        if path.stat().st_size > _MAX_REGISTRY_FILE_BYTES:
            logger.warning("project registry too large, ignoring: {}", path)
            return _default_registry()
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("failed to read project registry {}: {}", path, e)
        return _default_registry()
    if not isinstance(raw, dict) or raw.get("schema_version") != PROJECT_REGISTRY_SCHEMA_VERSION:
        return _default_registry()
    records = []
    seen_paths: set[str] = set()
    for item in raw.get("projects", []):
        record = _normalize_record(item)
        if record is None:
            continue
        root_path = record["root_path"]
        if root_path in seen_paths:
            continue
        seen_paths.add(root_path)
        records.append(record)
    return {
        "schema_version": PROJECT_REGISTRY_SCHEMA_VERSION,
        "projects": records,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None,
    }


def _write_registry(registry: dict[str, Any]) -> None:
    payload = {
        "schema_version": PROJECT_REGISTRY_SCHEMA_VERSION,
        "projects": registry.get("projects", []),
        "updated_at": _now_iso(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    if len(encoded) > _MAX_REGISTRY_FILE_BYTES:
        raise ValueError("project registry is too large")
    path = project_registry_path()
    write_bytes_atomic(path, encoded + b"\n", fsync=True)


def _resolve_docs(root_path: Path) -> dict[str, str]:
    docs = {}
    for name in ("PROJECT.md", "PLAN.md", "TASKS.md", "SUPERPOWERS.md", "DECISION_LOG.md", "RESEARCH.md"):
        path = root_path / name
        if path.is_file():
            docs[name.removesuffix(".md").lower()] = str(path)
    state_path = root_path / ".teai_builder" / "project.json"
    if state_path.is_file():
        docs["state"] = str(state_path)
    return docs


def _parse_task_progress(tasks_path: Path) -> dict[str, int]:
    counts = {"total": 0, "completed": 0, "in_progress": 0, "blocked": 0}
    if not tasks_path.is_file():
        return counts
    try:
        for line in tasks_path.read_text(encoding="utf-8").splitlines():
            match = _CHECKBOX_RE.match(line)
            if not match:
                continue
            counts["total"] += 1
            state = match.group("state").strip().lower()
            if state == "x":
                counts["completed"] += 1
            elif state == "~":
                counts["in_progress"] += 1
            elif state == "!":
                counts["blocked"] += 1
    except OSError:
        return counts
    return counts


def _detect_phase(root_path: Path) -> str | None:
    state_path = root_path / ".teai_builder" / "project.json"
    if state_path.is_file():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            phase = raw.get("phase")
            if isinstance(phase, str) and phase.strip():
                return phase.strip()
        except (OSError, json.JSONDecodeError):
            pass
    project_md = root_path / "PROJECT.md"
    if project_md.is_file():
        try:
            for line in project_md.read_text(encoding="utf-8").splitlines():
                if line.lower().startswith("phase:"):
                    phase = line.split(":", 1)[1].strip()
                    if phase:
                        return phase
        except OSError:
            pass
    return None


def _derive_status(progress: dict[str, int]) -> str:
    if progress["blocked"] > 0:
        return "blocked"
    if progress["in_progress"] > 0:
        return "active"
    if progress["total"] > 0 and progress["completed"] >= progress["total"]:
        return "completed"
    if progress["total"] > 0:
        return "planned"
    return "idle"


def _project_summary(
    record: dict[str, Any],
    *,
    linked_chat_ids: list[str] | None = None,
    active_chat_id: str | None = None,
) -> dict[str, Any]:
    root_path = Path(record["root_path"])
    progress = _parse_task_progress(root_path / "TASKS.md")
    percent = 0
    if progress["total"] > 0:
        percent = int((progress["completed"] / progress["total"]) * 100)
    return {
        "id": record["id"],
        "name": record["name"],
        "slug": record["slug"],
        "root_path": record["root_path"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "phase": _detect_phase(root_path),
        "status": _derive_status(progress),
        "progress": {
            **progress,
            "percent": percent,
        },
        "docs": _resolve_docs(root_path),
        "active_chat_id": active_chat_id,
        "linked_chat_ids": linked_chat_ids or [],
        "chat_count": len(linked_chat_ids or []),
    }


def _ensure_project_files(root_path: Path, project_name: str, project_id: str) -> None:
    hidden_dir = root_path / ".teai_builder"
    hidden_dir.mkdir(parents=True, exist_ok=True)
    state_path = hidden_dir / "project.json"
    if not state_path.exists():
        state_path.write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "name": project_name,
                    "phase": "init",
                    "status": "active",
                    "updated_at": _now_iso(),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
    seeds = {
        "PROJECT.md": (
            f"# {project_name}\n\n"
            "Phase: init\n\n"
            "## Status\n"
            "- Progress: 0%\n"
            "- Current focus: Project bootstrapped\n"
            "- Remaining: Define plan and execute tasks\n"
        ),
        "PLAN.md": f"# {project_name} Plan\n\n- Define architecture\n- Break work into tasks\n- Execute and verify\n",
        "TASKS.md": "# Tasks\n\n- [~] Bootstrap project tracking\n- [ ] Define implementation plan\n- [ ] Execute next verified slice\n",
        "SUPERPOWERS.md": (
            "# Superpowers Workflow\n\n"
            "This project is tracked with TeAI Builder's Superpowers-inspired workflow.\n\n"
            "- Keep `PROJECT.md` as the live status view.\n"
            "- Keep `PLAN.md` as the approved execution plan.\n"
            "- Keep `TASKS.md` updated as work progresses.\n"
        ),
    }
    for name, content in seeds.items():
        path = root_path / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def _registered_project_for_path(root_path: Path) -> dict[str, Any] | None:
    resolved = str(root_path.resolve(strict=False))
    registry = _read_registry()
    return next(
        (record for record in registry["projects"] if record["root_path"] == resolved),
        None,
    )


def _bootstrap_target(root_path: Path, project_name: str) -> tuple[Path, str, bool]:
    slug = _slugify(project_name)
    if slug in _RESERVED_PROJECT_DIR_NAMES:
        slug = f"project-{slug}"
    candidate = root_path / slug
    display_name = project_name
    suffix = 2
    while candidate.exists():
        if candidate.is_dir():
            registered = _registered_project_for_path(candidate)
            if registered is not None:
                return candidate, registered["name"], False
            try:
                if next(candidate.iterdir(), None) is None:
                    return candidate, display_name, False
            except OSError:
                pass
        candidate = root_path / f"{slug}-{suffix}"
        display_name = f"{project_name} {suffix}"
        suffix += 1
    return candidate, display_name, True


def ensure_project_for_scope(
    scope: WorkspaceScope,
    *,
    default_workspace: Path,
) -> dict[str, Any] | None:
    root_path = Path(scope.project_path).resolve(strict=False)
    default_root = Path(default_workspace).resolve(strict=False)
    if root_path == default_root:
        return None
    registry = _read_registry()
    records = registry["projects"]
    existing = next((record for record in records if record["root_path"] == str(root_path)), None)
    changed = False
    project_name = scope.project_name or root_path.name or "Project"
    if existing is None:
        existing = {
            "id": f"proj_{uuid.uuid4().hex[:12]}",
            "name": project_name,
            "slug": _slugify(project_name),
            "root_path": str(root_path),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        records.append(existing)
        changed = True
    else:
        if existing["name"] != project_name and project_name:
            existing["name"] = project_name
            changed = True
        existing["updated_at"] = _now_iso()
        changed = True
    _ensure_project_files(root_path, existing["name"], existing["id"])
    if changed:
        _write_registry(registry)
    return _project_summary(existing)


def bootstrap_project(
    project_name: str,
    *,
    default_workspace: Path,
    access_mode: str = "restricted",
    source_channel: str = "websocket",
) -> dict[str, Any]:
    cleaned_name = " ".join(project_name.split()).strip()
    if not cleaned_name:
        raise ValueError("project name is required")
    workspace_root = Path(default_workspace).expanduser().resolve(strict=False)
    workspace_root.mkdir(parents=True, exist_ok=True)
    target_root, resolved_name, created = _bootstrap_target(workspace_root, cleaned_name)
    if target_root.exists() and not target_root.is_dir():
        raise ValueError("project path is not a directory")
    target_root.mkdir(parents=True, exist_ok=True)
    scope = build_workspace_scope(
        target_root,
        access_mode,
        project_name=resolved_name,
        source_channel=source_channel,
    )
    project = ensure_project_for_scope(scope, default_workspace=workspace_root)
    if project is None:
        raise ValueError("failed to create project")
    return {
        "created": created,
        "project": project,
        "workspace_scope": scope.payload(),
    }


def project_for_session_metadata(
    metadata: Any,
    *,
    scope: WorkspaceScope,
    default_workspace: Path,
) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return ensure_project_for_scope(scope, default_workspace=default_workspace)
    lightweight = metadata.get(PROJECT_METADATA_KEY)
    if isinstance(lightweight, dict):
        root_path = lightweight.get("root_path")
        if isinstance(root_path, str) and root_path.strip():
            registry = _read_registry()
            record = next(
                (item for item in registry["projects"] if item["root_path"] == str(Path(root_path).resolve(strict=False))),
                None,
            )
            if record is not None:
                return _project_summary(record)
    return ensure_project_for_scope(scope, default_workspace=default_workspace)


def bind_project_metadata(
    metadata: dict[str, Any],
    *,
    scope: WorkspaceScope,
    default_workspace: Path,
) -> dict[str, Any] | None:
    project = ensure_project_for_scope(scope, default_workspace=default_workspace)
    if project is None:
        metadata.pop(PROJECT_METADATA_KEY, None)
        return None
    metadata[PROJECT_METADATA_KEY] = {
        "id": project["id"],
        "name": project["name"],
        "root_path": project["root_path"],
        "slug": project["slug"],
    }
    return project


def projects_payload(
    *,
    session_manager: Any | None,
    default_workspace: Path,
) -> dict[str, Any]:
    registry = _read_registry()
    by_id = {record["id"]: _project_summary(record) for record in registry["projects"]}
    linked_chat_ids: dict[str, list[str]] = {project_id: [] for project_id in by_id}
    active_chat_ids: dict[str, str | None] = {project_id: None for project_id in by_id}
    if session_manager is not None:
        for path in sorted(session_manager.sessions_dir.glob("*.jsonl")):
            session_key = path.stem.replace("_", ":", 1)
            session = session_manager.read_session_file(session_key)
            if not isinstance(session, dict):
                continue
            metadata = session.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            raw_scope = metadata.get("workspace_scope")
            if not isinstance(raw_scope, dict):
                continue
            try:
                scope = build_workspace_scope(
                    raw_scope.get("project_path", ""),
                    raw_scope.get("access_mode", "restricted"),
                    source_channel="websocket",
                )
            except Exception:
                continue
            summary = project_for_session_metadata(
                metadata,
                scope=scope,
                default_workspace=default_workspace,
            )
            if summary is None:
                continue
            project_id = summary["id"]
            if project_id not in by_id:
                by_id[project_id] = summary
                linked_chat_ids[project_id] = []
                active_chat_ids[project_id] = None
            chat_id = session_key.split(":", 1)[1] if ":" in session_key else session_key
            linked_chat_ids.setdefault(project_id, []).append(chat_id)
            active_chat_ids[project_id] = chat_id
    items = []
    for project_id, summary in by_id.items():
        items.append({
            **summary,
            "linked_chat_ids": linked_chat_ids.get(project_id, []),
            "active_chat_id": active_chat_ids.get(project_id),
            "chat_count": len(linked_chat_ids.get(project_id, [])),
        })
    items.sort(key=lambda item: (item.get("updated_at") or "", item["name"].lower()), reverse=True)
    return {
        "schema_version": PROJECT_REGISTRY_SCHEMA_VERSION,
        "projects": items,
    }
