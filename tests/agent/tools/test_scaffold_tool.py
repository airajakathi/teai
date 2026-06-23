from __future__ import annotations

from types import SimpleNamespace

import pytest

from teai_builder.agent.tools.product_surface_planner import PlanProductSurfacesTool
from teai_builder.agent.tools.scaffold import ScaffoldProjectTool


@pytest.mark.asyncio
async def test_desktop_scaffold_creates_project_dir(tmp_path) -> None:
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(project_name="deskapp", platform="desktop")

    project_dir = tmp_path / "deskapp"
    assert "Scaffolded Electron + React desktop workspace." in result
    assert project_dir.exists()
    assert (project_dir / "package.json").exists()
    assert (project_dir / "index.html").exists()
    assert (project_dir / "src" / "main.tsx").exists()
    assert (project_dir / "src" / "App.tsx").exists()
    assert (project_dir / "electron" / "main.js").exists()
    assert (project_dir / "electron" / "preload.js").exists()
    assert (project_dir / "PROJECT.md").exists()
    assert (project_dir / "DECISION_LOG.md").exists()
    assert (project_dir / "RESEARCH.md").exists()
    assert (project_dir / "PLAN.md").exists()
    assert (project_dir / "TASKS.md").exists()
    assert (project_dir / "SUPERPOWERS.md").exists()
    assert (project_dir / ".env.example").exists()
    assert (project_dir / "docs" / "local-runtime.md").exists()
    assert (project_dir / "docs" / "superpowers" / "specs" / ".gitkeep").exists()
    assert (project_dir / "docs" / "superpowers" / "plans" / ".gitkeep").exists()
    assert (project_dir / "scripts" / "bootstrap.sh").exists()
    assert (project_dir / "scripts" / "dev.sh").exists()
    assert (project_dir / "scripts" / "seed_admin.sh").exists()


@pytest.mark.asyncio
async def test_mobile_scaffold_uses_workspace_local_runtime_dirs(tmp_path, monkeypatch) -> None:
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=True)
    captured: dict[str, object] = {}

    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("teai_builder.agent.tools.scaffold.subprocess.run", _run)

    result = await tool.execute(project_name="mobilegame", platform="mobile")

    env = captured["env"]
    project_parent = tmp_path
    assert "Scaffolded Expo project." in result
    assert captured["cwd"] == project_parent
    assert env["HOME"] == str(project_parent / ".teai_builder-home")
    assert env["NPM_CONFIG_CACHE"] == str(project_parent / ".teai_builder-home" / ".npm")
    assert env["XDG_STATE_HOME"] == str(project_parent / ".teai_builder-home" / ".local" / "state")


@pytest.mark.asyncio
async def test_scaffold_defaults_to_workspace_even_without_restrict_flag(tmp_path) -> None:
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=False)

    await tool.execute(project_name="workspace-default", platform="backend")

    assert (tmp_path / "workspace-default" / "pyproject.toml").exists()


@pytest.mark.asyncio
async def test_web_saas_scaffold_creates_fullstack_runtime_baseline(tmp_path) -> None:
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(project_name="crm-suite", platform="web", template="saas")

    project_dir = tmp_path / "crm-suite"
    assert "Scaffolded SaaS baseline project." in result
    assert (project_dir / "frontend" / "package.json").exists()
    assert (project_dir / "frontend" / "src" / "App.tsx").exists()
    assert (project_dir / "backend" / "pyproject.toml").exists()
    assert (project_dir / "backend" / "app" / "main.py").exists()
    assert (project_dir / "backend" / "app" / "database.py").exists()
    assert (project_dir / "backend" / "app" / "models.py").exists()
    assert (project_dir / "backend" / "app" / "security.py").exists()
    assert (project_dir / "backend" / "Dockerfile").exists()
    assert (project_dir / "backend" / "scripts" / "seed_admin.py").exists()
    assert (project_dir / "docker-compose.yml").exists()
    assert (project_dir / ".env.example").exists()
    assert (project_dir / "PLAN.md").exists()
    assert (project_dir / "TASKS.md").exists()
    assert (project_dir / "SUPERPOWERS.md").exists()
    assert (project_dir / "docs" / "superpowers" / "specs" / ".gitkeep").exists()
    assert (project_dir / "docs" / "superpowers" / "plans" / ".gitkeep").exists()

    app_tsx = (project_dir / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    backend_main = (project_dir / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    backend_models = (project_dir / "backend" / "app" / "models.py").read_text(encoding="utf-8")
    backend_security = (project_dir / "backend" / "app" / "security.py").read_text(encoding="utf-8")
    env_example = (project_dir / ".env.example").read_text(encoding="utf-8")
    bootstrap = (project_dir / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    dev = (project_dir / "scripts" / "dev.sh").read_text(encoding="utf-8")
    seed = (project_dir / "scripts" / "seed_admin.sh").read_text(encoding="utf-8")
    runtime_doc = (project_dir / "docs" / "local-runtime.md").read_text(encoding="utf-8")
    dockerfile = (project_dir / "backend" / "Dockerfile").read_text(encoding="utf-8")
    superpowers = (project_dir / "SUPERPOWERS.md").read_text(encoding="utf-8")

    assert "backend/.venv/bin/python -m pip install -e ./backend" in bootstrap
    assert "cd frontend && npm install" in bootstrap
    assert "uvicorn app.main:app" in dev
    assert "backend/scripts/seed_admin.py" in seed
    assert "docker-compose.yml" in runtime_doc
    assert "Sign in" in app_tsx
    assert "/api/auth/login" in app_tsx
    assert "Authorization: `Bearer ${session.access_token}`" in app_tsx
    assert "@app.post(\"/api/auth/login\")" in backend_main
    assert "@app.get(\"/api/dashboard/summary\")" in backend_main
    assert "Header(default=None)" in backend_main
    assert "create_access_token" in backend_main
    assert "class Tenant(SQLModel, table=True)" in backend_models
    assert "class Workspace(SQLModel, table=True)" in backend_models
    assert "class User(SQLModel, table=True)" in backend_models
    assert "jwt.encode" in backend_security
    assert "JWT_SECRET=dev-secret-change-me" in env_example
    assert "CMD [\"uvicorn\", \"app.main:app\"" in dockerfile
    assert "docs/superpowers/specs/" in superpowers
    assert "docs/superpowers/plans/" in superpowers


@pytest.mark.asyncio
async def test_backend_scaffold_creates_fastapi_service(tmp_path) -> None:
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(project_name="signal-api", platform="backend")

    project_dir = tmp_path / "signal-api"
    assert "Scaffolded FastAPI backend service." in result
    assert (project_dir / "pyproject.toml").exists()
    assert (project_dir / "app" / "main.py").exists()
    assert (project_dir / "PROJECT.md").exists()
    assert (project_dir / "scripts" / "bootstrap.sh").exists()

    main_py = (project_dir / "app" / "main.py").read_text(encoding="utf-8")
    dev_script = (project_dir / "scripts" / "dev.sh").read_text(encoding="utf-8")
    assert "@app.get(\"/health\")" in main_py
    assert "uvicorn app.main:app" in dev_script


@pytest.mark.asyncio
async def test_solution_scaffold_creates_desktop_web_backend_suite(tmp_path) -> None:
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=True)

    result = await tool.execute(project_name="cursor-suite", platform="solution", template="desktop-suite")

    project_dir = tmp_path / "cursor-suite"
    assert "Scaffolded multi-platform product suite." in result
    assert (project_dir / "frontend" / "package.json").exists()
    assert (project_dir / "backend" / "pyproject.toml").exists()
    assert (project_dir / "desktop" / "package.json").exists()
    assert (project_dir / "desktop" / "electron" / "main.js").exists()
    assert (project_dir / "docs" / "solution-architecture.md").exists()

    architecture = (project_dir / "docs" / "solution-architecture.md").read_text(encoding="utf-8")
    bootstrap = (project_dir / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    assert "Primary surface: desktop app" in architecture
    assert "Companion surface: account/admin web app" in architecture
    assert "cd desktop && npm install && cd .." in bootstrap


@pytest.mark.asyncio
async def test_scaffold_prefills_company_docs_from_planner_result(tmp_path) -> None:
    planner = PlanProductSurfacesTool()
    planner_result = await planner.execute(
        project_name="cursor-suite",
        user_request=(
            "Build a Cursor-like AI coding app with a desktop app, website for downloads, "
            "user login, billing, and account management."
        ),
    )
    tool = ScaffoldProjectTool(workspace=tmp_path, restrict_to_workspace=True)

    await tool.execute(
        project_name="cursor-suite",
        platform="solution",
        template="desktop-suite",
        planner_result=planner_result,
    )

    project_dir = tmp_path / "cursor-suite"
    project_doc = (project_dir / "PROJECT.md").read_text(encoding="utf-8")
    research_doc = (project_dir / "RESEARCH.md").read_text(encoding="utf-8")
    plan_doc = (project_dir / "PLAN.md").read_text(encoding="utf-8")
    tasks_doc = (project_dir / "TASKS.md").read_text(encoding="utf-8")

    assert "Cursor Suite is a coordinated desktop-led product suite" in project_doc
    assert "**Color theme:** primary `#14b8a6`" in project_doc
    assert "authentication and session management" in project_doc
    assert "backend-architecture" in research_doc
    assert "Expand the rough idea into a detailed product brief" in plan_doc
    assert "[ ] 1.1 Expand the rough idea into a detailed product brief" in tasks_doc
