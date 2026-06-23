import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProjectPicker } from "@/components/thread/WorkspaceProjectPicker";
import { bootstrapProject, fetchProjects } from "@/lib/api";
import type { WorkspaceScopePayload } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  bootstrapProject: vi.fn(),
  fetchProjects: vi.fn(),
}));

vi.mock("@/lib/runtime", () => ({
  getHostApi: () => null,
}));

const DEFAULT_SCOPE: WorkspaceScopePayload = {
  project_path: "/workspace",
  project_name: "Workspace",
  access_mode: "restricted",
  restrict_to_workspace: true,
};

describe("WorkspaceProjectPicker", () => {
  beforeEach(() => {
    vi.mocked(fetchProjects).mockResolvedValue({
      schema_version: 1,
      projects: [
        {
          id: "proj_1",
          name: "Workspace App",
          slug: "workspace-app",
          root_path: "/workspace/workspace-app",
          created_at: "2026-06-17T00:00:00Z",
          updated_at: "2026-06-17T00:00:00Z",
          status: "active",
          progress: { total: 1, completed: 0, in_progress: 1, blocked: 0, percent: 0 },
          docs: {},
        },
        {
          id: "proj_2",
          name: "External App",
          slug: "external-app",
          root_path: "/other/external-app",
          created_at: "2026-06-17T00:00:00Z",
          updated_at: "2026-06-17T00:00:00Z",
          status: "active",
          progress: { total: 1, completed: 0, in_progress: 1, blocked: 0, percent: 0 },
          docs: {},
        },
      ],
    });
    vi.mocked(bootstrapProject).mockResolvedValue({
      created: true,
      project: {
        id: "proj_new",
        name: "New Project",
        slug: "new-project",
        root_path: "/workspace/new-project",
        created_at: "2026-06-17T00:00:00Z",
        updated_at: "2026-06-17T00:00:00Z",
        status: "idle",
        progress: { total: 0, completed: 0, in_progress: 0, blocked: 0, percent: 0 },
        docs: {},
      },
      workspace_scope: {
        project_path: "/workspace/new-project",
        project_name: "New Project",
        access_mode: "restricted",
        restrict_to_workspace: true,
      },
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows tracked workspace projects only and removes manual path controls", async () => {
    const onChange = vi.fn();

    render(
      <WorkspaceProjectPicker
        isHero={false}
        visible
        scope={DEFAULT_SCOPE}
        defaultScope={DEFAULT_SCOPE}
        controls={{ can_change_project: true, can_use_full_access: true }}
        onChange={onChange}
        authToken="token"
      />,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByText("Workspace App")).toBeInTheDocument();
    expect(screen.queryByText("External App")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Create project" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Paste path" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use Path" })).not.toBeInTheDocument();
  });

  it("shows a load failure instead of a false empty state when projects cannot be fetched", async () => {
    vi.mocked(fetchProjects).mockRejectedValueOnce(new Error("network down"));

    render(
      <WorkspaceProjectPicker
        isHero={false}
        visible
        scope={DEFAULT_SCOPE}
        defaultScope={DEFAULT_SCOPE}
        controls={{ can_change_project: true, can_use_full_access: true }}
        onChange={vi.fn()}
        authToken="token"
      />,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "Choose project" }));

    expect(await screen.findByText("Could not load tracked workspace projects.")).toBeInTheDocument();
    expect(screen.queryByText("No tracked workspace folders found.")).not.toBeInTheDocument();
  });
});
