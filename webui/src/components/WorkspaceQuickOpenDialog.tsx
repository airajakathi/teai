import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, AtSign, FileSearch, GitBranch, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ApiError,
  fetchWorkspaceContentSearch,
  fetchWorkspaceProblems,
  fetchWorkspaceReferenceSearch,
  fetchWorkspaceSearch,
  fetchWorkspaceSymbolSearch,
} from "@/lib/api";
import type {
  WorkspaceContentSearchItem,
  WorkspaceProblemItem,
  WorkspaceReferenceSearchItem,
  WorkspaceSearchItem,
  WorkspaceSymbolSearchItem,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type WorkspaceSearchMode = "files" | "content" | "symbols" | "references" | "problems";

interface WorkspaceQuickOpenDialogProps {
  open: boolean;
  token: string;
  sessionKey: string;
  runtimeProblems?: WorkspaceProblemItem[];
  initialMode?: WorkspaceSearchMode;
  initialQuery?: string;
  onOpenChange: (open: boolean) => void;
  onSelect: (path: string) => void;
}

type FileSearchState =
  | { status: "idle"; items: WorkspaceSearchItem[]; truncated: boolean }
  | { status: "loading"; items: WorkspaceSearchItem[]; truncated: boolean }
  | { status: "ready"; items: WorkspaceSearchItem[]; truncated: boolean }
  | { status: "error"; items: WorkspaceSearchItem[]; truncated: boolean; message: string };

type ContentSearchState =
  | { status: "idle"; items: WorkspaceContentSearchItem[]; truncated: boolean }
  | { status: "loading"; items: WorkspaceContentSearchItem[]; truncated: boolean }
  | { status: "ready"; items: WorkspaceContentSearchItem[]; truncated: boolean }
  | { status: "error"; items: WorkspaceContentSearchItem[]; truncated: boolean; message: string };

type SymbolSearchState =
  | { status: "idle"; items: WorkspaceSymbolSearchItem[]; truncated: boolean }
  | { status: "loading"; items: WorkspaceSymbolSearchItem[]; truncated: boolean }
  | { status: "ready"; items: WorkspaceSymbolSearchItem[]; truncated: boolean }
  | { status: "error"; items: WorkspaceSymbolSearchItem[]; truncated: boolean; message: string };

type ReferenceSearchState =
  | { status: "idle"; items: WorkspaceReferenceSearchItem[]; truncated: boolean }
  | { status: "loading"; items: WorkspaceReferenceSearchItem[]; truncated: boolean }
  | { status: "ready"; items: WorkspaceReferenceSearchItem[]; truncated: boolean }
  | { status: "error"; items: WorkspaceReferenceSearchItem[]; truncated: boolean; message: string };

type ProblemsSearchState =
  | { status: "idle"; items: WorkspaceProblemItem[]; truncated: boolean }
  | { status: "loading"; items: WorkspaceProblemItem[]; truncated: boolean }
  | { status: "ready"; items: WorkspaceProblemItem[]; truncated: boolean }
  | { status: "error"; items: WorkspaceProblemItem[]; truncated: boolean; message: string };

const DEFAULT_FILE_STATE: FileSearchState = { status: "idle", items: [], truncated: false };
const DEFAULT_CONTENT_STATE: ContentSearchState = { status: "idle", items: [], truncated: false };
const DEFAULT_SYMBOL_STATE: SymbolSearchState = { status: "idle", items: [], truncated: false };
const DEFAULT_REFERENCE_STATE: ReferenceSearchState = { status: "idle", items: [], truncated: false };
const DEFAULT_PROBLEMS_STATE: ProblemsSearchState = { status: "idle", items: [], truncated: false };
const MIN_CONTENT_QUERY_LENGTH = 2;
const MIN_REFERENCE_QUERY_LENGTH = 2;

export function WorkspaceQuickOpenDialog({
  open,
  token,
  sessionKey,
  runtimeProblems = [],
  initialMode = "files",
  initialQuery = "",
  onOpenChange,
  onSelect,
}: WorkspaceQuickOpenDialogProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [mode, setMode] = useState<WorkspaceSearchMode>(initialMode);
  const [query, setQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [fileState, setFileState] = useState<FileSearchState>(DEFAULT_FILE_STATE);
  const [contentState, setContentState] = useState<ContentSearchState>(DEFAULT_CONTENT_STATE);
  const [symbolState, setSymbolState] = useState<SymbolSearchState>(DEFAULT_SYMBOL_STATE);
  const [referenceState, setReferenceState] = useState<ReferenceSearchState>(DEFAULT_REFERENCE_STATE);
  const [problemsState, setProblemsState] = useState<ProblemsSearchState>(DEFAULT_PROBLEMS_STATE);
  const filteredRuntimeProblems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const terms = normalizedQuery ? normalizedQuery.split(/\s+/).filter(Boolean) : [];
    const ranked = runtimeProblems
      .map((item) => {
        let score = Number(item.score || 0) + 180;
        if (terms.length > 0) {
          const haystack = [
            item.message,
            item.preview,
            item.display_path,
            item.source,
            item.name,
          ].join(" ").toLowerCase();
          for (const term of terms) {
            if (!haystack.includes(term)) return null;
            if (item.message.toLowerCase().includes(term)) score += 48;
            if (item.display_path.toLowerCase().includes(term)) score += 26;
            if (item.source.toLowerCase().includes(term)) score += 18;
          }
        }
        return { ...item, score };
      })
      .filter((item): item is WorkspaceProblemItem => item !== null);
    ranked.sort((left, right) => (
      right.score - left.score
      || (left.severity === "error" ? 0 : 1) - (right.severity === "error" ? 0 : 1)
      || left.display_path.length - right.display_path.length
      || left.line - right.line
    ));
    return ranked.slice(0, 40);
  }, [query, runtimeProblems]);
  const mergedProblems = useMemo(() => {
    const combined = new Map<string, WorkspaceProblemItem>();
    for (const item of [...filteredRuntimeProblems, ...problemsState.items]) {
      const key = `${item.path}|${item.message}`;
      if (!combined.has(key)) {
        combined.set(key, item);
        continue;
      }
      const existing = combined.get(key)!;
      if ((item.score ?? 0) > (existing.score ?? 0)) combined.set(key, item);
    }
    return [...combined.values()].sort((left, right) => (
      (right.score ?? 0) - (left.score ?? 0)
      || (left.severity === "error" ? 0 : 1) - (right.severity === "error" ? 0 : 1)
      || left.display_path.length - right.display_path.length
      || left.line - right.line
    ));
  }, [filteredRuntimeProblems, problemsState.items]);

  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setQuery(initialQuery);
    setHighlightedIndex(0);
    setFileState(DEFAULT_FILE_STATE);
    setContentState(DEFAULT_CONTENT_STATE);
    setSymbolState(DEFAULT_SYMBOL_STATE);
    setReferenceState(DEFAULT_REFERENCE_STATE);
    setProblemsState(DEFAULT_PROBLEMS_STATE);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [initialMode, initialQuery, open]);

  useEffect(() => {
    if (!open) return undefined;
    if (mode === "content" && query.trim().length < MIN_CONTENT_QUERY_LENGTH) {
      setContentState(DEFAULT_CONTENT_STATE);
      return undefined;
    }
    if (mode === "references" && query.trim().length < MIN_REFERENCE_QUERY_LENGTH) {
      setReferenceState(DEFAULT_REFERENCE_STATE);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (mode === "files") {
        setFileState((current) => ({
          status: "loading",
          items: current.items,
          truncated: current.truncated,
        }));
        void fetchWorkspaceSearch(token, sessionKey, query, 40)
          .then((payload) => {
            if (cancelled) return;
            setFileState({
              status: "ready",
              items: payload.items,
              truncated: payload.truncated,
            });
          })
          .catch((error: unknown) => {
            if (cancelled) return;
            setFileState((current) => ({
              status: "error",
              items: current.items,
              truncated: current.truncated,
              message: error instanceof ApiError
                ? error.message
                : t("workspaceQuickOpen.failed", { defaultValue: "Could not search workspace files." }),
            }));
          });
        return;
      }

      if (mode === "content") {
        setContentState((current) => ({
          status: "loading",
          items: current.items,
          truncated: current.truncated,
        }));
        void fetchWorkspaceContentSearch(token, sessionKey, query, 40)
          .then((payload) => {
            if (cancelled) return;
            setContentState({
              status: "ready",
              items: payload.items,
              truncated: payload.truncated,
            });
          })
          .catch((error: unknown) => {
            if (cancelled) return;
            setContentState((current) => ({
              status: "error",
              items: current.items,
              truncated: current.truncated,
              message: error instanceof ApiError
                ? error.message
                : t("workspaceQuickOpen.contentFailed", { defaultValue: "Could not search workspace contents." }),
            }));
          });
        return;
      }

      if (mode === "symbols") {
        setSymbolState((current) => ({
          status: "loading",
          items: current.items,
          truncated: current.truncated,
        }));
        void fetchWorkspaceSymbolSearch(token, sessionKey, query, 40)
          .then((payload) => {
            if (cancelled) return;
            setSymbolState({
              status: "ready",
              items: payload.items,
              truncated: payload.truncated,
            });
          })
          .catch((error: unknown) => {
            if (cancelled) return;
            setSymbolState((current) => ({
              status: "error",
              items: current.items,
              truncated: current.truncated,
              message: error instanceof ApiError
                ? error.message
                : t("workspaceQuickOpen.symbolFailed", { defaultValue: "Could not search workspace symbols." }),
            }));
          });
        return;
      }

      if (mode === "references") {
        setReferenceState((current) => ({
          status: "loading",
          items: current.items,
          truncated: current.truncated,
        }));
        void fetchWorkspaceReferenceSearch(token, sessionKey, query, 40)
          .then((payload) => {
            if (cancelled) return;
            setReferenceState({
              status: "ready",
              items: payload.items,
              truncated: payload.truncated,
            });
          })
          .catch((error: unknown) => {
            if (cancelled) return;
            setReferenceState((current) => ({
              status: "error",
              items: current.items,
              truncated: current.truncated,
              message: error instanceof ApiError
                ? error.message
                : t("workspaceQuickOpen.referenceFailed", { defaultValue: "Could not search workspace references." }),
            }));
          });
        return;
      }

      setProblemsState((current) => ({
        status: "loading",
        items: current.items,
        truncated: current.truncated,
      }));
      void fetchWorkspaceProblems(token, sessionKey, query, 40)
        .then((payload) => {
          if (cancelled) return;
          setProblemsState({
            status: "ready",
            items: payload.items,
            truncated: payload.truncated,
          });
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          setProblemsState((current) => ({
            status: "error",
            items: current.items,
            truncated: current.truncated,
            message: error instanceof ApiError
              ? error.message
              : t("workspaceQuickOpen.problemsFailed", { defaultValue: "Could not load workspace problems." }),
          }));
        });
    }, query.trim() ? 120 : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mode, open, query, sessionKey, t, token]);

  const items = mode === "files"
    ? fileState.items
    : (mode === "content"
      ? contentState.items
      : (mode === "symbols"
        ? symbolState.items
        : (mode === "references" ? referenceState.items : mergedProblems)));
  const itemCount = items.length;
  const activeState = mode === "files"
    ? fileState
    : (mode === "content"
      ? contentState
      : (mode === "symbols"
        ? symbolState
        : (mode === "references"
          ? referenceState
          : {
            status: problemsState.status,
            items: mergedProblems,
            truncated: problemsState.truncated || runtimeProblems.length > filteredRuntimeProblems.length,
            ...(problemsState.status === "error" ? { message: problemsState.message } : {}),
          })));
  const loading = activeState.status === "loading";
  const errorMessage = activeState.status === "error" ? activeState.message : null;
  const queryTrimmed = query.trim();
  const sectionLabel = mode === "files"
    ? (queryTrimmed
      ? t("workspaceQuickOpen.results", { defaultValue: "Matching files" })
      : t("workspaceQuickOpen.suggested", { defaultValue: "Workspace files" }))
    : (mode === "content"
      ? t("workspaceQuickOpen.contentResults", { defaultValue: "Content matches" })
      : (mode === "symbols"
        ? t("workspaceQuickOpen.symbolResults", { defaultValue: "Workspace symbols" })
        : (mode === "references"
          ? t("workspaceQuickOpen.referenceResults", { defaultValue: "Workspace references" })
          : t("workspaceQuickOpen.problemResults", { defaultValue: "Workspace problems" }))));

  useEffect(() => {
    setHighlightedIndex(0);
  }, [mode, query]);

  useEffect(() => {
    setHighlightedIndex((index) => (itemCount === 0 ? 0 : Math.min(index, itemCount - 1)));
  }, [itemCount]);

  useEffect(() => {
    itemRefs.current = itemRefs.current.slice(0, itemCount);
  }, [itemCount]);

  useEffect(() => {
    if (!open) return;
    itemRefs.current[highlightedIndex]?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }, [highlightedIndex, open]);

  const handleSelect = (path: string) => {
    onOpenChange(false);
    onSelect(path);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((index) => (itemCount === 0 ? 0 : (index + 1) % itemCount));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) => (itemCount === 0 ? 0 : (index - 1 + itemCount) % itemCount));
      return;
    }
    if (event.key === "Enter") {
      const highlighted = items[highlightedIndex];
      if (!highlighted) return;
      event.preventDefault();
      handleSelect(highlighted.path);
    }
  };

  const emptyLabel = useMemo(() => {
    if (items.length > 0) return null;
    if (loading) return null;
    if (errorMessage) return errorMessage;
    if (mode === "content" && queryTrimmed.length < MIN_CONTENT_QUERY_LENGTH) {
      return t("workspaceQuickOpen.contentIdle", {
        defaultValue: "Type at least 2 characters to search file contents.",
      });
    }
    if (mode === "references" && queryTrimmed.length < MIN_REFERENCE_QUERY_LENGTH) {
      return t("workspaceQuickOpen.referenceIdle", {
        defaultValue: "Type at least 2 characters to search symbol references.",
      });
    }
    if (queryTrimmed) {
      if (mode === "content") {
        return t("workspaceQuickOpen.contentEmpty", { defaultValue: "No content matches." });
      }
      if (mode === "symbols") {
        return t("workspaceQuickOpen.symbolEmpty", { defaultValue: "No matching symbols." });
      }
      if (mode === "references") {
        return t("workspaceQuickOpen.referenceEmpty", { defaultValue: "No matching references." });
      }
      if (mode === "problems") {
        return t("workspaceQuickOpen.problemEmpty", { defaultValue: "No matching problems." });
      }
      return t("workspaceQuickOpen.empty", { defaultValue: "No matching files." });
    }
    return mode === "files"
      ? t("workspaceQuickOpen.idle", { defaultValue: "Start typing to jump to a file." })
      : (mode === "content"
        ? t("workspaceQuickOpen.contentIdle", {
          defaultValue: "Type at least 2 characters to search file contents.",
        })
        : (mode === "symbols"
          ? t("workspaceQuickOpen.symbolIdle", {
            defaultValue: "Start typing to jump to a symbol.",
          })
          : (mode === "references"
            ? t("workspaceQuickOpen.referenceIdle", {
              defaultValue: "Type at least 2 characters to search symbol references.",
            })
            : t("workspaceQuickOpen.problemIdle", {
              defaultValue: "Browse or search workspace problems.",
            }))));
  }, [errorMessage, items.length, loading, mode, queryTrimmed, t]);

  if (!open) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className={cn(
          "flex max-h-[min(40rem,calc(100vh-2rem))] w-[calc(100vw-2rem)] max-w-[44rem] flex-col gap-0 overflow-hidden p-0",
          "rounded-[22px] border border-border bg-background text-foreground shadow-[0_22px_70px_rgba(0,0,0,0.22)]",
          "dark:border-white/14 dark:bg-[#2b2b2b] dark:shadow-[0_26px_90px_rgba(0,0,0,0.44)] sm:rounded-[22px]",
        )}
      >
        <DialogTitle className="sr-only">
          {t("workspaceQuickOpen.title", { defaultValue: "Quick open" })}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {t("workspaceQuickOpen.description", {
            defaultValue: "Search files or file contents in the current workspace.",
          })}
        </DialogDescription>
        <div className="flex h-[62px] shrink-0 items-center gap-3 border-b border-border px-[18px]">
          {loading ? (
            <Loader2 className="h-[18px] w-[18px] shrink-0 animate-spin text-muted-foreground" aria-hidden />
          ) : mode === "problems" ? (
            <AlertCircle className="h-[18px] w-[18px] shrink-0 text-muted-foreground" aria-hidden />
          ) : mode === "references" ? (
            <GitBranch className="h-[18px] w-[18px] shrink-0 text-muted-foreground" aria-hidden />
          ) : mode === "symbols" ? (
            <AtSign className="h-[18px] w-[18px] shrink-0 text-muted-foreground" aria-hidden />
          ) : mode === "content" ? (
            <Search className="h-[18px] w-[18px] shrink-0 text-muted-foreground" aria-hidden />
          ) : (
            <FileSearch className="h-[18px] w-[18px] shrink-0 text-muted-foreground" aria-hidden />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={mode === "files"
              ? t("workspaceQuickOpen.placeholder", { defaultValue: "Quick open files" })
              : (mode === "content"
                ? t("workspaceQuickOpen.contentPlaceholder", { defaultValue: "Search workspace contents" })
                : (mode === "symbols"
                  ? t("workspaceQuickOpen.symbolPlaceholder", { defaultValue: "Search workspace symbols" })
                  : (mode === "references"
                    ? t("workspaceQuickOpen.referencePlaceholder", { defaultValue: "Search symbol references" })
                    : t("workspaceQuickOpen.problemPlaceholder", { defaultValue: "Search workspace problems" }))))}
            aria-label={mode === "files"
              ? t("workspaceQuickOpen.aria", { defaultValue: "Quick open files" })
              : (mode === "content"
                ? t("workspaceQuickOpen.contentAria", { defaultValue: "Search workspace contents" })
                : (mode === "symbols"
                  ? t("workspaceQuickOpen.symbolAria", { defaultValue: "Search workspace symbols" })
                  : (mode === "references"
                    ? t("workspaceQuickOpen.referenceAria", { defaultValue: "Search symbol references" })
                    : t("workspaceQuickOpen.problemAria", { defaultValue: "Search workspace problems" }))))}
            className="h-full min-w-0 flex-1 bg-transparent text-[19px] font-normal leading-none text-foreground outline-none placeholder:text-muted-foreground"
          />
        </div>
        <div className="flex items-center gap-2 border-b border-border/70 px-[18px] py-2">
          <button
            type="button"
            onClick={() => setMode("files")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "files"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/60 text-muted-foreground hover:text-foreground",
            )}
          >
            <FileSearch className="h-3.5 w-3.5" aria-hidden />
            {t("workspaceQuickOpen.filesTab", { defaultValue: "Files" })}
          </button>
          <button
            type="button"
            onClick={() => setMode("content")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "content"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/60 text-muted-foreground hover:text-foreground",
            )}
          >
            <Search className="h-3.5 w-3.5" aria-hidden />
            {t("workspaceQuickOpen.contentTab", { defaultValue: "Content" })}
          </button>
          <button
            type="button"
            onClick={() => setMode("symbols")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "symbols"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/60 text-muted-foreground hover:text-foreground",
            )}
          >
            <AtSign className="h-3.5 w-3.5" aria-hidden />
            {t("workspaceQuickOpen.symbolTab", { defaultValue: "Symbols" })}
          </button>
          <button
            type="button"
            onClick={() => setMode("references")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "references"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/60 text-muted-foreground hover:text-foreground",
            )}
          >
            <GitBranch className="h-3.5 w-3.5" aria-hidden />
            {t("workspaceQuickOpen.referenceTab", { defaultValue: "References" })}
          </button>
          <button
            type="button"
            onClick={() => setMode("problems")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "problems"
                ? "bg-primary text-primary-foreground"
                : "bg-muted/60 text-muted-foreground hover:text-foreground",
            )}
          >
            <AlertCircle className="h-3.5 w-3.5" aria-hidden />
            {t("workspaceQuickOpen.problemTab", { defaultValue: "Problems" })}
          </button>
          <span className="ml-auto text-[11px] text-muted-foreground">
            {mode === "files"
              ? t("workspaceQuickOpen.shortcut", { defaultValue: "Quick open files (Ctrl+P)" })
              : (mode === "content"
                ? t("workspaceQuickOpen.contentShortcut", { defaultValue: "Search contents (Ctrl+Shift+F)" })
                : (mode === "symbols"
                  ? t("workspaceQuickOpen.symbolShortcut", { defaultValue: "Search symbols (Ctrl+Alt+O)" })
                  : (mode === "references"
                    ? t("workspaceQuickOpen.referenceShortcut", { defaultValue: "Search references (Ctrl+Alt+R)" })
                    : t("workspaceQuickOpen.problemShortcut", { defaultValue: "Show problems (Ctrl+Shift+M)" }))))}
          </span>
        </div>

        <div
          data-testid="workspace-quick-open-scroll"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2.5 scrollbar-thin scrollbar-track-transparent"
        >
          <section>
            <div className="flex items-center justify-between gap-3 px-2.5 pb-1.5 pt-1 text-[12px] font-medium text-muted-foreground">
              <span>{sectionLabel}</span>
              {activeState.truncated ? (
                <span>{t("workspaceQuickOpen.truncated", { defaultValue: "Showing top matches" })}</span>
              ) : null}
            </div>

            {emptyLabel ? (
              <div className="px-3 py-7 text-[13px] text-muted-foreground">
                {emptyLabel}
              </div>
            ) : (
              <ul className="space-y-0.5">
                {items.map((item, index) => {
                  const highlighted = index === highlightedIndex;
                  return (
                    <li key={item.path}>
                      <button
                        ref={(node) => {
                          itemRefs.current[index] = node;
                        }}
                        type="button"
                        onClick={() => handleSelect(item.path)}
                        onMouseEnter={() => setHighlightedIndex(index)}
                        className={cn(
                          "grid min-h-[54px] w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-[11px] px-3 py-2 text-left transition-colors",
                          highlighted
                            ? "bg-muted text-foreground"
                            : "text-foreground hover:bg-muted",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-medium leading-5">
                            {mode === "problems"
                              ? (item as WorkspaceProblemItem).message
                              : item.name}
                          </span>
                          {mode === "content" ? (
                            <>
                              <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                                {item.display_path}:{(item as WorkspaceContentSearchItem).line}
                              </span>
                              <span className="mt-1 block line-clamp-2 text-[12px] leading-4 text-foreground/80">
                                {(item as WorkspaceContentSearchItem).preview}
                              </span>
                            </>
                          ) : mode === "symbols" ? (
                            <>
                              <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                                {[
                                  (item as WorkspaceSymbolSearchItem).container_name,
                                  (item as WorkspaceSymbolSearchItem).kind,
                                ].filter(Boolean).join(" • ")}
                              </span>
                              <span className="mt-1 block truncate text-[12px] leading-4 text-foreground/80">
                                {item.display_path}:{(item as WorkspaceSymbolSearchItem).line}
                              </span>
                            </>
                          ) : mode === "references" ? (
                            <>
                              <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                                {[
                                  (item as WorkspaceReferenceSearchItem).container_name,
                                  (item as WorkspaceReferenceSearchItem).kind,
                                ].filter(Boolean).join(" • ")}
                              </span>
                              <span className="mt-1 block truncate text-[12px] leading-4 text-foreground/80">
                                {(item as WorkspaceReferenceSearchItem).display_path}:{(item as WorkspaceReferenceSearchItem).line}
                              </span>
                              <span className="mt-1 block line-clamp-2 text-[12px] leading-4 text-foreground/80">
                                {(item as WorkspaceReferenceSearchItem).preview}
                              </span>
                            </>
                          ) : mode === "problems" ? (
                            <>
                              <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                                {[
                                  (item as WorkspaceProblemItem).source,
                                  (item as WorkspaceProblemItem).severity,
                                ].filter(Boolean).join(" • ")}
                              </span>
                              <span className="mt-1 block truncate text-[12px] leading-4 text-foreground/80">
                                {(item as WorkspaceProblemItem).display_path}:{(item as WorkspaceProblemItem).line}:{(item as WorkspaceProblemItem).column}
                              </span>
                              <span className="mt-1 block line-clamp-2 text-[12px] leading-4 text-foreground/80">
                                {(item as WorkspaceProblemItem).preview || (item as WorkspaceProblemItem).message}
                              </span>
                            </>
                          ) : (
                            <span className="block truncate text-[12px] leading-4 text-muted-foreground">
                              {item.display_path}
                            </span>
                          )}
                        </span>
                        {mode === "content" ? (
                          <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
                            {t("workspaceQuickOpen.lineLabel", {
                              defaultValue: "Line {{line}}",
                              line: (item as WorkspaceContentSearchItem).line,
                            })}
                          </span>
                        ) : mode === "symbols" ? (
                          <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium capitalize text-muted-foreground">
                            {(item as WorkspaceSymbolSearchItem).kind}
                          </span>
                        ) : mode === "references" ? (
                          <span className="rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
                            {t("workspaceQuickOpen.referenceLine", {
                              defaultValue: "Ref {{line}}",
                              line: (item as WorkspaceReferenceSearchItem).line,
                            })}
                          </span>
                        ) : mode === "problems" ? (
                          <span
                            className={cn(
                              "rounded-full px-2 py-1 text-[11px] font-medium capitalize",
                              (item as WorkspaceProblemItem).severity === "error"
                                ? "bg-rose-500/10 text-rose-700 dark:text-rose-300"
                                : "bg-amber-500/10 text-amber-700 dark:text-amber-300",
                            )}
                          >
                            {(item as WorkspaceProblemItem).severity}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
