from __future__ import annotations

from pathlib import Path

from teai_builder.security.workspace_access import WorkspaceSandboxStatus, WorkspaceScope
from teai_builder.webui.workspace_search import (
    workspace_content_search_payload,
    workspace_problems_payload,
    workspace_reference_search_payload,
    workspace_search_payload,
    workspace_symbol_search_payload,
)
from teai_builder.webui.file_preview import file_symbol_payload


def _scope(root: Path) -> WorkspaceScope:
    return WorkspaceScope(
        project_path=root,
        access_mode="restricted",
        restrict_to_workspace=True,
        sandbox_status=WorkspaceSandboxStatus(
            restrict_to_workspace=True,
            workspace_root=str(root),
            level="application",
            enforced=True,
            provider="none",
            provider_label="None",
            exec_backend="",
            exec_backend_available=False,
            exec_backend_required=False,
            summary="Workspace scoped",
        ),
    )


def test_workspace_search_prioritizes_filename_matches(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export default function App() {}", encoding="utf-8")
    (tmp_path / "docs" / "app-architecture.md").write_text("# app", encoding="utf-8")

    payload = workspace_search_payload(scope=_scope(tmp_path), query="app", limit=10)

    assert payload["items"]
    assert payload["items"][0]["display_path"] == "src/App.tsx"
    assert any(item["display_path"] == "docs/app-architecture.md" for item in payload["items"])


def test_workspace_search_hides_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "ignored.ts").write_text("ignored", encoding="utf-8")
    (tmp_path / "src" / "main.ts").write_text("main", encoding="utf-8")

    payload = workspace_search_payload(scope=_scope(tmp_path), query="ignored", limit=10)

    assert payload["items"] == []


def test_workspace_search_returns_default_ranked_files_without_query(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("main", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme", encoding="utf-8")

    payload = workspace_search_payload(scope=_scope(tmp_path), query="", limit=10)

    assert [item["display_path"] for item in payload["items"][:2]] == ["README.md", "src/main.ts"]


def test_workspace_content_search_returns_ranked_line_matches(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text(
        "\n".join(
            [
                "export function App() {",
                "  const label = 'video editor';",
                "  return <main>video editor</main>;",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text("video editor roadmap", encoding="utf-8")

    payload = workspace_content_search_payload(scope=_scope(tmp_path), query="video editor", limit=10)

    assert payload["items"]
    assert payload["items"][0]["display_path"] == "src/App.tsx"
    assert payload["items"][0]["path"].startswith(str(tmp_path / "src" / "App.tsx"))
    assert "video editor" in payload["items"][0]["preview"].lower()
    assert any(item["path"].endswith("App.tsx:2") for item in payload["items"])


def test_workspace_content_search_hides_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "ignored.ts").write_text("secret needle", encoding="utf-8")
    (tmp_path / "src" / "main.ts").write_text("const needle = true", encoding="utf-8")

    payload = workspace_content_search_payload(scope=_scope(tmp_path), query="secret needle", limit=10)

    assert payload["items"] == []


def test_workspace_symbol_search_extracts_python_symbols(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "\n".join(
            [
                "class VideoEditor:",
                "    def render(self):",
                "        return True",
                "",
                "def build_timeline():",
                "    return []",
            ]
        ),
        encoding="utf-8",
    )

    payload = workspace_symbol_search_payload(scope=_scope(tmp_path), query="render", limit=10)

    assert payload["items"]
    assert payload["items"][0]["name"] == "render"
    assert payload["items"][0]["kind"] == "method"
    assert payload["items"][0]["container_name"] == "VideoEditor"
    assert payload["items"][0]["path"].endswith("app.py:2:5")


def test_workspace_symbol_search_extracts_typescript_symbols(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "editor.ts").write_text(
        "\n".join(
            [
                "export class TimelineEditor {",
                "  renderPreview() {",
                "    return true;",
                "  }",
                "}",
                "",
                "export const buildScene = async () => true;",
            ]
        ),
        encoding="utf-8",
    )

    payload = workspace_symbol_search_payload(scope=_scope(tmp_path), query="timeline", limit=10)

    assert payload["items"]
    assert payload["items"][0]["name"] == "TimelineEditor"
    assert payload["items"][0]["kind"] == "class"
    assert any(item["name"] == "renderPreview" and item["kind"] == "method" for item in payload["items"])


def test_file_symbol_payload_returns_file_scoped_symbols(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "editor.ts"
    source.write_text(
        "\n".join(
            [
                "export class TimelineEditor {",
                "  renderPreview() {",
                "    return true;",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    payload = file_symbol_payload(str(source), scope=_scope(tmp_path))

    assert payload["display_path"] == "src/editor.ts"
    assert [item["name"] for item in payload["items"]] == ["TimelineEditor", "renderPreview"]
    assert payload["items"][1]["container_name"] == "TimelineEditor"


def test_workspace_reference_search_returns_symbol_usages(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "editor.py").write_text(
        "\n".join(
            [
                "class VideoEditor:",
                "    def render_preview(self):",
                "        return True",
                "",
                "def run_render(editor: VideoEditor):",
                "    return editor.render_preview()",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "src" / "workflow.py").write_text(
        "\n".join(
            [
                "from editor import VideoEditor",
                "editor = VideoEditor()",
                "editor.render_preview()",
            ]
        ),
        encoding="utf-8",
    )

    payload = workspace_reference_search_payload(scope=_scope(tmp_path), query="render_preview", limit=10)

    assert payload["items"]
    assert payload["items"][0]["name"] == "render_preview"
    assert payload["items"][0]["path"].endswith(":6:19") or payload["items"][0]["path"].endswith(":3:8")
    assert any(item["definition_display_path"] == "src/editor.py" for item in payload["items"])
    assert all(not item["path"].endswith("editor.py:2:5") for item in payload["items"])


def test_workspace_problems_reports_python_syntax_errors(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "broken.py").write_text(
        "\n".join(
            [
                "def broken(",
                "    return 1",
            ]
        ),
        encoding="utf-8",
    )

    payload = workspace_problems_payload(scope=_scope(tmp_path), query="", limit=10)

    assert payload["items"]
    assert payload["items"][0]["severity"] == "error"
    assert payload["items"][0]["source"] == "python"
    assert payload["items"][0]["display_path"] == "src/broken.py"


def test_workspace_problems_reports_merge_conflict_markers(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "merge.ts").write_text(
        "\n".join(
            [
                "export const value = true;",
                "<<<<<<< HEAD",
                "export const value = false;",
                "=======",
                "export const value = maybe;",
                ">>>>>>> branch",
            ]
        ),
        encoding="utf-8",
    )

    payload = workspace_problems_payload(scope=_scope(tmp_path), query="merge", limit=10)

    assert payload["items"]
    assert payload["items"][0]["source"] == "merge"
    assert payload["items"][0]["message"] == "Merge conflict marker detected."
