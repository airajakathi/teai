import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionInfoPopover } from "@/components/thread/SessionInfoPopover";
import { setAppLanguage } from "@/i18n";

function automationJob(
  nextRunAt = Date.now() + 3_600_000,
  state: Record<string, unknown> = {},
) {
  return {
    id: "job-1",
    name: "Morning check",
    enabled: true,
    schedule: { kind: "every", every_ms: 3_600_000 },
    payload: { message: "Check the project status" },
    state: { next_run_at_ms: nextRunAt, ...state },
  };
}

function automationsResponse(jobs: unknown[]) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({
      jobs,
    }),
  } as Response;
}

function workflowRunsResponse(items: unknown[]) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({ items }),
  } as Response;
}

function checkpointsResponse(items: unknown[]) {
  return {
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => ({ items }),
  } as Response;
}

function sessionInfoFetchMock({
  jobs = [automationJob()],
  workflowRuns = [],
  checkpoints = [],
}: {
  jobs?: unknown[];
  workflowRuns?: unknown[];
  checkpoints?: unknown[];
}) {
  return vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/automations")) return automationsResponse(jobs);
    if (url.includes("/workflow-runs")) return workflowRunsResponse(workflowRuns);
    if (url.includes("/checkpoints") && init?.method === "POST") {
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ checkpoint_id: "cp-new" }),
      } as Response;
    }
    if (url.includes("/checkpoints/") && url.endsWith("/restore")) {
      return {
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ restored: true }),
      } as Response;
    }
    if (url.includes("/checkpoints")) return checkpointsResponse(checkpoints);
    throw new Error(`Unhandled fetch: ${url}`);
  });
}

describe("SessionInfoPopover", () => {
  beforeEach(async () => {
    await setAppLanguage("en");
    vi.stubGlobal("fetch", sessionInfoFetchMock({}));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("loads and displays session automations when opened", async () => {
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/websocket%3Achat-1/automations",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      );
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/workflow-runs",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/checkpoints",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
    expect(await screen.findByText("Morning check")).toBeInTheDocument();
    expect(screen.getByText("Check the project status")).toBeInTheDocument();
  });

  it("localizes the panel chrome in Simplified Chinese", async () => {
    await setAppLanguage("zh-CN");
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="@hyperframes 使用指南"
      />,
    );

    await user.click(screen.getByRole("button", { name: "会话详情" }));

    expect(await screen.findByText("会话")).toBeInTheDocument();
    expect(screen.getByText("自动任务")).toBeInTheDocument();
    expect(screen.getByText("Morning check")).toBeInTheDocument();
    expect(screen.getByText(/下次/)).toBeInTheDocument();
    expect(screen.queryByText("Session")).not.toBeInTheDocument();
    expect(screen.queryByText("Automations")).not.toBeInTheDocument();
  });

  it("shows a short pending label for deferred automations", async () => {
    vi.stubGlobal("fetch", sessionInfoFetchMock({
      jobs: [automationJob(Date.now() - 1000, { pending: true })],
    }));
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    expect(await screen.findByText("Runs shortly")).toBeInTheDocument();
    expect(screen.queryByText(/ago/i)).not.toBeInTheDocument();
  });

  it("refreshes while open so completed one-shot automations disappear", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes("/automations")) {
          const mock = vi.mocked(fetch);
          const calls = mock.mock.calls.filter(([called]) => String(called).includes("/automations")).length;
          return calls <= 1
            ? automationsResponse([automationJob(Date.now() + 1000)])
            : automationsResponse([]);
        }
        if (url.includes("/workflow-runs")) return workflowRunsResponse([]);
        if (url.includes("/checkpoints")) return checkpointsResponse([]);
        throw new Error(`Unhandled fetch: ${url}`);
      }),
    );
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    expect(await screen.findByText("Morning check")).toBeInTheDocument();

    await waitFor(
      () => {
        expect(screen.queryByText("Morning check")).not.toBeInTheDocument();
      },
      { timeout: 4500 },
    );
    expect(screen.getByText("No automations in this session yet.")).toBeInTheDocument();
  }, 8000);

  it("shows workflow runs and checkpoints in the session dashboard", async () => {
    vi.stubGlobal("fetch", sessionInfoFetchMock({
      workflowRuns: [
        {
          run_id: "run-1",
          workflow_id: "app_build_v1",
          goal_id: "goal-1",
          state: "running",
          current_step: "verify",
          updated_at: Date.now() / 1000,
          step_count: 3,
          completed_steps: 2,
        },
      ],
      checkpoints: [
        {
          checkpoint_id: "cp-1",
          created_at: Date.now() / 1000,
          kind: "workflow",
          workflow_id: "app_build_v1",
          step_id: "verify",
        },
      ],
    }));
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    expect(await screen.findByText("Workflow runs")).toBeInTheDocument();
    expect(screen.getByText("app_build_v1")).toBeInTheDocument();
    expect(screen.getByText("Current step: verify")).toBeInTheDocument();
    expect(screen.getByText("Checkpoints")).toBeInTheDocument();
    expect(screen.getByText("cp-1")).toBeInTheDocument();
  });

  it("saves and restores checkpoints from the popover", async () => {
    const fetchMock = sessionInfoFetchMock({
      checkpoints: [
        {
          checkpoint_id: "cp-1",
          created_at: Date.now() / 1000,
          kind: "session",
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));
    await screen.findByText("cp-1");

    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => {
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

  it("surfaces automation fetch failures instead of a false empty state", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    expect(await screen.findByText("Could not load automations.")).toBeInTheDocument();
    expect(screen.queryByText("No automations in this session yet.")).not.toBeInTheDocument();
  });

  it("surfaces runtime fetch failures instead of silently freezing stale data", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes("/automations")) return automationsResponse([]);
        throw new Error("runtime unreachable");
      }),
    );

    render(
      <SessionInfoPopover
        sessionKey="websocket:chat-1"
        token="tok"
        title="Release work"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Session details" }));

    const failures = screen.getAllByText("Could not load workflow activity.");
    expect(failures.length).toBeGreaterThanOrEqual(1);
  });
});
