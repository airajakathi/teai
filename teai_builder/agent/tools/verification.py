"""Independent verification runner for generated projects.

Subagents self-report success; this tool actually re-runs the static/build
checks inside the project and returns a structured pass/fail result. The result
is persisted to the project state file so ``project_gate`` consumes real
evidence before allowing delivery/deploy. Designed to never block on a missing
toolchain: an unavailable checker is reported as ``skip``, not ``fail``.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

import httpx

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.project_state import (
    load_state,
    record_verification_result,
    resolve_project_dir,
)
from teai_builder.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema

_MAX_FILES_PER_CHECK = 40
_SCRIPT_BLOCK_RE = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)
# Production-readiness smells. Reported as warnings (non-blocking) so the gate
# isn't tripped by legitimate uses, but surfaced so the CEO can demand fixes.
_SMELL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"lorem ipsum", "placeholder lorem-ipsum copy"),
    (r"\bTODO\b|\bFIXME\b", "unfinished TODO/FIXME markers"),
    (r"your[_-]?api[_-]?key|REPLACE[_-]?ME|changeme", "placeholder credentials"),
    (r"coming soon|under construction", "stub 'coming soon' content"),
)
_RUNTIME_TEXT_EXTS = {
    ".env",
    ".example",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
_BACKEND_RUNTIME_HINTS = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "express",
    "fastify",
    "hono",
    "postgres",
    "redis",
    "jwt",
    "rbac",
    "tenant",
)
_SERVICE_HINTS = ("postgres", "postgresql", "redis")
_LOCAL_FALLBACK_HINTS = (
    "sqlite",
    "in-memory",
    "in memory",
    "fakeredis",
    "use_sqlite",
    "dev_database_url",
)
_ADMIN_HINTS = (
    "seed admin",
    "seed_admin",
    "super_admin",
    "admin seed",
    "rbac",
)
_PLACEHOLDER_RUNTIME_HINTS = (
    "add a real admin/dev seed step",
    "add project bootstrap steps here",
    "add project dev start command here",
)


async def _run(cmd: str, cwd: Path, timeout: int) -> tuple[int, str]:
    """Run a shell command via a login shell so PATH (node/npx) is available."""
    shell = shutil.which("bash") or "/bin/bash"
    try:
        proc = await asyncio.create_subprocess_exec(
            shell, "-lc", cmd,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return 127, f"failed to launch: {exc}"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        with __import__("contextlib").suppress(Exception):
            await proc.wait()
        return 124, f"timed out after {timeout}s"
    return proc.returncode or 0, out.decode("utf-8", errors="replace")[-4000:]


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


@tool_parameters(
    tool_parameters_schema(
        project=StringSchema(
            "Project name under projects/ or an absolute path. "
            "Optional when there is a single project.",
            nullable=True,
        ),
        timeout=IntegerSchema(
            300,
            description="Per-check timeout in seconds (default 300, max 900).",
            minimum=10,
            maximum=900,
            nullable=True,
        ),
    )
)
class RunVerificationTool(Tool):
    """Re-run static/build checks on a project and return structured results."""

    _scopes = {"core", "subagent"}

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    @classmethod
    def create(cls, ctx: Any) -> "RunVerificationTool":
        return cls(workspace=getattr(ctx, "workspace", None))

    @property
    def name(self) -> str:
        return "run_verification"

    @property
    def description(self) -> str:
        return (
            "Independently verify a generated project by actually re-running its "
            "static and build checks (node --check on HTML/JS, tsc --noEmit, "
            "npm run build, python compile) plus production-readiness smell scans. "
            "Returns structured pass/fail JSON and records the result on the "
            "project state file so project_gate can consume it. Run this before "
            "asking project_gate to advance to qa/deliver/deploy. Unavailable "
            "toolchains are reported as 'skip', never a false failure."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters_schema  # type: ignore[attr-defined]

    async def execute(
        self,
        project: str | None = None,
        timeout: int | None = None,
        **_: Any,
    ) -> str:
        project_dir, error = resolve_project_dir(self._workspace, project)
        if project_dir is None:
            return f"run_verification error: {error}"
        per_timeout = max(10, min(900, int(timeout or 300)))

        checks: list[dict[str, Any]] = []
        checks.append(await self._check_node_syntax(project_dir, per_timeout))
        checks.append(await self._check_typescript(project_dir, per_timeout))
        checks.append(await self._check_npm_build(project_dir, per_timeout))
        checks.append(await self._check_python_compile(project_dir, per_timeout))
        checks.append(await self._check_expo_config(project_dir))
        checks.append(await self._check_runtime_contract(project_dir))
        checks.append(await self._check_preview_evidence(project_dir))
        checks.append(await self._check_preview_runtime(project_dir, min(per_timeout, 10)))
        warnings = self._scan_smells(project_dir)

        failed = [c for c in checks if c["status"] == "fail"]
        ran = [c for c in checks if c["status"] in ("pass", "fail")]
        status = "fail" if failed else ("pass" if ran else "inconclusive")
        result = {
            "status": status,
            "project": project_dir.name,
            "project_path": str(project_dir),
            "checks": checks,
            "warnings": warnings,
            "summary": self._summary(status, checks, warnings),
        }
        try:
            record_verification_result(project_dir, result)
        except OSError:
            pass
        return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def _summary(status: str, checks: list[dict[str, Any]], warnings: list[str]) -> str:
        passed = sum(1 for c in checks if c["status"] == "pass")
        failed = sum(1 for c in checks if c["status"] == "fail")
        skipped = sum(1 for c in checks if c["status"] == "skip")
        bits = [f"{passed} passed", f"{failed} failed", f"{skipped} skipped"]
        if warnings:
            bits.append(f"{len(warnings)} warning(s)")
        verdict = {
            "pass": "VERIFIED",
            "fail": "FAILED — fix before delivery",
            "inconclusive": "INCONCLUSIVE — no runnable checks matched this project",
        }[status]
        return f"{verdict}: " + ", ".join(bits)

    # ── individual checks ────────────────────────────────────────────────

    async def _check_node_syntax(self, project_dir: Path, timeout: int) -> dict[str, Any]:
        name = "node_syntax"
        if not _has_tool("node"):
            return {"name": name, "status": "skip", "detail": "node not installed"}
        html_files = self._collect(project_dir, "*.html")
        js_files = [
            p for p in self._collect(project_dir, "*.js")
            if "node_modules" not in p.parts and "dist" not in p.parts and "build" not in p.parts
        ]
        if not html_files and not js_files:
            return {"name": name, "status": "skip", "detail": "no standalone HTML/JS"}
        problems: list[str] = []
        checked = 0
        for html in html_files[:_MAX_FILES_PER_CHECK]:
            code = self._extract_inline_js(html)
            if not code.strip():
                continue
            checked += 1
            rc, out = await self._node_check_source(code, timeout)
            if rc != 0:
                problems.append(f"{html.name}: {out.strip()[:300]}")
        for js in js_files[:_MAX_FILES_PER_CHECK]:
            checked += 1
            rc, out = await _run(f"node --check {self._q(js)}", project_dir, timeout)
            if rc != 0:
                problems.append(f"{js.name}: {out.strip()[:300]}")
        if checked == 0:
            return {"name": name, "status": "skip", "detail": "no inline JS to check"}
        if problems:
            return {"name": name, "status": "fail", "detail": "; ".join(problems[:10])}
        return {"name": name, "status": "pass", "detail": f"{checked} file(s) parse cleanly"}

    async def _check_typescript(self, project_dir: Path, timeout: int) -> dict[str, Any]:
        name = "typescript"
        if not (project_dir / "tsconfig.json").is_file():
            return {"name": name, "status": "skip", "detail": "no tsconfig.json"}
        if not _has_tool("npx") and not (project_dir / "node_modules" / ".bin" / "tsc").exists():
            return {"name": name, "status": "skip", "detail": "tsc/npx unavailable"}
        local = project_dir / "node_modules" / ".bin" / "tsc"
        cmd = f"{self._q(local)} --noEmit" if local.exists() else "npx --no-install tsc --noEmit"
        rc, out = await _run(cmd, project_dir, timeout)
        if "could not determine executable" in out.lower() or "not found" in out.lower():
            return {"name": name, "status": "skip", "detail": "tsc not installed"}
        if rc != 0:
            return {"name": name, "status": "fail", "detail": out.strip()[-1500:]}
        return {"name": name, "status": "pass", "detail": "tsc --noEmit clean"}

    async def _check_npm_build(self, project_dir: Path, timeout: int) -> dict[str, Any]:
        name = "npm_build"
        pkg = project_dir / "package.json"
        if not pkg.is_file():
            return {"name": name, "status": "skip", "detail": "no package.json"}
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"name": name, "status": "fail", "detail": "package.json is not valid JSON"}
        scripts = data.get("scripts") if isinstance(data, dict) else None
        if not isinstance(scripts, dict) or "build" not in scripts:
            return {"name": name, "status": "skip", "detail": "no build script"}
        if not _has_tool("npm"):
            return {"name": name, "status": "skip", "detail": "npm not installed"}
        if not (project_dir / "node_modules").is_dir():
            return {
                "name": name,
                "status": "skip",
                "detail": "node_modules missing — run npm install first",
            }
        rc, out = await _run("npm run build --if-present", project_dir, timeout)
        if rc != 0:
            return {"name": name, "status": "fail", "detail": out.strip()[-1500:]}
        return {"name": name, "status": "pass", "detail": "npm run build succeeded"}

    async def _check_python_compile(self, project_dir: Path, timeout: int) -> dict[str, Any]:
        name = "python_compile"
        py_files = [
            p for p in self._collect(project_dir, "*.py")
            if "venv" not in p.parts and ".venv" not in p.parts and "node_modules" not in p.parts
        ]
        if not py_files:
            return {"name": name, "status": "skip", "detail": "no python files"}
        py = shutil.which("python3") or shutil.which("python")
        if not py:
            return {"name": name, "status": "skip", "detail": "python not installed"}
        rc, out = await _run(
            f"{self._q(Path(py))} -m compileall -q .", project_dir, timeout
        )
        if rc != 0:
            return {"name": name, "status": "fail", "detail": out.strip()[-1500:]}
        return {"name": name, "status": "pass", "detail": f"{len(py_files)} file(s) compile"}

    async def _check_runtime_contract(self, project_dir: Path) -> dict[str, Any]:
        name = "runtime_contract"
        package_data = self._load_package_json(project_dir)
        text_blob = self._project_text_blob(project_dir)
        if not self._needs_runtime_contract(project_dir, package_data, text_blob):
            return {"name": name, "status": "skip", "detail": "no backend/full-stack runtime contract detected"}

        missing: list[str] = []
        findings: list[str] = []

        if not (project_dir / ".env.example").is_file():
            missing.append("missing .env.example")
        else:
            findings.append(".env.example")

        bootstrap = self._bootstrap_contract(project_dir, package_data)
        if bootstrap is None:
            missing.append("missing bootstrap path (scripts/bootstrap.*, Makefile target, package script, or compose file)")
        else:
            findings.append(f"bootstrap via {bootstrap}")

        start = self._start_contract(project_dir, package_data)
        if start is None:
            missing.append("missing dev/start path (scripts/dev.*, package script, Procfile, or compose file)")
        else:
            findings.append(f"start via {start}")

        if self._mentions_any(text_blob, _ADMIN_HINTS):
            seed = self._seed_contract(project_dir, package_data)
            if seed is None:
                missing.append("missing admin seed path (scripts/seed_admin.*, package script, or documented equivalent)")
            else:
                findings.append(f"seed via {seed}")

        if self._mentions_any(text_blob, _SERVICE_HINTS):
            has_compose = any((project_dir / name).is_file() for name in ("docker-compose.yml", "compose.yaml", "compose.yml"))
            has_fallback = self._mentions_any(text_blob, _LOCAL_FALLBACK_HINTS)
            if not has_compose and not has_fallback:
                missing.append("missing local Postgres/Redis strategy (docker compose or SQLite/in-memory fallback)")
            elif has_compose:
                findings.append("compose-backed local services")
            else:
                findings.append("documented SQLite/in-memory fallback")

        if self._mentions_any(text_blob, ("fastapi", "uvicorn")):
            if not self._python_dependency_manifest(project_dir):
                missing.append("missing Python dependency manifest for backend runtime")
            if "uvicorn" not in text_blob and "python -m uvicorn" not in text_blob:
                missing.append("uvicorn runtime/start command not declared")
            else:
                findings.append("uvicorn runtime declared")

        if missing:
            return {"name": name, "status": "fail", "detail": "; ".join(missing)}
        detail = ", ".join(findings) if findings else "local runtime contract detected"
        return {"name": name, "status": "pass", "detail": detail}

    async def _check_expo_config(self, project_dir: Path) -> dict[str, Any]:
        name = "expo_config"
        package_data = self._load_package_json(project_dir)
        if not self._is_expo_project(project_dir, package_data):
            return {"name": name, "status": "skip", "detail": "not an Expo project"}

        deps = {
            *self._package_keys(package_data, "dependencies"),
            *self._package_keys(package_data, "devDependencies"),
        }
        missing: list[str] = []
        findings: list[str] = []

        main_entry = package_data.get("main") if isinstance(package_data, dict) else None
        if main_entry != "expo/AppEntry.js":
            missing.append("package.json main must be expo/AppEntry.js")
        else:
            findings.append("main=expo/AppEntry.js")

        required_deps = ("expo", "react", "react-native")
        absent_runtime = [dep for dep in required_deps if dep not in deps]
        if absent_runtime:
            missing.append(f"missing Expo runtime deps: {', '.join(absent_runtime)}")
        else:
            findings.append("Expo runtime deps installed")

        missing_web_preview = [
            dep for dep in ("react-dom", "react-native-web", "@expo/metro-runtime")
            if dep not in deps
        ]
        if missing_web_preview:
            missing.append(
                "missing Expo web preview deps: " + ", ".join(missing_web_preview)
            )
        else:
            findings.append("Expo web preview deps installed")

        expo_config = self._load_expo_json_config(project_dir)
        if expo_config is None:
            findings.append("no JSON Expo config found (app config may be JS/TS)")
        else:
            broken_assets = self._find_missing_expo_assets(project_dir, expo_config)
            if broken_assets:
                missing.append("missing Expo assets: " + ", ".join(broken_assets))
            else:
                findings.append("Expo asset references resolve")

        graphics_deps = sorted(deps & {"expo-gl", "expo-three", "three", "@shopify/react-native-skia"})
        if graphics_deps:
            findings.append(
                "graphics-heavy Expo deps detected: "
                + ", ".join(graphics_deps)
                + " (require runtime render verification before delivery)"
            )

        if missing:
            return {"name": name, "status": "fail", "detail": "; ".join(missing)}
        return {"name": name, "status": "pass", "detail": ", ".join(findings)}

    async def _check_preview_evidence(self, project_dir: Path) -> dict[str, Any]:
        name = "preview_evidence"
        state = load_state(project_dir)
        platform = str(state.get("platform") or "unknown").strip().lower()
        artifacts = state.get("artifacts")
        artifacts = artifacts if isinstance(artifacts, dict) else {}

        if platform == "mobile":
            native_ref = artifacts.get("expo_native_preview") or artifacts.get("mobile_preview")
            web_ref = artifacts.get("expo_web_preview") or artifacts.get("web_preview")
            missing: list[str] = []
            findings: list[str] = []
            if isinstance(native_ref, str) and native_ref.startswith(("exp://", "exp+")):
                findings.append("native Expo preview recorded")
            else:
                missing.append("missing expo_native_preview")
            if isinstance(web_ref, str) and web_ref.startswith(("http://", "https://")):
                findings.append("Expo web mirror recorded")
            else:
                missing.append("missing expo_web_preview")
            if missing:
                return {
                    "name": name,
                    "status": "fail",
                    "detail": "; ".join(missing),
                }
            return {"name": name, "status": "pass", "detail": ", ".join(findings)}

        if platform in {"web", "desktop", "backend", "solution", "extension", "bot"}:
            web_ref = artifacts.get("web_preview")
            if isinstance(web_ref, str) and web_ref.startswith(("http://", "https://")):
                return {"name": name, "status": "pass", "detail": "web preview recorded"}
            return {"name": name, "status": "fail", "detail": "missing web_preview"}

        return {"name": name, "status": "skip", "detail": "preview evidence check not required for this platform"}

    async def _check_preview_runtime(self, project_dir: Path, timeout: int) -> dict[str, Any]:
        name = "preview_runtime"
        state = load_state(project_dir)
        platform = str(state.get("platform") or "unknown").strip().lower()
        artifacts = state.get("artifacts")
        artifacts = artifacts if isinstance(artifacts, dict) else {}

        preview_url: str | None = None
        if platform == "mobile":
            candidate = artifacts.get("expo_web_preview") or artifacts.get("web_preview")
            if isinstance(candidate, str):
                preview_url = candidate
        elif platform in {"web", "desktop", "backend", "solution", "extension", "bot"}:
            candidate = artifacts.get("web_preview")
            if isinstance(candidate, str):
                preview_url = candidate
        else:
            return {"name": name, "status": "skip", "detail": "preview runtime check not required for this platform"}

        if not preview_url:
            return {"name": name, "status": "skip", "detail": "no local preview URL recorded"}

        parsed = urlparse(preview_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"}:
            return {"name": name, "status": "skip", "detail": "preview URL is not an HTTP(S) endpoint"}
        if host not in {"127.0.0.1", "localhost"}:
            return {"name": name, "status": "skip", "detail": "preview runtime only probes localhost URLs"}

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=float(timeout)) as client:
                response = await client.get(preview_url)
        except httpx.HTTPError as exc:
            return {"name": name, "status": "fail", "detail": f"preview request failed: {exc}"}

        content_type = response.headers.get("content-type", "").lower()
        body = response.text[:4000]
        if response.status_code >= 400:
            return {"name": name, "status": "fail", "detail": f"preview returned HTTP {response.status_code}"}
        if "text/html" not in content_type:
            return {
                "name": name,
                "status": "fail",
                "detail": f"preview returned unexpected content-type '{content_type or 'unknown'}'",
            }
        if "<html" not in body.lower():
            return {"name": name, "status": "fail", "detail": "preview did not return an HTML document"}
        return {"name": name, "status": "pass", "detail": f"preview responded with HTML from {preview_url}"}

    def _scan_smells(self, project_dir: Path) -> list[str]:
        warnings: list[str] = []
        exts = {".html", ".js", ".jsx", ".ts", ".tsx", ".css", ".py", ".md", ".json"}
        seen: set[str] = set()
        scanned = 0
        for path in project_dir.rglob("*"):
            if scanned >= 300:
                break
            if not path.is_file() or path.suffix.lower() not in exts:
                continue
            if any(part in {"node_modules", "dist", "build", ".git", ".teai_builder"} for part in path.parts):
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern, label in _SMELL_PATTERNS:
                if label in seen:
                    continue
                if re.search(pattern, text, re.IGNORECASE):
                    seen.add(label)
                    warnings.append(f"{label} (e.g. {path.name})")
        return warnings

    @staticmethod
    def _load_package_json(project_dir: Path) -> dict[str, Any] | None:
        pkg = project_dir / "package.json"
        if not pkg.is_file():
            return None
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _project_text_blob(self, project_dir: Path) -> str:
        parts: list[str] = []
        for path in project_dir.rglob("*"):
            if len(parts) >= 80:
                break
            if not path.is_file():
                continue
            if any(part in {"node_modules", "dist", "build", ".git", ".teai_builder", ".venv", "venv"} for part in path.parts):
                continue
            if path.suffix.lower() not in _RUNTIME_TEXT_EXTS and path.name not in {
                "Dockerfile",
                "Procfile",
                ".env.example",
                "docker-compose.yml",
                "compose.yaml",
                "compose.yml",
                "Makefile",
            }:
                continue
            try:
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
        return "\n".join(parts).lower()

    @staticmethod
    def _mentions_any(text: str, needles: tuple[str, ...]) -> bool:
        return any(needle in text for needle in needles)

    def _needs_runtime_contract(
        self,
        project_dir: Path,
        package_data: dict[str, Any] | None,
        text_blob: str,
    ) -> bool:
        if self._mentions_any(text_blob, _BACKEND_RUNTIME_HINTS):
            return True
        if any((project_dir / name).is_file() for name in ("docker-compose.yml", "compose.yaml", "compose.yml", "Dockerfile", "pyproject.toml", "requirements.txt")):
            return True
        scripts = package_data.get("scripts") if isinstance(package_data, dict) else None
        if isinstance(scripts, dict) and any(key in scripts for key in ("start", "dev", "bootstrap", "seed", "seed:admin")):
            deps = {
                *self._package_keys(package_data, "dependencies"),
                *self._package_keys(package_data, "devDependencies"),
            }
            return bool(deps & {"express", "fastify", "hono", "next", "@nestjs/core"})
        return False

    @staticmethod
    def _package_keys(package_data: dict[str, Any] | None, key: str) -> set[str]:
        if not isinstance(package_data, dict):
            return set()
        value = package_data.get(key)
        return set(value.keys()) if isinstance(value, dict) else set()

    @staticmethod
    def _bootstrap_contract(project_dir: Path, package_data: dict[str, Any] | None) -> str | None:
        for candidate in ("scripts/bootstrap.sh", "scripts/bootstrap.py", "scripts/bootstrap.js"):
            if (project_dir / candidate).is_file() and not RunVerificationTool._file_has_placeholder(project_dir / candidate):
                return candidate
        if any((project_dir / name).is_file() for name in ("docker-compose.yml", "compose.yaml", "compose.yml")):
            return "docker compose"
        scripts = package_data.get("scripts") if isinstance(package_data, dict) else None
        if isinstance(scripts, dict):
            for key in ("bootstrap", "setup", "install"):
                if isinstance(scripts.get(key), str) and scripts.get(key):
                    return f"package.json#{key}"
        makefile = project_dir / "Makefile"
        if makefile.is_file():
            text = makefile.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"^bootstrap:\s*$", text, re.MULTILINE) or re.search(r"^install:\s*$", text, re.MULTILINE):
                return "Makefile"
        if (project_dir / "pyproject.toml").is_file() or list(project_dir.glob("requirements*.txt")):
            return "Python dependency manifest"
        return None

    @staticmethod
    def _start_contract(project_dir: Path, package_data: dict[str, Any] | None) -> str | None:
        for candidate in ("scripts/dev.sh", "scripts/start.sh", "scripts/dev.py", "scripts/start.py"):
            if (project_dir / candidate).is_file() and not RunVerificationTool._file_has_placeholder(project_dir / candidate):
                return candidate
        if any((project_dir / name).is_file() for name in ("docker-compose.yml", "compose.yaml", "compose.yml")):
            return "docker compose"
        scripts = package_data.get("scripts") if isinstance(package_data, dict) else None
        if isinstance(scripts, dict):
            for key in ("dev", "start"):
                if isinstance(scripts.get(key), str) and scripts.get(key):
                    return f"package.json#{key}"
        if (project_dir / "Procfile").is_file():
            return "Procfile"
        return None

    @staticmethod
    def _seed_contract(project_dir: Path, package_data: dict[str, Any] | None) -> str | None:
        for candidate in ("scripts/seed_admin.sh", "scripts/seed.py", "scripts/seed_admin.py", "scripts/seed.js"):
            if (project_dir / candidate).is_file() and not RunVerificationTool._file_has_placeholder(project_dir / candidate):
                return candidate
        scripts = package_data.get("scripts") if isinstance(package_data, dict) else None
        if isinstance(scripts, dict):
            for key in ("seed", "seed:admin", "seed-admin", "db:seed"):
                if isinstance(scripts.get(key), str) and scripts.get(key):
                    return f"package.json#{key}"
        return None

    @staticmethod
    def _python_dependency_manifest(project_dir: Path) -> bool:
        return (project_dir / "pyproject.toml").is_file() or any(project_dir.glob("requirements*.txt"))

    @staticmethod
    def _file_has_placeholder(path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            return False
        return any(marker in text for marker in _PLACEHOLDER_RUNTIME_HINTS)

    @staticmethod
    def _is_expo_project(project_dir: Path, package_data: dict[str, Any] | None) -> bool:
        if not isinstance(package_data, dict):
            return (project_dir / "app.json").is_file() or (project_dir / "app.config.json").is_file()
        deps = {
            *RunVerificationTool._package_keys(package_data, "dependencies"),
            *RunVerificationTool._package_keys(package_data, "devDependencies"),
        }
        return "expo" in deps or package_data.get("main") == "expo/AppEntry.js"

    @staticmethod
    def _load_expo_json_config(project_dir: Path) -> dict[str, Any] | None:
        for name in ("app.json", "app.config.json"):
            path = project_dir / name
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(data, dict):
                return None
            expo = data.get("expo")
            if isinstance(expo, dict):
                return expo
            return data
        return None

    @staticmethod
    def _find_missing_expo_assets(project_dir: Path, expo_config: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for path_bits in (
            ("icon",),
            ("notification", "icon"),
            ("ios", "icon"),
            ("splash", "image"),
            ("android", "adaptiveIcon", "foregroundImage"),
            ("android", "adaptiveIcon", "backgroundImage"),
            ("web", "favicon"),
        ):
            value = RunVerificationTool._nested_string(expo_config, path_bits)
            if not value or not RunVerificationTool._looks_like_asset_path(value):
                continue
            resolved = (project_dir / value).resolve()
            if not resolved.exists():
                missing.append(".".join(path_bits) + f" -> {value}")
        return missing

    @staticmethod
    def _nested_string(data: dict[str, Any], path_bits: tuple[str, ...]) -> str | None:
        current: Any = data
        for bit in path_bits:
            if not isinstance(current, dict):
                return None
            current = current.get(bit)
        return current if isinstance(current, str) else None

    @staticmethod
    def _looks_like_asset_path(value: str) -> bool:
        lowered = value.lower().strip()
        if not lowered or lowered.startswith(("http://", "https://", "data:")):
            return False
        return lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"))

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _collect(project_dir: Path, pattern: str) -> list[Path]:
        out: list[Path] = []
        for p in project_dir.rglob(pattern):
            if any(part in {"node_modules", "dist", "build", ".git", ".teai_builder"} for part in p.parts):
                continue
            if p.is_file():
                out.append(p)
            if len(out) >= _MAX_FILES_PER_CHECK * 2:
                break
        return out

    @staticmethod
    def _extract_inline_js(html_file: Path) -> str:
        try:
            html = html_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        return "\n;\n".join(m.group(1) for m in _SCRIPT_BLOCK_RE.finditer(html))

    async def _node_check_source(self, code: str, timeout: int) -> tuple[int, str]:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(code)
            tmp = Path(fh.name)
        try:
            return await _run(f"node --check {self._q(tmp)}", tmp.parent, timeout)
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _q(path: Path) -> str:
        return "'" + str(path).replace("'", "'\\''") + "'"
