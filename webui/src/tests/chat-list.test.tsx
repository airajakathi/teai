import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatList } from "@/components/ChatList";
import type { ChatSummary } from "@/lib/types";

function session(overrides: Partial<ChatSummary>): ChatSummary {
  const chatId = overrides.chatId ?? "chat";
  return {
    key: `websocket:${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: "2026-05-20T10:00:00Z",
    updatedAt: "2026-05-20T10:00:00Z",
    preview: "",
    ...overrides,
  };
}

describe("ChatList", () => {
  it("groups WebUI chats by workspace project while preserving in-project sorting and activity", () => {
    const sessions = [
      session({
        chatId: "zeta",
        title: "Zeta task",
        updatedAt: "2026-05-20T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/teai_builder",
          project_name: "teai_builder",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "alpha",
        title: "Alpha task",
        updatedAt: "2026-05-20T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/teai_builder",
          project_name: "teai_builder",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "bench",
        title: "Bench task",
        updatedAt: "2026-05-21T09:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/teai_builder-bench",
          project_name: "teai_builder-bench",
          access_mode: "full",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:alpha"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        sort="title_asc"
        showTimestamps
        runningChatIds={["zeta"]}
      />,
    );

    const teai_builderSection = screen.getByRole("region", { name: "teai_builder" });
    const teai_builderText = teai_builderSection.textContent ?? "";

    expect(screen.getByRole("region", { name: "teai_builder-bench" })).toBeInTheDocument();
    expect(within(teai_builderSection).getByText("Alpha task")).toBeInTheDocument();
    expect(within(teai_builderSection).getByText("Zeta task")).toBeInTheDocument();
    expect(teai_builderText.indexOf("Alpha task")).toBeLessThan(teai_builderText.indexOf("Zeta task"));
    expect(within(teai_builderSection).getByLabelText("Agent running")).toBeInTheDocument();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("keeps default workspace chats in the Chats section instead of a project folder", () => {
    const sessions = [
      session({
        chatId: "default",
        title: "Default workspace chat",
        updatedAt: "2026-05-21T10:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/.teai_builder/workspace",
          project_name: "workspace",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "project",
        title: "Project chat",
        updatedAt: "2026-05-21T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/teai_builder",
          project_name: "teai_builder",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:default"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        defaultWorkspacePath="/Users/me/.teai_builder/workspace"
        showTimestamps
      />,
    );

    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "teai_builder" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "workspace" })).not.toBeInTheDocument();

    const chatsSection = screen.getByRole("region", { name: "Earlier" });
    expect(within(chatsSection).getByText("Default workspace chat")).toBeInTheDocument();
    expect(within(chatsSection).queryByText("Project chat")).not.toBeInTheDocument();
  });

  it("can collapse a project group and keeps project rename separate from chat titles", async () => {
    const onToggleGroup = vi.fn();
    const onRequestRenameProject = vi.fn();
    const onNewChatInProject = vi.fn();
    const onOpenProject = vi.fn();
    const sessions = [
      session({
        chatId: "alpha",
        title: "Alpha task",
        project: {
          id: "proj_photos",
          name: "Photos",
          slug: "photos",
          root_path: "/Users/me/teai_builder",
          created_at: "2026-05-20T10:00:00Z",
          updated_at: "2026-05-20T10:00:00Z",
          status: "active",
          progress: { total: 4, completed: 1, in_progress: 1, blocked: 0, percent: 25 },
          docs: {},
        },
        workspaceScope: {
          project_path: "/Users/me/teai_builder",
          project_name: "teai_builder",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:alpha"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        onToggleGroup={onToggleGroup}
        onRequestRenameProject={onRequestRenameProject}
        onNewChatInProject={onNewChatInProject}
        onOpenProject={onOpenProject}
        projectNameOverrides={{ "/Users/me/teai_builder": "Photos" }}
        collapsedGroups={{ "project:/Users/me/teai_builder": true }}
      />,
    );

    const projectSection = screen.getByRole("region", { name: "Photos" });
    fireEvent.click(within(projectSection).getByRole("button", { name: "Expand project" }));

    expect(onToggleGroup).toHaveBeenCalledWith("project:/Users/me/teai_builder");
    expect(within(projectSection).queryByText("Alpha task")).not.toBeInTheDocument();

    fireEvent.click(within(projectSection).getByRole("button", { name: "Photos 25%" }));
    expect(onOpenProject).toHaveBeenCalledWith("proj_photos");

    fireEvent.click(
      within(projectSection).getByRole("button", { name: "Start a new chat in Photos" }),
    );
    expect(onNewChatInProject).toHaveBeenCalledWith("/Users/me/teai_builder", "Photos");
    expect(onToggleGroup).toHaveBeenCalledTimes(1);

    fireEvent.pointerDown(
      within(projectSection).getByLabelText("Chat actions for Photos"),
      { button: 0 },
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));

    expect(onRequestRenameProject).toHaveBeenCalledWith("/Users/me/teai_builder", "Photos");
  });

  it("hides the completed dot for the active chat", () => {
    const sessions = [
      session({
        chatId: "active",
        title: "Active task",
      }),
      session({
        chatId: "done",
        title: "Done task",
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:active"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        completedChatIds={["active", "done"]}
      />,
    );

    const finished = screen.getAllByLabelText("Agent finished");
    expect(finished).toHaveLength(1);
    expect(finished[0].firstElementChild).toHaveClass("h-2", "w-2");
  });

  it("folds long default workspace chats and can show all", () => {
    const sessions = Array.from({ length: 10 }, (_, index) =>
      session({
        chatId: `chat-${index}`,
        title: `Chat ${index}`,
        updatedAt: `2026-05-21T10:${String(index).padStart(2, "0")}:00Z`,
        workspaceScope: {
          project_path: "/Users/me/.teai_builder/workspace",
          project_name: "workspace",
          access_mode: "restricted",
        },
      }),
    );
    const onToggleGroup = vi.fn();
    const baseProps = {
      sessions,
      activeKey: null,
      onSelect: vi.fn(),
      onRequestDelete: vi.fn(),
      onTogglePin: vi.fn(),
      onRequestRename: vi.fn(),
      onToggleArchive: vi.fn(),
      onToggleGroup,
      defaultWorkspacePath: "/Users/me/.teai_builder/workspace",
    };

    const { rerender } = render(<ChatList {...baseProps} />);
    const chatsSection = screen.getByRole("region", { name: "Earlier" });

    expect(within(chatsSection).getByText("Chat 9")).toBeInTheDocument();
    expect(within(chatsSection).getByText("Chat 2")).toBeInTheDocument();
    expect(within(chatsSection).queryByText("Chat 1")).not.toBeInTheDocument();
    expect(within(chatsSection).queryByRole("button", { name: "Show all" })).not.toBeInTheDocument();
    fireEvent.click(within(chatsSection).getByRole("button", { name: "2 hidden chats" }));

    expect(onToggleGroup).toHaveBeenCalledWith("general:Earlier");

    rerender(
      <ChatList
        {...baseProps}
        collapsedGroups={{ "general:Earlier": false }}
      />,
    );

    expect(within(chatsSection).getByText("Chat 0")).toBeInTheDocument();
    expect(within(chatsSection).getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("sorts Chats section among project groups by recency", () => {
    const sessions = [
      session({
        chatId: "recent-chat",
        title: "Recent chat",
        updatedAt: "2026-05-21T12:00:00Z",
      }),
      session({
        chatId: "project-a",
        title: "Project A task",
        updatedAt: "2026-05-21T10:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-a",
          project_name: "project-a",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "project-b",
        title: "Project B task",
        updatedAt: "2026-05-21T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-b",
          project_name: "project-b",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:recent-chat"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showTimestamps
      />,
    );

    const allRegions = screen.getAllByRole("region");

    // The most recently updated conversation ("Recent chat" at 12:00) is grouped
    // under a General date bucket, while project groups are sorted by recency.
    const recentChatRegion = allRegions.find((region) => (region.textContent ?? "").includes("Recent chat"));
    expect(recentChatRegion).toBeDefined();
    const generalIdx = allRegions.indexOf(recentChatRegion);
    const projAIdx = allRegions.findIndex((region) => (region.getAttribute("aria-label") ?? "").includes("project-a"));
    const projBIdx = allRegions.findIndex((region) => (region.getAttribute("aria-label") ?? "").includes("project-b"));

    expect(generalIdx).toBeGreaterThanOrEqual(0);
    expect(projAIdx).toBeGreaterThanOrEqual(0);
    expect(projBIdx).toBeGreaterThanOrEqual(0);
  });

  it("keeps one Projects heading when Chats sorts between project groups", () => {
    const sessions = [
      session({
        chatId: "project-a",
        title: "Project A task",
        updatedAt: "2026-05-21T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-a",
          project_name: "project-a",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "middle-chat",
        title: "Middle chat",
        updatedAt: "2026-05-21T11:00:00Z",
      }),
      session({
        chatId: "project-b",
        title: "Project B task",
        updatedAt: "2026-05-21T10:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-b",
          project_name: "project-b",
          access_mode: "restricted",
        },
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:middle-chat"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showTimestamps
      />,
    );

    const regionNames = screen
      .getAllByRole("region")
      .map((r) => r.getAttribute("aria-label") ?? "");

    expect(regionNames).toEqual(["project-a", "project-b", "Earlier"]);
    expect(screen.getAllByText("Projects")).toHaveLength(1);
  });

  it("keeps General last when its latest conversation is older than all projects", () => {
    const sessions = [
      session({
        chatId: "project-a",
        title: "Project A task",
        updatedAt: "2026-05-21T12:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-a",
          project_name: "project-a",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "project-b",
        title: "Project B task",
        updatedAt: "2026-05-21T11:00:00Z",
        workspaceScope: {
          project_path: "/Users/me/project-b",
          project_name: "project-b",
          access_mode: "restricted",
        },
      }),
      session({
        chatId: "old-chat",
        title: "Old chat",
        updatedAt: "2026-05-21T10:00:00Z",
      }),
    ];

    render(
      <ChatList
        sessions={sessions}
        activeKey="websocket:old-chat"
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRequestRename={vi.fn()}
        onToggleArchive={vi.fn()}
        showTimestamps
      />,
    );

    const regionNames = screen
      .getAllByRole("region")
      .map((r) => r.getAttribute("aria-label") ?? "");

    expect(regionNames).toEqual(["project-a", "project-b", "Earlier"]);
    expect(screen.getAllByText("Projects")).toHaveLength(1);
  });
});
