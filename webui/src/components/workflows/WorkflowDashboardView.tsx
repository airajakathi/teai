import { useCallback, useEffect, useMemo, useState } from "react";
import {
  DatabaseZap,
  GitBranch,
  ListFilter,
  RefreshCcw,
  RotateCcw,
  Save,
  SquareTerminal,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { Button } from "@/components/ui/button";
import type { TeaiBuilderClient } from "@/lib/teai_builder-client";
import {
  controlSessionWorkflowRun,
  createCheckpoint,
  fetchSessionWorkflowRuns,
  fetchSessionWorkflowRunDetail,
  listCheckpoints,
  listWorkflows,
  rebuildCheckpoint,
  restoreCheckpoint,
} from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { currentLocale } from "@/i18n";
import type {
  CheckpointSummary,
  InboundEvent,
  WorkflowRunDetail,
  WorkflowRunLivePayload,
  WorkflowRunSummary,
  WorkflowSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface WorkflowDashboardViewProps {
  client?: Pick<TeaiBuilderClient, "onRunStatus" | "onChat"> | null;
  token: string;
  sessionKey: string | null;
  sessionTitle: string | null;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onToggleSidebar: () => void;
  onBackToChat: () => void;
  hideSidebarToggleForHostChrome?: boolean;
  hostChromeTitleInset?: boolean;
}

export function WorkflowDashboardView({
  client = null,
  token,
  sessionKey,
  sessionTitle,
  theme,
  onToggleTheme,
  onToggleSidebar,
  onBackToChat,
  hideSidebarToggleForHostChrome = false,
  hostChromeTitleInset = false,
}: WorkflowDashboardViewProps) {
  const { t } = useTranslation("common");
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointSummary[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>("all");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<WorkflowRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingCheckpoint, setSavingCheckpoint] = useState(false);
  const [restoringCheckpointId, setRestoringCheckpointId] = useState<string | null>(null);
  const [runAction, setRunAction] = useState<"resume" | "cancel" | null>(null);
  const [rebuildSummary, setRebuildSummary] = useState<string | null>(null);
  const [rebuildLoadingId, setRebuildLoadingId] = useState<string | null>(null);
  const [rebuildCheckpointId, setRebuildCheckpointId] = useState<string | null>(null);
  const [rebuildCheckpointItem, setRebuildCheckpointItem] = useState<CheckpointSummary | null>(null);
  const [liveNotice, setLiveNotice] = useState<string | null>(null);

  const activeChatId = useMemo(() => {
    if (!sessionKey?.startsWith("websocket:")) return null;
    return sessionKey.slice("websocket:".length);
  }, [sessionKey]);

  const refresh = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setError(null);
    try {
      const workflowsPromise = listWorkflows(token);
      const runsPromise = sessionKey
        ? fetchSessionWorkflowRuns(token, sessionKey)
        : Promise.resolve({ items: [] as WorkflowRunSummary[] });
      const checkpointsPromise = sessionKey
        ? listCheckpoints(token, sessionKey)
        : Promise.resolve({ items: [] as CheckpointSummary[] });
      const [workflowPayload, runsPayload, checkpointsPayload] = await Promise.all([
        workflowsPromise,
        runsPromise,
        checkpointsPromise,
      ]);
      setWorkflows(workflowPayload.workflows);
      setRuns(runsPayload.items);
      setCheckpoints(checkpointsPayload.items);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : t("workflowDashboard.loadFailed"),
      );
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [sessionKey, t, token]);

  useEffect(() => {
    void refresh(true);
  }, [sessionKey, token]);

  useEffect(() => {
    if (!client || !activeChatId) return;
    return client.onRunStatus((chatId) => {
      if (chatId !== activeChatId) return;
      void refresh(false);
      if (selectedRunId) {
        void fetchSessionWorkflowRunDetail(token, sessionKey!, selectedRunId)
          .then((payload) => setSelectedRunDetail(payload.run))
          .catch(() => {
            // keep previous detail if transient refresh fails
          });
      }
    });
  }, [activeChatId, client, refresh, selectedRunId, sessionKey, token]);

  useEffect(() => {
    if (!client || !activeChatId) return;
    return client.onChat(activeChatId, (ev: InboundEvent) => {
      const update = parseWorkflowRunUpdate(ev);
      if (!update) return;
      setRuns((current) => upsertWorkflowRunSummary(current, toWorkflowRunSummary(update)));
      if (selectedRunId === update.run_id) {
        setSelectedRunDetail((current) => {
          const previousState = current?.state;
          const next = toWorkflowRunDetail(update);
          if (
            previousState !== next.state
            && ["completed", "failed", "cancelled"].includes(next.state)
          ) {
            setLiveNotice(t("workflowDashboard.liveUpdate", { state: next.state }));
          }
          return next;
        });
      }
    });
  }, [activeChatId, client, selectedRunId, t]);

  const filteredRuns = useMemo(
    () => runs.filter((run) => selectedWorkflowId === "all" || run.workflow_id === selectedWorkflowId),
    [runs, selectedWorkflowId],
  );
  const filteredCheckpoints = useMemo(
    () => checkpoints.filter(
      (checkpoint) => selectedWorkflowId === "all" || checkpoint.workflow_id === selectedWorkflowId,
    ),
    [checkpoints, selectedWorkflowId],
  );
  const selectedRun = useMemo(() => {
    if (!filteredRuns.length) return null;
    return filteredRuns.find((run) => run.run_id === selectedRunId) ?? filteredRuns[0];
  }, [filteredRuns, selectedRunId]);

  useEffect(() => {
    setSelectedRunId((current) => {
      if (!filteredRuns.length) return null;
      if (current && filteredRuns.some((run) => run.run_id === current)) return current;
      return filteredRuns[0]?.run_id ?? null;
    });
  }, [filteredRuns]);

  useEffect(() => {
    setLiveNotice(null);
  }, [selectedRunId]);

  useEffect(() => {
    if (!sessionKey || !selectedRun?.run_id) {
      setSelectedRunDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void fetchSessionWorkflowRunDetail(token, sessionKey, selectedRun.run_id)
      .then((payload) => {
        if (!cancelled) setSelectedRunDetail(payload.run);
      })
      .catch((cause) => {
        if (!cancelled) {
          setSelectedRunDetail(null);
          setError(
            cause instanceof Error
              ? cause.message
              : t("workflowDashboard.loadFailed"),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRun?.run_id, sessionKey, t, token]);

  useEffect(() => {
    const runState = selectedRunDetail?.state ?? selectedRun?.state;
    if (!sessionKey || !selectedRun?.run_id || runState !== "running") return;
    const timer = window.setInterval(() => {
      void refresh(false);
      void fetchSessionWorkflowRunDetail(token, sessionKey, selectedRun.run_id)
        .then((payload) => setSelectedRunDetail(payload.run))
        .catch(() => {
          // ignore transient detail refresh failures during polling
        });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refresh, selectedRun?.run_id, selectedRun?.state, selectedRunDetail?.state, sessionKey, token]);

  const workflowCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const run of runs) {
      counts.set(run.workflow_id, (counts.get(run.workflow_id) ?? 0) + 1);
    }
    return counts;
  }, [runs]);

  const focusCheckpointContext = useCallback(async (checkpoint: CheckpointSummary) => {
    if (checkpoint.workflow_id) {
      setSelectedWorkflowId(checkpoint.workflow_id);
    }
    if (!sessionKey || !checkpoint.run_id) return;
    setSelectedRunId(checkpoint.run_id);
    try {
      const payload = await fetchSessionWorkflowRunDetail(token, sessionKey, checkpoint.run_id);
      setRuns((current) => upsertWorkflowRunSummary(current, payload.run));
      setSelectedRunDetail(payload.run);
    } catch {
      // Keep rebuild guidance visible even if the linked run is no longer available.
    }
  }, [sessionKey, token]);

  const handleSaveCheckpoint = async () => {
    if (!sessionKey) return;
    setSavingCheckpoint(true);
    try {
      await createCheckpoint(token, sessionKey);
      await refresh(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("workflowDashboard.checkpointSaveFailed"));
    } finally {
      setSavingCheckpoint(false);
    }
  };

  const handleRestoreCheckpoint = async (checkpointId: string) => {
    if (!sessionKey) return;
    setRestoringCheckpointId(checkpointId);
    try {
      await restoreCheckpoint(token, sessionKey, checkpointId);
      await refresh(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("workflowDashboard.checkpointRestoreFailed"));
    } finally {
      setRestoringCheckpointId((current) => (current === checkpointId ? null : current));
    }
  };

  const handleRunAction = async (action: "resume" | "cancel") => {
    if (!sessionKey || !selectedRun) return;
    setRunAction(action);
    try {
      await controlSessionWorkflowRun(token, sessionKey, selectedRun.run_id, action);
      await refresh(false);
      const payload = await fetchSessionWorkflowRunDetail(token, sessionKey, selectedRun.run_id);
      setSelectedRunDetail(payload.run);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("workflowDashboard.actionFailed"));
    } finally {
      setRunAction(null);
    }
  };

  const handleRebuildCheckpoint = async (checkpointId: string) => {
    if (!sessionKey) return;
    setRebuildLoadingId(checkpointId);
    try {
      const checkpointSummary = checkpoints.find((item) => item.checkpoint_id === checkpointId) ?? null;
      const payload = await rebuildCheckpoint(token, sessionKey, checkpointId);
      setRebuildSummary(payload.summary);
      const sourceCheckpoint = payload.checkpoint ?? checkpointSummary;
      setRebuildCheckpointItem(sourceCheckpoint ?? null);
      setRebuildCheckpointId(sourceCheckpoint?.checkpoint_id ?? checkpointId);
      if (sourceCheckpoint) {
        await focusCheckpointContext(sourceCheckpoint);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("workflowDashboard.rebuildFailed"));
    } finally {
      setRebuildLoadingId((current) => (current === checkpointId ? null : current));
    }
  };

  const highlightedCheckpoint = useMemo(
    () => checkpoints.find((checkpoint) => checkpoint.checkpoint_id === rebuildCheckpointId)
      ?? rebuildCheckpointItem,
    [checkpoints, rebuildCheckpointId, rebuildCheckpointItem],
  );
  const effectiveSelectedRunState = selectedRunDetail?.state ?? selectedRun?.state ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <ThreadHeader
        title={t("workflowDashboard.title")}
        onToggleSidebar={onToggleSidebar}
        theme={theme}
        onToggleTheme={onToggleTheme}
        hideSidebarToggleForHostChrome={hideSidebarToggleForHostChrome}
        hostChromeTitleInset={hostChromeTitleInset}
        promptNavigatorAction={(
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 rounded-full px-3 text-[12px]"
            onClick={onBackToChat}
          >
            {t("settings.backToChat")}
          </Button>
        )}
      />

      <div className="mx-auto flex w-full max-w-7xl min-h-0 flex-1 flex-col gap-4 px-4 pb-6 pt-2 lg:px-6">
        <section className="grid gap-3 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-2xl border border-border/65 bg-card/85 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h1 className="text-lg font-semibold text-foreground">
                  {t("workflowDashboard.title")}
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  {sessionKey
                    ? t("workflowDashboard.sessionScope", {
                        title: sessionTitle ?? sessionKey,
                      })
                    : t("workflowDashboard.noSession")}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 rounded-full px-3 text-[12px]"
                onClick={() => void refresh(true)}
              >
                <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
                {t("workflowDashboard.refresh")}
              </Button>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <FilterChip
                active={selectedWorkflowId === "all"}
                label={t("workflowDashboard.filters.all")}
                count={runs.length}
                onClick={() => setSelectedWorkflowId("all")}
              />
              {workflows.map((workflow) => (
                <FilterChip
                  key={workflow.workflow_id}
                  active={selectedWorkflowId === workflow.workflow_id}
                  label={workflow.name}
                  count={workflowCounts.get(workflow.workflow_id) ?? 0}
                  onClick={() => setSelectedWorkflowId(workflow.workflow_id)}
                />
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-border/65 bg-card/85 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <DatabaseZap className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-semibold text-foreground">
                  {t("workflowDashboard.checkpoints")}
                </h2>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 rounded-full px-3 text-[12px]"
                disabled={!sessionKey || savingCheckpoint}
                onClick={() => void handleSaveCheckpoint()}
              >
                {savingCheckpoint ? (
                  <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                {t("workflowDashboard.saveCheckpoint")}
              </Button>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("workflowDashboard.checkpointSummary", { count: filteredCheckpoints.length })}
            </p>
          </div>
        </section>

        {error ? (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}
        {liveNotice ? (
          <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300">
            {liveNotice}
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <section className="flex min-h-0 flex-col rounded-2xl border border-border/65 bg-card/80">
            <div className="flex items-center justify-between gap-3 border-b border-border/55 px-4 py-3">
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-semibold text-foreground">
                  {t("workflowDashboard.runs")}
                </h2>
              </div>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                {filteredRuns.length}
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {loading ? (
                <EmptyState label={t("workflowDashboard.loading")} />
              ) : filteredRuns.length ? (
                <div className="space-y-2">
                  {filteredRuns.map((run) => (
                    <button
                      key={run.run_id}
                      type="button"
                      className={cn(
                        "w-full rounded-2xl border px-3 py-3 text-left transition-colors",
                        selectedRun?.run_id === run.run_id
                          ? "border-primary/40 bg-accent/45"
                          : "border-border/55 bg-background hover:bg-muted/45",
                      )}
                      onClick={() => setSelectedRunId(run.run_id)}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-foreground">
                            {run.workflow_id}
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {run.current_step
                              ? t("workflowDashboard.currentStep", { step: run.current_step })
                              : t("workflowDashboard.progress", {
                                  done: run.completed_steps ?? 0,
                                  total: run.step_count ?? 0,
                                })}
                          </div>
                        </div>
                        <span className={cn(
                          "rounded-full px-2 py-0.5 text-[10.5px] font-medium",
                          runStateBadgeClass(run.state),
                        )}>
                          {run.state}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <EmptyState
                  label={sessionKey
                    ? t("workflowDashboard.emptyRuns")
                    : t("workflowDashboard.noSessionRuns")}
                />
              )}
            </div>
          </section>

          <section className="grid min-h-0 gap-4">
            <div className="flex min-h-[280px] flex-col rounded-2xl border border-border/65 bg-card/80">
              <div className="flex items-center justify-between gap-3 border-b border-border/55 px-4 py-3">
                <div className="flex items-center gap-2">
                  <ListFilter className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-semibold text-foreground">
                    {t("workflowDashboard.runDetails")}
                  </h2>
                </div>
              </div>
              <div className="flex-1 p-4">
                {selectedRun ? (
                  <RunDetails
                    run={selectedRunDetail ?? selectedRun}
                    loading={detailLoading}
                    actionInFlight={runAction}
                    onResume={() => void handleRunAction("resume")}
                    onCancel={() => void handleRunAction("cancel")}
                  />
                ) : (
                  <EmptyState label={t("workflowDashboard.noRunSelected")} />
                )}
              </div>
            </div>

            <div className="flex min-h-0 flex-col rounded-2xl border border-border/65 bg-card/80">
              <div className="flex items-center justify-between gap-3 border-b border-border/55 px-4 py-3">
                <div className="flex items-center gap-2">
                  <DatabaseZap className="h-4 w-4 text-muted-foreground" />
                  <h2 className="text-sm font-semibold text-foreground">
                    {t("workflowDashboard.recentCheckpoints")}
                  </h2>
                </div>
                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {filteredCheckpoints.length}
                </span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {loading ? (
                  <EmptyState label={t("workflowDashboard.loading")} />
                ) : filteredCheckpoints.length ? (
                  <div className="space-y-2">
                    {filteredCheckpoints.map((checkpoint) => (
                      <div
                        key={checkpoint.checkpoint_id}
                        className={cn(
                          "rounded-2xl border bg-background px-3 py-3",
                          rebuildCheckpointId === checkpoint.checkpoint_id
                            ? "border-primary/40 bg-accent/35"
                            : "border-border/55",
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-foreground">
                              {checkpoint.checkpoint_id}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {fmtDateTime(checkpoint.created_at * 1000, currentLocale())}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {[checkpoint.workflow_id, checkpoint.step_id].filter(Boolean).join(" · ") || checkpoint.kind}
                            </div>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-8 rounded-full px-2.5 text-[12px]"
                            disabled={!sessionKey || restoringCheckpointId === checkpoint.checkpoint_id}
                            onClick={() => void handleRestoreCheckpoint(checkpoint.checkpoint_id)}
                          >
                            {restoringCheckpointId === checkpoint.checkpoint_id ? (
                              <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            {t("workflowDashboard.restore")}
                          </Button>
                        </div>
                        <div className="mt-2 flex justify-end">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-8 rounded-full px-2.5 text-[12px]"
                            disabled={!sessionKey || rebuildLoadingId === checkpoint.checkpoint_id}
                            onClick={() => void handleRebuildCheckpoint(checkpoint.checkpoint_id)}
                          >
                            {rebuildLoadingId === checkpoint.checkpoint_id ? (
                              <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <SquareTerminal className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            {t("workflowDashboard.rebuild")}
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    label={sessionKey
                      ? t("workflowDashboard.emptyCheckpoints")
                      : t("workflowDashboard.noSessionCheckpoints")}
                  />
                )}
              </div>
            </div>
          </section>
        </div>
        {rebuildSummary ? (
          <section className="rounded-2xl border border-border/65 bg-card/80 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <SquareTerminal className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-semibold text-foreground">
                  {t("workflowDashboard.rebuildPlan")}
                </h2>
              </div>
              <div className="flex flex-wrap gap-2">
                {highlightedCheckpoint?.run_id ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-[12px]"
                    onClick={() => void focusCheckpointContext(highlightedCheckpoint)}
                  >
                    <GitBranch className="mr-1.5 h-3.5 w-3.5" />
                    {t("workflowDashboard.focusRunAction")}
                  </Button>
                ) : null}
                {highlightedCheckpoint ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-[12px]"
                    disabled={restoringCheckpointId === highlightedCheckpoint.checkpoint_id}
                    onClick={() => void handleRestoreCheckpoint(highlightedCheckpoint.checkpoint_id)}
                  >
                    {restoringCheckpointId === highlightedCheckpoint.checkpoint_id ? (
                      <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    {t("workflowDashboard.restoreCheckpointAction")}
                  </Button>
                ) : null}
                {selectedRun && (effectiveSelectedRunState === "failed" || effectiveSelectedRunState === "cancelled") ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 rounded-full px-3 text-[12px]"
                    disabled={runAction !== null}
                    onClick={() => void handleRunAction("resume")}
                  >
                    {runAction === "resume" ? (
                      <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    {t("workflowDashboard.resumeRunAction")}
                  </Button>
                ) : null}
              </div>
            </div>
            <pre className="mt-3 whitespace-pre-wrap rounded-2xl border border-border/55 bg-background p-3 text-[12.5px] leading-6 text-foreground">
              {rebuildSummary}
            </pre>
            {highlightedCheckpoint ? (
              <div className="mt-3 flex flex-wrap gap-2">
                <MetaPill
                  label={t("workflowDashboard.checkpointId")}
                  value={highlightedCheckpoint.checkpoint_id}
                  mono
                />
                {highlightedCheckpoint.workflow_id ? (
                  <MetaPill
                    label={t("workflowDashboard.workflowId")}
                    value={highlightedCheckpoint.workflow_id}
                  />
                ) : null}
                {highlightedCheckpoint.run_id ? (
                  <MetaPill
                    label={t("workflowDashboard.runId")}
                    value={highlightedCheckpoint.run_id}
                    mono
                  />
                ) : null}
                {highlightedCheckpoint.step_id ? (
                  <MetaPill
                    label={t("workflowDashboard.currentStepLabel")}
                    value={highlightedCheckpoint.step_id}
                  />
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </div>
  );
}

function FilterChip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors",
        active
          ? "border-primary/40 bg-accent text-foreground"
          : "border-border/55 bg-background text-muted-foreground hover:bg-muted/45 hover:text-foreground",
      )}
    >
      <span>{label}</span>
      <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10.5px]">
        {count}
      </span>
    </button>
  );
}

function RunDetails({
  run,
  loading = false,
  actionInFlight,
  onResume,
  onCancel,
}: {
  run: WorkflowRunSummary | WorkflowRunDetail;
  loading?: boolean;
  actionInFlight: "resume" | "cancel" | null;
  onResume: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("common");
  const locale = currentLocale();
  const detailed = "step_states" in run;
  const canResume = run.state === "failed" || run.state === "cancelled";
  const canCancel = run.state === "running";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 rounded-full px-3 text-[12px]"
          disabled={!canResume || actionInFlight !== null}
          onClick={onResume}
        >
          {actionInFlight === "resume" ? (
            <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
          )}
          {t("workflowDashboard.resume")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 rounded-full px-3 text-[12px]"
          disabled={!canCancel || actionInFlight !== null}
          onClick={onCancel}
        >
          {actionInFlight === "cancel" ? (
            <RefreshCcw className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <XCircle className="mr-1.5 h-3.5 w-3.5" />
          )}
          {t("workflowDashboard.cancel")}
        </Button>
      </div>
      {loading ? (
        <EmptyState label={t("workflowDashboard.loading")} />
      ) : null}
      <dl className="grid gap-3">
      <DetailRow label={t("workflowDashboard.workflowId")} value={run.workflow_id} />
      <DetailRow label={t("workflowDashboard.runId")} value={run.run_id} mono />
      <DetailRow label={t("workflowDashboard.state")} value={run.state} />
      <DetailRow label={t("workflowDashboard.goalId")} value={run.goal_id} mono />
      <DetailRow
        label={t("workflowDashboard.currentStepLabel")}
        value={run.current_step ?? t("workflowDashboard.none")}
      />
      <DetailRow
        label={t("workflowDashboard.progressLabel")}
        value={t("workflowDashboard.progress", {
          done: run.completed_steps ?? 0,
          total: run.step_count ?? 0,
        })}
      />
      <DetailRow
        label={t("workflowDashboard.updatedAt")}
        value={fmtDateTime(run.updated_at * 1000, locale)}
      />
      {run.finished_at ? (
        <DetailRow
          label={t("workflowDashboard.finishedAt")}
          value={fmtDateTime(run.finished_at * 1000, locale)}
        />
      ) : null}
      {run.error ? (
        <DetailRow label={t("workflowDashboard.error")} value={run.error} />
      ) : null}
      </dl>
      {detailed ? (
        <>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("workflowDashboard.stepTimeline")}
            </div>
            <div className="space-y-2">
              {run.step_states.map((step) => (
                <div
                  key={step.step_id}
                  className="rounded-xl border border-border/50 bg-background px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-foreground">
                        {step.name}
                      </div>
                      <div className="mt-1 text-[11.5px] text-muted-foreground">
                        {step.step_id}
                      </div>
                    </div>
                    <span className={cn(
                      "rounded-full px-2 py-0.5 text-[10.5px] font-medium",
                      runStateBadgeClass(step.state),
                    )}>
                      {step.state}
                    </span>
                  </div>
                  <div className="mt-2 text-[11.5px] text-muted-foreground">
                    {t("workflowDashboard.attempts", { count: step.attempts })}
                  </div>
                  {step.error ? (
                    <div className="mt-1 text-[11.5px] text-destructive">{step.error}</div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("workflowDashboard.statusHistory")}
            </div>
            <div className="space-y-2">
              {run.status_history.map((item, index) => (
                <div
                  key={`${item.state}-${item.at}-${index}`}
                  className="rounded-xl border border-border/50 bg-background px-3 py-2 text-[12px]"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-foreground">{item.state}</span>
                    <span className="text-muted-foreground">
                      {fmtDateTime(item.at * 1000, locale)}
                    </span>
                  </div>
                  {item.detail ? (
                    <div className="mt-1 text-muted-foreground">{item.detail}</div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-1 rounded-xl border border-border/50 bg-background px-3 py-2">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className={cn("text-sm text-foreground", mono && "font-mono text-[12.5px]")}>
        {value}
      </dd>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[120px] items-center justify-center rounded-2xl border border-dashed border-border/55 bg-background px-4 text-center text-sm text-muted-foreground">
      {label}
    </div>
  );
}

function MetaPill({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-border/55 bg-background px-3 py-1 text-[11.5px] text-muted-foreground">
      <span className="font-medium text-foreground">{label}:</span>
      <span className={cn(mono && "font-mono text-[11px]")}>{value}</span>
    </div>
  );
}

function runStateBadgeClass(state: string): string {
  switch (state) {
    case "completed":
      return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
    case "failed":
      return "bg-destructive/10 text-destructive";
    case "cancelled":
      return "bg-amber-500/10 text-amber-700 dark:text-amber-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function parseWorkflowRunUpdate(ev: InboundEvent): WorkflowRunLivePayload | null {
  if (ev.event !== "message" || ev.kind !== "progress") return null;
  if (ev.agent_ui?.kind !== "workflow_run") return null;
  const data = ev.agent_ui.data;
  if (!data || typeof data !== "object") return null;
  const payload = data as Partial<WorkflowRunLivePayload>;
  if (
    typeof payload.run_id !== "string"
    || typeof payload.workflow_id !== "string"
    || typeof payload.goal_id !== "string"
    || typeof payload.state !== "string"
    || typeof payload.started_at !== "number"
    || typeof payload.updated_at !== "number"
  ) {
    return null;
  }
  return payload as WorkflowRunLivePayload;
}

function toWorkflowRunSummary(payload: WorkflowRunLivePayload): WorkflowRunSummary {
  return {
    run_id: payload.run_id,
    workflow_id: payload.workflow_id,
    goal_id: payload.goal_id,
    state: payload.state,
    current_step: payload.current_step ?? null,
    updated_at: payload.updated_at,
    finished_at: payload.finished_at ?? null,
    error: payload.error ?? null,
    step_count: payload.step_count,
    completed_steps: payload.completed_steps,
  };
}

function toWorkflowRunDetail(payload: WorkflowRunLivePayload): WorkflowRunDetail {
  return {
    ...toWorkflowRunSummary(payload),
    started_at: payload.started_at,
    cancel_requested: payload.cancel_requested,
    step_results: {},
    status_history: (payload.status_history ?? []).map((item) => ({
      state: typeof item.state === "string" ? item.state : "unknown",
      at: typeof item.at === "number" ? item.at : payload.updated_at,
      detail: typeof item.detail === "string" ? item.detail : null,
    })),
    checkpoints: (payload.checkpoints ?? []).map((checkpoint) => ({
      step_id: checkpoint.step_id ?? null,
      saved_at: checkpoint.saved_at ?? null,
      checkpoint_id: checkpoint.checkpoint_id ?? null,
      result_keys: checkpoint.result_keys ?? [],
    })),
    step_states: (payload.step_states ?? []).map((step) => ({
      step_id: step.step_id,
      name: step.name,
      state: step.state,
      attempts: step.attempts,
      started_at: step.started_at ?? null,
      finished_at: step.finished_at ?? null,
      error: step.error ?? null,
      output: step.output,
    })),
  };
}

function upsertWorkflowRunSummary(
  current: WorkflowRunSummary[],
  next: WorkflowRunSummary,
): WorkflowRunSummary[] {
  const index = current.findIndex((run) => run.run_id === next.run_id);
  if (index === -1) return [next, ...current];
  const copy = current.slice();
  copy[index] = next;
  copy.sort((left, right) => right.updated_at - left.updated_at);
  return copy;
}
