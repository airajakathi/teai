import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceQuickOpenDialog } from "@/components/WorkspaceQuickOpenDialog";

describe("WorkspaceQuickOpenDialog", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("workspace-problems")) {
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              query: "syntax",
              workspace_root: "/workspace",
              truncated: false,
              scanned_files: 2,
              items: [
                {
                  path: "/workspace/src/broken.py:3:10",
                  display_path: "src/broken.py",
                  name: "broken.py",
                  message: "invalid syntax",
                  severity: "error",
                  source: "python",
                  line: 3,
                  column: 10,
                  preview: "return value(",
                  score: 260,
                },
              ],
            }),
          };
        }
        if (url.includes("workspace-reference-search")) {
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              query: "render",
              workspace_root: "/workspace",
              truncated: false,
              scanned_files: 2,
              items: [
                {
                  path: "/workspace/src/editor.py:22:9",
                  display_path: "src/editor.py",
                  name: "render_preview",
                  kind: "method",
                  container_name: "VideoEditor",
                  line: 22,
                  column: 9,
                  preview: "return editor.render_preview()",
                  definition_path: "/workspace/src/editor.py:14:5",
                  definition_display_path: "src/editor.py",
                  score: 230,
                },
              ],
            }),
          };
        }
        if (url.includes("workspace-symbol-search")) {
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              query: "render",
              workspace_root: "/workspace",
              truncated: false,
              scanned_files: 2,
              items: [
                {
                  path: "/workspace/src/editor.py:14:5",
                  display_path: "src/editor.py",
                  name: "render_preview",
                  kind: "method",
                  container_name: "VideoEditor",
                  line: 14,
                  column: 5,
                  score: 250,
                },
              ],
            }),
          };
        }
        if (url.includes("workspace-content-search")) {
          return {
            ok: true,
            headers: { get: () => "application/json" },
            json: async () => ({
              query: "video",
              workspace_root: "/workspace",
              truncated: false,
              scanned_files: 2,
              items: [
                {
                  path: "/workspace/src/App.tsx:12",
                  display_path: "src/App.tsx",
                  name: "App.tsx",
                  line: 12,
                  column: 9,
                  preview: "const label = 'video editor';",
                  score: 240,
                },
              ],
            }),
          };
        }
        return {
          ok: true,
          headers: { get: () => "application/json" },
          json: async () => ({
            query: "",
            workspace_root: "/workspace",
            truncated: false,
            scanned_files: 2,
            items: [
              {
                path: "/workspace/src/App.tsx",
                display_path: "src/App.tsx",
                name: "App.tsx",
                score: 220,
              },
              {
                path: "/workspace/src/main.ts",
                display_path: "src/main.ts",
                name: "main.ts",
                score: 180,
              },
            ],
          }),
        };
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("loads quick-open results and opens the highlighted file", async () => {
    const onOpenChange = vi.fn();
    const onSelect = vi.fn();

    render(
      <WorkspaceQuickOpenDialog
        open
        token="tok"
        sessionKey="websocket:chat-1"
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />,
    );

    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/workspace-search?q=&limit=40",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
        credentials: "same-origin",
      }),
    );

    expect(await screen.findByText("App.tsx")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Quick open files" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelect).toHaveBeenCalledWith("/workspace/src/main.ts");
  });

  it("switches to content mode and opens the matched line target", async () => {
    const onOpenChange = vi.fn();
    const onSelect = vi.fn();

    render(
      <WorkspaceQuickOpenDialog
        open
        token="tok"
        sessionKey="websocket:chat-1"
        initialMode="content"
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search workspace contents" });
    fireEvent.change(input, { target: { value: "video" } });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workspace-content-search?q=video&limit=40",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
          credentials: "same-origin",
        }),
      );
    });

    expect(await screen.findByText("const label = 'video editor';")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelect).toHaveBeenCalledWith("/workspace/src/App.tsx:12");
  });

  it("loads symbol mode results and opens the selected symbol target", async () => {
    const onOpenChange = vi.fn();
    const onSelect = vi.fn();

    render(
      <WorkspaceQuickOpenDialog
        open
        token="tok"
        sessionKey="websocket:chat-1"
        initialMode="symbols"
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search workspace symbols" });
    fireEvent.change(input, { target: { value: "render" } });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workspace-symbol-search?q=render&limit=40",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
          credentials: "same-origin",
        }),
      );
    });

    expect(await screen.findByText("render_preview")).toBeInTheDocument();
    expect(screen.getByText("VideoEditor • method")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelect).toHaveBeenCalledWith("/workspace/src/editor.py:14:5");
  });

  it("loads reference mode results and opens the selected reference target", async () => {
    const onOpenChange = vi.fn();
    const onSelect = vi.fn();

    render(
      <WorkspaceQuickOpenDialog
        open
        token="tok"
        sessionKey="websocket:chat-1"
        initialMode="references"
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search symbol references" });
    fireEvent.change(input, { target: { value: "render" } });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workspace-reference-search?q=render&limit=40",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
          credentials: "same-origin",
        }),
      );
    });

    expect(await screen.findByText("return editor.render_preview()")).toBeInTheDocument();
    expect(screen.getByText("VideoEditor • method")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelect).toHaveBeenCalledWith("/workspace/src/editor.py:22:9");
  });

  it("loads problems mode results and opens the selected diagnostic target", async () => {
    const onOpenChange = vi.fn();
    const onSelect = vi.fn();

    render(
      <WorkspaceQuickOpenDialog
        open
        token="tok"
        sessionKey="websocket:chat-1"
        initialMode="problems"
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search workspace problems" });
    fireEvent.change(input, { target: { value: "syntax" } });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workspace-problems?q=syntax&limit=40",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
          credentials: "same-origin",
        }),
      );
    });

    expect(await screen.findByText("invalid syntax")).toBeInTheDocument();
    expect(screen.getByText("python • error")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelect).toHaveBeenCalledWith("/workspace/src/broken.py:3:10");
  });

  it("merges runtime problems into problems mode results", async () => {
    const onOpenChange = vi.fn();
    const onSelect = vi.fn();

    render(
      <WorkspaceQuickOpenDialog
        open
        token="tok"
        sessionKey="websocket:chat-1"
        initialMode="problems"
        runtimeProblems={[{
          path: "/workspace/tests/test_editor.py:42:1",
          display_path: "tests/test_editor.py",
          name: "test_editor.py",
          message: "pytest failed: AssertionError",
          severity: "error",
          source: "runtime-pytest",
          line: 42,
          column: 1,
          preview: "AssertionError",
          score: 320,
        }]}
        onOpenChange={onOpenChange}
        onSelect={onSelect}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Search workspace problems" });
    fireEvent.change(input, { target: { value: "pytest" } });

    expect(await screen.findByText("pytest failed: AssertionError")).toBeInTheDocument();
    expect(screen.getByText("runtime-pytest • error")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Enter" });

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSelect).toHaveBeenCalledWith("/workspace/tests/test_editor.py:42:1");
  });
});
