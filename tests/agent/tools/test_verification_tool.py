from __future__ import annotations

import json

import httpx
import pytest

from teai_builder.agent.tools.verification import RunVerificationTool


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_run_verification_fails_backend_without_runtime_contract(tmp_path) -> None:
    project_dir = tmp_path / "projects" / "saas-app"
    _write(
        project_dir / "main.py",
        (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "DATABASE_URL = 'postgresql://local'\n"
            "CACHE_URL = 'redis://localhost:6379/0'\n"
            "ROLE = 'super_admin'\n"
        ),
    )

    tool = RunVerificationTool(workspace=str(tmp_path))
    result = json.loads(await tool.execute(project="saas-app"))

    runtime_check = next(check for check in result["checks"] if check["name"] == "runtime_contract")
    assert runtime_check["status"] == "fail"
    assert ".env.example" in runtime_check["detail"]
    assert "docker compose or SQLite/in-memory fallback" in runtime_check["detail"]
    assert "admin seed path" in runtime_check["detail"]


@pytest.mark.asyncio
async def test_run_verification_passes_backend_with_runtime_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "projects" / "saas-app"
    _write(
        project_dir / "main.py",
        (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "DATABASE_URL = 'postgresql://local'\n"
            "CACHE_URL = 'redis://localhost:6379/0'\n"
            "ROLE = 'super_admin'\n"
        ),
    )
    _write(
        project_dir / "pyproject.toml",
        (
            "[project]\n"
            "name = 'saas-app'\n"
            "version = '0.1.0'\n"
            "dependencies = ['fastapi', 'uvicorn']\n"
        ),
    )
    _write(project_dir / ".env.example", "DATABASE_URL=\nREDIS_URL=\n")
    _write(project_dir / "docker-compose.yml", "services:\n  db:\n    image: postgres:16\n")
    _write(project_dir / "scripts" / "bootstrap.sh", "#!/usr/bin/env bash\npython3 -m pip install -e .\n")
    _write(project_dir / "scripts" / "dev.sh", "#!/usr/bin/env bash\npython3 -m uvicorn main:app --port 8000\n")
    _write(project_dir / "scripts" / "seed_admin.sh", "#!/usr/bin/env bash\necho seed\n")
    _write(
        project_dir / ".teai_builder" / "state.json",
        '{\n  "project": "saas-app",\n  "platform": "backend",\n  "phase": "qa",\n  "phases": {},\n  "artifacts": {"web_preview": "http://127.0.0.1:8000"},\n  "verification": null\n}\n',
    )

    async def fake_get(self, url: str) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>ok</body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = RunVerificationTool(workspace=str(tmp_path))
    result = json.loads(await tool.execute(project="saas-app"))

    runtime_check = next(check for check in result["checks"] if check["name"] == "runtime_contract")
    assert runtime_check["status"] == "pass"
    assert "bootstrap via scripts/bootstrap.sh" in runtime_check["detail"]
    assert "start via scripts/dev.sh" in runtime_check["detail"]
    assert "seed via scripts/seed_admin.sh" in runtime_check["detail"]
    preview_check = next(check for check in result["checks"] if check["name"] == "preview_evidence")
    preview_runtime = next(check for check in result["checks"] if check["name"] == "preview_runtime")
    assert preview_check["status"] == "pass"
    assert "web preview recorded" in preview_check["detail"]
    assert preview_runtime["status"] == "pass"


@pytest.mark.asyncio
async def test_run_verification_fails_expo_project_with_missing_preview_contract(tmp_path) -> None:
    project_dir = tmp_path / "projects" / "expo-app"
    _write(
        project_dir / "package.json",
        json.dumps(
            {
                "name": "expo-app",
                "main": "index.js",
                "dependencies": {
                    "expo": "~53.0.0",
                    "react": "19.0.0",
                    "react-native": "0.79.0",
                },
            }
        ),
    )
    _write(
        project_dir / "app.json",
        json.dumps(
            {
                "expo": {
                    "icon": "./assets/icon.png",
                }
            }
        ),
    )
    _write(
        project_dir / ".teai_builder" / "state.json",
        '{\n  "project": "expo-app",\n  "platform": "mobile",\n  "phase": "qa",\n  "phases": {},\n  "artifacts": {},\n  "verification": null\n}\n',
    )

    tool = RunVerificationTool(workspace=str(tmp_path))
    result = json.loads(await tool.execute(project="expo-app"))

    expo_check = next(check for check in result["checks"] if check["name"] == "expo_config")
    preview_check = next(check for check in result["checks"] if check["name"] == "preview_evidence")
    preview_runtime = next(check for check in result["checks"] if check["name"] == "preview_runtime")
    assert expo_check["status"] == "fail"
    assert "package.json main must be expo/AppEntry.js" in expo_check["detail"]
    assert "missing Expo web preview deps" in expo_check["detail"]
    assert "missing Expo assets" in expo_check["detail"]
    assert preview_check["status"] == "fail"
    assert "missing expo_native_preview" in preview_check["detail"]
    assert preview_runtime["status"] == "skip"


@pytest.mark.asyncio
async def test_run_verification_passes_expo_project_with_preview_contract(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "projects" / "expo-app"
    _write(project_dir / "assets" / "icon.png", "png")
    _write(
        project_dir / "package.json",
        json.dumps(
            {
                "name": "expo-app",
                "main": "expo/AppEntry.js",
                "dependencies": {
                    "expo": "~53.0.0",
                    "react": "19.0.0",
                    "react-native": "0.79.0",
                    "react-dom": "19.0.0",
                    "react-native-web": "^0.20.0",
                    "@expo/metro-runtime": "~4.0.0",
                },
            }
        ),
    )
    _write(
        project_dir / "app.json",
        json.dumps(
            {
                "expo": {
                    "icon": "./assets/icon.png",
                }
            }
        ),
    )
    _write(
        project_dir / ".teai_builder" / "state.json",
        '{\n  "project": "expo-app",\n  "platform": "mobile",\n  "phase": "qa",\n  "phases": {},\n  "artifacts": {"expo_native_preview": "exp://192.168.0.8:8081", "expo_web_preview": "http://127.0.0.1:8081"},\n  "verification": null\n}\n',
    )

    async def fake_get(self, url: str) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><body>expo web</body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = RunVerificationTool(workspace=str(tmp_path))
    result = json.loads(await tool.execute(project="expo-app"))

    expo_check = next(check for check in result["checks"] if check["name"] == "expo_config")
    preview_check = next(check for check in result["checks"] if check["name"] == "preview_evidence")
    preview_runtime = next(check for check in result["checks"] if check["name"] == "preview_runtime")
    assert expo_check["status"] == "pass"
    assert "main=expo/AppEntry.js" in expo_check["detail"]
    assert "Expo web preview deps installed" in expo_check["detail"]
    assert "Expo asset references resolve" in expo_check["detail"]
    assert preview_check["status"] == "pass"
    assert "native Expo preview recorded" in preview_check["detail"]
    assert preview_runtime["status"] == "pass"
    assert "http://127.0.0.1:8081" in preview_runtime["detail"]


@pytest.mark.asyncio
async def test_run_verification_fails_when_local_preview_runtime_is_unhealthy(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "projects" / "web-app"
    _write(project_dir / "package.json", json.dumps({"name": "web-app", "scripts": {"build": "vite build"}}))
    _write(
        project_dir / ".teai_builder" / "state.json",
        '{\n  "project": "web-app",\n  "platform": "web",\n  "phase": "qa",\n  "phases": {},\n  "artifacts": {"web_preview": "http://127.0.0.1:4173"},\n  "verification": null\n}\n',
    )

    async def fake_get(self, url: str) -> httpx.Response:
        return httpx.Response(
            500,
            headers={"content-type": "text/html"},
            text="<html><body>boom</body></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tool = RunVerificationTool(workspace=str(tmp_path))
    result = json.loads(await tool.execute(project="web-app"))

    preview_check = next(check for check in result["checks"] if check["name"] == "preview_evidence")
    preview_runtime = next(check for check in result["checks"] if check["name"] == "preview_runtime")
    assert preview_check["status"] == "pass"
    assert preview_runtime["status"] == "fail"
    assert "HTTP 500" in preview_runtime["detail"]
