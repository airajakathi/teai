import { type Dispatch, type ReactNode, type SetStateAction } from "react";
import {
  Layers,
  Loader2,
  RotateCcw,
  Server,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { getHostApi } from "@/lib/runtime";
import type {
  NetworkSafetySettingsUpdate,
  SettingsPayload,
  WebuiDefaultAccessMode,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { shortWorkspacePath } from "@/lib/workspace";

type StatusTone = "neutral" | "success" | "warning" | "danger";

export function AdvancedSettingsSection({
  form,
  settings,
  dirty,
  saving,
  requiresRestartPending,
  isNativeHostSurface,
  onChangeForm,
  onSave,
  onRestart,
  isRestarting,
}: {
  form: NetworkSafetySettingsUpdate;
  settings: SettingsPayload;
  dirty: boolean;
  saving: boolean;
  requiresRestartPending: boolean;
  isNativeHostSurface: boolean;
  onChangeForm: Dispatch<SetStateAction<NetworkSafetySettingsUpdate>>;
  onSave: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const sandbox = settings.advanced.workspace_sandbox;
  const sandboxMeta = sandboxLevelMeta(sandbox);
  const permissionSummary = toolPermissionSummary(settings);
  const activeProfile =
    settings.tool_governance?.profiles.find((profile) => profile.active)
    ?? settings.tool_governance?.profiles.find(
      (profile) => profile.name === settings.tool_governance?.active_profile,
    )
    ?? null;

  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>
          {isNativeHostSurface
            ? tx("settings.sections.hostSafety", "App safety")
            : tx("settings.sections.webuiSafety", "Web safety")}
        </SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={tx("settings.rows.localServiceAccess", "Local Service Access")}
            description={tx(
              isNativeHostSurface
                ? "settings.help.localServiceAccessNative"
                : "settings.help.localServiceAccess",
              isNativeHostSurface
                ? "Allow Full Access shell commands to reach services on this Mac."
                : "Allow Full Access shell commands to reach localhost services.",
            )}
          >
            <ToggleButton
              checked={form.webuiAllowLocalServiceAccess}
              onChange={(webuiAllowLocalServiceAccess) =>
                onChangeForm((prev) => ({ ...prev, webuiAllowLocalServiceAccess }))
              }
              ariaLabel={tx("settings.rows.localServiceAccess", "Local Service Access")}
              label={form.webuiAllowLocalServiceAccess ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.webuiDefaultAccess", "Default access")}
            description={tx(
              isNativeHostSurface
                ? "settings.help.webuiDefaultAccessNative"
                : "settings.help.webuiDefaultAccess",
              isNativeHostSurface
                ? "Used by native chats without a project-specific permission."
                : "Used by web chats without a project-specific permission.",
            )}
          >
            <SegmentedControl
              value={form.webuiDefaultAccessMode}
              options={[
                {
                  value: "default",
                  label: tx("settings.values.defaultPermission", "Default Permission"),
                },
                { value: "full", label: tx("settings.values.fullAccess", "Full Access") },
              ]}
              onChange={(webuiDefaultAccessMode) =>
                onChangeForm((prev) => ({
                  ...prev,
                  webuiDefaultAccessMode:
                    webuiDefaultAccessMode as WebuiDefaultAccessMode,
                }))
              }
            />
          </SettingsRow>
          <RestartSettingsFooter
            dirty={dirty}
            saving={saving}
            pendingRestart={requiresRestartPending}
            onSave={onSave}
            onRestart={onRestart}
            isRestarting={isRestarting}
          />
        </SettingsGroup>
      </section>

      <section aria-label={tx("settings.sections.runtimeSafety", "Runtime safety")}>
        <SettingsSectionTitle>
          {tx("settings.sections.runtimeSafety", "Runtime safety")}
        </SettingsSectionTitle>
        <div className="grid gap-3 md:grid-cols-3">
          <StatusCard
            icon={ShieldCheck}
            title={tx("settings.runtime.workspaceSandbox", "Workspace sandbox")}
            badge={<StatusBadge tone={sandboxMeta.tone}>{sandboxMeta.label}</StatusBadge>}
          >
            <div>
              {sandbox?.summary
                ?? tx("settings.runtime.sandboxUnknown", "Sandbox status is unavailable.")}
            </div>
            <StatusMetric
              label={tx("settings.rows.provider", "Provider")}
              value={sandbox?.provider_label ?? tx("settings.values.none", "None")}
            />
            <StatusMetric
              label={tx("settings.rows.workspace", "Workspace")}
              value={shortWorkspacePath(
                sandbox?.workspace_root ?? settings.runtime.workspace_path,
              )}
            />
          </StatusCard>
          <StatusCard
            icon={Server}
            title={tx("settings.runtime.execSafety", "Exec safety")}
            badge={
              <StatusBadge
                tone={
                  settings.advanced.exec_enabled
                    ? settings.advanced.exec_strict_sandbox
                      ? "success"
                      : "warning"
                    : "neutral"
                }
              >
                {!settings.advanced.exec_enabled
                  ? tx("settings.values.disabled", "Disabled")
                  : settings.advanced.exec_strict_sandbox
                    ? tx("settings.values.failClosed", "Fail closed")
                    : tx("settings.values.fallbackAllowed", "Fallback allowed")}
              </StatusBadge>
            }
          >
            <div>
              {!settings.advanced.exec_enabled
                ? tx(
                    "settings.runtime.execDisabled",
                    "Shell execution is disabled for this runtime.",
                  )
                : sandbox?.level === "degraded"
                  ? tx(
                      "settings.runtime.execBlockedBySandbox",
                      "Exec commands are blocked until the configured sandbox backend becomes available.",
                    )
                  : settings.advanced.exec_strict_sandbox
                    ? tx(
                        "settings.runtime.execStrict",
                        "Configured sandboxing must be available before exec commands are allowed to run.",
                      )
                    : tx(
                        "settings.runtime.execFallback",
                        "Exec can fall back to application-level guards if the host sandbox is unavailable.",
                      )}
            </div>
            <StatusMetric
              label={tx("settings.rows.sandboxBackend", "Sandbox backend")}
              value={settings.advanced.exec_sandbox ?? tx("settings.values.none", "None")}
            />
            <StatusMetric
              label={tx("settings.rows.backendAvailability", "Backend availability")}
              value={
                sandbox?.exec_backend
                  ? sandbox.exec_backend_available
                    ? tx("settings.values.available", "Available")
                    : tx("settings.values.unavailable", "Unavailable")
                  : tx("settings.values.notConfigured", "Not configured")
              }
            />
          </StatusCard>
          <StatusCard
            icon={Layers}
            title={tx("settings.runtime.toolGovernance", "Tool governance")}
            badge={
              <StatusBadge
                tone={
                  permissionSummary.deny > 0 || permissionSummary.confirm > 0
                    ? "success"
                    : "neutral"
                }
              >
                {settings.tool_governance?.active_profile
                  ?? tx("settings.values.default", "Default")}
              </StatusBadge>
            }
          >
            <div>
              {activeProfile?.description
                ? activeProfile.description
                : tx(
                    "settings.runtime.toolGovernanceHint",
                    "Profiles decide which tools exist; permissions decide whether a tool is allowed, confirmed, or denied.",
                  )}
            </div>
            <StatusMetric
              label={tx("settings.rows.permissionRules", "Permission rules")}
              value={String(permissionSummary.total)}
            />
            <StatusMetric
              label={tx("settings.rows.reviewedCalls", "Review required")}
              value={String(permissionSummary.confirm)}
            />
            <StatusMetric
              label={tx("settings.rows.deniedCalls", "Denied")}
              value={String(permissionSummary.deny)}
            />
          </StatusCard>
        </div>
      </section>

      <p className="max-w-3xl px-1 text-sm leading-6 text-muted-foreground">
        {tx(
          "settings.help.securityManagedControls",
          "Web fetches always protect local, private, and metadata services. Core channel safety stays in config.json.",
        )}
      </p>
    </div>
  );
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
        tone === "success"
          && "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        tone === "warning"
          && "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
        tone === "danger"
          && "border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-300",
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
      <div className="mt-3 space-y-2 text-[12px] leading-5 text-muted-foreground">
        {children}
      </div>
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

function sandboxLevelMeta(
  status: NonNullable<SettingsPayload["advanced"]["workspace_sandbox"]> | undefined,
): { label: string; tone: StatusTone } {
  if (!status) return { label: "Unknown", tone: "neutral" };
  switch (status.level) {
    case "system":
      return { label: "System enforced", tone: "success" };
    case "process":
      return { label: "Process enforced", tone: "success" };
    case "degraded":
      return { label: "Degraded", tone: "danger" };
    case "application":
      return { label: "App guards", tone: "warning" };
    case "off":
      return { label: "Off", tone: "neutral" };
    default:
      return { label: status.level, tone: status.enforced ? "success" : "warning" };
  }
}

function toolPermissionSummary(settings: SettingsPayload): {
  total: number;
  confirm: number;
  deny: number;
} {
  const permissions = settings.tool_governance?.permissions ?? {};
  return Object.values(permissions).reduce(
    (acc, mode) => {
      acc.total += 1;
      if (mode === "confirm") acc.confirm += 1;
      if (mode === "deny") acc.deny += 1;
      return acc;
    },
    { total: 0, confirm: 0, deny: 0 },
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

function SegmentedControl({
  value,
  options,
  onChange,
}: {
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="inline-flex h-8 items-center rounded-full bg-muted p-0.5 text-[12px] font-medium text-muted-foreground">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-full px-3 py-1 transition-colors",
            value === option.value && "bg-background text-foreground shadow-sm",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
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
