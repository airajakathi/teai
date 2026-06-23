"""Project scaffolding tool for TeAI Builder."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.schema import (
    BooleanSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)


@tool_parameters(
    tool_parameters_schema(
        project_name=StringSchema("Name of the project to scaffold"),
        platform=StringSchema(
            "Target platform",
            enum=["web", "mobile", "desktop", "cli", "backend", "extension", "bot", "solution"],
        ),
        template=StringSchema(
            "Optional template or starter name",
            nullable=True,
        ),
        planner_result=ObjectSchema(
            description="Optional structured planning output used to prefill project docs.",
            additional_properties=True,
            nullable=True,
        ),
        force=BooleanSchema(
            description="Overwrite existing project files if present.",
            default=False,
            nullable=True,
        ),
        required=["project_name", "platform"],
    )
)
class ScaffoldProjectTool(Tool):
    """Scaffold a new project in the current workspace."""

    _scopes = {"core", "subagent"}

    def __init__(
        self,
        workspace: str | Path | None = None,
        restrict_to_workspace: bool = False,
    ) -> None:
        self._workspace = Path(workspace) if workspace is not None else None
        self._restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "scaffold_project"

    @property
    def description(self) -> str:
        return (
            "Create a new project scaffold for the requested platform. "
            "Supports production-shaped web, mobile, desktop, backend, CLI, "
            "extension, bot, and multi-platform solution workspaces."
        )

    def _resolve_project_dir(self, project_name: str) -> Path:
        base = self._workspace if self._workspace is not None else Path.cwd()
        return (base / project_name).resolve()

    @staticmethod
    def _template_root() -> Path:
        return Path(__file__).resolve().parents[2] / "templates"

    @staticmethod
    def _runtime_env(project_parent: Path) -> dict[str, str]:
        tool_home = project_parent / ".teai_builder-home"
        env = os.environ.copy()
        env.update({
            "HOME": str(tool_home),
            "XDG_CONFIG_HOME": str(tool_home / ".config"),
            "XDG_CACHE_HOME": str(tool_home / ".cache"),
            "XDG_STATE_HOME": str(tool_home / ".local" / "state"),
            "NPM_CONFIG_CACHE": str(tool_home / ".npm"),
            "EXPO_NO_TELEMETRY": "1",
        })
        for path in (
            tool_home,
            Path(env["XDG_CONFIG_HOME"]),
            Path(env["XDG_CACHE_HOME"]),
            Path(env["XDG_STATE_HOME"]),
            Path(env["NPM_CONFIG_CACHE"]),
        ):
            path.mkdir(parents=True, exist_ok=True)
        return env

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _display_project_name(project_name: str, planner_result: dict[str, Any] | None = None) -> str:
        source = str((planner_result or {}).get("project_name") or Path(project_name).name or project_name)
        cleaned = " ".join(part for part in source.replace("_", " ").replace("-", " ").split() if part)
        return cleaned.title() or "Project"

    @staticmethod
    def _planner_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _planner_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _render_project_doc(
        self,
        *,
        project_name: str,
        platform: str,
        planner_result: dict[str, Any],
        today: str,
    ) -> str:
        brief = self._planner_dict(planner_result.get("product_brief"))
        ui_direction = self._planner_dict(brief.get("ui_direction"))
        color_theme = self._planner_dict(ui_direction.get("color_theme"))
        backend = self._planner_dict(brief.get("backend"))
        success_metrics = self._planner_list(brief.get("success_metrics"))
        surfaces = self._planner_list(brief.get("delivery_surfaces")) or [
            surface.get("platform", "")
            for surface in planner_result.get("surfaces", [])
            if isinstance(surface, dict) and surface.get("platform")
        ]
        shared_capabilities = self._planner_list(planner_result.get("shared_capabilities"))
        display_name = self._display_project_name(project_name, planner_result)
        stack_rows = [
            f"| Frontend | {platform if platform in {'web', 'desktop', 'mobile', 'extension'} else 'shared surface'} runtime | planned |",
            f"| Backend | {'Required' if backend.get('required') else 'Optional'} service layer | planned |",
            f"| Database | {'Persistent storage' if 'persistent-storage' in shared_capabilities else 'SQLite / local-first fallback'} | planned |",
            f"| Auth | {backend.get('auth_strategy', 'Define during research')} | planned |",
            "| Hosting | Define during research | planned |",
            "| CI/CD | Verification-first pipeline | planned |",
        ]
        ai_rows = [
            "| Architect | planned | Product brief, architecture, and research packet are required before major coding. |",
            "| Designer | planned | Define screens, theme, states, and interaction quality bar. |",
            "| Frontend Engineer | planned | Build the primary user flows and production UI states. |",
            "| Backend Engineer | planned | Implement APIs, auth, data, and operational readiness. |",
            "| DevOps Engineer | planned | Wire local runtime, deployment path, and release automation. |",
            "| QA Engineer | planned | Verify build quality, regression coverage, and release readiness. |",
        ]
        quality_bar = self._planner_list(brief.get("quality_bar"))
        return (
            f"# Project: {display_name}\n\n"
            f"**Status:** research\n\n"
            f"**Idea:** {brief.get('elevator_pitch') or planner_result.get('summary') or f'Initial {platform} scaffold created by TeAI Builder.'}\n\n"
            f"**Deployment Target:** Define after research for {' / '.join(surfaces) if surfaces else platform} delivery.\n\n"
            f"**Started:** {today}\n\n"
            "---\n\n"
            "## Product Brief\n\n"
            f"- **Target users:** {', '.join(self._planner_list(brief.get('target_users'))) or 'To be refined in research'}\n"
            f"- **Core problem:** {brief.get('core_user_problem') or 'Clarify the main user problem.'}\n"
            f"- **Primary journey:** {' -> '.join(self._planner_list(brief.get('primary_user_journey'))) or 'Define the core journey before implementation.'}\n"
            f"- **Surfaces:** {', '.join(surfaces) or platform}\n"
            f"- **Core features:** {', '.join(self._planner_list(brief.get('core_features'))) or 'Define in planning'}\n\n"
            "---\n\n"
            "## Tech Stack\n\n"
            "| Layer | Technology | Version |\n"
            "|-------|-----------|---------|\n"
            + "\n".join(stack_rows)
            + "\n\n---\n\n"
            "## UX / UI Direction\n\n"
            f"- **Style keywords:** {', '.join(self._planner_list(ui_direction.get('style_keywords'))) or 'Define during design research'}\n"
            f"- **Color theme:** primary `{color_theme.get('primary', 'tbd')}`, accent `{color_theme.get('accent', 'tbd')}`, background `{color_theme.get('background', 'tbd')}`, surface `{color_theme.get('surface', 'tbd')}`\n"
            f"- **Layout guidance:** {ui_direction.get('layout_guidance') or 'Document screens, states, and layout system.'}\n\n"
            "---\n\n"
            "## AI Team Status\n\n"
            "| Role | Status | Notes |\n"
            "|------|--------|-------|\n"
            + "\n".join(ai_rows)
            + "\n\n---\n\n"
            "## Success Criteria\n\n"
            + "\n".join(f"- {item}" for item in success_metrics)
            + ("\n" if success_metrics else "- Define measurable success criteria during research.\n")
            + "\n---\n\n"
            "## Local Runtime\n\n"
            "**Bootstrap Command:** `./scripts/bootstrap.sh`\n\n"
            "**Dev Start Command:** `./scripts/dev.sh`\n\n"
            "**Seed/Admin Command:** `./scripts/seed_admin.sh`\n\n"
            "**Health Check URL:** `http://127.0.0.1:<port>/health`\n\n"
            f"**Service Strategy:** {backend.get('auth_strategy') or 'Choose a local runtime and persistence strategy during research.'}\n\n"
            "---\n\n"
            "## Quality Bar\n\n"
            + "\n".join(f"- {item}" for item in quality_bar)
            + ("\n" if quality_bar else "- Keep the project production-shaped and publishable.\n")
            + "\n---\n\n"
            "## Changelog\n\n"
            "| Version | Date | Changes |\n"
            "|---------|------|---------|\n"
            f"| 0.1.0 | {today} | Initial planner-seeded scaffold created |\n"
        )

    def _render_research_doc(
        self,
        *,
        project_name: str,
        planner_result: dict[str, Any],
        today: str,
    ) -> str:
        display_name = self._display_project_name(project_name, planner_result)
        research_tracks = planner_result.get("research_tracks") if isinstance(planner_result.get("research_tracks"), list) else []
        assumptions = self._planner_list(self._planner_dict(planner_result.get("product_brief")).get("assumptions"))
        questions = self._planner_list(planner_result.get("clarification_questions"))
        query_rows = []
        for track in research_tracks:
            if isinstance(track, dict):
                query_rows.append(f"| {track.get('track', '')} | {track.get('goal', '')} |")
        risk_rows = [
            "| Scope drift from rough idea | Medium | Lock the brief, success criteria, and first release boundaries before coding. |",
            "| Stack choice mismatch | Medium | Validate libraries, packaging, and deployment constraints with fresh research. |",
        ]
        if questions:
            risk_rows.append("| Unanswered product questions | High | Resolve clarification questions before final delivery scope is locked. |")
        todo_items = [
            "Research leading reference products and expected UX patterns.",
            "Validate stack, auth, and persistence choices for the required surfaces.",
            "Confirm deployment, release, and verification strategy.",
            "Update PLAN.md with researched decisions and final acceptance criteria.",
            "Update TASKS.md with owners and dependencies before major implementation.",
        ]
        return (
            f"# Research: architect on {display_name}\n\n"
            f"**Date:** {today}\n"
            "**Role:** architect\n"
            "**Task assigned:** Convert the rough idea into a researched, implementation-ready product definition.\n\n"
            "---\n\n"
            "## Context Read\n\n"
            "- [x] `PROJECT.md` reviewed — current status: research\n"
            "- [ ] `DECISION_LOG.md` reviewed — relevant decisions: none yet\n"
            "- [ ] `docs/architecture.md` reviewed (if exists)\n"
            "- [ ] Existing source files read: none yet\n\n"
            "---\n\n"
            "## Web Research\n\n"
            "| Query | Key Finding |\n"
            "|-------|------------|\n"
            + ("\n".join(query_rows) if query_rows else "| product-shape | Research required before implementation. |")
            + "\n\n---\n\n"
            "## Key Findings To Confirm\n\n"
            + "\n".join(f"{index}. {item}" for index, item in enumerate(assumptions or ["Validate the first release assumptions with current research."], start=1))
            + "\n\n---\n\n"
            "## Risks and Unknowns\n\n"
            "| Risk | Likelihood | Mitigation |\n"
            "|------|-----------|-----------|\n"
            + "\n".join(risk_rows)
            + "\n\n---\n\n"
            "## Clarification Questions\n\n"
            + ("\n".join(f"- {item}" for item in questions) if questions else "- No blocking clarification questions were identified by the planner.")
            + "\n\n---\n\n"
            "## Todo List (ordered by dependency)\n\n"
            + "\n".join(f"- [ ] {item}" for item in todo_items)
            + "\n"
        )

    def _render_plan_doc(
        self,
        *,
        project_name: str,
        planner_result: dict[str, Any],
        today: str,
    ) -> str:
        display_name = self._display_project_name(project_name, planner_result)
        brief = self._planner_dict(planner_result.get("product_brief"))
        ui_direction = self._planner_dict(brief.get("ui_direction"))
        backend = self._planner_dict(brief.get("backend"))
        phases = planner_result.get("implementation_phases") if isinstance(planner_result.get("implementation_phases"), list) else []
        tasks = planner_result.get("initial_tasks") if isinstance(planner_result.get("initial_tasks"), list) else []
        phase_blocks: list[str] = []
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            phase_id = str(phase.get("phase") or "Phase")
            phase_name = str(phase.get("name") or "Unnamed Phase")
            goal = str(phase.get("goal") or "Define the goal.")
            deliverables = self._planner_list(phase.get("deliverables"))
            phase_tasks = [task for task in tasks if isinstance(task, dict) and task.get("phase") == phase_id]
            block = [f"### {phase_id}: {phase_name} — {goal}"]
            for task in phase_tasks:
                depends = self._planner_list(task.get("depends_on"))
                depends_suffix = f" (depends: {', '.join(depends)})" if depends else ""
                block.append(f"- **Task {task.get('id')}** {task.get('title')} — owner: {task.get('owner')}{depends_suffix}")
                for subtask in self._planner_list(task.get("subtasks")):
                    block.append(f"  - {subtask}")
            if deliverables:
                block.append(f"- **Deliverables:** {', '.join(deliverables)}")
            phase_blocks.append("\n".join(block))
        return (
            f"# Plan: {display_name}\n\n"
            f"_Created: {today} · Last updated: {today}_\n\n"
            "## 1. Idea & Goal\n"
            f"- **What we're building:** {brief.get('elevator_pitch') or planner_result.get('summary')}\n"
            f"- **Core value:** {brief.get('core_user_problem') or 'Solve the primary user problem well.'}\n"
            "- **Success criteria (measurable):**\n"
            + "\n".join(f"  - {item}" for item in self._planner_list(brief.get("success_metrics")))
            + "\n\n## 2. Research Summary (the idea, not just the tech)\n"
            "- **Reference / competitor apps:** Research current leaders before implementation.\n"
            f"- **Core mechanics / features users expect:** {', '.join(self._planner_list(brief.get('core_features'))) or 'Define from research'}\n"
            "- **Chosen tech stack + why:** Confirm after the research pass and log in `DECISION_LOG.md`.\n"
            f"- **Risks / unknowns:** {', '.join(self._planner_list(planner_result.get('clarification_questions'))) or 'Document risks discovered during research.'}\n\n"
            "## 3. UX / UI Plan\n"
            f"- **Screens / views:** {', '.join(self._planner_list(brief.get('primary_user_journey'))) or 'Define the primary screens.'}\n"
            "- **Navigation flow:** Map the onboarding, core workflow, and settings/account flows.\n"
            "- **Key components & interactions:** Cover loading, empty, success, and error states before coding.\n"
            f"- **Visual style:** {', '.join(self._planner_list(ui_direction.get('style_keywords'))) or 'Define a production UI system'} with theme guidance `{self._planner_dict(ui_direction.get('color_theme')).get('primary', 'tbd')}` primary.\n\n"
            "## 4. Backend / Data Plan\n"
            f"- **Data models / entities:** {', '.join(self._planner_list(backend.get('data_entities'))) or 'Document the domain models.'}\n"
            "- **Persistence:** Prefer a documented local-first or SQLite fallback plus production-ready persistence options.\n"
            f"- **APIs / services:** {', '.join(self._planner_list(backend.get('core_services'))) or 'Define after research'}\n\n"
            "## 5. Architecture Plan\n"
            f"- **Module / file structure:** Organize around {', '.join(self._planner_list(brief.get('delivery_surfaces'))) or 'the required surfaces'}.\n"
            "- **State management:** Keep state boundaries explicit between UI, domain, and server concerns.\n"
            f"- **Key algorithms / systems:** {planner_result.get('scaffold_strategy', 'scaffold')} plus a documented verification path.\n\n"
            "## 6. Phased Breakdown (Phases -> Tasks -> Subtasks)\n\n"
            + ("\n\n".join(phase_blocks) if phase_blocks else "Document phases before major implementation.")
            + "\n\n## 7. Milestones & Definition of Done\n"
            "- **Milestone 1:** Planner-seeded scaffold plus approved brief/research/plan/task artifacts.\n"
            "- **Milestone 2:** Core user journey implemented across required surfaces.\n"
            "- **Final DoD:** builds clean · verification passes · preview renders · core docs stay in sync with implementation.\n"
        )

    def _render_tasks_doc(
        self,
        *,
        project_name: str,
        planner_result: dict[str, Any],
        today: str,
    ) -> str:
        display_name = self._display_project_name(project_name, planner_result)
        tasks = planner_result.get("initial_tasks") if isinstance(planner_result.get("initial_tasks"), list) else []
        phase_order: list[str] = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            if not isinstance(task, dict):
                continue
            phase = str(task.get("phase") or "Unassigned")
            if phase not in grouped:
                grouped[phase] = []
                phase_order.append(phase)
            grouped[phase].append(task)
        task_total = len([task for task in tasks if isinstance(task, dict)])
        next_up = grouped[phase_order[0]][0] if phase_order else None
        next_up_label = (
            f"{next_up.get('id')} {next_up.get('title')}"
            if isinstance(next_up, dict)
            else "Define the first task"
        )
        blocks: list[str] = []
        for phase in phase_order:
            blocks.append(f"## {phase}: status: todo")
            for task in grouped[phase]:
                depends = self._planner_list(task.get("depends_on"))
                depends_suffix = f" (depends: {', '.join(depends)})" if depends else ""
                blocks.append(f"- [ ] {task.get('id')} {task.get('title')} — owner: {task.get('owner')}{depends_suffix}")
                for subtask in self._planner_list(task.get("subtasks")):
                    blocks.append(f"  - [ ] {subtask}")
            blocks.append("")
        return (
            f"# Live Tasks: {display_name}\n\n"
            f"_Last updated: {today}_\n\n"
            "## Summary\n"
            f"- **Current phase:** {phase_order[0] if phase_order else 'Phase 1'}\n"
            f"- **Done:** 0 / {task_total} tasks\n"
            f"- **Next up:** {next_up_label}\n"
            "- **Blocked:** none yet\n\n"
            + "\n".join(blocks)
            + "## Blocked / Issues\n"
            "- (none yet — list blockers here as they appear)\n"
        )

    @staticmethod
    def _python_package_name(project_name: str) -> str:
        normalized = "".join(ch if ch.isalnum() else "_" for ch in project_name.strip().lower())
        normalized = normalized.strip("_")
        return normalized or "app"

    @staticmethod
    def _make_executable(path: Path) -> None:
        current = path.stat().st_mode
        path.chmod(current | 0o111)

    def _ensure_company_files(
        self,
        project_dir: Path,
        project_name: str,
        platform: str,
        planner_result: dict[str, Any] | None = None,
    ) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        replacements = {
            "{name}": project_name,
            "{project name}": project_name,
            "{user's original idea — one paragraph}": f"Initial {platform} project scaffold created by TeAI Builder.",
            "{where the user wants to deploy — Vercel / Railway / Render / Fly.io / VPS / other}": "local-dev (set final target later)",
            "{date}": today,
            "{role}": "ceo",
            "{architect | designer | frontend_engineer | backend_engineer | devops_engineer | qa_engineer}": "ceo",
            "{brief description of the task}": f"Bootstrap the initial {platform} project runtime and delivery workflow.",
            "{status}": "research",
            "{list}": "none yet",
        }
        decision_log_template = self._template_root() / "DECISION_LOG.md"
        if decision_log_template.is_file():
            content = decision_log_template.read_text(encoding="utf-8")
            for old, new in replacements.items():
                content = content.replace(old, new)
            self._write_text(project_dir / "DECISION_LOG.md", content)

        if isinstance(planner_result, dict):
            self._write_text(
                project_dir / "PROJECT.md",
                self._render_project_doc(
                    project_name=project_name,
                    platform=platform,
                    planner_result=planner_result,
                    today=today,
                ),
            )
            self._write_text(
                project_dir / "RESEARCH.md",
                self._render_research_doc(
                    project_name=project_name,
                    planner_result=planner_result,
                    today=today,
                ),
            )
            self._write_text(
                project_dir / "PLAN.md",
                self._render_plan_doc(
                    project_name=project_name,
                    planner_result=planner_result,
                    today=today,
                ),
            )
            self._write_text(
                project_dir / "TASKS.md",
                self._render_tasks_doc(
                    project_name=project_name,
                    planner_result=planner_result,
                    today=today,
                ),
            )
        else:
            for template_name in ("PROJECT.md", "RESEARCH.md", "PLAN.md", "TASKS.md"):
                template_path = self._template_root() / template_name
                if not template_path.is_file():
                    continue
                content = template_path.read_text(encoding="utf-8")
                for old, new in replacements.items():
                    content = content.replace(old, new)
                self._write_text(project_dir / template_name, content)

        superpowers_doc = (
            "# Superpowers Workflow\n\n"
            "This project uses TeAI Builder's Superpowers-inspired build workflow.\n\n"
            "## Required Order\n\n"
            "1. Research and clarify the real problem before code.\n"
            "2. Write a spec/design in `docs/superpowers/specs/`.\n"
            "3. Write a concrete implementation plan in `docs/superpowers/plans/`.\n"
            "4. Mirror the approved work into `PLAN.md` and `TASKS.md`.\n"
            "5. Execute task-by-task with specialized employees/subagents.\n"
            "6. Run independent verification before declaring completion.\n\n"
            "## Project Paths\n\n"
            "- Specs: `docs/superpowers/specs/`\n"
            "- Plans: `docs/superpowers/plans/`\n"
            "- Live project plan: `PLAN.md`\n"
            "- Live task board: `TASKS.md`\n"
            "- Research log: `RESEARCH.md`\n"
            "- Runtime contract: `docs/local-runtime.md`\n"
        )
        self._write_text(project_dir / "SUPERPOWERS.md", superpowers_doc)
        for path in (
            project_dir / "docs" / "superpowers" / "specs" / ".gitkeep",
            project_dir / "docs" / "superpowers" / "plans" / ".gitkeep",
        ):
            self._write_text(path, "")

    def _ensure_runtime_files(self, project_dir: Path, platform: str, template: str | None = None) -> None:
        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        if platform == "web" and (template or "").strip().lower() == "saas":
            bootstrap_cmd = (
                "python3 -m venv backend/.venv\n"
                "backend/.venv/bin/python -m pip install --upgrade pip\n"
                "backend/.venv/bin/python -m pip install -e ./backend\n"
                "cd frontend && npm install\n"
            )
            dev_cmd = (
                "backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 &\n"
                "BACK_PID=$!\n"
                "trap 'kill \"$BACK_PID\" 2>/dev/null || true' EXIT\n"
                "cd frontend && npm run dev -- --host 0.0.0.0 --port 4173\n"
            )
            seed_cmd = "backend/.venv/bin/python backend/scripts/seed_admin.py\n"
        elif platform == "solution":
            companion_bootstrap = []
            if (project_dir / "desktop" / "package.json").exists():
                companion_bootstrap.append("cd desktop && npm install && cd ..")
            if (project_dir / "mobile" / "package.json").exists():
                companion_bootstrap.append("cd mobile && npm install && cd ..")
            bootstrap_cmd = (
                "python3 -m venv backend/.venv\n"
                "backend/.venv/bin/python -m pip install --upgrade pip\n"
                "backend/.venv/bin/python -m pip install -e ./backend\n"
                "cd frontend && npm install && cd ..\n"
                + ("\n".join(companion_bootstrap) + "\n" if companion_bootstrap else "")
            )
            dev_cmd = (
                "backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 &\n"
                "BACK_PID=$!\n"
                "trap 'kill \"$BACK_PID\" 2>/dev/null || true' EXIT\n"
                "cd frontend && npm run dev -- --host 0.0.0.0 --port 4173\n"
            )
            seed_cmd = "backend/.venv/bin/python backend/scripts/seed_admin.py\n"
        else:
            bootstrap_cmd = {
                "mobile": "npm install",
                "web": "npm install",
                "desktop": "npm install",
                "backend": "python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e .",
                "cli": "python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e .",
                "extension": "npm install",
                "bot": "python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e .",
            }.get(platform, "echo 'Add project bootstrap steps here'")
            dev_cmd = {
                "mobile": "npx expo start",
                "web": "npm run dev -- --host 0.0.0.0",
                "desktop": "npm run electron:dev",
                "backend": ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000",
                "cli": ".venv/bin/python -m app --help",
                "extension": "npm run dev",
                "bot": ".venv/bin/python -m app",
            }.get(platform, "echo 'Add project dev start command here'")
            seed_cmd = (
                "echo 'Add a real admin/dev seed step before delivery if this project uses auth, RBAC, or seeded tenants.'\n"
            )
        bootstrap_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            f"cd \"$(dirname \"$0\")/..\"\n{bootstrap_cmd}\n"
        )
        dev_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            f"cd \"$(dirname \"$0\")/..\"\n{dev_cmd}\n"
        )
        seed_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            f"cd \"$(dirname \"$0\")/..\"\n{seed_cmd}"
        )
        for path, content in (
            (scripts_dir / "bootstrap.sh", bootstrap_script),
            (scripts_dir / "dev.sh", dev_script),
            (scripts_dir / "seed_admin.sh", seed_script),
        ):
            self._write_text(path, content)
            self._make_executable(path)

        env_example = (
            "# Document every required environment variable here.\n"
            "# If the project later adds Postgres or Redis, either provide docker compose\n"
            "# for local dev or document a SQLite/in-memory fallback that works without them.\n"
        )
        env_path = project_dir / ".env.example"
        if not env_path.exists():
            self._write_text(env_path, env_example)

        runtime_doc = (
            "# Local Runtime Contract\n\n"
            "This project must stay runnable in a fresh local environment.\n\n"
            "## Required Commands\n\n"
            f"- Bootstrap: `./scripts/bootstrap.sh`\n"
            f"- Start dev runtime: `./scripts/dev.sh`\n"
            "- Seed admin/dev data when auth or RBAC exists: `./scripts/seed_admin.sh`\n\n"
            "## Service Strategy\n\n"
            "- If the app needs Postgres/Redis, add `docker-compose.yml` (or `compose.yaml`) for local dev.\n"
            "- If Docker/services are not available, implement a documented SQLite or in-memory fallback for local dev.\n"
            "- Python backends must declare runtime deps in `pyproject.toml` or `requirements*.txt` and include `uvicorn` when using FastAPI.\n"
        )
        self._write_text(project_dir / "docs" / "local-runtime.md", runtime_doc)

    def _scaffold_saas(self, project_dir: Path, project_name: str) -> str:
        project_dir.mkdir(parents=True, exist_ok=True)

        frontend_package = """{
  "name": "%s-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0"
  }
}
""" % project_name
        frontend_tsconfig = """{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "Bundler",
    "allowImportingTsExtensions": false,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
"""
        frontend_vite = """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4173,
    host: "0.0.0.0",
  },
});
"""
        frontend_html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>%s</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""" % project_name
        frontend_main = """import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
"""
        frontend_app = """import { FormEvent, useEffect, useMemo, useState } from "react";

const apiBase = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const localTokenKey = "teai-saas-token";

type LoginState = {
  email: string;
  password: string;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: {
    email: string;
    role: string;
  };
};

type BootstrapInfo = {
  admin_email: string;
  seed_command: string;
  login_hint: string;
};

type HealthInfo = {
  status: string;
  app: string;
  database_url: string;
  redis_enabled: boolean;
};

type DashboardSummary = {
  workspace_name: string;
  tenant_name: string;
  active_users: number;
  open_tasks: number;
  system_mode: string;
  role: string;
};

export function App() {
  const [form, setForm] = useState<LoginState>({
    email: "admin@example.com",
    password: "change-me-now",
  });
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [bootstrap, setBootstrap] = useState<BootstrapInfo | null>(null);
  const [session, setSession] = useState<LoginResponse | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [message, setMessage] = useState("Run bootstrap and seed scripts, then sign in.");
  const isAuthenticated = useMemo(() => Boolean(session?.access_token), [session]);

  useEffect(() => {
    void fetch(`${apiBase}/health`)
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => null);
    void fetch(`${apiBase}/api/admin/bootstrap`)
      .then((response) => response.json())
      .then(setBootstrap)
      .catch(() => null);
    const cached = window.localStorage.getItem(localTokenKey);
    if (cached) {
      setSession({
        access_token: cached,
        token_type: "bearer",
        user: {
          email: form.email,
          role: "owner",
        },
      });
    }
  }, [form.email]);

  useEffect(() => {
    if (!session?.access_token) {
      setSummary(null);
      return;
    }
    void fetch(`${apiBase}/api/dashboard/summary`, {
      headers: {
        Authorization: `Bearer ${session.access_token}`,
      },
    })
      .then((response) => response.json())
      .then(setSummary)
      .catch(() => null);
  }, [session]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("Signing in...");
    const response = await fetch(`${apiBase}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(form),
    });
    if (!response.ok) {
      setMessage("Login failed. Run ./scripts/seed_admin.sh or update .env first.");
      return;
    }
    const payload = (await response.json()) as LoginResponse;
    window.localStorage.setItem(localTokenKey, payload.access_token);
    setSession(payload);
    setMessage(`Signed in as ${payload.user.email}`);
  }

  function signOut() {
    window.localStorage.removeItem(localTokenKey);
    setSession(null);
    setMessage("Signed out.");
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <span className="badge">TeAI Builder SaaS Baseline</span>
        <h1>%s</h1>
        <p>
          This scaffold includes a React dashboard shell, FastAPI auth/bootstrap endpoints,
          local admin seeding, and a SQLite-first fallback with optional Postgres and Redis.
        </p>
        <div className="actions">
          <a href={`${apiBase}/health`} target="_blank" rel="noreferrer">
            Check API Health
          </a>
          <a href={`${apiBase}/api/admin/bootstrap`} target="_blank" rel="noreferrer">
            Admin Bootstrap Info
          </a>
        </div>
      </section>

      <section className="dashboard-grid">
        <article className="panel login-panel">
          <h2>{isAuthenticated ? "Workspace Session" : "Admin Sign In"}</h2>
          {!isAuthenticated ? (
            <form className="stack" onSubmit={onSubmit}>
              <label>
                Email
                <input
                  value={form.email}
                  onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={form.password}
                  onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                />
              </label>
              <button type="submit">Sign in</button>
            </form>
          ) : (
            <div className="stack">
              <p className="session-pill">{session?.user.email}</p>
              <p>Role: {session?.user.role}</p>
              <button type="button" className="ghost" onClick={signOut}>
                Sign out
              </button>
            </div>
          )}
          <p className="muted">{message}</p>
        </article>

        <article className="panel">
          <h2>Runtime</h2>
          <ul className="plain-list">
            <li>Frontend: Vite + React on port 4173</li>
            <li>Backend: FastAPI + SQLModel on port 8000</li>
            <li>Fallback DB: SQLite at `backend/data/app.db`</li>
            <li>Optional services: Postgres + Redis in compose</li>
          </ul>
        </article>

        <article className="panel">
          <h2>Bootstrap</h2>
          <ul className="plain-list">
            <li>Seed command: {bootstrap?.seed_command || "./scripts/seed_admin.sh"}</li>
            <li>Admin email: {bootstrap?.admin_email || "admin@example.com"}</li>
            <li>Login hint: {bootstrap?.login_hint || "Use the seeded admin credentials."}</li>
          </ul>
        </article>
      </section>

      <section className="panel-grid">
        <article className="panel">
          <h2>Workspace Snapshot</h2>
          <ul className="plain-list">
            <li>Workspace: {summary?.workspace_name || "Sign in to load"}</li>
            <li>Tenant: {summary?.tenant_name || "Default Tenant"}</li>
            <li>Role: {summary?.role || session?.user.role || "owner"}</li>
          </ul>
        </article>
        <article className="panel">
          <h2>Health Snapshot</h2>
          <pre>{JSON.stringify(health, null, 2)}</pre>
        </article>
        <article className="panel">
          <h2>Starter Modules</h2>
          <ul className="plain-list">
            <li>Auth login endpoint</li>
            <li>JWT bearer token flow</li>
            <li>Admin bootstrap info endpoint</li>
            <li>Tenant, workspace, and user SQLModel tables</li>
            <li>Admin seed script</li>
            <li>Backend Dockerfile</li>
            <li>Optional local compose stack</li>
          </ul>
        </article>
        <article className="panel">
          <h2>Next steps</h2>
          <ol>
            <li>Run <code>./scripts/bootstrap.sh</code></li>
            <li>Run <code>./scripts/seed_admin.sh</code></li>
            <li>Run <code>./scripts/dev.sh</code></li>
          </ol>
        </article>
      </section>
    </main>
  );
}
""" % project_name
        frontend_styles = """:root {
  color-scheme: dark;
  font-family: Inter, system-ui, sans-serif;
  background: #0f172a;
  color: #e2e8f0;
}

body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at top, rgba(59, 130, 246, 0.24), transparent 35%),
    linear-gradient(180deg, #0f172a 0%%, #111827 100%%);
}

.app-shell {
  max-width: 1040px;
  margin: 0 auto;
  padding: 48px 24px 72px;
}

.hero {
  padding: 32px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 24px;
  background: rgba(15, 23, 42, 0.72);
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.4);
}

.badge {
  display: inline-block;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.16);
  color: #93c5fd;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.hero h1 {
  margin-bottom: 12px;
  font-size: clamp(2.2rem, 5vw, 4rem);
}

.hero p {
  max-width: 720px;
  line-height: 1.65;
  color: #cbd5e1;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

.actions a {
  color: #0f172a;
  background: #f8fafc;
  padding: 12px 16px;
  border-radius: 12px;
  text-decoration: none;
  font-weight: 600;
}

.panel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-top: 20px;
}

.panel {
  padding: 20px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.75);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.panel h2 {
  margin-top: 0;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1fr;
  gap: 16px;
  margin-top: 20px;
}

.stack {
  display: grid;
  gap: 12px;
}

label {
  display: grid;
  gap: 8px;
  color: #cbd5e1;
}

input {
  width: 100%;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.88);
  color: #f8fafc;
}

button {
  border: 0;
  border-radius: 12px;
  padding: 12px 16px;
  font-weight: 700;
  color: #0f172a;
  background: #93c5fd;
  cursor: pointer;
}

.ghost {
  color: #e2e8f0;
  background: rgba(148, 163, 184, 0.16);
}

.muted {
  color: #94a3b8;
}

.plain-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 8px;
}

.session-pill {
  display: inline-flex;
  width: fit-content;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.16);
  color: #bbf7d0;
}

pre {
  margin: 0;
  padding: 12px;
  overflow-x: auto;
  border-radius: 14px;
  background: rgba(2, 6, 23, 0.55);
}

@media (max-width: 860px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

code {
  font-family: "SFMono-Regular", Consolas, monospace;
}
"""
        backend_pyproject = """[project]
name = "%s-backend"
version = "0.1.0"
description = "FastAPI backend baseline for a TeAI Builder SaaS scaffold"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115,<1.0",
  "uvicorn[standard]>=0.30,<1.0",
  "sqlmodel>=0.0.22,<1.0",
  "pydantic-settings>=2.3,<3.0",
  "PyJWT>=2.9,<3.0"
]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["app*"]
""" % project_name
        backend_main = """from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Header, status
from pydantic import BaseModel
from sqlmodel import Session, select

from .config import Settings, get_settings
from .database import create_db_and_tables, get_session
from .models import Tenant, User, Workspace
from .security import create_access_token, decode_access_token, verify_password

app = FastAPI(title="%s API", version="0.1.0")


class LoginRequest(BaseModel):
    email: str
    password: str


def get_current_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    user = session.exec(select(User).where(User.email == payload["sub"])).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


@app.get("/health")
def health(settings: Settings = get_settings()) -> dict[str, object]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "database_url": settings.database_url,
        "redis_enabled": bool(settings.redis_url),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/admin/bootstrap")
def admin_bootstrap(
    settings: Settings = get_settings(),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    tenant = session.exec(select(Tenant)).first()
    workspace = session.exec(select(Workspace)).first()
    return {
        "admin_email": settings.admin_email,
        "seed_command": "./scripts/seed_admin.sh",
        "login_hint": "Use the seeded owner credentials from backend/data/seed-admin.txt for local sign-in.",
        "tenant_name": tenant.name if tenant else "Default Tenant",
        "workspace_name": workspace.name if workspace else settings.app_name,
    }


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    settings: Settings = get_settings(),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.email, role=user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "role": user.role,
            "workspace_id": user.workspace_id,
        },
    }


@app.get("/api/dashboard/summary")
def dashboard_summary(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    workspace = session.get(Workspace, current_user.workspace_id)
    tenant = session.get(Tenant, workspace.tenant_id) if workspace else None
    user_count = len(session.exec(select(User).where(User.workspace_id == current_user.workspace_id)).all())
    return {
        "workspace_name": workspace.name if workspace else "Unknown Workspace",
        "tenant_name": tenant.name if tenant else "Unknown Tenant",
        "active_users": user_count,
        "open_tasks": 5,
        "system_mode": "local-dev",
        "role": current_user.role,
    }
""" % project_name
        backend_config = """from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "%s"
    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = ""
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-now"
    admin_role: str = "owner"
    jwt_secret: str = "dev-secret-change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
""" % project_name
        backend_database = """from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
"""
        backend_models = """from __future__ import annotations

from typing import Optional

from sqlmodel import Field, SQLModel


class Tenant(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(index=True, unique=True)


class Workspace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(index=True, foreign_key="tenant.id")
    name: str
    slug: str = Field(index=True, unique=True)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(index=True, foreign_key="workspace.id")
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: str = "owner"
"""
        backend_security = """from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status

from .config import get_settings


def hash_password(raw_password: str) -> str:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def verify_password(raw_password: str, password_hash: str) -> bool:
    return hash_password(raw_password) == password_hash


def create_access_token(subject: str, *, role: str) -> str:
    settings = get_settings()
    payload = {
        "sub": subject,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, str]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
"""
        backend_seed = """from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.database import create_db_and_tables, engine
from app.models import Tenant, User, Workspace
from app.security import hash_password


def main() -> None:
    settings = get_settings()
    create_db_and_tables()
    with Session(engine) as session:
        tenant = session.exec(select(Tenant).where(Tenant.slug == "default-tenant")).first()
        if tenant is None:
            tenant = Tenant(name="Default Tenant", slug="default-tenant")
            session.add(tenant)
            session.commit()
            session.refresh(tenant)

        workspace = session.exec(select(Workspace).where(Workspace.slug == "main-workspace")).first()
        if workspace is None:
            workspace = Workspace(
                tenant_id=tenant.id,
                name=settings.app_name,
                slug="main-workspace",
            )
            session.add(workspace)
            session.commit()
            session.refresh(workspace)

        user = session.exec(select(User).where(User.email == settings.admin_email)).first()
        if user is None:
            user = User(
                workspace_id=workspace.id,
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                role=settings.admin_role,
            )
            session.add(user)
        else:
            user.workspace_id = workspace.id
            user.password_hash = hash_password(settings.admin_password)
            user.role = settings.admin_role
        session.commit()

    out = Path(__file__).resolve().parents[1] / "data" / "seed-admin.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        (
            f"email={settings.admin_email}\\n"
            f"password={settings.admin_password}\\n"
            f"tenant=Default Tenant\\n"
            f"workspace={settings.app_name}\\n"
            "note=replace these credentials before production use\\n"
        ),
        encoding="utf-8",
    )
    print(f"Seeded local admin metadata at {out}")


if __name__ == "__main__":
    main()
"""
        backend_readme = """# Backend

FastAPI baseline for the TeAI Builder SaaS scaffold.

## Local development

- Install: `../scripts/bootstrap.sh`
- Start: `../scripts/dev.sh`
- Seed admin: `../scripts/seed_admin.sh`
"""
        backend_dockerfile = """FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts

RUN python -m pip install --upgrade pip && python -m pip install .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""
        compose = """services:
  backend:
    build:
      context: ./backend
    env_file:
      - .env.example
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 10s
      timeout: 5s
      retries: 10

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      timeout: 5s
      retries: 10
    volumes:
      - postgres-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  postgres-data:
"""
        env_example = """# Frontend
VITE_API_BASE_URL=http://127.0.0.1:8000

# Backend
APP_NAME=%s
DATABASE_URL=sqlite:///./backend/data/app.db
# For Postgres local dev via docker compose:
# DATABASE_URL=postgresql://app:app@127.0.0.1:5432/app
REDIS_URL=
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=change-me-now
ADMIN_ROLE=owner
JWT_SECRET=dev-secret-change-me
""" % project_name

        files: dict[Path, str] = {
            project_dir / "frontend" / "package.json": frontend_package,
            project_dir / "frontend" / "tsconfig.json": frontend_tsconfig,
            project_dir / "frontend" / "vite.config.ts": frontend_vite,
            project_dir / "frontend" / "index.html": frontend_html,
            project_dir / "frontend" / "src" / "main.tsx": frontend_main,
            project_dir / "frontend" / "src" / "App.tsx": frontend_app,
            project_dir / "frontend" / "src" / "styles.css": frontend_styles,
            project_dir / "backend" / "pyproject.toml": backend_pyproject,
            project_dir / "backend" / "README.md": backend_readme,
            project_dir / "backend" / "Dockerfile": backend_dockerfile,
            project_dir / "backend" / "app" / "__init__.py": "",
            project_dir / "backend" / "app" / "main.py": backend_main,
            project_dir / "backend" / "app" / "config.py": backend_config,
            project_dir / "backend" / "app" / "database.py": backend_database,
            project_dir / "backend" / "app" / "models.py": backend_models,
            project_dir / "backend" / "app" / "security.py": backend_security,
            project_dir / "backend" / "scripts" / "seed_admin.py": backend_seed,
            project_dir / "docker-compose.yml": compose,
            project_dir / ".env.example": env_example,
        }
        for path, content in files.items():
            self._write_text(path, content)

        return (
            "Scaffolded SaaS baseline project.\n\n"
            f"- Path: {project_dir}\n"
            "- Frontend: React + Vite + TypeScript dashboard/login shell\n"
            "- Backend: FastAPI + uvicorn with auth/bootstrap endpoints\n"
            "- Runtime packaging: backend Dockerfile + compose health checks\n"
            "- Local services: optional Postgres + Redis via docker compose\n"
            "- Local fallback: SQLite by default for backend development\n\n"
            "Next: run `./scripts/bootstrap.sh` and then `./scripts/dev.sh`."
        )

    async def execute(
        self,
        project_name: str,
        platform: str,
        template: str | None = None,
        planner_result: dict[str, Any] | None = None,
        force: bool = False,
        **kwargs: Any,
    ) -> Any:
        project_dir = self._resolve_project_dir(project_name)

        if project_dir.exists() and not force:
            return f"Error: project already exists at {project_dir}. Use force=true to overwrite."

        if project_dir.exists() and force:
            shutil.rmtree(project_dir)

        try:
            if platform == "mobile":
                result = self._scaffold_mobile(project_dir, project_name, template)
            elif platform == "web":
                if (template or "").strip().lower() == "saas":
                    result = self._scaffold_saas(project_dir, project_name)
                else:
                    result = self._scaffold_web(project_dir, project_name, template)
            elif platform == "desktop":
                if (template or "").strip().lower() in {"suite", "desktop-suite", "desktop_suite"}:
                    result = self._scaffold_solution(project_dir, project_name, "desktop-suite")
                    platform = "solution"
                else:
                    result = self._scaffold_desktop(project_dir, project_name, template)
            elif platform == "backend":
                result = self._scaffold_backend(project_dir, project_name)
            elif platform == "cli":
                result = self._scaffold_cli(project_dir, project_name)
            elif platform == "extension":
                result = self._scaffold_extension(project_dir, project_name)
            elif platform == "bot":
                result = self._scaffold_bot(project_dir, project_name)
            elif platform == "solution":
                result = self._scaffold_solution(project_dir, project_name, template)
            else:
                return f"Error: unsupported platform '{platform}'"
            self._ensure_company_files(project_dir, project_name, platform, planner_result)
            self._ensure_runtime_files(project_dir, platform, template)
            return result
        except Exception as exc:
            return f"Error scaffolding project: {exc}"

    def _scaffold_mobile(self, project_dir: Path, project_name: str, template: str | None) -> str:
        cmd = [
            "npx",
            "--yes",
            "create-expo-app@latest",
            str(project_dir),
            "--template",
            "blank-typescript",
        ]
        if template:
            cmd[cmd.index("blank-typescript")] = template
        env = self._runtime_env(project_dir.parent)

        completed = subprocess.run(
            cmd,
            cwd=project_dir.parent,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            return (
                "Error: create-expo-app failed.\n\n"
                f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
            )
        return (
            "Scaffolded Expo project.\n\n"
            f"- Path: {project_dir}\n"
            f"- Command: {' '.join(cmd)}\n\n"
            "Next: run `npx expo start` inside the project."
        )

    def _scaffold_web(self, project_dir: Path, project_name: str, template: str | None) -> str:
        cmd = [
            "npx",
            "--yes",
            "create-vite@latest",
            str(project_dir),
            "--template",
            "react-ts",
        ]
        env = self._runtime_env(project_dir.parent)
        completed = subprocess.run(
            cmd,
            cwd=project_dir.parent,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            return (
                "Error: create-vite failed.\n\n"
                f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
            )
        return (
            "Scaffolded Vite + TypeScript project.\n\n"
            f"- Path: {project_dir}\n"
            f"- Command: {' '.join(cmd)}\n\n"
            "Next: run `npm install && npm run dev` inside the project."
        )

    def _scaffold_desktop(self, project_dir: Path, project_name: str, template: str | None) -> str:
        project_dir.mkdir(parents=True, exist_ok=True)
        package_json = """{
  "name": "%s",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "main": "electron/main.js",
  "scripts": {
    "dev": "vite --host 0.0.0.0",
    "electron": "electron .",
    "electron:dev": "concurrently -k \\\"vite --host 0.0.0.0\\\" \\\"wait-on tcp:5173 && electron .\\\"",
    "build": "tsc -b && vite build"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.1",
    "concurrently": "^9.0.1",
    "electron": "^31.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "wait-on": "^8.0.1"
  }
}
""" % project_name
        tsconfig = """{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
"""
        vite_config = """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173
  }
});
"""
        index_html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>%s</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""" % project_name
        main_tsx = """import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
"""
        app_tsx = """export function App() {
  return (
    <main className="shell">
      <section className="card">
        <p className="eyebrow">Desktop Product</p>
        <h1>%s</h1>
        <p>
          This Electron shell is ready to host the native desktop experience for your
          product, with room for auth, sync, downloads, updater flows, and account management.
        </p>
        <ul>
          <li>Renderer: React + Vite + TypeScript</li>
          <li>Shell: Electron main process with preload bridge</li>
          <li>Next step: connect native menus, updates, and platform services</li>
        </ul>
      </section>
    </main>
  );
}
""" % project_name
        styles = """:root {
  color-scheme: dark;
  font-family: Inter, system-ui, sans-serif;
  background: #0b1020;
  color: #f8fafc;
}

body {
  margin: 0;
  min-height: 100vh;
  background: radial-gradient(circle at top, #1e293b, #0b1020 65%);
}

.shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
}

.card {
  width: min(720px, 100%);
  padding: 32px;
  border-radius: 24px;
  background: rgba(15, 23, 42, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.2);
  box-shadow: 0 20px 80px rgba(15, 23, 42, 0.45);
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: #38bdf8;
  font-size: 12px;
}
"""
        electron_main = """import { app, BrowserWindow } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    void win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    void win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
"""
        electron_preload = """import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
});
"""
        files = {
            project_dir / "package.json": package_json,
            project_dir / "tsconfig.json": tsconfig,
            project_dir / "vite.config.ts": vite_config,
            project_dir / "index.html": index_html,
            project_dir / "src" / "main.tsx": main_tsx,
            project_dir / "src" / "App.tsx": app_tsx,
            project_dir / "src" / "styles.css": styles,
            project_dir / "electron" / "main.js": electron_main,
            project_dir / "electron" / "preload.js": electron_preload,
        }
        for path, content in files.items():
            self._write_text(path, content)
        return (
            "Scaffolded Electron + React desktop workspace.\n\n"
            f"- Path: {project_dir}\n"
            "- Stack: Electron shell + React + Vite + TypeScript\n"
            "- Runtime: `npm run electron:dev`\n\n"
            "Next: run `npm install && npm run electron:dev` inside the project."
        )

    def _scaffold_backend(self, project_dir: Path, project_name: str) -> str:
        package_name = self._python_package_name(project_name)
        pyproject = """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "%s-api"
version = "0.1.0"
description = "Production-shaped FastAPI service scaffold"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111,<1.0",
  "uvicorn[standard]>=0.30,<1.0",
  "pydantic-settings>=2.3,<3.0",
]
""" % project_name
        main_py = """from fastapi import FastAPI

app = FastAPI(title="%s API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
""" % project_name
        readme = (
            f"# {project_name} API\n\n"
            "This scaffold starts with FastAPI, a health endpoint, and project-level "
            "runtime scripts intended for real product work.\n"
        )
        self._write_text(project_dir / "pyproject.toml", pyproject)
        self._write_text(project_dir / "app" / "__init__.py", "")
        self._write_text(project_dir / "app" / "main.py", main_py)
        self._write_text(project_dir / "README.md", readme)
        return (
            "Scaffolded FastAPI backend service.\n\n"
            f"- Path: {project_dir}\n"
            "- Runtime: `./scripts/bootstrap.sh` then `./scripts/dev.sh`\n"
        )

    def _scaffold_cli(self, project_dir: Path, project_name: str) -> str:
        package_name = self._python_package_name(project_name)
        pyproject = """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "%s"
version = "0.1.0"
description = "Production-shaped CLI scaffold"
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12,<1.0",
]

[project.scripts]
%s = "%s.__main__:main"
""" % (project_name, package_name, package_name)
        main_py = """import typer

app = typer.Typer(help="CLI entrypoint for %s.")


@app.command()
def doctor() -> None:
    typer.echo("runtime ok")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
""" % project_name
        self._write_text(project_dir / "pyproject.toml", pyproject)
        self._write_text(project_dir / package_name / "__init__.py", "")
        self._write_text(project_dir / package_name / "__main__.py", main_py)
        return (
            "Scaffolded Python CLI workspace.\n\n"
            f"- Path: {project_dir}\n"
            f"- Entry command: `{package_name} doctor`\n"
        )

    def _scaffold_extension(self, project_dir: Path, project_name: str) -> str:
        package_json = """{
  "name": "%s-extension",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "echo 'Load this extension unpacked from the project root'",
    "build": "echo 'Package extension assets for release'"
  }
}
""" % project_name
        manifest = """{
  "manifest_version": 3,
  "name": "%s",
  "version": "0.1.0",
  "action": {
    "default_popup": "popup.html"
  },
  "background": {
    "service_worker": "background.js",
    "type": "module"
  },
  "options_page": "options.html",
  "permissions": ["storage", "tabs"],
  "host_permissions": ["<all_urls>"]
}
""" % project_name
        popup_html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>%s</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <main class="panel">
      <h1>%s</h1>
      <p>Browser extension production scaffold with popup, options, and background worker.</p>
      <button id="ping">Check runtime</button>
      <pre id="output">ready</pre>
    </main>
    <script type="module" src="popup.js"></script>
  </body>
</html>
""" % (project_name, project_name)
        popup_js = """const output = document.getElementById("output");
document.getElementById("ping")?.addEventListener("click", async () => {
  output.textContent = "extension runtime ready";
});
"""
        options_html = """<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>%s Settings</title><link rel="stylesheet" href="styles.css" /></head>
  <body><main class="panel"><h1>Settings</h1><p>Persist API keys and account settings here.</p></main></body>
</html>
""" % project_name
        background_js = """chrome.runtime.onInstalled.addListener(() => {
  console.log("extension installed");
});
"""
        styles = ".panel{font-family:Inter,system-ui,sans-serif;padding:16px;min-width:320px}"
        files = {
            project_dir / "package.json": package_json,
            project_dir / "manifest.json": manifest,
            project_dir / "popup.html": popup_html,
            project_dir / "popup.js": popup_js,
            project_dir / "options.html": options_html,
            project_dir / "background.js": background_js,
            project_dir / "styles.css": styles,
        }
        for path, content in files.items():
            self._write_text(path, content)
        return (
            "Scaffolded browser extension workspace.\n\n"
            f"- Path: {project_dir}\n"
            "- Includes popup, options page, and MV3 background worker.\n"
        )

    def _scaffold_bot(self, project_dir: Path, project_name: str) -> str:
        pyproject = """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "%s-bot"
version = "0.1.0"
description = "Production-shaped bot service scaffold"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111,<1.0",
  "uvicorn[standard]>=0.30,<1.0",
]
""" % project_name
        main_py = """import os

from fastapi import FastAPI

app = FastAPI(title="%s Bot Service")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": os.getenv("BOT_PROVIDER", "telegram")}


@app.post("/webhooks/events")
def webhook(payload: dict) -> dict:
    return {"accepted": True, "received": payload}
""" % project_name
        env_example = (
            "BOT_PROVIDER=telegram\n"
            "BOT_TOKEN=\n"
            "WEBHOOK_SECRET=\n"
        )
        self._write_text(project_dir / "pyproject.toml", pyproject)
        self._write_text(project_dir / "app" / "__init__.py", "")
        self._write_text(project_dir / "app" / "main.py", main_py)
        self._write_text(project_dir / ".env.example", env_example)
        return (
            "Scaffolded bot service workspace.\n\n"
            f"- Path: {project_dir}\n"
            "- Includes webhook endpoint and provider/token environment contract.\n"
        )

    def _scaffold_solution(self, project_dir: Path, project_name: str, template: str | None) -> str:
        mode = (template or "desktop-suite").strip().lower()
        if mode in {"suite", "desktop_suite"}:
            mode = "desktop-suite"
        if mode == "mobile_suite":
            mode = "mobile-suite"
        if mode not in {"desktop-suite", "mobile-suite"}:
            mode = "desktop-suite"

        base_summary = self._scaffold_saas(project_dir, project_name)
        if mode == "desktop-suite":
            companion_summary = self._scaffold_desktop(project_dir / "desktop", f"{project_name}-desktop", "electron")
            surface_matrix = (
                "- Primary surface: desktop app in `desktop/`\n"
                "- Companion surface: account/admin web app in `frontend/`\n"
                "- Shared backend and auth layer in `backend/`\n"
            )
        else:
            companion_summary = self._scaffold_mobile(project_dir / "mobile", f"{project_name}-mobile", None)
            surface_matrix = (
                "- Primary surface: mobile app in `mobile/`\n"
                "- Companion surface: account/admin web app in `frontend/`\n"
                "- Shared backend and auth layer in `backend/`\n"
            )

        architecture = (
            "# Solution Architecture\n\n"
            f"Product: {project_name}\n\n"
            "## Surface Matrix\n\n"
            f"{surface_matrix}\n"
            "## Delivery Expectation\n\n"
            "- Treat this as one product with multiple deliverables, not disconnected demos.\n"
            "- Shared auth, billing, and account state should live in the backend contract.\n"
            "- Shared domain models and API contracts should be documented before major implementation.\n"
        )
        self._write_text(project_dir / "docs" / "solution-architecture.md", architecture)
        return (
            "Scaffolded multi-platform product suite.\n\n"
            f"- Path: {project_dir}\n"
            f"- Mode: {mode}\n"
            "- Includes web + backend plus a primary native surface.\n\n"
            f"{base_summary}\n\n{companion_summary}"
        )
