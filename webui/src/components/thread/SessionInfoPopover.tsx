import { useEffect, useMemo, useState } from "react";
import {
  CalendarClock,
  CircleAlert,
  CircleDot,
  DatabaseZap,
  GitBranch,
  ListTodo,
  RefreshCcw,
  RotateCcw,
  Save,
} from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSessionAutomationJobs } from "@/hooks/useSessionAutomationJobs";
import { currentLocale } from "@/i18n";
import { fmtDateTime } from "@/lib/format";
import {
  createCheckpoint,
  fetchSessionWorkflowRuns,
  listCheckpoints,
  restoreCheckpoint,
} from "@/lib/api";
import type {
  CheckpointSummary,
  SessionAutomationJob,
  WorkflowRunSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const RELATIVE_THRESHOLDS: [number, Intl.RelativeTimeFormatUnit][] = [
  [60, "second"],
  [60, "minute"],
  [24, "hour"],
  [7, "day"],
  [4.345, "week"],
  [12, "month"],
  [Number.POSITIVE_INFINITY, "year"],
];

interface SessionInfoPopoverProps {
  sessionKey: string;
  token: string;
  title: string;
}

export function SessionInfoPopover({ sessionKey, token, title }: SessionInfoPopoverProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const { jobs, loading, loadFailed, now } = useSessionAutomationJobs(open, token, sessionKey);
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRunSummary[]>([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointSummary[]>([]);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeLoadFailed, setRuntimeLoadFailed] = useState(false);
  const [savingCheckpoint, setSavingCheckpoint] = useState(false);
  const [restoringCheckpointId, setRestoringCheckpointId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let loadedOnce = false;

    const refresh = async (showLoading = false) => {
      if (showLoading) {
        setRuntimeLoading(true);
        setRuntimeLoadFailed(false);
      }
      try {
        const [runsPayload, checkpointsPayload] = await Promise.all([
          fetchSessionWorkflowRuns(token, sessionKey),
          listCheckpoints(token, sessionKey),
        ]);
        if (cancelled) return;
        setWorkflowRuns(runsPayload.items);
        setCheckpoints(checkpointsPayload.items);
        setRuntimeLoadFailed(false);
        loadedOnce = true;
      } catch {
        if (!cancelled && !loadedOnce) setRuntimeLoadFailed(true);
      } finally {
        if (!cancelled && showLoading) setRuntimeLoading(false);
      }
    };

    void refresh(true);
    const refreshId = window.setInterval(() => void refresh(false), 3000);
    const refreshOnFocus = () => {
      if (document.visibilityState !== "hidden") void refresh(false);
    };
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearInterval(refreshId);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshOnFocus);
    };
  }, [open, sessionKey, token]);

  const handleSaveCheckpoint = async () => {
    setSavingCheckpoint(true);
    try {
      await createCheckpoint(token, sessionKey);
      const next = await listCheckpoints(token, sessionKey);
      setCheckpoints(next.items);
      setRuntimeLoadFailed(false);
    } catch {
      setRuntimeLoadFailed(true);
    } finally {
      setSavingCheckpoint(false);
    }
  };

  const handleRestoreCheckpoint = async (checkpointId: string) => {
    setRestoringCheckpointId(checkpointId);
    try {
      await restoreCheckpoint(token, sessionKey, checkpointId);
    } finally {
      setRestoringCheckpointId((current) => (current === checkpointId ? null : current));
    }
  };

  const automationContent = loading ? (
    <div className="flex items-center gap-2 rounded-[16px] bg-muted/45 px-3 py-3 text-[12.5px] text-muted-foreground">
      <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
      {t("thread.sessionInfo.loading")}
    </div>
  ) : loadFailed ? (
    <div className="flex items-center gap-2 rounded-[16px] bg-destructive/10 px-3 py-3 text-[12.5px] text-destructive">
      <CircleAlert className="h-3.5 w-3.5" />
      {t("thread.sessionInfo.loadFailed")}
    </div>
  ) : jobs.length ? (
    <div className="space-y-1.5">
      {jobs.map((job) => (
        <AutomationRow key={job.id} job={job} now={now} />
      ))}
    </div>
  ) : (
    <div className="rounded-[16px] bg-muted/35 px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
      {t("thread.sessionInfo.empty")}
    </div>
  );
  const runtimeStatus = runtimeLoading ? (
    <div className="flex items-center gap-2 rounded-[16px] bg-muted/45 px-3 py-3 text-[12.5px] text-muted-foreground">
      <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
      {t("thread.sessionInfo.runtimeLoading", { defaultValue: "Loading workflow activity..." })}
    </div>
  ) : runtimeLoadFailed ? (
    <div className="flex items-center gap-2 rounded-[16px] bg-destructive/10 px-3 py-3 text-[12.5px] text-destructive">
      <CircleAlert className="h-3.5 w-3.5" />
      {t("thread.sessionInfo.runtimeLoadFailed", { defaultValue: "Could not load workflow activity." })}
    </div>
  ) : null;
  const workflowRows = workflowRuns.length ? (
    <div className="space-y-1.5">
      {workflowRuns.map((run) => (
        <WorkflowRunRow key={run.run_id} run={run} />
      ))}
    </div>
  ) : (
    <div className="rounded-[16px] bg-muted/35 px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
      {t("thread.sessionInfo.workflowEmpty", { defaultValue: "No workflow runs in this session yet." })}
    </div>
  );
  const checkpointRows = checkpoints.length ? (
    <div className="space-y-1.5">
      {checkpoints.map((checkpoint) => (
        <CheckpointRow
          key={checkpoint.checkpoint_id}
          checkpoint={checkpoint}
          restoring={restoringCheckpointId === checkpoint.checkpoint_id}
          onRestore={handleRestoreCheckpoint}
        />
      ))}
    </div>
  ) : (
    <div className="rounded-[16px] bg-muted/35 px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
      {t("thread.sessionInfo.checkpointEmpty", { defaultValue: "No checkpoints in this session yet." })}
    </div>
  );
  const workflowCountLabel = useMemo(
    () => t("thread.sessionInfo.count", { count: workflowRuns.length }),
    [t, workflowRuns.length],
  );
  const checkpointCountLabel = useMemo(
    () => t("thread.sessionInfo.count", { count: checkpoints.length }),
    [checkpoints.length, t],
  );

  return (
    <DropdownMenu modal={false} open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.sessionInfo")}
          className={cn(
            "host-no-drag h-8 w-8 rounded-full text-muted-foreground/85",
            "hover:bg-accent/40 hover:text-foreground",
          )}
        >
          <ListTodo className="h-4 w-4 stroke-[1.75]" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={8}
        className="w-[min(23rem,calc(100vw-1.5rem))] rounded-[24px] p-0"
      >
        <div className="space-y-3 px-4 py-3.5">
          <div className="min-w-0">
            <div className="text-[12px] font-normal text-muted-foreground/75">
              {t("thread.sessionInfo.title")}
            </div>
            <div className="mt-0.5 truncate text-[14px] font-medium text-foreground">
              {title || t("thread.sessionInfo.untitled")}
            </div>
          </div>

          <div className="h-px bg-border/45" />

          <SectionHeader
            icon={<CalendarClock className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80" />}
            label={t("thread.sessionInfo.automations")}
            countLabel={t("thread.sessionInfo.count", { count: jobs.length })}
          />
          {automationContent}

          <div className="h-px bg-border/45" />

          <SectionHeader
            icon={<GitBranch className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80" />}
            label={t("thread.sessionInfo.workflows", { defaultValue: "Workflow runs" })}
            countLabel={workflowCountLabel}
          />
          {runtimeStatus}
          {!runtimeStatus ? workflowRows : null}

          <div className="h-px bg-border/45" />

          <SectionHeader
            icon={<DatabaseZap className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80" />}
            label={t("thread.sessionInfo.checkpoints", { defaultValue: "Checkpoints" })}
            countLabel={checkpointCountLabel}
            action={(
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 rounded-full px-2 text-[11px]"
                disabled={savingCheckpoint}
                onClick={handleSaveCheckpoint}
              >
                {savingCheckpoint ? (
                  <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                {t("thread.sessionInfo.saveCheckpoint", { defaultValue: "Save" })}
              </Button>
            )}
          />
          {runtimeStatus}
          {!runtimeStatus ? checkpointRows : null}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SectionHeader({
  icon,
  label,
  countLabel,
  action,
}: {
  icon: React.ReactNode;
  label: string;
  countLabel: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <span className="truncate text-[13px] font-medium text-foreground">
          {label}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {action}
        <span className="rounded-full bg-muted/70 px-2 py-0.5 text-[11px] text-muted-foreground">
          {countLabel}
        </span>
      </div>
    </div>
  );
}

function WorkflowRunRow({ run }: { run: WorkflowRunSummary }) {
  const { t } = useTranslation("common");
  const stateClass = workflowStateClassName(run.state);

  return (
    <div className="rounded-[16px] px-3 py-2.5 transition-colors hover:bg-muted/40">
      <div className="flex items-start gap-2.5">
        <CircleDot className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", stateClass)} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[13px] font-medium text-foreground">
              {run.workflow_id}
            </span>
            <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
              {run.state}
            </span>
          </div>
          <div className="mt-1 text-[12px] leading-snug text-muted-foreground">
            {run.current_step
              ? t("thread.sessionInfo.workflowCurrentStep", {
                  defaultValue: "Current step: {{step}}",
                  step: run.current_step,
                })
              : t("thread.sessionInfo.workflowProgress", {
                  defaultValue: "{{done}} / {{total}} steps complete",
                  done: run.completed_steps ?? 0,
                  total: run.step_count ?? 0,
                })}
          </div>
          {run.error ? (
            <div className="mt-1 line-clamp-2 text-[11.5px] text-destructive">
              {run.error}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function workflowStateClassName(state: string): string {
  switch (state) {
    case "completed":
      return "text-emerald-500";
    case "failed":
      return "text-destructive";
    case "cancelled":
      return "text-amber-500";
    default:
      return "text-muted-foreground";
  }
}

function CheckpointRow({
  checkpoint,
  restoring,
  onRestore,
}: {
  checkpoint: CheckpointSummary;
  restoring: boolean;
  onRestore: (checkpointId: string) => void;
}) {
  const { t } = useTranslation("common");
  const locale = currentLocale();
  const subtitle = [
    checkpoint.workflow_id ? `workflow ${checkpoint.workflow_id}` : null,
    checkpoint.step_id ? `step ${checkpoint.step_id}` : null,
    checkpoint.label ?? null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="rounded-[16px] px-3 py-2.5 transition-colors hover:bg-muted/40">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] font-medium text-foreground">
              {checkpoint.checkpoint_id}
            </span>
            {checkpoint.kind ? (
              <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
                {checkpoint.kind}
              </span>
            ) : null}
          </div>
          <div className="mt-1 text-[11.5px] text-muted-foreground/80">
            {fmtDateTime(checkpoint.created_at * 1000, locale)}
          </div>
          {subtitle ? (
            <div className="mt-1 line-clamp-2 text-[11.5px] text-muted-foreground">
              {subtitle}
            </div>
          ) : null}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 shrink-0 rounded-full px-2 text-[11px]"
          disabled={restoring}
          onClick={() => onRestore(checkpoint.checkpoint_id)}
        >
          {restoring ? (
            <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
          )}
          {t("thread.sessionInfo.restoreCheckpoint", { defaultValue: "Restore" })}
        </Button>
      </div>
    </div>
  );
}

function AutomationRow({ job, now }: { job: SessionAutomationJob; now: number }) {
  const { t } = useTranslation("common");
  const schedule = formatSchedule(job, t);
  const nextRun = formatNextRun(job, t, now);
  const statusClass = job.enabled
    ? job.state.last_status === "error"
      ? "bg-destructive"
      : "bg-emerald-500"
    : "bg-muted-foreground/35";

  return (
    <div className="rounded-[16px] px-3 py-2.5 transition-colors hover:bg-muted/40">
      <div className="flex items-start gap-2.5">
        <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", statusClass)} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[13px] font-medium text-foreground">{job.name}</span>
            {!job.enabled ? (
              <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
                {t("thread.sessionInfo.disabled")}
              </span>
            ) : null}
          </div>
          <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-muted-foreground">
            {job.payload.message}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground/80">
            <span>{schedule}</span>
            <span aria-hidden>·</span>
            <span title={nextRun.title}>{nextRun.label}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatSchedule(job: SessionAutomationJob, t: TFunction) {
  const locale = currentLocale();
  if (job.schedule.kind === "at" && job.schedule.at_ms) {
    return t("thread.sessionInfo.schedule.at", { time: fmtDateTime(job.schedule.at_ms, locale) });
  }
  if (job.schedule.kind === "every" && job.schedule.every_ms) {
    return t("thread.sessionInfo.schedule.every", {
      duration: formatDuration(job.schedule.every_ms, locale),
    });
  }
  if (job.schedule.kind === "cron" && job.schedule.expr) {
    return job.schedule.tz
      ? t("thread.sessionInfo.schedule.cronWithTz", {
          expr: job.schedule.expr,
          tz: job.schedule.tz,
        })
      : t("thread.sessionInfo.schedule.cron", { expr: job.schedule.expr });
  }
  return t("thread.sessionInfo.schedule.unknown");
}

function formatNextRun(job: SessionAutomationJob, t: TFunction, now: number) {
  const locale = currentLocale();
  if (!job.enabled) {
    return { label: t("thread.sessionInfo.next.disabled"), title: "" };
  }
  if (job.state.pending) {
    return { label: t("thread.sessionInfo.next.pending"), title: "" };
  }
  const next = job.state.next_run_at_ms;
  if (!next) {
    return { label: t("thread.sessionInfo.next.none"), title: "" };
  }
  return {
    label: t("thread.sessionInfo.next.label", { time: relativeTimeFrom(next, now, locale) }),
    title: fmtDateTime(next, locale),
  };
}

function relativeTimeFrom(value: number, now: number, locale: string): string {
  let delta = (value - now) / 1000;
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [step, unit] of RELATIVE_THRESHOLDS) {
    if (Math.abs(delta) < step) {
      return formatter.format(Math.round(delta), unit);
    }
    delta /= step;
  }
  return formatter.format(Math.round(delta), "year");
}

function formatDuration(ms: number, locale: string): string {
  const units: Array<[Intl.NumberFormatOptions["unit"], number]> = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
    ["second", 1000],
  ];
  for (const [unit, size] of units) {
    if (ms >= size && ms % size === 0) {
      return new Intl.NumberFormat(locale, {
        style: "unit",
        unit,
        unitDisplay: "long",
        maximumFractionDigits: 0,
      }).format(ms / size);
    }
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: "minute",
    unitDisplay: "long",
    maximumFractionDigits: 1,
  }).format(ms / 60_000);
}
