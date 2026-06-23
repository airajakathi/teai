import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowDashboardView } from "@/components/workflows/WorkflowDashboardView";
import { setAppLanguage } from "@/i18n";

function workflowsResponse(workflows: unknown[]) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({ workflows }),
  } as Response;
}

function itemsResponse(items: unknown[]) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({ items }),
  } as Response;
}

describe("WorkflowDashboardView", () => {
  beforeEach(async () => {
    await setAppLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows workflow runs, filters them, and triggers checkpoint actions", async () => {
    let runStatusHandler: ((chatId: string, startedAt: number | null) => void) | null = null;
    let chatHandler: ((ev: import("@/lib/types").InboundEvent) => void) | null = null;
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/workflows")) {
        return workflowsResponse([
          { workflow_id: "app_build_v1", name: "App build", description: "Build app" },
          { workflow_id: "deploy_v1", name: "Deploy", description: "Deploy app" },
        ]);
      }
      if (url.includes("/workflow-runs/run-1/cancel")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ accepted: true, action: "cancel", command: "/workflow cancel run-1" }),
        } as Response;
      }
      if (url.includes("/workflow-runs/run-2/re")) {
        throw new Error(`Unhandled fetch: ${url}`);
      }
      if (url.includes("/workflow-runs/run-2/resume")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ accepted: true, action: "resume", command: "/workflow resume run-2" }),
        } as Response;
      }
      if (url.includes("/workflow-runs/run-1")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            run: {
              run_id: "run-1",
              workflow_id: "app_build_v1",
              goal_id: "goal-1",
              state: "running",
              current_step: "verify",
              started_at: 1_720_000_000,
              updated_at: 1_720_000_000,
              finished_at: null,
              error: null,
              step_count: 3,
              completed_steps: 2,
              cancel_requested: false,
              step_results: {},
              status_history: [{ state: "running", at: 1_720_000_000, detail: "started" }],
              checkpoints: [{ checkpoint_id: "cp-from-run", step_id: "verify", saved_at: 1_720_000_020, result_keys: ["plan"] }],
              step_states: [
                {
                  step_id: "plan",
                  name: "Plan",
                  state: "completed",
                  attempts: 1,
                  started_at: 1_720_000_000,
                  finished_at: 1_720_000_005,
                  error: null,
                  output: { ok: true },
                },
                {
                  step_id: "verify",
                  name: "Verify",
                  state: "running",
                  attempts: 1,
                  started_at: 1_720_000_010,
                  finished_at: null,
                  error: null,
                  output: null,
                },
              ],
            },
          }),
        } as Response;
      }
      if (url.includes("/workflow-runs/run-2")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            run: {
              run_id: "run-2",
              workflow_id: "deploy_v1",
              goal_id: "goal-2",
              state: "failed",
              current_step: null,
              started_at: 1_720_000_030,
              updated_at: 1_720_000_030,
              finished_at: 1_720_000_060,
              error: "release blocked",
              step_count: 2,
              completed_steps: 1,
              cancel_requested: false,
              step_results: {},
              status_history: [{ state: "failed", at: 1_720_000_060, detail: "release blocked" }],
              checkpoints: [],
              step_states: [
                {
                  step_id: "release",
                  name: "Release",
                  state: "failed",
                  attempts: 2,
                  started_at: 1_720_000_040,
                  finished_at: 1_720_000_060,
                  error: "release blocked",
                  output: null,
                },
              ],
            },
          }),
        } as Response;
      }
      if (url.includes("/workflow-runs")) {
        return itemsResponse([
          {
            run_id: "run-1",
            workflow_id: "app_build_v1",
            goal_id: "goal-1",
            state: "running",
            current_step: "verify",
            updated_at: 1_720_000_000,
            step_count: 3,
            completed_steps: 2,
          },
          {
            run_id: "run-2",
            workflow_id: "deploy_v1",
            goal_id: "goal-2",
            state: "completed",
            current_step: null,
            updated_at: 1_720_000_030,
            finished_at: 1_720_000_060,
            step_count: 2,
            completed_steps: 2,
          },
        ]);
      }
      if (url.includes("/checkpoints/") && url.endsWith("/restore")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ restored: true }),
        } as Response;
      }
      if (url.includes("/checkpoints/") && url.endsWith("/rebuild")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            summary: "Checkpoint: `cp-1`\nRun: `run-2`\nRebuild guidance:",
            checkpoint: {
              checkpoint_id: "cp-1",
              created_at: 1_720_000_040,
              kind: "workflow",
              workflow_id: "deploy_v1",
              run_id: "run-2",
              step_id: "release",
            },
          }),
        } as Response;
      }
      if (url.includes("/checkpoints") && init?.method === "POST") {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ checkpoint_id: "cp-new" }),
        } as Response;
      }
      if (url.includes("/checkpoints")) {
        return itemsResponse([
          {
            checkpoint_id: "cp-1",
            created_at: 1_720_000_040,
            kind: "workflow",
            workflow_id: "deploy_v1",
            run_id: "run-2",
            step_id: "release",
          },
        ]);
      }
      throw new Error(`Unhandled fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const client = {
      onRunStatus(handler: (chatId: string, startedAt: number | null) => void) {
        runStatusHandler = handler;
        return () => {
          runStatusHandler = null;
        };
      },
      onChat(_chatId: string, handler: (ev: import("@/lib/types").InboundEvent) => void) {
        chatHandler = handler;
        return () => {
          chatHandler = null;
        };
      },
    };

    render(
      <WorkflowDashboardView
        client={client}
        token="tok"
        sessionKey="websocket:chat-1"
        sessionTitle="Release chat"
        theme="light"
        onToggleTheme={() => {}}
        onToggleSidebar={() => {}}
        onBackToChat={() => {}}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Workflows" })).toBeInTheDocument();
    expect(screen.getByText("Showing workflow activity for Release chat.")).toBeInTheDocument();
    expect((await screen.findAllByText("app_build_v1")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Step timeline")).toBeInTheDocument();
    expect(screen.getByText("Verify")).toBeInTheDocument();

    await act(async () => {
      runStatusHandler?.("chat-1", null);
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workflow-runs",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      );
    });

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await act(async () => {
      chatHandler?.({
        event: "message",
        chat_id: "chat-1",
        text: "",
        kind: "progress",
        agent_ui: {
          kind: "workflow_run",
          data: {
            version: 1,
            run_id: "run-1",
            workflow_id: "app_build_v1",
            goal_id: "goal-1",
            session_key: "websocket:chat-1",
            state: "completed",
            current_step: null,
            started_at: 1_720_000_000,
            updated_at: 1_720_000_120,
            finished_at: 1_720_000_120,
            error: null,
            cancel_requested: false,
            step_count: 3,
            completed_steps: 3,
            status_history: [{ state: "completed", at: 1_720_000_120, detail: "done" }],
            checkpoints: [],
            step_states: [
              {
                step_id: "verify",
                name: "Verify",
                state: "completed",
                attempts: 1,
                started_at: 1_720_000_010,
                finished_at: 1_720_000_120,
                error: null,
                output: null,
              },
            ],
          },
        },
      });
    });

    expect(await screen.findByText("Live update: run is now completed.")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: /Deploy/i })[0]);

    await waitFor(() => {
      expect(screen.getByText("run-2")).toBeInTheDocument();
      expect(screen.queryByText("run-1")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Resume" }));
    await user.click(screen.getByRole("button", { name: "Save checkpoint" }));
    await user.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workflow-runs/run-1/cancel",
        expect.objectContaining({
          method: "POST",
          headers: { Authorization: "Bearer tok" },
        }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/workflow-runs/run-2/resume",
        expect.objectContaining({
          method: "POST",
          headers: { Authorization: "Bearer tok" },
        }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/checkpoints",
        expect.objectContaining({
          method: "POST",
          headers: { Authorization: "Bearer tok" },
        }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/checkpoints/cp-1/restore",
        expect.objectContaining({
          method: "POST",
          headers: { Authorization: "Bearer tok" },
        }),
      );
    });
  });

});
