import type {
  CheckpointRebuildPayload,
  ChatSummary,
  CliAppsPayload,
  FilePreviewPayload,
  ImageGenerationSettingsUpdate,
  McpPresetsPayload,
  ModelConfigurationCreate,
  ModelConfigurationUpdate,
  NetworkSafetySettingsUpdate,
  ProjectBootstrapPayload,
  ProviderModelsPayload,
  ProjectsPayload,
  ProviderSettingsUpdate,
  SessionDeleteResult,
  SessionAutomationsPayload,
  SettingsPayload,
  SettingsUpdate,
  SidebarStatePayload,
  SkillDetail,
  SkillsPayload,
  ToolsPayload,
  SlashCommand,
  TranscriptionSettingsUpdate,
  WebSearchSettingsUpdate,
  WorkspacesPayload,
  WebuiThreadPersistedPayload,
  WorkspaceContentSearchPayload,
  WorkspaceProblemsPayload,
  WorkspaceReferenceSearchPayload,
  WorkspaceScopePayload,
  WorkspaceAccessMode,
  WorkspaceSearchPayload,
  WorkspaceSymbolSearchPayload,
  WorkspaceTreePayload,
} from "./types";
import { sanitizeAssistantVisibleContent, sanitizePreviewText } from "./assistantContent";
import { fetchWithTimeout } from "./http";

const API_READ_TIMEOUT_MS = 20_000;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  url: string,
  token: string,
  init?: RequestInit,
  timeoutMs: number = 0,
): Promise<T> {
  const res = await fetchWithTimeout(
    url,
    {
      ...(init ?? {}),
      headers: {
        ...(init?.headers ?? {}),
        Authorization: `Bearer ${token}`,
      },
      credentials: "same-origin",
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = typeof res.text === "function" ? (await res.text()).trim() : "";
    throw new ApiError(res.status, text || `HTTP ${res.status}`);
  }
  const contentType = res.headers?.get?.("content-type") ?? "";
  if (contentType && !contentType.toLowerCase().includes("application/json")) {
    const text = typeof res.text === "function" ? await res.text() : "";
    const isHtml = text.trimStart().toLowerCase().startsWith("<!doctype");
    throw new ApiError(
      res.status,
      isHtml
        ? "Gateway returned WebUI HTML instead of JSON. Restart teai_builder gateway and try again."
        : "Gateway returned a non-JSON response.",
    );
  }
  return (await res.json()) as T;
}

function mcpValuesHeader(values: Record<string, unknown>): HeadersInit | undefined {
  const payload: Record<string, unknown> = {};
  Object.entries(values).forEach(([key, value]) => {
    if (value === null || value === undefined) return;
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed) payload[key] = trimmed;
      return;
    }
    payload[key] = value;
  });
  if (!Object.keys(payload).length) return undefined;
  return { "X-TeaiBuilder-MCP-Values": JSON.stringify(payload) };
}

function splitKey(key: string): { channel: string; chatId: string } {
  const idx = key.indexOf(":");
  if (idx === -1) return { channel: "", chatId: key };
  return { channel: key.slice(0, idx), chatId: key.slice(idx + 1) };
}

export async function listSessions(
  token: string,
  base: string = "",
): Promise<ChatSummary[]> {
  type Row = {
    key: string;
    created_at: string | null;
    updated_at: string | null;
    title?: string;
    preview?: string;
    run_started_at?: number | null;
    workspace_scope?: WorkspaceScopePayload | null;
    project?: import("./types").ProjectSummary | null;
  };
  const body = await request<{ sessions: Row[] }>(
    `${base}/api/sessions`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
  return body.sessions.map((s) => ({
    key: s.key,
    ...splitKey(s.key),
    createdAt: s.created_at,
    updatedAt: s.updated_at,
    title: sanitizeAssistantVisibleContent(s.title ?? ""),
    preview: sanitizePreviewText(s.preview ?? ""),
    runStartedAt: s.run_started_at ?? null,
    workspaceScope: s.workspace_scope ?? null,
    project: s.project ?? null,
  }));
}

/** Disk-backed WebUI display thread snapshot (separate from agent session). */
export interface FetchWebuiThreadOptions {
  limit?: number;
  direction?: "latest";
  before?: string | null;
}

export async function fetchWebuiThread(
  token: string,
  key: string,
  optionsOrBase?: FetchWebuiThreadOptions | string,
  base: string = "",
): Promise<WebuiThreadPersistedPayload | null> {
  const options = typeof optionsOrBase === "string" ? undefined : optionsOrBase;
  const resolvedBase = typeof optionsOrBase === "string" ? optionsOrBase : base;
  const params = new URLSearchParams();
  if (options?.limit !== undefined) params.set("limit", String(options.limit));
  if (options?.direction) params.set("direction", options.direction);
  if (options?.before) params.set("before", options.before);
  const query = params.toString();
  const suffix = query ? `?${query}` : "";
  const url = `${resolvedBase}/api/sessions/${encodeURIComponent(key)}/webui-thread${suffix}`;
  const res = await fetchWithTimeout(url, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "same-origin",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return (await res.json()) as WebuiThreadPersistedPayload;
}

export async function fetchFilePreview(
  token: string,
  key: string,
  path: string,
  base: string = "",
): Promise<FilePreviewPayload> {
  const query = new URLSearchParams();
  query.set("path", path);
  return request<FilePreviewPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/file-preview?${query}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchFileSymbols(
  token: string,
  key: string,
  path: string,
  base: string = "",
): Promise<import("./types").FileSymbolsPayload> {
  const query = new URLSearchParams();
  query.set("path", path);
  return request<import("./types").FileSymbolsPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/file-symbols?${query}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceTree(
  token: string,
  key: string,
  base: string = "",
): Promise<WorkspaceTreePayload> {
  return request<WorkspaceTreePayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/workspace-tree`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceSearch(
  token: string,
  key: string,
  query: string,
  limit: number = 40,
  base: string = "",
): Promise<WorkspaceSearchPayload> {
  const params = new URLSearchParams();
  params.set("q", query);
  params.set("limit", String(limit));
  return request<WorkspaceSearchPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/workspace-search?${params.toString()}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceContentSearch(
  token: string,
  key: string,
  query: string,
  limit: number = 40,
  base: string = "",
): Promise<WorkspaceContentSearchPayload> {
  const params = new URLSearchParams();
  params.set("q", query);
  params.set("limit", String(limit));
  return request<WorkspaceContentSearchPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/workspace-content-search?${params.toString()}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceSymbolSearch(
  token: string,
  key: string,
  query: string,
  limit: number = 40,
  base: string = "",
): Promise<WorkspaceSymbolSearchPayload> {
  const params = new URLSearchParams();
  params.set("q", query);
  params.set("limit", String(limit));
  return request<WorkspaceSymbolSearchPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/workspace-symbol-search?${params.toString()}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceReferenceSearch(
  token: string,
  key: string,
  query: string,
  limit: number = 40,
  base: string = "",
): Promise<WorkspaceReferenceSearchPayload> {
  const params = new URLSearchParams();
  params.set("q", query);
  params.set("limit", String(limit));
  return request<WorkspaceReferenceSearchPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/workspace-reference-search?${params.toString()}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceProblems(
  token: string,
  key: string,
  query: string,
  limit: number = 40,
  base: string = "",
): Promise<WorkspaceProblemsPayload> {
  const params = new URLSearchParams();
  params.set("q", query);
  params.set("limit", String(limit));
  return request<WorkspaceProblemsPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/workspace-problems?${params.toString()}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function rebuildCheckpoint(
  token: string,
  sessionKey: string,
  checkpointId: string,
  base: string = "",
): Promise<CheckpointRebuildPayload> {
  return request<CheckpointRebuildPayload>(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/checkpoints/${encodeURIComponent(checkpointId)}/rebuild`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSessionAutomations(
  token: string,
  key: string,
  base: string = "",
): Promise<SessionAutomationsPayload> {
  return request<SessionAutomationsPayload>(
    `${base}/api/sessions/${encodeURIComponent(key)}/automations`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSessionWorkflowRuns(
  token: string,
  key: string,
  base: string = "",
): Promise<{ items: Array<{
  run_id: string;
  workflow_id: string;
  goal_id: string;
  state: string;
  current_step?: string | null;
  updated_at: number;
  finished_at?: number | null;
  error?: string | null;
  step_count?: number;
  completed_steps?: number;
}> }> {
  return request(
    `${base}/api/sessions/${encodeURIComponent(key)}/workflow-runs`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSessionWorkflowRunDetail(
  token: string,
  key: string,
  runId: string,
  base: string = "",
): Promise<{ run: {
  run_id: string;
  workflow_id: string;
  goal_id: string;
  state: string;
  current_step?: string | null;
  started_at: number;
  updated_at: number;
  finished_at?: number | null;
  error?: string | null;
  step_count?: number;
  completed_steps?: number;
  cancel_requested: boolean;
  step_results: Record<string, unknown>;
  status_history: Array<{ state: string; at: number; detail?: string | null }>;
  checkpoints: Array<{
    step_id?: string | null;
    saved_at?: number | null;
    checkpoint_id?: string | null;
    result_keys?: string[];
  }>;
  step_states: Array<{
    step_id: string;
    name: string;
    state: string;
    attempts: number;
    started_at?: number | null;
    finished_at?: number | null;
    error?: string | null;
    output?: unknown;
  }>;
} }> {
  return request(
    `${base}/api/sessions/${encodeURIComponent(key)}/workflow-runs/${encodeURIComponent(runId)}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function controlSessionWorkflowRun(
  token: string,
  key: string,
  runId: string,
  action: "resume" | "cancel",
  base: string = "",
): Promise<{ accepted: boolean; action: string; command: string }> {
  return request(
    `${base}/api/sessions/${encodeURIComponent(key)}/workflow-runs/${encodeURIComponent(runId)}/${action}`,
    token,
    { method: "POST" },
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSkills(
  token: string,
  base: string = "",
): Promise<SkillsPayload> {
  return request<SkillsPayload>(
    `${base}/api/webui/skills`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSkillDetail(
  token: string,
  name: string,
  base: string = "",
): Promise<SkillDetail> {
  return request<SkillDetail>(
    `${base}/api/webui/skills/${encodeURIComponent(name)}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchTools(
  token: string,
  base: string = "",
): Promise<ToolsPayload> {
  return request<ToolsPayload>(
    `${base}/api/webui/tools`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function deleteSession(
  token: string,
  key: string,
  optionsOrBase?: { deleteAutomations?: boolean } | string,
  base: string = "",
): Promise<SessionDeleteResult> {
  const options = typeof optionsOrBase === "string" ? undefined : optionsOrBase;
  const resolvedBase = typeof optionsOrBase === "string" ? optionsOrBase : base;
  const query = new URLSearchParams();
  if (options?.deleteAutomations) query.set("delete_automations", "true");
  const suffix = query.toString() ? `?${query}` : "";
  return request<SessionDeleteResult>(
    `${resolvedBase}/api/sessions/${encodeURIComponent(key)}/delete${suffix}`,
    token,
  );
}

export async function fetchSettings(
  token: string,
  base: string = "",
): Promise<SettingsPayload> {
  return request<SettingsPayload>(
    `${base}/api/settings`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchSettingsUsage(
  token: string,
  base: string = "",
): Promise<NonNullable<SettingsPayload["usage"]>> {
  return request<NonNullable<SettingsPayload["usage"]>>(
    `${base}/api/settings/usage`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export interface VersionCheckResult {
  updateAvailable: {
    currentVersion: string;
    latestVersion: string;
    pypiUrl?: string;
  } | null;
}

export async function checkVersion(
  token: string,
  base: string = "",
): Promise<VersionCheckResult> {
  return request<VersionCheckResult>(
    `${base}/api/settings/version-check`,
    token,
    undefined,
    10_000,
  );
}

export async function fetchWorkspaces(
  token: string,
  base: string = "",
): Promise<WorkspacesPayload> {
  return request<WorkspacesPayload>(
    `${base}/api/workspaces`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchProjects(
  token: string,
  base: string = "",
): Promise<ProjectsPayload> {
  return request<ProjectsPayload>(
    `${base}/api/projects`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchWorkspaceFolders(
  token: string,
  base: string = "",
): Promise<{ folders: { path: string; name: string }[] }> {
  return request<{ folders: { path: string; name: string }[] }>(
    `${base}/api/workspace-folders`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function bootstrapProject(
  token: string,
  name: string,
  accessMode: WorkspaceAccessMode,
  base: string = "",
): Promise<ProjectBootstrapPayload> {
  const query = new URLSearchParams();
  query.set("name", name);
  query.set("access_mode", accessMode);
  return request<ProjectBootstrapPayload>(
    `${base}/api/projects/bootstrap?${query}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchCliApps(
  token: string,
  base: string = "",
): Promise<CliAppsPayload> {
  return request<CliAppsPayload>(
    `${base}/api/settings/cli-apps`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function runCliAppAction(
  token: string,
  action: "install" | "update" | "uninstall" | "test",
  name: string,
  base: string = "",
): Promise<CliAppsPayload> {
  const query = new URLSearchParams();
  query.set("name", name);
  return request<CliAppsPayload>(`${base}/api/settings/cli-apps/${action}?${query}`, token);
}

export async function fetchMcpPresets(
  token: string,
  base: string = "",
): Promise<McpPresetsPayload> {
  return request<McpPresetsPayload>(
    `${base}/api/settings/mcp-presets`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function fetchProviderModels(
  token: string,
  provider: string,
  base: string = "",
): Promise<ProviderModelsPayload> {
  const query = new URLSearchParams();
  query.set("provider", provider);
  return request<ProviderModelsPayload>(
    `${base}/api/settings/provider-models?${query}`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function runMcpPresetAction(
  token: string,
  action: "enable" | "remove" | "test",
  name: string,
  values: Record<string, string> = {},
  base: string = "",
): Promise<McpPresetsPayload> {
  const query = new URLSearchParams();
  query.set("name", name);
  return request<McpPresetsPayload>(
    `${base}/api/settings/mcp-presets/${action}?${query}`,
    token,
    { headers: mcpValuesHeader(values) },
  );
}

export async function saveCustomMcpServer(
  token: string,
  values: Record<string, string>,
  base: string = "",
): Promise<McpPresetsPayload> {
  return request<McpPresetsPayload>(
    `${base}/api/settings/mcp-presets/custom`,
    token,
    { headers: mcpValuesHeader(values) },
  );
}

export async function importMcpConfig(
  token: string,
  config: string,
  base: string = "",
): Promise<McpPresetsPayload> {
  return request<McpPresetsPayload>(
    `${base}/api/settings/mcp-presets/import`,
    token,
    { headers: mcpValuesHeader({ config }) },
  );
}

export async function updateMcpServerTools(
  token: string,
  name: string,
  enabledTools: string[],
  base: string = "",
): Promise<McpPresetsPayload> {
  return request<McpPresetsPayload>(
    `${base}/api/settings/mcp-presets/tools`,
    token,
    { headers: mcpValuesHeader({ name, enabled_tools: enabledTools }) },
  );
}

export async function listSlashCommands(
  token: string,
  base: string = "",
): Promise<SlashCommand[]> {
  type Row = {
    command: string;
    title: string;
    description: string;
    icon: string;
    arg_hint?: string;
  };
  const body = await request<{ commands: Row[] }>(
    `${base}/api/commands`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
  return body.commands
    .filter((command) => !["/stop", "/restart"].includes(command.command))
    .map((command) => ({
      command: command.command,
      title: command.title,
      description: command.description,
      icon: command.icon,
      argHint: command.arg_hint ?? "",
    }));
}

export async function fetchSidebarState(
  token: string,
  base: string = "",
): Promise<SidebarStatePayload> {
  return request<SidebarStatePayload>(
    `${base}/api/webui/sidebar-state`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function updateSidebarState(
  token: string,
  state: SidebarStatePayload,
  base: string = "",
): Promise<SidebarStatePayload> {
  const query = new URLSearchParams();
  query.set("state", JSON.stringify(state));
  return request<SidebarStatePayload>(
    `${base}/api/webui/sidebar-state/update?${query}`,
    token,
  );
}

export async function updateSettings(
  token: string,
  update: SettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  if (update.modelPreset !== undefined) {
    query.set("model_preset", update.modelPreset ?? "default");
  }
  if (update.model !== undefined) query.set("model", update.model);
  if (update.provider !== undefined) query.set("provider", update.provider);
  if (update.contextWindowTokens !== undefined) {
    query.set("context_window_tokens", String(update.contextWindowTokens));
  }
  if (update.timezone !== undefined) query.set("timezone", update.timezone);
  if (update.botName !== undefined) query.set("bot_name", update.botName);
  if (update.botIcon !== undefined) query.set("bot_icon", update.botIcon);
  if (update.toolHintMaxLength !== undefined) {
    query.set("tool_hint_max_length", String(update.toolHintMaxLength));
  }
  if (update.channelSendProgress !== undefined) {
    query.set("channel_send_progress", String(update.channelSendProgress));
  }
  if (update.channelSendToolHints !== undefined) {
    query.set("channel_send_tool_hints", String(update.channelSendToolHints));
  }
  if (update.channelShowReasoning !== undefined) {
    query.set("channel_show_reasoning", String(update.channelShowReasoning));
  }
  if (update.channelExtractDocumentText !== undefined) {
    query.set("channel_extract_document_text", String(update.channelExtractDocumentText));
  }
  if (update.channelSendMaxRetries !== undefined) {
    query.set("channel_send_max_retries", String(update.channelSendMaxRetries));
  }
  return request<SettingsPayload>(`${base}/api/settings/update?${query}`, token);
}

export async function createModelConfiguration(
  token: string,
  configuration: ModelConfigurationCreate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  if (configuration.name !== undefined) query.set("name", configuration.name);
  query.set("label", configuration.label);
  query.set("provider", configuration.provider);
  query.set("model", configuration.model);
  return request<SettingsPayload>(
    `${base}/api/settings/model-configurations/create?${query}`,
    token,
  );
}

export async function updateModelConfiguration(
  token: string,
  configuration: ModelConfigurationUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("name", configuration.name);
  if (configuration.label !== undefined) query.set("label", configuration.label);
  if (configuration.provider !== undefined) query.set("provider", configuration.provider);
  if (configuration.model !== undefined) query.set("model", configuration.model);
  if (configuration.contextWindowTokens !== undefined) {
    query.set("context_window_tokens", String(configuration.contextWindowTokens));
  }
  return request<SettingsPayload>(
    `${base}/api/settings/model-configurations/update?${query}`,
    token,
  );
}

export async function updateProviderSettings(
  token: string,
  update: ProviderSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("provider", update.provider);
  if (update.apiKey !== undefined) query.set("api_key", update.apiKey);
  if (update.apiBase !== undefined) query.set("api_base", update.apiBase);
  if (update.apiType !== undefined) query.set("api_type", update.apiType);
  return request<SettingsPayload>(
    `${base}/api/settings/provider/update?${query}`,
    token,
  );
}

export async function loginProviderOAuth(
  token: string,
  provider: string,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("provider", provider);
  return request<SettingsPayload>(
    `${base}/api/settings/provider/oauth-login?${query}`,
    token,
  );
}

export async function logoutProviderOAuth(
  token: string,
  provider: string,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("provider", provider);
  return request<SettingsPayload>(
    `${base}/api/settings/provider/oauth-logout?${query}`,
    token,
  );
}

export async function updateWebSearchSettings(
  token: string,
  update: WebSearchSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("provider", update.provider);
  if (update.apiKey !== undefined) query.set("api_key", update.apiKey);
  if (update.baseUrl !== undefined) query.set("base_url", update.baseUrl);
  if (update.maxResults !== undefined) query.set("max_results", String(update.maxResults));
  if (update.timeout !== undefined) query.set("timeout", String(update.timeout));
  if (update.useJinaReader !== undefined) {
    query.set("use_jina_reader", String(update.useJinaReader));
  }
  return request<SettingsPayload>(
    `${base}/api/settings/web-search/update?${query}`,
    token,
  );
}

export async function updateNetworkSafetySettings(
  token: string,
  update: NetworkSafetySettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("webui_allow_local_service_access", String(update.webuiAllowLocalServiceAccess));
  query.set("webui_default_access_mode", update.webuiDefaultAccessMode);
  return request<SettingsPayload>(
    `${base}/api/settings/network-safety/update?${query}`,
    token,
  );
}

export async function updateImageGenerationSettings(
  token: string,
  update: ImageGenerationSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("enabled", String(update.enabled));
  query.set("provider", update.provider);
  query.set("model", update.model);
  query.set("default_aspect_ratio", update.defaultAspectRatio);
  query.set("default_image_size", update.defaultImageSize);
  query.set("max_images_per_turn", String(update.maxImagesPerTurn));
  return request<SettingsPayload>(
    `${base}/api/settings/image-generation/update?${query}`,
    token,
  );
}

export async function updateTranscriptionSettings(
  token: string,
  update: TranscriptionSettingsUpdate,
  base: string = "",
): Promise<SettingsPayload> {
  const query = new URLSearchParams();
  query.set("enabled", String(update.enabled));
  query.set("provider", update.provider);
  query.set("model", update.model);
  query.set("language", update.language);
  query.set("max_duration_sec", String(update.maxDurationSec));
  query.set("max_upload_mb", String(update.maxUploadMb));
  return request<SettingsPayload>(
    `${base}/api/settings/transcription/update?${query}`,
    token,
  );
}

export async function listWorkflows(
  token: string,
  base: string = "",
): Promise<{ workflows: Array<{ workflow_id: string; name: string; description?: string }> }> {
  return request<{ workflows: Array<{ workflow_id: string; name: string; description?: string }> }>(
    `${base}/api/workflows`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function createCheckpoint(
  token: string,
  sessionKey: string,
  base: string = "",
): Promise<{ checkpoint_id: string }> {
  return request<{ checkpoint_id: string }>(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/checkpoints`,
    token,
    { method: "POST" },
  );
}

export async function listCheckpoints(
  token: string,
  sessionKey: string,
  base: string = "",
): Promise<{ items: Array<{
  checkpoint_id: string;
  created_at: number;
  kind?: string;
  message_count?: number;
  workflow_id?: string | null;
  run_id?: string | null;
  step_id?: string | null;
  label?: string | null;
}> }> {
  return request(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/checkpoints`,
    token,
    undefined,
    API_READ_TIMEOUT_MS,
  );
}

export async function restoreCheckpoint(
  token: string,
  sessionKey: string,
  checkpointId: string,
  base: string = "",
): Promise<{ restored: boolean }> {
  return request<{ restored: boolean }>(
    `${base}/api/sessions/${encodeURIComponent(sessionKey)}/checkpoints/${encodeURIComponent(checkpointId)}/restore`,
    token,
    { method: "POST" },
  );
}
