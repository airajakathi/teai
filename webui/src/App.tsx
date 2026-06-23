import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Moon, PanelLeft, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { RenameChatDialog } from "@/components/RenameChatDialog";
import { Sidebar } from "@/components/Sidebar";
import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

import { useSessions } from "@/hooks/useSessions";
import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import { useSidebarState } from "@/hooks/useSidebarState";
import { useSkills } from "@/hooks/useSkills";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import {
  clearSavedSecret,
  deriveWsUrl,
  fetchBootstrap,
  loadSavedSecret,
  saveSecret,
} from "@/lib/bootstrap";
import { displayTitle } from "@/lib/chat-groups";
import { deriveTitle } from "@/lib/format";
import { TeaiBuilderClient } from "@/lib/teai_builder-client";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import type {
  ChatSummary,
  ProjectSummary,
  RuntimeSurface,
  SessionAutomationJob,
  SettingsPayload,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchProjects, fetchSettings, fetchWorkspaces } from "@/lib/api";
import {
  createRuntimeHost,
  getHostApi,
  toRuntimeSurface,
} from "@/lib/runtime";
import {
  projectNameFromPath,
  sameWorkspacePath,
  selectedProjectScope as resolveProjectScope,
} from "@/lib/workspace";

const SettingsView = lazy(async () => {
  const mod = await import("@/components/settings/SettingsView");
  return { default: mod.SettingsView };
});

const WorkflowDashboardView = lazy(async () => {
  const mod = await import("@/components/workflows/WorkflowDashboardView");
  return { default: mod.WorkflowDashboardView };
});

type SettingsSectionKey = import("@/components/settings/SettingsView").SettingsSectionKey;

function preloadShellViewModules(): void {
  void import("@/components/settings/SettingsView");
  void import("@/components/workflows/WorkflowDashboardView");
}

type BootState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "auth"; failed?: boolean }
  | {
      status: "ready";
      client: TeaiBuilderClient;
      token: string;
      tokenExpiresAt: number;
      modelName: string | null;
      runtimeSurface: RuntimeSurface;
    };

const SIDEBAR_STORAGE_KEY = "teai_builder-webui.sidebar";
const COMPLETED_RUNS_STORAGE_KEY = "teai_builder-webui.sidebar.completed-runs.v1";
const RESTART_STARTED_KEY = "teai_builder-webui.restartStartedAt";
const SIDEBAR_WIDTH = 272;
const SIDEBAR_RAIL_WIDTH = 56;
const TOKEN_REFRESH_MARGIN_MS = 30_000;
const TOKEN_REFRESH_MIN_DELAY_MS = 5_000;
type ShellView = "chat" | "settings" | "apps" | "skills" | "workflows";
type ShellRoute = {
  view: ShellView;
  activeKey: string | null;
  projectId: string | null;
  settingsSection: SettingsSectionKey;
};

const SETTINGS_SECTION_KEYS: SettingsSectionKey[] = [
  "overview",
  "appearance",
  "models",
  "image",
  "voice",
  "browser",
  "apps",
  "skills",
  "runtime",
  "advanced",
];

function isSettingsSectionKey(value: string | null): value is SettingsSectionKey {
  return SETTINGS_SECTION_KEYS.includes(value as SettingsSectionKey);
}

function defaultShellRoute(): ShellRoute {
  return { view: "chat", activeKey: null, projectId: null, settingsSection: "overview" };
}

function shellViewForSettingsSection(section: SettingsSectionKey): ShellView {
  if (section === "apps" || section === "skills") return section;
  return "settings";
}

function readShellRoute(): ShellRoute {
  if (typeof window === "undefined") return defaultShellRoute();
  const hash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  if (!hash || hash === "/" || hash === "/new") return defaultShellRoute();

  const [path, query = ""] = hash.split("?", 2);
  const params = new URLSearchParams(query);
  const rawSettingsSection = params.get("section");
  const settingsSection = isSettingsSectionKey(rawSettingsSection)
    ? rawSettingsSection
    : "overview";
  const activeKey = params.get("chat")?.trim() || null;
  const projectId = params.get("project")?.trim() || null;

  if (path === "/settings") {
    return {
      view: shellViewForSettingsSection(settingsSection),
      activeKey,
      projectId,
      settingsSection,
    };
  }
  if (path === "/apps") {
    return { view: "apps", activeKey, projectId, settingsSection: "apps" };
  }
  if (path === "/skills") {
    return { view: "skills", activeKey, projectId, settingsSection: "skills" };
  }
  if (path === "/workflows") {
    return { view: "workflows", activeKey, projectId, settingsSection: "overview" };
  }
  if (path.startsWith("/projects/")) {
    const rest = path.slice("/projects/".length);
    const [encodedProjectId, ...segments] = rest.split("/");
    try {
      const parsedProjectId = decodeURIComponent(encodedProjectId).trim();
      if (!parsedProjectId) return defaultShellRoute();
      if (segments[0] === "chat" && segments.length > 1) {
        const key = decodeURIComponent(segments.slice(1).join("/")).trim();
        return {
          view: "chat",
          activeKey: key || null,
          projectId: parsedProjectId,
          settingsSection: "overview",
        };
      }
      return {
        view: "chat",
        activeKey: null,
        projectId: parsedProjectId,
        settingsSection: "overview",
      };
    } catch {
      return defaultShellRoute();
    }
  }
  if (path.startsWith("/chat/")) {
    const encoded = path.slice("/chat/".length);
    try {
      const key = decodeURIComponent(encoded).trim();
      return key
        ? { view: "chat", activeKey: key, projectId: null, settingsSection: "overview" }
        : defaultShellRoute();
    } catch {
      return defaultShellRoute();
    }
  }
  return defaultShellRoute();
}

function shellRouteHash(route: ShellRoute): string {
  if (route.view === "chat") {
    if (route.projectId) {
      return route.activeKey
        ? `#/projects/${encodeURIComponent(route.projectId)}/chat/${encodeURIComponent(route.activeKey)}`
        : `#/projects/${encodeURIComponent(route.projectId)}`;
    }
    return route.activeKey
      ? `#/chat/${encodeURIComponent(route.activeKey)}`
      : "#/new";
  }
  const params = new URLSearchParams();
  if (route.activeKey) params.set("chat", route.activeKey);
  if (route.projectId) params.set("project", route.projectId);
  if (route.view === "settings" && route.settingsSection !== "overview") {
    params.set("section", route.settingsSection);
  }
  const query = params.toString();
  return `#/${route.view}${query ? `?${query}` : ""}`;
}

function writeShellRoute(route: ShellRoute, replace = false): void {
  if (typeof window === "undefined") return;
  const nextHash = shellRouteHash(route);
  if (window.location.hash === nextHash) return;
  if (replace) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${nextHash}`,
    );
    return;
  }
  window.location.hash = nextHash;
}

function bootstrapTokenExpiresAt(expiresInSeconds: number): number {
  return Date.now() + Math.max(0, expiresInSeconds) * 1000;
}

function tokenRefreshDelayMs(expiresAt: number): number {
  const remaining = Math.max(0, expiresAt - Date.now());
  const margin = Math.min(
    TOKEN_REFRESH_MARGIN_MS,
    Math.max(1_000, remaining / 2),
  );
  return Math.max(TOKEN_REFRESH_MIN_DELAY_MS, remaining - margin);
}

function AuthForm({
  failed,
  onSecret,
}: {
  failed: boolean;
  onSecret: (secret: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const secret = value.trim();
    if (!secret) return;
    setSubmitting(true);
    onSecret(secret);
  };

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-4"
      >
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="text-lg font-semibold">{t("app.auth.title")}</p>
          <p className="text-sm text-muted-foreground">{t("app.auth.hint")}</p>
        </div>
        {failed && (
          <p className="text-center text-sm text-destructive">
            {t("app.auth.invalid")}
          </p>
        )}
        <Input
          type="password"
          placeholder={t("app.auth.placeholder")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={submitting}
          autoFocus
        />
        <Button
          type="submit"
          className="w-full"
          disabled={!value.trim() || submitting}
        >
          {t("app.auth.submit")}
        </Button>
      </form>
    </div>
  );
}

function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

function readCompletedRunChatIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(COMPLETED_RUNS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string"));
  } catch {
    return new Set();
  }
}

function writeCompletedRunChatIds(chatIds: Set<string>): void {
  try {
    window.localStorage.setItem(
      COMPLETED_RUNS_STORAGE_KEY,
      JSON.stringify(Array.from(chatIds)),
    );
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

function normalizeWorkspaceScope(scope: WorkspaceScopePayload): WorkspaceScopePayload {
  const accessMode = scope.access_mode === "restricted" ? "restricted" : "full";
  return {
    ...scope,
    project_name: scope.project_name ?? projectNameFromPath(scope.project_path),
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  };
}

function HostChrome({
  onToggleSidebar,
  onSidebarPreviewEnter,
  onSidebarPreviewLeave,
  sidebarOpen = true,
  rightAction,
}: {
  onToggleSidebar?: () => void;
  onSidebarPreviewEnter?: () => void;
  onSidebarPreviewLeave?: () => void;
  sidebarOpen?: boolean;
  rightAction?: ReactNode;
}) {
  const { t } = useTranslation();

  return (
    <header className="host-drag-region pointer-events-none absolute inset-x-0 top-0 z-40 h-11 bg-transparent text-foreground/90">
      {onToggleSidebar ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          data-testid="host-sidebar-toggle"
          onClick={onToggleSidebar}
          onFocus={!sidebarOpen ? onSidebarPreviewEnter : undefined}
          onBlur={!sidebarOpen ? onSidebarPreviewLeave : undefined}
          onMouseEnter={!sidebarOpen ? onSidebarPreviewEnter : undefined}
          onMouseLeave={!sidebarOpen ? onSidebarPreviewLeave : undefined}
          className="host-no-drag pointer-events-auto absolute left-[88px] top-[8px] h-7 w-7 rounded-lg bg-transparent text-muted-foreground/85 shadow-none hover:bg-transparent hover:text-foreground"
        >
          <PanelLeft className="h-[15px] w-[15px]" strokeWidth={1.75} />
        </Button>
      ) : null}
      {rightAction ? (
        <div className="host-no-drag pointer-events-auto absolute right-3 top-2">
          {rightAction}
        </div>
      ) : null}
    </header>
  );
}

function buildProjectScope(
  project: ProjectSummary,
  fallback: WorkspaceScopePayload | null,
): WorkspaceScopePayload {
  const accessMode = fallback?.access_mode === "restricted" ? "restricted" : "full";
  return normalizeWorkspaceScope({
    project_path: project.root_path,
    project_name: project.name,
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  });
}

function ProjectOverviewPanel({
  project,
  onCreateChat,
}: {
  project: ProjectSummary;
  onCreateChat: () => void;
}) {
  const docs = Object.entries(project.docs);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 pb-8 pt-24">
        <div className="rounded-3xl border border-border/70 bg-card/80 p-6 shadow-sm backdrop-blur">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground/75">
                Selected Project
              </p>
              <h1 className="truncate text-3xl font-semibold tracking-tight">{project.name}</h1>
              <p className="text-sm text-muted-foreground">{project.root_path}</p>
            </div>
            <Button onClick={onCreateChat}>Open project chat</Button>
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
              <p className="text-xs text-muted-foreground">Status</p>
              <p className="mt-1 text-sm font-medium capitalize">{project.status}</p>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
              <p className="text-xs text-muted-foreground">Phase</p>
              <p className="mt-1 text-sm font-medium">{project.phase || "Not set"}</p>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
              <p className="text-xs text-muted-foreground">Progress</p>
              <p className="mt-1 text-sm font-medium">{project.progress.percent}% complete</p>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
              <p className="text-xs text-muted-foreground">Chats</p>
              <p className="mt-1 text-sm font-medium">{project.chat_count ?? 0}</p>
            </div>
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
          <div className="rounded-3xl border border-border/70 bg-card/80 p-6 shadow-sm backdrop-blur">
            <h2 className="text-lg font-semibold">Project Progress</h2>
            <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-muted/70">
              <div
                className="h-full rounded-full bg-foreground/80 transition-[width] duration-300"
                style={{ width: `${Math.max(0, Math.min(100, project.progress.percent))}%` }}
              />
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
                <p className="text-xs text-muted-foreground">Completed Tasks</p>
                <p className="mt-1 text-sm font-medium">
                  {project.progress.completed} / {project.progress.total || 0}
                </p>
              </div>
              <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
                <p className="text-xs text-muted-foreground">In Progress</p>
                <p className="mt-1 text-sm font-medium">{project.progress.in_progress}</p>
              </div>
              <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
                <p className="text-xs text-muted-foreground">Blocked</p>
                <p className="mt-1 text-sm font-medium">{project.progress.blocked}</p>
              </div>
              <div className="rounded-2xl border border-border/60 bg-background/60 p-4">
                <p className="text-xs text-muted-foreground">Linked Chats</p>
                <p className="mt-1 text-sm font-medium">{project.linked_chat_ids?.length ?? 0}</p>
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-border/70 bg-card/80 p-6 shadow-sm backdrop-blur">
            <h2 className="text-lg font-semibold">Live Docs</h2>
            <div className="mt-4 space-y-2">
              {docs.length ? docs.map(([key, path]) => (
                <div
                  key={key}
                  className="rounded-2xl border border-border/60 bg-background/60 px-4 py-3"
                >
                  <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground/70">
                    {key}
                  </p>
                  <p className="mt-1 truncate text-sm font-medium">{path}</p>
                </div>
              )) : (
                <div className="rounded-2xl border border-dashed border-border/70 bg-background/40 px-4 py-6 text-sm text-muted-foreground">
                  No project documents registered yet.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ShellViewSkeleton({
  title,
  hostChromeInset = false,
}: {
  title: string;
  hostChromeInset?: boolean;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      <div
        className={cn(
          "border-b border-border/60 px-6 py-4",
          hostChromeInset ? "pt-16" : "pt-6",
        )}
      >
        <div className="text-lg font-semibold tracking-tight text-foreground">{title}</div>
        <div className="mt-2 h-4 w-40 animate-pulse rounded-full bg-muted/70" />
      </div>
      <div className="flex-1 space-y-4 overflow-auto px-6 py-6">
        <div className="h-24 animate-pulse rounded-3xl border border-border/60 bg-card/60" />
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-48 animate-pulse rounded-3xl border border-border/60 bg-card/60" />
          <div className="h-48 animate-pulse rounded-3xl border border-border/60 bg-card/60" />
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { t } = useTranslation();
  const [state, setState] = useState<BootState>({ status: "loading" });
  const bootstrapSecretRef = useRef("");

  const refreshReadyClient = useCallback(
    async (client: TeaiBuilderClient, fallbackSurface: RuntimeSurface) => {
      const boot = await fetchBootstrap("", bootstrapSecretRef.current);
      const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
      const runtimeSurface = boot.runtime_surface
        ? toRuntimeSurface(boot.runtime_surface)
        : fallbackSurface;
      const runtimeHost = createRuntimeHost(runtimeSurface, boot.runtime_capabilities);
      const tokenExpiresAt = bootstrapTokenExpiresAt(boot.expires_in);
      if (runtimeHost.socketFactory) {
        client.updateUrl(url, runtimeHost.socketFactory);
      } else {
        client.updateUrl(url);
      }
      setState((current) =>
        current.status === "ready" && current.client === client
          ? {
              ...current,
              token: boot.token,
              tokenExpiresAt,
              modelName: boot.model_name ?? current.modelName,
              runtimeSurface,
            }
          : current,
      );
      return { token: boot.token, url };
    },
    [],
  );

  const bootstrapWithSecret = useCallback(
    (secret: string) => {
      let cancelled = false;
      (async () => {
        setState({ status: "loading" });
        try {
          const boot = await fetchBootstrap("", secret);
          if (cancelled) return;
          if (secret) saveSecret(secret);
          const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
          const runtimeSurface = toRuntimeSurface(boot.runtime_surface);
          const runtimeHost = createRuntimeHost(runtimeSurface, boot.runtime_capabilities);
          const client = new TeaiBuilderClient({
            url,
            socketFactory: runtimeHost.socketFactory,
            onReauth: async () => {
              try {
                const refreshed = await refreshReadyClient(client, runtimeSurface);
                return refreshed.url;
              } catch {
                return null;
              }
            },
          });
          bootstrapSecretRef.current = secret;
          client.connect();
          setState({
            status: "ready",
            client,
            token: boot.token,
            tokenExpiresAt: bootstrapTokenExpiresAt(boot.expires_in),
            modelName: boot.model_name ?? null,
            runtimeSurface,
          });
        } catch (e) {
          if (cancelled) return;
          const msg = (e as Error).message;
          if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
            setState({ status: "auth", failed: true });
          } else {
            setState({ status: "error", message: msg });
          }
        }
      })();
      return () => {
        cancelled = true;
      };
    },
    [refreshReadyClient],
  );

  useEffect(() => {
    if (state.status !== "ready") return;
    const client = state.client;
    const timer = window.setTimeout(async () => {
      try {
        await refreshReadyClient(client, state.runtimeSurface);
      } catch (e) {
        const msg = (e as Error).message;
        if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
          setState({ status: "auth", failed: true });
        }
      }
    }, tokenRefreshDelayMs(state.tokenExpiresAt));
    return () => window.clearTimeout(timer);
  }, [refreshReadyClient, state]);

  useEffect(() => {
    const saved = loadSavedSecret();
    return bootstrapWithSecret(saved);
  }, [bootstrapWithSecret]);

  if (state.status === "loading") {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 animate-in fade-in-0 duration-300">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/60" />
            </span>
            {t("app.loading.connecting")}
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "auth") {
    return (
      <AuthForm
        failed={!!state.failed}
        onSecret={(s) => bootstrapWithSecret(s)}
      />
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>
    );
  }

  const handleModelNameChange = (modelName: string | null) => {
    setState((current) =>
      current.status === "ready" ? { ...current, modelName } : current,
    );
  };

  const handleLogout = () => {
    if (state.status === "ready") {
      state.client.close();
    }
    clearSavedSecret();
    setState({ status: "auth" });
  };

  const handleNativeEngineRestart = async (): Promise<string> => {
    const hostApi = getHostApi();
    if (!hostApi?.restartEngine) {
      throw new Error("native engine restart is unavailable");
    }
    await hostApi.restartEngine();
    const refreshed = await refreshReadyClient(state.client, state.runtimeSurface);
    return refreshed.token;
  };

  return (
    <ClientProvider
      client={state.client}
      token={state.token}
      modelName={state.modelName}
    >
      <Shell
        runtimeSurface={state.runtimeSurface}
        onModelNameChange={handleModelNameChange}
        onLogout={handleLogout}
        onNativeEngineRestart={handleNativeEngineRestart}
      />
    </ClientProvider>
  );
}

function Shell({
  runtimeSurface,
  onModelNameChange,
  onLogout,
  onNativeEngineRestart,
}: {
  runtimeSurface: RuntimeSurface;
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
}) {
  const { t, i18n } = useTranslation();
  const { client, token } = useClient();
  const { theme, toggle } = useTheme();
  const {
    sessions,
    loading,
    refresh,
    createChat,
    forkChat,
    deleteChat,
    getSessionAutomations,
  } = useSessions();
  const { state: sidebarState, update: updateSidebarState } =
    useSidebarState(sessions, !loading);
  const initialRouteRef = useRef<ShellRoute | null>(null);
  if (!initialRouteRef.current) initialRouteRef.current = readShellRoute();
  const [activeKey, setActiveKey] = useState<string | null>(
    initialRouteRef.current.activeKey,
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    initialRouteRef.current.projectId,
  );
  const [view, setView] = useState<ShellView>(initialRouteRef.current.view);
  const [settingsInitialSection, setSettingsInitialSection] =
    useState<SettingsSectionKey>(initialRouteRef.current.settingsSection);
  const [hostSidebarOpen, setHostSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [hostSidebarPreviewOpen, setHostSidebarPreviewOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sessionSearchOpen, setSessionSearchOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{
    key: string;
    label: string;
    automations?: SessionAutomationJob[];
  } | null>(null);
  const [pendingRename, setPendingRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const [pendingProjectRename, setPendingProjectRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const restartSawDisconnectRef = useRef(false);
  const [restartToast, setRestartToast] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [runningChatIds, setRunningChatIds] = useState<Set<string>>(() => new Set());
  const [completedChatIds, setCompletedChatIds] = useState<Set<string>>(readCompletedRunChatIds);
  const [workspaces, setWorkspaces] = useState<WorkspacesPayload | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const { skills, loading: skillsLoading, loadFailed: skillsLoadFailed } = useSkills(token);
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsPayload | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [draftWorkspaceScope, setDraftWorkspaceScope] =
    useState<WorkspaceScopePayload | null>(null);
  const [workspaceOverrides, setWorkspaceOverrides] =
    useState<Record<string, WorkspaceScopePayload>>({});
  const runningChatIdsRef = useRef<Set<string>>(new Set());
  const activeChatIdRef = useRef<string | null>(null);
  const hostSidebarPreviewCloseTimerRef = useRef<number | null>(null);
  const effectiveRuntimeSurface =
    settingsSnapshot?.surface ?? settingsSnapshot?.runtime_surface ?? runtimeSurface;
  const showHostChrome = effectiveRuntimeSurface === "native";
  const showMainSidebar = view !== "settings";

  const navigate = useCallback(
    (route: ShellRoute, options?: { replace?: boolean }) => {
      setActiveKey(route.activeKey);
      setSelectedProjectId(route.projectId);
      setView(route.view);
      setSettingsInitialSection(route.settingsSection);
      writeShellRoute(route, options?.replace);
    },
    [],
  );

  useEffect(() => {
    const applyRoute = () => {
      const route = readShellRoute();
      setActiveKey(route.activeKey);
      setSelectedProjectId(route.projectId);
      setView(route.view);
      setSettingsInitialSection(route.settingsSection);
      setWorkspaceError(null);
      if (route.view === "chat" && !route.activeKey && !route.projectId) {
        setDraftWorkspaceScope(null);
      }
    };
    window.addEventListener("hashchange", applyRoute);
    return () => window.removeEventListener("hashchange", applyRoute);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) setSettingsSnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) setSettingsSnapshot(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    const warm = () => preloadShellViewModules();
    if (typeof window === "undefined") {
      warm();
      return;
    }
    const browserWindow = window as Window & typeof globalThis & {
      requestIdleCallback?: (
        callback: IdleRequestCallback,
        options?: IdleRequestOptions,
      ) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (typeof browserWindow.requestIdleCallback === "function") {
      const handle = browserWindow.requestIdleCallback(warm, { timeout: 1_500 });
      return () => {
        browserWindow.cancelIdleCallback?.(handle);
      };
    }
    const timer = globalThis.setTimeout(warm, 500);
    return () => globalThis.clearTimeout(timer);
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        hostSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }, [hostSidebarOpen]);

  useEffect(() => {
    writeCompletedRunChatIds(completedChatIds);
  }, [completedChatIds]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);
  const runningChatIdList = useMemo(() => Array.from(runningChatIds), [runningChatIds]);
  const completedChatIdList = useMemo(() => Array.from(completedChatIds), [completedChatIds]);
  const selectedProject = useMemo<ProjectSummary | null>(() => {
    if (!selectedProjectId) return null;
    return projects.find((project) => project.id === selectedProjectId) ?? null;
  }, [projects, selectedProjectId]);
  const selectedProjectScope = useMemo<WorkspaceScopePayload | null>(() => {
    if (!selectedProject) return null;
    return buildProjectScope(selectedProject, workspaces?.default_scope ?? null);
  }, [selectedProject, workspaces?.default_scope]);
  const draftProjectScope = useMemo<WorkspaceScopePayload | null>(
    () => resolveProjectScope(draftWorkspaceScope, workspaces?.default_scope ?? null),
    [draftWorkspaceScope, workspaces?.default_scope],
  );
  const activeChatId = activeSession?.chatId ?? null;
  useEffect(() => {
    activeChatIdRef.current = activeChatId;
    if (!activeChatId) return;
    setCompletedChatIds((current) => {
      if (!current.has(activeChatId)) return current;
      const next = new Set(current);
      next.delete(activeChatId);
      return next;
    });
  }, [activeChatId]);
  const activeWorkspaceScope = useMemo<WorkspaceScopePayload | null>(() => {
    if (activeChatId && workspaceOverrides[activeChatId]) {
      return workspaceOverrides[activeChatId];
    }
    if (activeSession?.workspaceScope) {
      return activeSession.workspaceScope;
    }
    if (selectedProjectScope) {
      return selectedProjectScope;
    }
    return draftProjectScope;
  }, [
    activeChatId,
    activeSession?.workspaceScope,
    selectedProjectScope,
    draftProjectScope,
    workspaceOverrides,
  ]);
  const activeChatRunning = activeChatId ? runningChatIds.has(activeChatId) : false;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const payload = await fetchWorkspaces(token);
      setWorkspaces(payload);
    } catch {
      setWorkspaces(null);
    }
  }, [token]);

  const refreshProjects = useCallback(async () => {
    try {
      const payload = await fetchProjects(token);
      setProjects(payload.projects);
    } catch {
      setProjects([]);
    }
  }, [token]);

  useEffect(() => {
    void refreshWorkspaces();
  }, [refreshWorkspaces]);

  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  useEffect(() => {
    if (loading) return;
    const knownChatIds = new Set(sessions.map((session) => session.chatId));
    setCompletedChatIds((current) => {
      const next = new Set(
        Array.from(current).filter((chatId) => knownChatIds.has(chatId)),
      );
      return next.size === current.size ? current : next;
    });
    setWorkspaceOverrides((current) => {
      const entries = Object.entries(current).filter(([chatId]) => knownChatIds.has(chatId));
      return entries.length === Object.keys(current).length ? current : Object.fromEntries(entries);
    });
  }, [loading, sessions]);

  useEffect(() => {
    if (loading || !activeKey) return;
    if (sessions.some((session) => session.key === activeKey)) return;
    const currentRoute = readShellRoute();
    navigate(
      {
        ...currentRoute,
        activeKey: null,
      },
      { replace: true },
    );
  }, [activeKey, loading, navigate, sessions]);

  useEffect(() => {
    return client.onSessionUpdate((_chatId, _scope, workspaceScope, project) => {
      if (!workspaceScope) return;
      const next = normalizeWorkspaceScope(workspaceScope);
      setWorkspaceOverrides((current) => ({
        ...current,
        [_chatId]: next,
      }));
      setDraftWorkspaceScope(next);
      setWorkspaceError(null);
      if (_chatId === activeChatIdRef.current && project && typeof project.id === "string") {
        setSelectedProjectId(project.id);
        navigate({
          view: "chat",
          activeKey: `websocket:${_chatId}`,
          projectId: project.id,
          settingsSection: "overview",
        }, { replace: true });
      }
      void refreshWorkspaces();
      void refreshProjects();
    });
  }, [client, navigate, refreshProjects, refreshWorkspaces]);

  useEffect(() => {
    return client.onError((error) => {
      if (error.kind !== "workspace_scope_rejected") return;
      setWorkspaceError(error.reason || t("errors.workspaceScopeRejected.body"));
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces, t]);

  useEffect(() => {
    if (loading) return;
    const activeRunIds = sessions
      .filter((session) => typeof session.runStartedAt === "number")
      .map((session) => session.chatId);
    if (activeRunIds.length === 0) return;

    for (const chatId of activeRunIds) {
      client.attach(chatId);
    }
    setRunningChatIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const chatId of activeRunIds) {
        if (!next.has(chatId)) changed = true;
        next.add(chatId);
      }
      if (!changed) return current;
      runningChatIdsRef.current = next;
      return next;
    });
    setCompletedChatIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const chatId of activeRunIds) {
        if (next.delete(chatId)) changed = true;
      }
      return changed ? next : current;
    });
  }, [client, loading, sessions]);

  const clearHostSidebarPreviewCloseTimer = useCallback(() => {
    if (hostSidebarPreviewCloseTimerRef.current === null) return;
    window.clearTimeout(hostSidebarPreviewCloseTimerRef.current);
    hostSidebarPreviewCloseTimerRef.current = null;
  }, []);

  const closeHostSidebarPreview = useCallback(() => {
    clearHostSidebarPreviewCloseTimer();
    setHostSidebarPreviewOpen(false);
  }, [clearHostSidebarPreviewCloseTimer]);

  const openHostSidebarPreview = useCallback(() => {
    if (!showHostChrome || !showMainSidebar || hostSidebarOpen) return;
    clearHostSidebarPreviewCloseTimer();
    setHostSidebarPreviewOpen(true);
  }, [
    clearHostSidebarPreviewCloseTimer,
    hostSidebarOpen,
    showHostChrome,
    showMainSidebar,
  ]);

  const scheduleHostSidebarPreviewClose = useCallback(() => {
    clearHostSidebarPreviewCloseTimer();
    if (!showHostChrome || !showMainSidebar || hostSidebarOpen) {
      setHostSidebarPreviewOpen(false);
      return;
    }
    hostSidebarPreviewCloseTimerRef.current = window.setTimeout(() => {
      setHostSidebarPreviewOpen(false);
      hostSidebarPreviewCloseTimerRef.current = null;
    }, 160);
  }, [
    clearHostSidebarPreviewCloseTimer,
    hostSidebarOpen,
    showHostChrome,
    showMainSidebar,
  ]);

  useEffect(() => {
    return () => clearHostSidebarPreviewCloseTimer();
  }, [clearHostSidebarPreviewCloseTimer]);

  useEffect(() => {
    if (!showHostChrome || !showMainSidebar || hostSidebarOpen) {
      closeHostSidebarPreview();
    }
  }, [
    closeHostSidebarPreview,
    hostSidebarOpen,
    showHostChrome,
    showMainSidebar,
  ]);

  const closeHostSidebar = useCallback(() => {
    closeHostSidebarPreview();
    setHostSidebarOpen(false);
  }, [closeHostSidebarPreview]);

  const openHostSidebar = useCallback(() => {
    closeHostSidebarPreview();
    setHostSidebarOpen(true);
  }, [closeHostSidebarPreview]);

  const toggleHostSidebar = useCallback(() => {
    closeHostSidebarPreview();
    setHostSidebarOpen((v) => !v);
  }, [closeHostSidebarPreview]);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isNativeHost =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isNativeHost) {
      closeHostSidebarPreview();
      setHostSidebarOpen((v) => !v);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, [closeHostSidebarPreview]);

  const applyWorkspaceScope = useCallback(
    (scope: WorkspaceScopePayload) => {
      const next = normalizeWorkspaceScope(scope);
      setWorkspaceError(null);
      if (activeChatId) {
        if (!activeChatRunning) {
          client.setWorkspaceScope(activeChatId, next);
        }
        return;
      }
      setDraftWorkspaceScope(next);
    },
    [activeChatId, activeChatRunning, client],
  );

  const onCreateChat = useCallback(async (workspaceScope?: WorkspaceScopePayload | null) => {
    try {
      const scope = workspaceScope ?? activeWorkspaceScope;
      if (!scope || sameWorkspacePath(scope.project_path, workspaces?.default_scope?.project_path)) {
        setWorkspaceError(t("errors.projectRequired.body"));
        return null;
      }
      const chatId = await createChat(scope);
      navigate({
        view: "chat",
        activeKey: `websocket:${chatId}`,
        projectId:
          selectedProjectId
          ?? selectedProject?.id
          ?? activeSession?.project?.id
          ?? null,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      if (scope) {
        setWorkspaceOverrides((current) => ({
          ...current,
          [chatId]: normalizeWorkspaceScope(scope),
        }));
      }
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      if (e instanceof Error && e.message.startsWith("workspace_scope_rejected:")) {
        const reason = e.message.slice("workspace_scope_rejected:".length).trim();
        setWorkspaceError(reason || t("errors.workspaceScopeRejected.body"));
      }
      return null;
    }
  }, [
    activeSession?.project?.id,
    activeWorkspaceScope,
    createChat,
    navigate,
    selectedProject?.id,
    selectedProjectId,
    t,
    workspaces?.default_scope?.project_path,
  ]);

  const onForkChat = useCallback(async (
    sourceChatId: string,
    beforeUserIndex: number,
  ) => {
    try {
      const sourceSession = sessions.find((session) => session.chatId === sourceChatId);
      const sourceTitle = sourceSession
        ? displayTitle(sourceSession, sidebarState.title_overrides, t("chat.newChat"))
        : t("chat.newChat");
      const chatId = await forkChat(
        sourceChatId,
        beforeUserIndex,
        t("chat.forkTitle", { title: sourceTitle }),
      );
      navigate({
        view: "chat",
        activeKey: `websocket:${chatId}`,
        projectId: sourceSession?.project?.id ?? null,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to fork chat", e);
      return null;
    }
  }, [forkChat, navigate, sessions, sidebarState.title_overrides, t]);

  const onNewChat = useCallback(() => {
    const projectId =
      selectedProjectId
      ?? selectedProject?.id
      ?? activeSession?.project?.id
      ?? null;
    navigate(projectId
      ? {
          view: "chat",
          activeKey: null,
          projectId,
          settingsSection: "overview",
        }
      : defaultShellRoute());
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
    setSessionSearchOpen(false);
    setMobileSidebarOpen(false);
  }, [activeSession?.project?.id, navigate, selectedProject?.id, selectedProjectId]);

  const onNewChatInProject = useCallback(
    (projectPath: string, projectName: string) => {
      const base = workspaces?.default_scope ?? activeWorkspaceScope;
      const trimmed = projectPath.trim();
      if (!base || !trimmed) {
        onNewChat();
        return;
      }
      const matchingProject = projects.find((project) => project.root_path === trimmed);
      navigate({
        view: "chat",
        activeKey: null,
        projectId: matchingProject?.id ?? null,
        settingsSection: "overview",
      });
      setDraftWorkspaceScope(normalizeWorkspaceScope({
        project_path: trimmed,
        project_name: projectName || projectNameFromPath(trimmed),
        access_mode: base.access_mode,
        restrict_to_workspace: base.access_mode === "restricted",
      }));
      setWorkspaceError(null);
      setMobileSidebarOpen(false);
    },
    [activeWorkspaceScope, navigate, onNewChat, projects, workspaces?.default_scope],
  );

  const onOpenProject = useCallback((projectId: string) => {
    navigate({
      view: "chat",
      activeKey: null,
      projectId,
      settingsSection: "overview",
    });
    setWorkspaceError(null);
    setMobileSidebarOpen(false);
  }, [navigate]);

  const onSelectChat = useCallback(
    (key: string) => {
      const selected = sessions.find((session) => session.key === key);
      const selectedChatId = selected?.chatId;
      if (selectedChatId) {
        setCompletedChatIds((current) => {
          if (!current.has(selectedChatId)) return current;
          const next = new Set(current);
          next.delete(selectedChatId);
          return next;
        });
      }
      if (selected?.workspaceScope) {
        setDraftWorkspaceScope(normalizeWorkspaceScope(selected.workspaceScope));
      } else {
        setDraftWorkspaceScope(null);
      }
      setWorkspaceError(null);
      navigate({
        view: "chat",
        activeKey: key,
        projectId: selected?.project?.id ?? null,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
    },
    [navigate, sessions],
  );

  const onTogglePin = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const pinned = new Set(current.pinned_keys);
        if (pinned.has(key)) {
          pinned.delete(key);
        } else {
          pinned.add(key);
        }
        return {
          ...current,
          pinned_keys: Array.from(pinned),
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRename = useCallback((key: string, label: string) => {
    setPendingRename({ key, label });
  }, []);

  const onConfirmRename = useCallback(
    (title: string) => {
      if (!pendingRename) return;
      const key = pendingRename.key;
      setPendingRename(null);
      void updateSidebarState((current) => {
        const titleOverrides = { ...current.title_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          titleOverrides[key] = cleaned;
        } else {
          delete titleOverrides[key];
        }
        return {
          ...current,
          title_overrides: titleOverrides,
        };
      });
    },
    [pendingRename, updateSidebarState],
  );

  const onToggleGroup = useCallback(
    (groupId: string) => {
      void updateSidebarState((current) => {
        const collapsedGroups = { ...current.collapsed_groups };
        if (groupId === "workspace:chats" || groupId === "date:all") {
          if (collapsedGroups[groupId] === false) {
            delete collapsedGroups[groupId];
          } else {
            collapsedGroups[groupId] = false;
          }
          return {
            ...current,
            collapsed_groups: collapsedGroups,
          };
        }
        if (collapsedGroups[groupId]) {
          delete collapsedGroups[groupId];
        } else {
          collapsedGroups[groupId] = true;
        }
        return {
          ...current,
          collapsed_groups: collapsedGroups,
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRenameProject = useCallback((key: string, label: string) => {
    setPendingProjectRename({ key, label });
  }, []);

  const onConfirmProjectRename = useCallback(
    (title: string) => {
      if (!pendingProjectRename) return;
      const key = pendingProjectRename.key;
      setPendingProjectRename(null);
      void updateSidebarState((current) => {
        const projectNameOverrides = { ...current.project_name_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          projectNameOverrides[key] = cleaned;
        } else {
          delete projectNameOverrides[key];
        }
        return {
          ...current,
          project_name_overrides: projectNameOverrides,
        };
      });
    },
    [pendingProjectRename, updateSidebarState],
  );

  const onToggleArchive = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const archived = new Set(current.archived_keys);
        const pinned = current.pinned_keys.filter((item) => item !== key);
        if (archived.has(key)) {
          archived.delete(key);
        } else {
          archived.add(key);
        }
        return {
          ...current,
          pinned_keys: pinned,
          archived_keys: Array.from(archived),
        };
      });
      if (activeKey === key && !sidebarState.archived_keys.includes(key)) {
        const archived = new Set([...sidebarState.archived_keys, key]);
        const next = sessions.find((session) => !archived.has(session.key));
        navigate({
          view: "chat",
          activeKey: next?.key ?? null,
          projectId: next?.project?.id ?? null,
          settingsSection: "overview",
        });
      }
    },
    [activeKey, navigate, sessions, sidebarState.archived_keys, updateSidebarState],
  );

  const onToggleArchived = useCallback(() => {
    void updateSidebarState((current) => ({
      ...current,
      view: {
        ...current.view,
        show_archived: !current.view.show_archived,
      },
    }));
  }, [updateSidebarState]);

  const onOpenSessionSearch = useCallback(() => {
    setMobileSidebarOpen(false);
    setSessionSearchOpen(true);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const commandShiftO =
        (event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey;
      if (commandShiftO && event.key.toLowerCase() === "o") {
        event.preventDefault();
        onNewChat();
        return;
      }
      const plainCommandK =
        (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
      if (!plainCommandK) return;
      if (event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      onOpenSessionSearch();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onNewChat, onOpenSessionSearch]);

  const onSelectSearchResult = useCallback(
    (key: string) => {
      setSessionSearchOpen(false);
      onSelectChat(key);
    },
    [onSelectChat],
  );

  const onOpenSettings = useCallback((section: SettingsSectionKey = "overview") => {
    setSessionSearchOpen(false);
    navigate({ view: "settings", activeKey, projectId: selectedProjectId, settingsSection: section });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate, selectedProjectId]);

  const onOpenModelSettings = useCallback(() => {
    onOpenSettings("models");
  }, [onOpenSettings]);

  const onOpenApps = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "apps", activeKey, projectId: selectedProjectId, settingsSection: "apps" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate, selectedProjectId]);

  const onOpenSkills = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "skills", activeKey, projectId: selectedProjectId, settingsSection: "skills" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate, selectedProjectId]);

  const onOpenWorkflows = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "workflows", activeKey, projectId: selectedProjectId, settingsSection: "overview" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate, selectedProjectId]);

  const onSettingsSectionChange = useCallback(
    (section: SettingsSectionKey) => {
      navigate({
        view: shellViewForSettingsSection(section),
        activeKey,
        projectId: selectedProjectId,
        settingsSection: section,
      });
    },
    [activeKey, navigate, selectedProjectId],
  );

  const onBackToChat = useCallback(() => {
    setMobileSidebarOpen(false);
    const nextKey = (() => {
      if (!activeKey) return null;
      if (sessions.some((session) => session.key === activeKey)) return activeKey;
      return sessions[0]?.key ?? null;
    })();
    navigate({
      view: "chat",
      activeKey: nextKey,
      projectId: selectedProjectId,
      settingsSection: "overview",
    });
  }, [activeKey, navigate, selectedProjectId, sessions]);

  const onRestart = useCallback(() => {
    const chatId = activeSession?.chatId ?? client.defaultChatId;
    if (!chatId) return;
    restartSawDisconnectRef.current = false;
    setIsRestarting(true);
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    client.sendMessage(chatId, "/restart");
  }, [activeSession?.chatId, client]);

  useEffect(() => {
    return client.onRuntimeModelUpdate((modelName) => {
      onModelNameChange(modelName);
    });
  }, [client, onModelNameChange]);

  useEffect(() => {
    return client.onRunStatus((chatId, startedAt) => {
      if (startedAt != null) {
        const nextRunning = new Set(runningChatIdsRef.current);
        nextRunning.add(chatId);
        runningChatIdsRef.current = nextRunning;
        setRunningChatIds(nextRunning);
        setCompletedChatIds((current) => {
          if (!current.has(chatId)) return current;
          const next = new Set(current);
          next.delete(chatId);
          return next;
        });
        return;
      }

      if (!runningChatIdsRef.current.has(chatId)) return;
      const nextRunning = new Set(runningChatIdsRef.current);
      nextRunning.delete(chatId);
      runningChatIdsRef.current = nextRunning;
      setRunningChatIds(nextRunning);
      setCompletedChatIds((current) => {
        const next = new Set(current);
        if (activeChatIdRef.current === chatId) {
          next.delete(chatId);
        } else {
          next.add(chatId);
        }
        return next;
      });
    });
  }, [client]);

  useEffect(() => {
    return client.onStatus((status) => {
      const startedAt = (() => {
        try {
          return Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
        } catch {
          return 0;
        }
      })();
      if (!startedAt) return;
      if (status !== "open") {
        restartSawDisconnectRef.current = true;
        return;
      }
      const elapsedMs = Date.now() - startedAt;
      if (!restartSawDisconnectRef.current && elapsedMs < 1500) return;
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
      } catch {
        // ignore storage errors
      }
      setIsRestarting(false);
      setRestartToast(t("app.restart.completed", { seconds: (elapsedMs / 1000).toFixed(1) }));
      window.setTimeout(() => setRestartToast(null), 3_500);
    });
  }, [client, t]);

  const onTurnEnd = useDeferredTitleRefresh(activeSession, refresh);

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const hasAutomations = (pendingDelete.automations?.length ?? 0) > 0;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ?? sessions[currentIndex - 1]?.key ?? null)
      : activeKey;
    try {
      const result = await deleteChat(
        key,
        hasAutomations ? { deleteAutomations: true } : undefined,
      );
      if (result.blocked_by_automations) {
        setPendingDelete({
          ...pendingDelete,
          automations: result.automations ?? [],
        });
        return;
      }
      setPendingDelete(null);
      if (deletingActive) {
        navigate({
          view: "chat",
          activeKey: fallbackKey,
          projectId: fallbackKey ? (sessions.find((s) => s.key === fallbackKey)?.project?.id ?? null) : selectedProjectId,
          settingsSection: "overview",
        }, { replace: true });
      }
    } catch (e) {
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, navigate, selectedProjectId, sessions]);

  const onRequestDelete = useCallback(async (key: string, label: string) => {
    let automations: SessionAutomationJob[] = [];
    try {
      automations = await getSessionAutomations(key);
    } catch {
      // Delete remains protected by the backend block; prefetch only improves the first prompt.
    }
    setPendingDelete({ key, label, automations });
  }, [getSessionAutomations]);

  const headerTitle = activeSession
    ? sidebarState.title_overrides[activeSession.key] ||
      activeSession.title ||
      deriveTitle(activeSession.preview, t("chat.newChat"))
    : selectedProject?.name ?? t("app.brand");

  useEffect(() => {
    if (view === "settings") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.sidebar.title"),
      });
      return;
    }
    if (view === "apps") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.apps", { defaultValue: "Apps" }),
      });
      return;
    }
    if (view === "skills") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.skills", { defaultValue: "Skills" }),
      });
      return;
    }
    if (view === "workflows") {
      document.title = t("app.documentTitle.chat", {
        title: t("workflowDashboard.title"),
      });
      return;
    }
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : selectedProject
        ? t("app.documentTitle.chat", { title: selectedProject.name })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, selectedProject, t, view]);

  const sidebarSessions = useMemo(() => {
    if (view !== "chat" || !selectedProjectId) return sessions;
    return sessions.filter((session) => session.project?.id === selectedProjectId);
  }, [selectedProjectId, sessions, view]);

  const sidebarProps = {
    sessions: sidebarSessions,
    activeKey,
    loading,
    onNewChat,
    onSelect: onSelectChat,
    onRequestDelete,
    onTogglePin,
    onRequestRename,
    onToggleArchive,
    onToggleGroup,
    onRequestRenameProject,
    onNewChatInProject,
    onOpenProject,
    onOpenSettings,
    onOpenApps,
    onOpenSkills,
    onOpenWorkflows,
    onOpenSearch: onOpenSessionSearch,
    activeUtility: view === "apps" || view === "skills" || view === "workflows" ? view : null,
    onToggleArchived,
    pinnedKeys: sidebarState.pinned_keys,
    archivedKeys: sidebarState.archived_keys,
    titleOverrides: sidebarState.title_overrides,
    projectNameOverrides: sidebarState.project_name_overrides,
    collapsedGroups: sidebarState.collapsed_groups,
    runningChatIds: runningChatIdList,
    completedChatIds: completedChatIdList,
    viewState: sidebarState.view,
    showArchived: sidebarState.view.show_archived,
    archivedCount: sidebarState.archived_keys.length,
    defaultWorkspacePath: workspaces?.default_scope.project_path ?? null,
  };
  const hostSidebarCollapsed = showHostChrome && !hostSidebarOpen;
  const showHostSidebarPreview =
    showMainSidebar && hostSidebarCollapsed && hostSidebarPreviewOpen;
  const hostSidebarFlowWidth = showHostChrome
    ? (hostSidebarOpen ? SIDEBAR_WIDTH : 0)
    : (hostSidebarOpen ? SIDEBAR_WIDTH : SIDEBAR_RAIL_WIDTH);
  const renderHostSidebarFlowContent = !showHostChrome || hostSidebarOpen;

  useEffect(() => {
    document.documentElement.classList.toggle("native-host", showHostChrome);
    return () => {
      document.documentElement.classList.remove("native-host");
    };
  }, [showHostChrome]);

  return (
    <ThemeProvider theme={theme}>
      <div
        className={cn(
          "relative h-full w-full overflow-hidden",
          showHostChrome && "host-window-shell",
        )}
      >
        {showHostChrome ? (
          <HostChrome
            onToggleSidebar={showMainSidebar ? toggleHostSidebar : undefined}
            onSidebarPreviewEnter={openHostSidebarPreview}
            onSidebarPreviewLeave={scheduleHostSidebarPreviewClose}
            sidebarOpen={hostSidebarOpen}
            rightAction={
              view === "chat" ? undefined : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("thread.header.toggleTheme")}
                  onClick={toggle}
                  className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
                >
                  {theme === "dark" ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </Button>
              )
            }
          />
        ) : null}
        <div
          className={cn(
            "relative flex h-full w-full overflow-hidden",
          )}
        >
          {/* Host sidebar: in normal flow, so the thread area width stays honest. */}
          {showMainSidebar ? (
            <aside
              data-testid="host-sidebar-flow"
              className={cn(
                "relative z-20 hidden shrink-0 overflow-hidden lg:block",
                "transition-[width] duration-300 ease-out",
              )}
              style={{
                width: hostSidebarFlowWidth,
              }}
            >
              {renderHostSidebarFlowContent ? (
                <div
                  className={cn(
                    "absolute inset-y-0 left-0 h-full w-full overflow-hidden",
                    showHostChrome
                      ? "host-sidebar-glass"
                      : "bg-sidebar shadow-inner-right",
                  )}
                >
                  <Sidebar
                    {...sidebarProps}
                    collapsed={!showHostChrome && !hostSidebarOpen}
                    hostChromeInset={showHostChrome}
                    onCollapse={closeHostSidebar}
                    onExpand={openHostSidebar}
                  />
                </div>
              ) : null}
            </aside>
          ) : null}

          {showHostSidebarPreview ? (
            <aside
              data-testid="host-sidebar-preview"
              className="absolute inset-y-0 left-0 z-30 hidden overflow-hidden lg:block animate-in fade-in-0 slide-in-from-left-2 duration-150"
              style={{ width: SIDEBAR_WIDTH }}
              onMouseEnter={openHostSidebarPreview}
              onMouseLeave={scheduleHostSidebarPreviewClose}
            >
              <div className="h-full w-full overflow-hidden host-sidebar-glass shadow-2xl">
                <Sidebar
                  {...sidebarProps}
                  hostChromeInset={showHostChrome}
                  onCollapse={closeHostSidebar}
                  onExpand={openHostSidebar}
                />
              </div>
            </aside>
          ) : null}

          {showMainSidebar ? (
            <Sheet
              open={mobileSidebarOpen}
              onOpenChange={(open) => setMobileSidebarOpen(open)}
            >
              <SheetContent
                side="left"
                showCloseButton={false}
                aria-describedby={undefined}
                className="p-0 lg:hidden"
                style={{ width: SIDEBAR_WIDTH, maxWidth: SIDEBAR_WIDTH }}
              >
                <SheetTitle className="sr-only">{t("sidebar.navigation")}</SheetTitle>
                <Sidebar
                  {...sidebarProps}
                  onCollapse={closeMobileSidebar}
                  containActionMenus
                />
              </SheetContent>
            </Sheet>
          ) : null}

          <SessionSearchDialog
            open={sessionSearchOpen}
            onOpenChange={setSessionSearchOpen}
            sessions={sessions}
            activeKey={activeKey}
            loading={loading}
            titleOverrides={sidebarState.title_overrides}
            onSelect={onSelectSearchResult}
          />
        <main
          className={cn(
            "relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background",
            showHostChrome && hostSidebarOpen && "border-l border-border/55",
          )}
        >
            <div
              className={cn(
                "absolute inset-0 flex flex-col",
                view !== "chat" && "invisible pointer-events-none",
              )}
            >
              {selectedProject && !activeSession ? (
                <ProjectOverviewPanel
                  project={selectedProject}
                  onCreateChat={() => {
                    void onCreateChat(selectedProjectScope);
                  }}
                />
              ) : (
                <ThreadShell
                  session={activeSession}
                  title={headerTitle}
                  onToggleSidebar={toggleSidebar}
                  onNewChat={onNewChat}
                  onCreateChat={onCreateChat}
                  onForkChat={onForkChat}
                  onTurnEnd={onTurnEnd}
                  theme={theme}
                  onToggleTheme={toggle}
                  hideSidebarToggleForHostChrome
                  hostChromeTitleInset={hostSidebarCollapsed}
                  hideHeader={false}
                  project={activeSession?.project ?? selectedProject ?? null}
                  workspaceScope={activeWorkspaceScope}
                  workspaceDefaultScope={workspaces?.default_scope ?? null}
                  workspaceControls={workspaces?.controls ?? null}
                  workspaceScopeDisabled={activeChatRunning}
                  workspaceError={workspaceError}
                  onWorkspaceScopeChange={applyWorkspaceScope}
                  settingsSnapshot={settingsSnapshot}
                  onOpenModelSettings={onOpenModelSettings}
                />
              )}
            </div>
            {view !== "chat" && (
              <div className="absolute inset-0 flex flex-col">
                <Suspense
                  fallback={
                    <ShellViewSkeleton
                      title={view === "workflows" ? t("workflowDashboard.title") : t("settings.sidebar.title")}
                      hostChromeInset={showHostChrome}
                    />
                  }
                >
                  {view === "workflows" ? (
                    <WorkflowDashboardView
                      client={client}
                      token={token}
                      sessionKey={activeSession?.key ?? activeKey}
                      sessionTitle={activeSession ? headerTitle : null}
                      theme={theme}
                      onToggleTheme={toggle}
                      onToggleSidebar={toggleSidebar}
                      onBackToChat={onBackToChat}
                      hideSidebarToggleForHostChrome
                      hostChromeTitleInset={hostSidebarCollapsed}
                    />
                  ) : (
                    <SettingsView
                      theme={theme}
                      initialSection={settingsInitialSection}
                      initialSettings={settingsSnapshot}
                      showSidebar={view === "settings"}
                      onToggleTheme={toggle}
                      onBackToChat={onBackToChat}
                      onModelNameChange={onModelNameChange}
                      onSettingsChange={setSettingsSnapshot}
                      skills={skills}
                      skillsLoading={skillsLoading}
                      skillsLoadFailed={skillsLoadFailed}
                      onWorkspaceSettingsChange={refreshWorkspaces}
                      onSectionChange={onSettingsSectionChange}
                      onLogout={onLogout}
                      onRestart={onRestart}
                      onNativeEngineRestart={onNativeEngineRestart}
                      isRestarting={isRestarting}
                      hostChromeInset={showHostChrome}
                    />
                  )}
                </Suspense>
              </div>
            )}
          </main>
        </div>

        <DeleteConfirm
          open={!!pendingDelete}
          title={pendingDelete?.label ?? ""}
          automations={pendingDelete?.automations}
          onCancel={() => setPendingDelete(null)}
          onConfirm={onConfirmDelete}
        />
        <RenameChatDialog
          open={!!pendingRename}
          title={pendingRename?.label ?? ""}
          onCancel={() => setPendingRename(null)}
          onConfirm={onConfirmRename}
        />
        <RenameChatDialog
          open={!!pendingProjectRename}
          title={pendingProjectRename?.label ?? ""}
          dialogTitle={t("chat.renameProjectTitle")}
          description={t("chat.renameProjectDescription")}
          placeholder={t("chat.renameProjectPlaceholder")}
          onCancel={() => setPendingProjectRename(null)}
          onConfirm={onConfirmProjectRename}
        />
        {restartToast ? (
          <div
            role="status"
            className="fixed left-1/2 top-4 z-50 -translate-x-1/2 rounded-full border border-border/70 bg-popover px-4 py-2 text-sm font-medium text-popover-foreground shadow-lg"
          >
            {restartToast}
          </div>
        ) : null}
      </div>
    </ThemeProvider>
  );
}
