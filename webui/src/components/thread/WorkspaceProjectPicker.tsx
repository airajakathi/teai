import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, Folder, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type {
  ProjectSummary,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { getHostApi } from "@/lib/runtime";
import { cn } from "@/lib/utils";
import {
  isAbsoluteWorkspacePath,
  isWorkspaceProjectPath,
  projectNameFromPath,
  selectedProjectScope,
  shortWorkspacePath,
} from "@/lib/workspace";
import { bootstrapProject, fetchProjects } from "@/lib/api";

interface WorkspaceFolder {
  path: string;
  name: string;
}

export function WorkspaceProjectPicker({
  isHero,
  visible,
  disabled,
  scope,
  defaultScope,
  controls,
  error,
  onChange,
  authToken,
}: {
  isHero: boolean;
  visible?: boolean;
  disabled?: boolean;
  scope: WorkspaceScopePayload | null;
  defaultScope: WorkspaceScopePayload | null;
  controls: WorkspacesPayload["controls"] | null;
  error?: string | null;
  onChange?: (scope: WorkspaceScopePayload) => void;
  authToken?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState("");
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [pickingFolder, setPickingFolder] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [projectsLoadFailed, setProjectsLoadFailed] = useState(false);
  const [projects, setProjects] = useState<WorkspaceFolder[]>([]);
  const currentProjectScope = selectedProjectScope(scope, defaultScope);
  const projectLabel = currentProjectScope
    ? currentProjectScope.project_name || projectNameFromPath(currentProjectScope.project_path)
    : t("thread.composer.workspace.projectPlaceholder");
  const resolvedVisible = (visible ?? isHero)
    && !!defaultScope
    && !!onChange
    && controls?.can_change_project !== false;
  const hostApi = getHostApi();
  const nativeProjectPicker = !!hostApi;

  useEffect(() => {
    if (!open) return;
    setCreateDraft("");
    setPickerError(null);
    setProjectsLoadFailed(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (!defaultScope) return;
    let cancelled = false;
    setLoadingProjects(true);
    setProjectsLoadFailed(false);
    fetchProjects(authToken ?? "")
      .then((result) => {
        if (!cancelled) {
          setProjects(
            (result.projects ?? [])
              .filter((project: ProjectSummary) =>
                isWorkspaceProjectPath(project.root_path, defaultScope.project_path))
              .map((project: ProjectSummary) => ({
                path: project.root_path,
                name: project.name,
              })),
          );
          setProjectsLoadFailed(false);
          setLoadingProjects(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProjects([]);
          setProjectsLoadFailed(true);
          setLoadingProjects(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authToken, defaultScope, open]);

  useEffect(() => {
    if (error && resolvedVisible) setOpen(true);
  }, [error, resolvedVisible]);

  const applyProjectPath = useCallback(
    (projectPath: string, projectName?: string) => {
      const base = scope ?? defaultScope;
      const resolved = projectPath.trim();
      if (!base || !onChange) return;
      if (!resolved || !isAbsoluteWorkspacePath(resolved)) {
        setPickerError(t("workspace.dialog.absolutePathRequired"));
        return;
      }
      onChange({
        ...base,
        project_path: resolved,
        project_name: projectName || projectNameFromPath(resolved),
        restrict_to_workspace: base.access_mode === "restricted",
      });
      setPickerError(null);
      setOpen(false);
    },
    [defaultScope, onChange, scope, t],
  );

  const pickNativeFolder = useCallback(async () => {
    if (!hostApi || disabled) return;
    setPickingFolder(true);
    try {
      const picked = await hostApi.pickFolder();
      if (picked) applyProjectPath(picked);
    } catch (err) {
      setPickerError((err as Error).message);
    } finally {
      setPickingFolder(false);
    }
  }, [applyProjectPath, disabled, hostApi]);

  const createProject = useCallback(async () => {
    const base = scope ?? defaultScope;
    const cleaned = createDraft.trim();
    if (!base || !onChange) return;
    if (!cleaned) {
      setPickerError(t("workspace.dialog.nameRequired"));
      return;
    }
    setCreatingProject(true);
    setPickerError(null);
    try {
      const result = await bootstrapProject(authToken ?? "", cleaned, base.access_mode);
      onChange({
        ...result.workspace_scope,
        restrict_to_workspace: result.workspace_scope.access_mode === "restricted",
      });
      setProjects((prev) => {
        const next = [
          { path: result.project.root_path, name: result.project.name },
          ...prev.filter((folder) => folder.path !== result.project.root_path),
        ];
        return next.sort((a, b) => a.name.localeCompare(b.name));
      });
      setCreateDraft("");
      setOpen(false);
    } catch (err) {
      setPickerError((err as Error).message || t("workspace.dialog.creationFailed"));
    } finally {
      setCreatingProject(false);
    }
  }, [authToken, createDraft, defaultScope, onChange, scope, t]);

  if (!resolvedVisible || !defaultScope || !onChange) return null;

  return (
    <div className="flex items-center rounded-b-[28px] border-t border-border/25 bg-muted/60 px-4 py-1.5 dark:bg-white/[0.055]">
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={t("thread.composer.workspace.projectAria")}
            className={cn(
              "inline-flex h-7 max-w-[18rem] items-center gap-2 rounded-full px-2.5",
              "text-[12px] font-medium text-muted-foreground/90 transition-colors",
              "hover:bg-background/70 hover:text-foreground disabled:pointer-events-none disabled:opacity-55",
              currentProjectScope && "text-foreground/82",
            )}
          >
            <Folder className={cn("h-3.5 w-3.5 shrink-0", currentProjectScope && "text-primary")} />
            <span className="truncate">{projectLabel}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          side="bottom"
          sideOffset={8}
          className="max-h-80 w-[min(25rem,calc(100vw-2rem))] overflow-y-auto rounded-[22px]"
        >
          {nativeProjectPicker ? (
            <>
              <DropdownMenuItem
                onSelect={() => {
                  void pickNativeFolder();
                }}
                className="flex min-h-[48px] gap-3 rounded-[16px] px-3 py-2.5 focus:bg-muted/55"
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[12px] bg-muted text-foreground/80">
                  {pickingFolder ? <Loader2 className="h-4 w-4 animate-spin" /> : <Folder className="h-4 w-4" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-foreground">
                    {t("workspace.dialog.chooseFolder")}
                  </span>
                  <span className="block truncate text-[11.5px] text-muted-foreground">
                    {t("workspace.dialog.chooseFolderHint")}
                  </span>
                </span>
              </DropdownMenuItem>
              <div className="my-1 h-px bg-border/45" />
            </>
          ) : null}
          {loadingProjects ? (
            <div className="flex items-center gap-2 px-3 py-2 text-[12px] text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>{t("workspace.dialog.loadingProjects")}</span>
            </div>
          ) : (
            <div className="max-h-56 overflow-y-auto px-1.5 py-1.5">
              {projectsLoadFailed ? (
                <p role="alert" className="px-1 py-2 text-[12px] text-destructive">
                  {t("workspace.dialog.projectsLoadFailed", {
                    defaultValue: "Could not load tracked workspace projects.",
                  })}
                </p>
              ) : projects.length === 0 ? (
                <p className="px-1 py-2 text-[12px] text-muted-foreground">
                  {t("workspace.dialog.noFoldersFound")}
                </p>
              ) : (
                projects.map((folder) => {
                  const selected = currentProjectScope
                    ? currentProjectScope.project_path === folder.path
                    : false;
                  return (
                    <DropdownMenuItem
                      key={folder.path}
                      onSelect={() => applyProjectPath(folder.path, folder.name)}
                      className="flex min-h-[44px] gap-3 rounded-[16px] px-3 py-2.5 focus:bg-muted/55"
                    >
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-[12px] bg-muted text-foreground/80">
                        <Folder className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold text-foreground">
                          {folder.name}
                        </span>
                        <span className="block truncate text-[11.5px] text-muted-foreground">
                          {shortWorkspacePath(folder.path)}
                        </span>
                      </span>
                      {selected ? <Check className="h-4 w-4 text-foreground/80" /> : null}
                    </DropdownMenuItem>
                  );
                })
              )}
            </div>
          )}
          <div className="my-1 h-px bg-border/45" />
          <div
            className="space-y-1.5 px-1.5 py-1.5"
            onKeyDown={(event) => {
              if (event.key !== "Escape") event.stopPropagation();
            }}
          >
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void createProject();
              }}
            >
              <Input
                value={createDraft}
                disabled={disabled || creatingProject}
                onChange={(event) => {
                  setCreateDraft(event.target.value);
                  setPickerError(null);
                }}
                placeholder={t("workspace.dialog.createPlaceholder")}
                aria-label={t("workspace.dialog.createProject")}
                className={cn(
                  "h-9 rounded-full border-border/55 bg-background/80 px-3 text-[12.5px]",
                  "focus-visible:ring-1 focus-visible:ring-foreground/10 focus-visible:ring-offset-0",
                )}
              />
              <Button
                type="submit"
                disabled={disabled || creatingProject || !createDraft.trim()}
                className="h-9 shrink-0 rounded-full px-3 text-[12px]"
              >
                {creatingProject ? t("workspace.dialog.creating") : t("workspace.dialog.createAction")}
              </Button>
            </form>
          </div>
          {pickerError || error ? (
            <div className="px-3 pb-2 pt-1">
              <p role="alert" className="text-[11.5px] font-medium text-destructive">
                {pickerError ?? error}
              </p>
            </div>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
