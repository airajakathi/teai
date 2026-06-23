import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/FilePreviewPanel";

vi.mock("@/components/editor/MonacoEditor", () => ({
  MonacoEditor: ({
    value,
    onChange,
    readOnly,
    onActiveWordChange,
    onCursorPositionChange,
  }: {
    value?: string;
    onChange?: (value: string) => void;
    readOnly?: boolean;
    onActiveWordChange?: (value: string | null) => void;
    onCursorPositionChange?: (value: { line: number; column: number } | null) => void;
  }) => (
    <div>
      <button type="button" data-testid="mock-monaco-symbol" onClick={() => onActiveWordChange?.("one")}>
        Use symbol
      </button>
      <button
        type="button"
        data-testid="mock-monaco-cursor"
        onClick={() => onCursorPositionChange?.({ line: 2, column: 3 })}
      >
        Move cursor
      </button>
      <textarea
        data-testid="mock-monaco"
        value={value}
        readOnly={readOnly}
        onChange={(event) => onChange?.(event.target.value)}
      />
    </div>
  ),
}));

describe("FilePreviewPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("loads a workspace tree and navigates back and forward between file previews", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [
                {
                  path: "/workspace/src",
                  display_path: "src",
                  name: "src",
                  kind: "directory",
                  children: [
                    {
                      path: "/workspace/src/one.ts",
                      display_path: "src/one.ts",
                      name: "one.ts",
                      kind: "file",
                    },
                    {
                      path: "/workspace/src/two.ts",
                      display_path: "src/two.ts",
                      name: "two.ts",
                      kind: "file",
                    },
                  ],
                },
              ],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("one.ts")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/one.ts",
            display_path: "src/one.ts",
            project_path: "/workspace",
            language: "typescript",
            content: "export const one = 1;",
            size: 22,
            revision: "rev-one",
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("two.ts")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/two.ts",
            display_path: "src/two.ts",
            project_path: "/workspace",
            language: "typescript",
            content: "export const two = 2;",
            size: 22,
            revision: "rev-two",
            truncated: false,
          }),
        } as Response;
      }
      throw new Error(`Unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+one\s+=\s+1;/);
    });
    expect(screen.queryByTestId("mock-monaco")).not.toBeInTheDocument();
    expect(await screen.findByText("Workspace files")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "two.ts" }));

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+two\s+=\s+2;/);
    });
    expect(screen.queryByTestId("mock-monaco")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go back" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Go forward" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Go back" }));

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+one\s+=\s+1;/);
    });
    expect(screen.getByRole("button", { name: "Go forward" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Go forward" }));

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+two\s+=\s+2;/);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/workspace-tree",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("edits and saves a file through the live client", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-1",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const saveFile = vi.fn(async () => ({
      path: "/workspace/src/one.ts",
      display_path: "src/one.ts",
      project_path: "/workspace",
      language: "typescript",
      content: "export const one = 2;",
      size: 22,
      revision: "rev-2",
      truncated: false,
    }));

    render(
      <FilePreviewPanel
        client={{ saveFile }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(screen.getByTestId("mock-monaco"));
    await user.type(screen.getByTestId("mock-monaco"), "export const one = 2;");
    await user.click(screen.getByRole("button", { name: "Review & save" }));

    expect(saveFile).not.toHaveBeenCalled();
    expect(await screen.findByText("Saved vs draft")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Save after review" })[0]!);

    await waitFor(() => {
      expect(saveFile).toHaveBeenCalledWith("chat-1", "/workspace/src/one.ts", "export const one = 2;", {
        baseRevision: "rev-1",
      });
    });
    expect(await screen.findByText("File saved.")).toBeInTheDocument();
    expect(screen.queryByTestId("mock-monaco")).not.toBeInTheDocument();
    expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+one\s+=\s+2;/);
  });

  it("opens a definition search from the active editor symbol", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-definition",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const onGoToDefinition = vi.fn();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onGoToDefinition={onGoToDefinition}
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.click(screen.getByTestId("mock-monaco-symbol"));
    await user.click(screen.getByRole("button", { name: "Go to definition" }));

    expect(onGoToDefinition).toHaveBeenCalledWith({
      symbol: "one",
      sourcePath: "/workspace/src/one.ts",
    });
  });

  it("opens a reference search from the active editor symbol", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-refs",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const onFindReferences = vi.fn();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onFindReferences={onFindReferences}
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.click(screen.getByTestId("mock-monaco-symbol"));
    await user.click(screen.getByRole("button", { name: "Find references" }));

    expect(onFindReferences).toHaveBeenCalledWith({
      symbol: "one",
      sourcePath: "/workspace/src/one.ts",
    });
  });

  it("shows an inline definition peek and jumps from the result", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("/workspace-symbol-search")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            query: "one",
            workspace_root: "/workspace",
            scanned_files: 1,
            truncated: false,
            items: [{
              path: "/workspace/src/lib.ts:7:3",
              display_path: "src/lib.ts",
              name: "one",
              kind: "function",
              container_name: "helpers",
              line: 7,
              column: 3,
              score: 200,
            }],
          }),
        } as Response;
      }
      if (url.includes("lib.ts")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/lib.ts",
            display_path: "src/lib.ts",
            project_path: "/workspace",
            language: "typescript",
            content: "export function one() { return 1; }",
            size: 35,
            revision: "rev-lib",
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-peek-definition",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.click(screen.getByTestId("mock-monaco-symbol"));
    await user.click(screen.getByRole("button", { name: "Peek definition" }));

    expect(await screen.findByTestId("file-preview-peek")).toHaveTextContent("Definition peek");
    expect(screen.getByTestId("file-preview-peek")).toHaveTextContent("src/lib.ts:7:3");

    await user.click(screen.getByText("src/lib.ts:7:3").closest("button")!);

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export function one\(\)/);
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/Opened from search result at line 7/);
    });
  });

  it("shows an inline reference peek with matching preview text", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("/workspace-reference-search")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            query: "one",
            workspace_root: "/workspace",
            scanned_files: 1,
            truncated: false,
            items: [{
              path: "/workspace/src/consumer.ts:12:9",
              display_path: "src/consumer.ts",
              name: "one",
              kind: "function",
              container_name: "render",
              line: 12,
              column: 9,
              preview: "return one();",
              definition_path: "/workspace/src/lib.ts:7:3",
              definition_display_path: "src/lib.ts",
              score: 180,
            }],
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-peek-refs",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.click(screen.getByTestId("mock-monaco-symbol"));
    await user.click(screen.getByRole("button", { name: "Peek references" }));

    expect(await screen.findByTestId("file-preview-peek")).toHaveTextContent("References peek");
    expect(screen.getByTestId("file-preview-peek")).toHaveTextContent("src/consumer.ts:12:9");
    expect(screen.getByTestId("file-preview-peek")).toHaveTextContent("return one();");
  });

  it("shows the current symbol context for the editor cursor", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("/file-symbols")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/editor.ts",
            display_path: "src/editor.ts",
            project_path: "/workspace",
            items: [
              {
                path: "/workspace/src/editor.ts:1:14",
                display_path: "src/editor.ts",
                name: "TimelineEditor",
                kind: "class",
                line: 1,
                column: 14,
              },
              {
                path: "/workspace/src/editor.ts:2:3",
                display_path: "src/editor.ts",
                name: "renderPreview",
                kind: "method",
                container_name: "TimelineEditor",
                line: 2,
                column: 3,
              },
            ],
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/editor.ts",
          display_path: "src/editor.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export class TimelineEditor {\n  renderPreview() { return true; }\n}",
          size: 65,
          revision: "rev-context",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/editor.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    expect(await screen.findByTestId("file-preview-symbol-context")).toHaveTextContent("Move the cursor into a symbol");

    await user.click(screen.getByTestId("mock-monaco-cursor"));

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-symbol-context")).toHaveTextContent("TimelineEditor");
      expect(screen.getByTestId("file-preview-symbol-context")).toHaveTextContent("renderPreview");
      expect(screen.getByTestId("file-preview-symbol-context")).toHaveTextContent("2:3");
    });
  });

  it("shows a file outline and jumps to a selected symbol", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("/file-symbols")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/editor.ts",
            display_path: "src/editor.ts",
            project_path: "/workspace",
            items: [
              {
                path: "/workspace/src/editor.ts:1:14",
                display_path: "src/editor.ts",
                name: "TimelineEditor",
                kind: "class",
                line: 1,
                column: 14,
              },
              {
                path: "/workspace/src/editor.ts:2:3",
                display_path: "src/editor.ts",
                name: "renderPreview",
                kind: "method",
                container_name: "TimelineEditor",
                line: 2,
                column: 3,
              },
            ],
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/editor.ts",
          display_path: "src/editor.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export class TimelineEditor {\n  renderPreview() { return true; }\n}",
          size: 65,
          revision: "rev-outline",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/editor.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    const outline = await screen.findByTestId("file-preview-outline");
    expect(outline).toHaveTextContent("TimelineEditor");
    expect(outline).toHaveTextContent("renderPreview");

    await user.click(screen.getByRole("button", { name: /timelineeditor renderpreview 2:3/i }));

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/Opened from search result at line 2, column 3/);
    });
  });

  it("tracks external jump targets and navigates back and forward with keyboard history", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("/file-preview?") && url.includes("consumer.ts")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/consumer.ts",
            display_path: "src/consumer.ts",
            project_path: "/workspace",
            language: "typescript",
            content: "export function run() { return renderPreview(); }",
            size: 49,
            revision: "rev-consumer",
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/editor.ts",
          display_path: "src/editor.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export function renderPreview() { return true; }",
          size: 48,
          revision: "rev-editor",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="/workspace/src/editor.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export function renderPreview\(\)/);
    });

    rerender(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="/workspace/src/consumer.ts:5:12"
        token="tok"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export function run\(\)/);
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/Opened from search result at line 5/);
    });

    fireEvent.keyDown(window, { key: "ArrowLeft", altKey: true });

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export function renderPreview\(\)/);
    });

    fireEvent.keyDown(window, { key: "ArrowRight", altKey: true });

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export function run\(\)/);
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/Opened from search result at line 5/);
    });
  });

  it("reloads the latest file from disk", async () => {
    let previewCount = 0;
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      previewCount += 1;
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: previewCount === 1 ? "export const one = 1;" : "export const one = 2;",
          size: 22,
          revision: previewCount === 1 ? "rev-a" : "rev-b",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+one\s+=\s+1;/);
    });
    expect(screen.queryByTestId("mock-monaco")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reload" }));

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+one\s+=\s+2;/);
    });
    expect(screen.queryByTestId("mock-monaco")).not.toBeInTheDocument();
    expect(await screen.findByText("Reloaded latest file from disk.")).toBeInTheDocument();
  });

  it("shows a review pane for dirty edits", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-review",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(screen.getByTestId("mock-monaco"));
    await user.type(screen.getByTestId("mock-monaco"), "export const one = 4;");
    await user.click(screen.getByRole("button", { name: "Review changes" }));

    expect(await screen.findByText("Saved vs draft")).toBeInTheDocument();
    expect(screen.getByText("Line diff")).toBeInTheDocument();
    expect(screen.getByTestId("file-preview-diff-hunk")).toBeInTheDocument();
    expect(screen.getByText("Saved file")).toBeInTheDocument();
    expect(screen.getByText("Current draft")).toBeInTheDocument();
    expect(screen.getByTestId("activity-diff-pair")).toBeInTheDocument();
  });

  it("loads Monaco only after entering edit mode", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-start",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-panel")).toHaveTextContent(/export\s+const\s+one\s+=\s+1;/);
    });
    expect(screen.queryByTestId("mock-monaco")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit" }));

    expect(await screen.findByTestId("mock-monaco")).toHaveValue("export const one = 1;");
  });

  it("surfaces save conflicts and fetches the latest disk version", async () => {
    let previewCount = 0;
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [],
            },
            truncated: false,
          }),
        } as Response;
      }
      previewCount += 1;
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: previewCount === 1 ? "export const one = 1;" : "export const one = 9;",
          size: 22,
          revision: previewCount === 1 ? "rev-open" : "rev-disk",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const saveFile = vi.fn(async () => {
      throw new Error("file changed on disk");
    });

    render(
      <FilePreviewPanel
        client={{ saveFile }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(screen.getByTestId("mock-monaco"));
    await user.type(screen.getByTestId("mock-monaco"), "export const one = 2;");
    await user.click(screen.getByRole("button", { name: "Review & save" }));
    await user.click(screen.getAllByRole("button", { name: "Save after review" })[0]!);

    expect(await screen.findByText("File changed on disk. Review or reload the latest version before saving.")).toBeInTheDocument();
    expect(await screen.findByText("This file changed on disk while you were editing.")).toBeInTheDocument();
    expect(screen.getByText("Latest on disk vs draft")).toBeInTheDocument();
  });

  it("protects unsaved changes when closing and switching files", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            root: {
              path: "/workspace",
              display_path: ".",
              name: "workspace",
              kind: "directory",
              children: [
                {
                  path: "/workspace/src",
                  display_path: "src",
                  name: "src",
                  kind: "directory",
                  children: [
                    {
                      path: "/workspace/src/one.ts",
                      display_path: "src/one.ts",
                      name: "one.ts",
                      kind: "file",
                    },
                    {
                      path: "/workspace/src/two.ts",
                      display_path: "src/two.ts",
                      name: "two.ts",
                      kind: "file",
                    },
                  ],
                },
              ],
            },
            truncated: false,
          }),
        } as Response;
      }
      if (url.includes("two.ts")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            path: "/workspace/src/two.ts",
            display_path: "src/two.ts",
            project_path: "/workspace",
            language: "typescript",
            content: "export const two = 2;",
            size: 22,
            revision: "rev-two",
            truncated: false,
          }),
        } as Response;
      }
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-one",
          truncated: false,
        }),
      } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={onClose}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(screen.getByTestId("mock-monaco"));
    await user.type(screen.getByTestId("mock-monaco"), "export const one = 3;");

    expect(await screen.findByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close file preview" }));
    expect(confirm).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "two.ts" }));
    expect(screen.getByTestId("mock-monaco")).toHaveValue("export const one = 3;");
  });

  it("reverts dirty edits back to the saved file content", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        root: {
          path: "/workspace",
          display_path: ".",
          name: "workspace",
          kind: "directory",
          children: [],
        },
        truncated: false,
      }),
    }) as Response);
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/workspace-tree")) return fetchMock(input);
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          path: "/workspace/src/one.ts",
          display_path: "src/one.ts",
          project_path: "/workspace",
          language: "typescript",
          content: "export const one = 1;",
          size: 22,
          revision: "rev-revert",
          truncated: false,
        }),
      } as Response;
    }));
    const user = userEvent.setup();

    render(
      <FilePreviewPanel
        client={{ saveFile: vi.fn() }}
        sessionKey="websocket:chat-1"
        path="/workspace/src/one.ts"
        token="tok"
        onClose={() => {}}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(screen.getByTestId("mock-monaco"));
    await user.type(screen.getByTestId("mock-monaco"), "export const one = 9;");
    expect(await screen.findByText("Unsaved changes")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Revert" }));

    expect(screen.getByTestId("mock-monaco")).toHaveValue("export const one = 1;");
    await waitFor(() => {
      expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    });
  });
});
