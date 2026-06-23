import {
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  Check,
  ChevronDown,
  CircleAlert,
  Eye,
  HardDrive,
  Loader2,
  RotateCcw,
  Search,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { getHostApi } from "@/lib/runtime";
import type { SettingsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { shortWorkspacePath } from "@/lib/workspace";

type StatusTone = "neutral" | "success" | "warning" | "danger";

interface AgentSettingsDraft {
  timezone: string;
  botName: string;
  botIcon: string;
}

interface ChannelSettingsDraft {
  sendProgress: boolean;
  sendToolHints: boolean;
  showReasoning: boolean;
  extractDocumentText: boolean;
  sendMaxRetries: number;
}

export function RuntimeSettingsSection({
  form,
  channelForm,
  settings,
  dirty,
  saving,
  onSave,
  onRestart,
  isRestarting,
  requiresRestartPending,
  onBotNameChange,
  onBotIconChange,
  onTimezoneChange,
  onChannelSendProgressChange,
  onChannelSendToolHintsChange,
  onChannelShowReasoningChange,
  onChannelExtractDocumentTextChange,
  onChannelRetriesChange,
}: {
  form: AgentSettingsDraft;
  channelForm: ChannelSettingsDraft;
  settings: SettingsPayload;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
  requiresRestartPending: boolean;
  onBotNameChange: (value: string) => void;
  onBotIconChange: (value: string) => void;
  onTimezoneChange: (value: string) => void;
  onChannelSendProgressChange: (value: boolean) => void;
  onChannelSendToolHintsChange: (value: boolean) => void;
  onChannelShowReasoningChange: (value: boolean) => void;
  onChannelExtractDocumentTextChange: (value: boolean) => void;
  onChannelRetriesChange: (value: number) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const isNativeHost = getHostApi() !== null || (settings.surface ?? settings.runtime_surface) === "native";
  const restartActionLabel = isNativeHost
    ? tx("app.system.restartEngine", "Restart engine")
    : t("app.system.restart");
  const restartingActionLabel = isNativeHost
    ? tx("app.system.restartingEngine", "Restarting engine...")
    : t("app.system.restarting");
  const [diagnosticsPath, setDiagnosticsPath] = useState<string | null>(null);
  const [hostActionMessage, setHostActionMessage] = useState<{
    target: "logs" | "diagnostics";
    message: string;
  } | null>(null);
  const [hostActionBusy, setHostActionBusy] = useState<"logs" | "diagnostics" | null>(null);
  const hostApi = getHostApi();
  const engineState = isRestarting
    ? tx("settings.values.restartingEngine", "Restarting")
    : settings.apply_state?.status === "pending"
      ? tx("settings.values.pending", "Pending")
      : tx("settings.values.ready", "Ready");

  const runHostAction = async (
    target: "logs" | "diagnostics",
    action: () => Promise<string | void>,
    successMessage: (result: string | void) => string,
    failureMessage: string,
  ) => {
    if (!hostApi) {
      setHostActionMessage({
        target,
        message: tx(
          "settings.status.hostApiUnavailable",
          "Host actions are only available inside the native app.",
        ),
      });
      return;
    }
    setHostActionBusy(target);
    setHostActionMessage(null);
    try {
      const result = await action();
      setHostActionMessage({ target, message: successMessage(result) });
    } catch {
      setHostActionMessage({ target, message: failureMessage });
    } finally {
      setHostActionBusy(null);
    }
  };

  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>{tx("settings.sections.identity", "Identity")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={tx("settings.rows.botName", "Bot name")}
            description={tx(
              "settings.help.botName",
              "Shown wherever teai_builder uses a display name.",
            )}
          >
            <Input
              value={form.botName}
              onChange={(event) => onBotNameChange(event.target.value)}
              className="h-8 w-[220px] rounded-full text-[13px]"
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.botIcon", "Bot icon")}
            description={tx(
              "settings.help.botIcon",
              "Short emoji or text shown with the bot name.",
            )}
          >
            <Input
              value={form.botIcon}
              onChange={(event) => onBotIconChange(event.target.value)}
              className="h-8 w-[120px] rounded-full text-center text-[13px]"
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.timezone", "Timezone")}
            description={tx(
              "settings.help.timezone",
              "Used for schedules and time-aware replies.",
            )}
          >
            <TimezonePicker
              value={form.timezone}
              onChange={onTimezoneChange}
            />
          </SettingsRow>
          <RestartSettingsFooter
            dirty={dirty}
            saving={saving}
            pendingRestart={requiresRestartPending}
            dirtyMessage={
              isNativeHost
                ? tx(
                    "settings.status.hostRestartAfterSaving",
                    "Save changes and teai_builder will restart its engine.",
                  )
                : tx(
                    "settings.status.restartAfterSaving",
                    "Save changes, then restart when ready.",
                  )
            }
            pendingMessage={
              isNativeHost
                ? tx("settings.status.hostRestartPending", "Saved. Restarting engine when ready.")
                : tx("settings.status.savedRestartApply", "Saved. Restart when ready.")
            }
            onSave={onSave}
            onRestart={onRestart}
            isRestarting={isRestarting}
          />
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.channels", "Channels")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={tx("settings.rows.configuredChannels", "Configured channels")}
            description={tx(
              "settings.help.configuredChannels",
              "Shows the channel integrations currently configured for this builder runtime.",
            )}
          >
            <span className="max-w-[320px] truncate text-right text-[13px] text-muted-foreground">
              {settings.channels?.configured?.length
                ? settings.channels.configured.map((channel) => channel.name).join(", ")
                : tx("settings.values.webuiOnly", "websocket")}
            </span>
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.channelSendProgress", "Send progress")}
            description={tx(
              "settings.help.channelSendProgress",
              "Stream progress updates back through active channels while the agent is working.",
            )}
          >
            <ToggleButton
              checked={channelForm.sendProgress}
              onChange={onChannelSendProgressChange}
              ariaLabel={tx("settings.rows.channelSendProgress", "Send progress")}
              label={channelForm.sendProgress ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.channelSendToolHints", "Send tool hints")}
            description={tx(
              "settings.help.channelSendToolHints",
              "Expose lightweight tool-call hints in supported channels during execution.",
            )}
          >
            <ToggleButton
              checked={channelForm.sendToolHints}
              onChange={onChannelSendToolHintsChange}
              ariaLabel={tx("settings.rows.channelSendToolHints", "Send tool hints")}
              label={channelForm.sendToolHints ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.channelShowReasoning", "Show reasoning")}
            description={tx(
              "settings.help.channelShowReasoning",
              "Allow channels that support it to surface model reasoning updates.",
            )}
          >
            <ToggleButton
              checked={channelForm.showReasoning}
              onChange={onChannelShowReasoningChange}
              ariaLabel={tx("settings.rows.channelShowReasoning", "Show reasoning")}
              label={channelForm.showReasoning ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.channelExtractDocumentText", "Extract document text")}
            description={tx(
              "settings.help.channelExtractDocumentText",
              "Extract attachment text before sending channel documents into the model context.",
            )}
          >
            <ToggleButton
              checked={channelForm.extractDocumentText}
              onChange={onChannelExtractDocumentTextChange}
              ariaLabel={tx("settings.rows.channelExtractDocumentText", "Extract document text")}
              label={channelForm.extractDocumentText ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.channelRetries", "Delivery retries")}
            description={tx(
              "settings.help.channelRetries",
              "Retry failed outbound channel deliveries this many times before giving up.",
            )}
          >
            <Input
              type="number"
              min={0}
              max={10}
              value={String(channelForm.sendMaxRetries)}
              onChange={(event) => {
                const parsed = Number.parseInt(event.target.value || "0", 10);
                onChannelRetriesChange(
                  Number.isNaN(parsed) ? 0 : Math.min(10, Math.max(0, parsed)),
                );
              }}
              className="h-8 w-[96px] rounded-full text-right text-[13px]"
            />
          </SettingsRow>
        </SettingsGroup>
      </section>

      {settings.runtime.reliability ? (
        <section aria-label={tx("settings.sections.runtimeHealth", "Runtime health")}>
          <SettingsSectionTitle>
            {tx("settings.sections.runtimeHealth", "Runtime health")}
          </SettingsSectionTitle>
          <div className="grid gap-3 md:grid-cols-3">
            <StatusCard
              icon={Eye}
              title={tx("settings.runtime.telemetry", "Telemetry")}
              badge={
                <StatusBadge tone={settings.runtime.reliability.telemetry.enabled ? "success" : "neutral"}>
                  {settings.runtime.reliability.telemetry.enabled
                    ? tx("settings.values.enabled", "Enabled")
                    : tx("settings.values.disabled", "Disabled")}
                </StatusBadge>
              }
            >
              <div>
                {settings.runtime.reliability.telemetry.enabled
                  ? settings.runtime.reliability.telemetry.local_audit_log
                    ? tx(
                        "settings.runtime.telemetryLocalOnly",
                        "Local-only audit logging is active for runtime events.",
                      )
                    : tx(
                        "settings.runtime.telemetryWithoutAudit",
                        "Telemetry is enabled, but local audit log writing is disabled.",
                      )
                  : tx("settings.runtime.telemetryOff", "Telemetry audit logging is currently off.")}
              </div>
              <StatusMetric
                label={tx("settings.rows.capture", "Capture")}
                value={
                  settings.runtime.reliability.telemetry.capture_usage
                  && settings.runtime.reliability.telemetry.capture_errors
                    ? tx("settings.values.usageAndErrors", "Usage + errors")
                    : settings.runtime.reliability.telemetry.capture_errors
                      ? tx("settings.values.errorsOnly", "Errors only")
                      : settings.runtime.reliability.telemetry.capture_usage
                        ? tx("settings.values.usageOnly", "Usage only")
                        : tx("settings.values.none", "None")
                }
              />
              <StatusMetric
                label={tx("settings.rows.auditPath", "Audit path")}
                value={
                  settings.runtime.reliability.telemetry.path
                    ? shortWorkspacePath(settings.runtime.reliability.telemetry.path)
                    : tx("settings.values.notWriting", "Not writing")
                }
              />
            </StatusCard>
            <StatusCard
              icon={CircleAlert}
              title={tx("settings.runtime.crashReports", "Crash reports")}
              badge={
                <StatusBadge
                  tone={
                    settings.runtime.reliability.crash_reports.pending_count > 0
                      ? "warning"
                      : settings.runtime.reliability.crash_reports.enabled
                        ? "success"
                        : "neutral"
                  }
                >
                  {settings.runtime.reliability.crash_reports.pending_count > 0
                    ? tx("settings.values.attention", "Attention")
                    : settings.runtime.reliability.crash_reports.enabled
                      ? tx("settings.values.armed", "Armed")
                      : tx("settings.values.disabled", "Disabled")}
                </StatusBadge>
              }
            >
              <div>
                {settings.runtime.reliability.crash_reports.pending_count > 0
                  ? t("settings.runtime.pendingCrashReports", {
                      count: settings.runtime.reliability.crash_reports.pending_count,
                      defaultValue:
                        settings.runtime.reliability.crash_reports.pending_count === 1
                          ? "1 pending crash report is waiting for review."
                          : "{{count}} pending crash reports are waiting for review.",
                    })
                  : tx(
                      "settings.runtime.crashReportsRecovered",
                      "New crash reports are stored locally and archived after recovery.",
                    )}
              </div>
              <StatusMetric
                label={tx("settings.rows.pendingReports", "Pending")}
                value={String(settings.runtime.reliability.crash_reports.pending_count)}
              />
              <StatusMetric
                label={tx("settings.rows.archivedReports", "Archived")}
                value={String(settings.runtime.reliability.crash_reports.archived_count)}
              />
            </StatusCard>
            <StatusCard
              icon={HardDrive}
              title={tx("settings.runtime.runtimeLogs", "Runtime logs")}
              badge={<StatusBadge tone="neutral">{tx("settings.values.local", "Local")}</StatusBadge>}
            >
              <div>
                {tx(
                  "settings.runtime.logsHint",
                  "Component logs and operational traces are written under the active instance directory.",
                )}
              </div>
              <StatusMetric
                label={tx("settings.rows.logFile", "Log file")}
                value={shortWorkspacePath(settings.runtime.reliability.logs.path)}
              />
              <StatusMetric
                label={tx("settings.rows.reportStore", "Report store")}
                value={shortWorkspacePath(settings.runtime.reliability.crash_reports.path)}
              />
            </StatusCard>
          </div>
        </section>
      ) : null}

      {isNativeHost ? (
        <section>
          <SettingsSectionTitle>{tx("settings.sections.nativeHost", "Native host")}</SettingsSectionTitle>
          <SettingsGroup>
            <ReadOnlyRow title={tx("settings.rows.engine", "Engine")} value={engineState} />
            {settings.runtime_capabilities?.can_open_logs ? (
              <SettingsRow
                title={tx("settings.rows.logs", "Logs")}
                description={
                  hostActionMessage?.target === "logs"
                    ? hostActionMessage.message
                    : tx("settings.help.logs", "Open the native engine log folder.")
                }
              >
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void runHostAction(
                      "logs",
                      () => hostApi!.openLogs(),
                      () => tx("settings.status.logsOpened", "Opened logs folder."),
                      tx("settings.status.logsOpenFailed", "Could not open logs folder."),
                    )
                  }
                  disabled={hostActionBusy !== null}
                  className="rounded-full"
                >
                  {hostActionBusy === "logs"
                    ? tx("settings.actions.opening", "Opening...")
                    : tx("settings.actions.open", "Open")}
                </Button>
              </SettingsRow>
            ) : null}
            {settings.runtime_capabilities?.can_export_diagnostics ? (
              <SettingsRow
                title={tx("settings.rows.diagnostics", "Diagnostics")}
                description={
                  hostActionMessage?.target === "diagnostics"
                    ? hostActionMessage.message
                    : diagnosticsPath
                      ? diagnosticsPath
                      : tx("settings.help.diagnostics", "Export a small runtime report for support.")
                }
              >
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void runHostAction(
                      "diagnostics",
                      async () => {
                        const path = await hostApi!.exportDiagnostics();
                        setDiagnosticsPath(path);
                        return path;
                      },
                      (path) =>
                        t("settings.status.diagnosticsExported", {
                          path: String(path ?? ""),
                          defaultValue: "Diagnostics exported to {{path}}.",
                        }),
                      tx("settings.status.diagnosticsExportFailed", "Could not export diagnostics."),
                    )
                  }
                  disabled={hostActionBusy !== null}
                  className="rounded-full"
                >
                  {hostActionBusy === "diagnostics"
                    ? tx("settings.actions.exporting", "Exporting...")
                    : tx("settings.actions.export", "Export")}
                </Button>
              </SettingsRow>
            ) : null}
          </SettingsGroup>
        </section>
      ) : null}

      <section>
        <SettingsSectionTitle>{t("settings.sections.system")}</SettingsSectionTitle>
        <SettingsGroup>
          {!isNativeHost ? (
            <ReadOnlyRow
              title={tx("settings.rows.gateway", "Gateway")}
              value={`${settings.runtime.gateway_host}:${settings.runtime.gateway_port}`}
            />
          ) : null}
          <ReadOnlyRow title={t("settings.rows.configPath")} value={settings.runtime.config_path} />
          <ReadOnlyRow
            title={tx("settings.rows.workspacePath", "Default workspace")}
            value={settings.runtime.workspace_path}
          />
          {onRestart && !requiresRestartPending ? (
            <SettingsRow
              title={t("settings.rows.restart")}
              description={t("app.system.restartHint")}
            >
              <Button
                size="sm"
                variant="outline"
                onClick={onRestart}
                disabled={isRestarting}
                className="rounded-full"
              >
                {isRestarting ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                )}
                {isRestarting ? restartingActionLabel : restartActionLabel}
              </Button>
            </SettingsRow>
          ) : null}
        </SettingsGroup>
      </section>
    </div>
  );
}

function TimezonePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (timezone: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [query, setQuery] = useState("");
  const options = useMemo(() => timezoneOptions(value), [value]);
  const filteredOptions = useMemo(() => filterTimezoneOptions(options, query), [options, query]);

  return (
    <DropdownMenu onOpenChange={(open) => !open && setQuery("")}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className={cn(
            "h-8 w-[220px] justify-between rounded-full border-input bg-background px-3 text-[13px] font-normal shadow-none",
            "hover:bg-accent/55 focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          <span className="truncate">{value || tx("settings.timezone.select", "Select timezone")}</span>
          <ChevronDown className="ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[340px] max-w-[calc(100vw-2rem)]">
        <div className="sticky top-0 z-10 bg-popover px-1 pb-1">
          <div className="flex h-9 items-center gap-2 rounded-full border border-input bg-background px-3">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <Input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={tx("settings.timezone.search", "Search timezone")}
              className="h-7 border-0 bg-transparent px-0 text-[13px] shadow-none focus-visible:ring-0"
            />
          </div>
        </div>
        <div
          className="mt-1 max-h-[18rem] overflow-y-auto pr-0.5 scrollbar-thin scrollbar-track-transparent"
          data-testid="timezone-picker-list"
        >
          {filteredOptions.length ? (
            filteredOptions.map((option) => {
              const selected = option.name === value;
              return (
                <DropdownMenuItem
                  key={option.name}
                  onSelect={() => onChange(option.name)}
                  className={cn(
                    "flex h-9 cursor-default items-center justify-between gap-3 rounded-[12px] px-2.5 text-[13px]",
                    "focus:bg-muted/85 focus:text-foreground",
                    selected && "bg-muted/80 text-foreground focus:bg-muted",
                  )}
                >
                  <span className="min-w-0 truncate font-medium text-foreground">{option.name}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-2">
                    <span className="text-[11.5px] font-medium text-muted-foreground/80">
                      {option.offset}
                    </span>
                    {selected ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
                  </span>
                </DropdownMenuItem>
              );
            })
          ) : (
            <div className="px-3 py-5 text-center text-[12px] text-muted-foreground">
              {tx("settings.timezone.empty", "No matching timezones.")}
            </div>
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type TimezoneOption = { name: string; offset: string };

function timezoneOptions(selectedValue: string): TimezoneOption[] {
  const now = new Date();
  const supportedValues = typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : [selectedValue || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"];
  const unique = Array.from(new Set([selectedValue, ...supportedValues].filter(Boolean)));
  return unique.map((name) => ({
    name,
    offset: formatTimezoneOffset(name, now),
  }));
}

function filterTimezoneOptions(options: TimezoneOption[], query: string): TimezoneOption[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return options;
  return options.filter((option) => {
    const haystack = `${option.name} ${option.offset}`.toLowerCase();
    return haystack.includes(normalized);
  });
}

function formatTimezoneOffset(timezone: string, date: Date): string {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    timeZoneName: "shortOffset",
  });
  const part = formatter.formatToParts(date).find((item) => item.type === "timeZoneName")?.value ?? "UTC";
  return part.replace("GMT", "UTC");
}

function StatusBadge({
  tone = "neutral",
  children,
}: {
  tone?: StatusTone;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wide",
        tone === "success" && "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        tone === "warning" && "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
        tone === "danger" && "border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-300",
        tone === "neutral" && "border-border/60 bg-muted/60 text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

function StatusCard({
  icon: Icon,
  title,
  badge,
  children,
}: {
  icon: LucideIcon;
  title: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="rounded-[20px] border border-border/55 bg-card/82 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-2xl bg-muted/80 text-muted-foreground">
            <Icon className="h-4.5 w-4.5" aria-hidden />
          </span>
          <div className="text-[14px] font-semibold text-foreground">{title}</div>
        </div>
        {badge}
      </div>
      <div className="mt-3 space-y-2 text-[12px] leading-5 text-muted-foreground">{children}</div>
    </div>
  );
}

function StatusMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-muted/45 px-3 py-2">
      <span>{label}</span>
      <span className="truncate text-right font-medium text-foreground">{value}</span>
    </div>
  );
}

function SettingsSectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
      {children}
    </h2>
  );
}

function SettingsGroup({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[22px] border border-border/45 bg-card/86 shadow-[0_18px_65px_rgba(15,23,42,0.075)] backdrop-blur-xl dark:border-white/10 dark:shadow-[0_18px_65px_rgba(0,0,0,0.24)]">
      <div className="divide-y divide-border/45">{children}</div>
    </div>
  );
}

function SettingsRow({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-[62px] flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0">
        <div className="text-[14px] font-medium leading-5 text-foreground">{title}</div>
        {description ? (
          <div className="mt-0.5 max-w-[28rem] text-[12px] leading-5 text-muted-foreground">
            {description}
          </div>
        ) : null}
      </div>
      {children ? <div className="shrink-0 sm:ml-6">{children}</div> : null}
    </div>
  );
}

function ReadOnlyRow({
  title,
  value,
  description,
}: {
  title: string;
  value: string;
  description?: string;
}) {
  return (
    <SettingsRow title={title} description={description}>
      <span className="block max-w-[320px] truncate text-right text-[13px] text-muted-foreground">
        {value}
      </span>
    </SettingsRow>
  );
}

function RestartSettingsFooter({
  dirty,
  saving,
  pendingRestart,
  disabled = false,
  message,
  dirtyMessage,
  pendingMessage,
  onSave,
  onRestart,
  isRestarting,
}: {
  dirty: boolean;
  saving: boolean;
  pendingRestart: boolean;
  disabled?: boolean;
  message?: string;
  dirtyMessage?: string;
  pendingMessage?: string;
  onSave: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const isNativeHost = getHostApi() !== null;
  const restartLabel = isNativeHost
    ? tx("app.system.restartEngine", "Restart engine")
    : t("app.system.restart");
  const restartingLabel = isNativeHost
    ? tx("app.system.restartingEngine", "Restarting engine...")
    : t("app.system.restarting");
  const statusMessage =
    message
    ?? (pendingRestart && !dirty
      ? pendingMessage ?? tx("settings.status.savedRestartApply", "Saved. Restart when ready.")
      : dirty
        ? dirtyMessage ?? t("settings.status.unsaved")
        : undefined);
  const statusTone = disabled ? "danger" : dirty || pendingRestart ? "accent" : undefined;

  return (
    <div className="flex min-h-[58px] flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0 text-[13px] leading-5 text-muted-foreground">
        <SettingsStatusMessage tone={statusTone}>{statusMessage}</SettingsStatusMessage>
      </div>
      <div className="flex w-full shrink-0 flex-wrap justify-end gap-2 sm:w-auto">
        {pendingRestart && !dirty && onRestart ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={onRestart}
            disabled={isRestarting}
            className="rounded-full"
          >
            {isRestarting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {isRestarting ? restartingLabel : restartLabel}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          onClick={onSave}
          disabled={!dirty || disabled || saving}
          className="rounded-full"
        >
          {saving ? t("settings.actions.saving") : t("settings.actions.save")}
        </Button>
      </div>
    </div>
  );
}

function SettingsStatusMessage({
  children,
  tone,
}: {
  children?: ReactNode;
  tone?: "accent" | "danger";
}) {
  if (!children) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2",
        tone === "accent" && "font-medium text-blue-600 dark:text-blue-300",
        tone === "danger" && "font-medium text-destructive",
      )}
    >
      {tone ? (
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            tone === "accent"
              && "bg-blue-500 shadow-[0_0_0_3px_rgba(59,130,246,0.14)] dark:bg-blue-400 dark:shadow-[0_0_0_3px_rgba(96,165,250,0.18)]",
            tone === "danger" && "bg-destructive/70",
          )}
          aria-hidden
        />
      ) : null}
      <span>{children}</span>
    </span>
  );
}

function ToggleButton({
  checked,
  onChange,
  ariaLabel,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  ariaLabel?: string;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel ?? label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full p-[2px]",
        "transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        checked
          ? "bg-[#2997FF] shadow-[inset_0_0_0_1px_rgba(0,0,0,0.035)]"
          : "bg-muted shadow-[inset_0_0_0_1px_rgba(0,0,0,0.035)] hover:bg-muted/80",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-[18px] w-[18px] rounded-full bg-background shadow-[0_1px_2px_rgba(0,0,0,0.18),0_2px_7px_rgba(0,0,0,0.11)]",
          "transition-transform duration-200 ease-out",
          checked ? "translate-x-[16px]" : "translate-x-0",
        )}
      />
      <span className="sr-only">{label}</span>
    </button>
  );
}
