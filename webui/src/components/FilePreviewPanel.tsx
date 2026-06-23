import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Eye, FilePenLine, FileText, Folder, FolderOpen, GitBranch, Loader2, RefreshCw, RotateCcw, Save, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CodeBlock } from "@/components/CodeBlock";
import { splitFilePath } from "@/components/FileReferenceChip";
import { MonacoEditor } from "@/components/editor/MonacoEditor";
import { DiffPair } from "@/components/thread/activity/DiffPair";
import { ApiError, fetchFilePreview, fetchFileSymbols, fetchWorkspaceReferenceSearch, fetchWorkspaceSymbolSearch, fetchWorkspaceTree } from "@/lib/api";
import type { TeaiBuilderClient } from "@/lib/teai_builder-client";
import type {
  FilePreviewPayload,
  FileSymbolItem,
  WorkspaceReferenceSearchItem,
  WorkspaceSymbolSearchItem,
  WorkspaceTreeNode,
  WorkspaceTreePayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface FilePreviewPanelProps {
  client?: Pick<TeaiBuilderClient, "saveFile"> | null;
  sessionKey: string;
  path: string;
  token: string;
  desktopWidth?: number;
  isClosing?: boolean;
  onResizeStart?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onGoToDefinition?: (request: { symbol: string; sourcePath: string }) => void;
  onFindReferences?: (request: { symbol: string; sourcePath: string }) => void;
  onClose: () => void;
}

type PreviewState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; payload: FilePreviewPayload };

type TreeState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; payload: WorkspaceTreePayload };

type PeekMode = "definition" | "references";

type PeekResultItem = {
  path: string;
  displayPath: string;
  name: string;
  kind: string;
  containerName?: string | null;
  line: number;
  column: number;
  preview?: string;
};

type PeekState =
  | { status: "idle" }
  | { status: "loading"; mode: PeekMode; symbol: string }
  | { status: "error"; mode: PeekMode; symbol: string; message: string }
  | { status: "ready"; mode: PeekMode; symbol: string; items: PeekResultItem[] };

type FileSymbolState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: FileSymbolItem[] };

type DiffLine =
  | { kind: "context"; oldLineNumber: number; newLineNumber: number; text: string }
  | { kind: "removed"; oldLineNumber: number; newLineNumber: null; text: string }
  | { kind: "added"; oldLineNumber: null; newLineNumber: number; text: string };

interface DiffHunk {
  lines: DiffLine[];
}

const FILE_PREVIEW_REFRESH_MS = 10_000;
const DIFF_CONTEXT_LINES = 2;
const MAX_DIFF_MATRIX_CELLS = 120_000;
const MAX_RENDERED_DIFF_LINES = 240;

function supportsHoverCloseControl(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

function normalizeDefinitionSymbol(symbol: string | null | undefined): string | null {
  if (!symbol) return null;
  const trimmed = symbol.trim();
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(trimmed) ? trimmed : null;
}

function isEditableEventTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select";
}

function symbolPeekItem(item: WorkspaceSymbolSearchItem): PeekResultItem {
  return {
    path: item.path,
    displayPath: item.display_path,
    name: item.name,
    kind: item.kind,
    containerName: item.container_name ?? null,
    line: item.line,
    column: item.column,
  };
}

function referencePeekItem(item: WorkspaceReferenceSearchItem): PeekResultItem {
  return {
    path: item.path,
    displayPath: item.display_path,
    name: item.name,
    kind: item.kind,
    containerName: item.container_name ?? null,
    line: item.line,
    column: item.column,
    preview: item.preview,
  };
}

function resolveSymbolContext(
  items: FileSymbolItem[],
  cursor: { line: number; column: number } | null,
): FileSymbolItem | null {
  if (!cursor) return null;
  let best: FileSymbolItem | null = null;
  for (const item of items) {
    if (item.line > cursor.line) continue;
    if (item.line === cursor.line && item.column > cursor.column) continue;
    if (
      !best
      || item.line > best.line
      || (item.line === best.line && item.column >= best.column)
    ) {
      best = item;
    }
  }
  return best;
}

function summarizeLineDiff(previousText: string, nextText: string): {
  added: number;
  removed: number;
  changed: number;
} {
  const previousLines = previousText.split("\n");
  const nextLines = nextText.split("\n");
  const overlap = Math.min(previousLines.length, nextLines.length);
  let changed = 0;
  for (let index = 0; index < overlap; index += 1) {
    if (previousLines[index] !== nextLines[index]) changed += 1;
  }
  return {
    added: Math.max(0, nextLines.length - previousLines.length),
    removed: Math.max(0, previousLines.length - nextLines.length),
    changed,
  };
}

function buildLineDiffHunks(previousText: string, nextText: string): DiffHunk[] {
  const operations = diffLineOperations(previousText, nextText);
  const hunks: DiffHunk[] = [];
  let index = 0;

  while (index < operations.length) {
    while (index < operations.length && operations[index]?.kind === "context") index += 1;
    if (index >= operations.length) break;
    const start = Math.max(0, index - DIFF_CONTEXT_LINES);
    let end = index;
    let trailingContext = 0;
    while (end < operations.length) {
      const current = operations[end];
      if (current.kind === "context") {
        trailingContext += 1;
        if (trailingContext > DIFF_CONTEXT_LINES) break;
      } else {
        trailingContext = 0;
      }
      end += 1;
    }
    hunks.push({ lines: operations.slice(start, end) });
    index = end;
  }
  return hunks;
}

function diffLineOperations(previousText: string, nextText: string): DiffLine[] {
  const previousLines = previousText.split("\n");
  const nextLines = nextText.split("\n");
  const cellCount = previousLines.length * nextLines.length;

  if (cellCount > MAX_DIFF_MATRIX_CELLS) {
    return fallbackDiffOperations(previousLines, nextLines);
  }

  const matrix = Array.from({ length: previousLines.length + 1 }, () =>
    new Array<number>(nextLines.length + 1).fill(0));

  for (let i = previousLines.length - 1; i >= 0; i -= 1) {
    for (let j = nextLines.length - 1; j >= 0; j -= 1) {
      matrix[i]![j] = previousLines[i] === nextLines[j]
        ? matrix[i + 1]![j + 1]! + 1
        : Math.max(matrix[i + 1]![j]!, matrix[i]![j + 1]!);
    }
  }

  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < previousLines.length && j < nextLines.length) {
    if (previousLines[i] === nextLines[j]) {
      lines.push({
        kind: "context",
        oldLineNumber: i + 1,
        newLineNumber: j + 1,
        text: previousLines[i] ?? "",
      });
      i += 1;
      j += 1;
      continue;
    }
    if (matrix[i + 1]![j]! >= matrix[i]![j + 1]!) {
      lines.push({
        kind: "removed",
        oldLineNumber: i + 1,
        newLineNumber: null,
        text: previousLines[i] ?? "",
      });
      i += 1;
      continue;
    }
    lines.push({
      kind: "added",
      oldLineNumber: null,
      newLineNumber: j + 1,
      text: nextLines[j] ?? "",
    });
    j += 1;
  }

  while (i < previousLines.length) {
    lines.push({
      kind: "removed",
      oldLineNumber: i + 1,
      newLineNumber: null,
      text: previousLines[i] ?? "",
    });
    i += 1;
  }
  while (j < nextLines.length) {
    lines.push({
      kind: "added",
      oldLineNumber: null,
      newLineNumber: j + 1,
      text: nextLines[j] ?? "",
    });
    j += 1;
  }
  return lines;
}

function fallbackDiffOperations(previousLines: string[], nextLines: string[]): DiffLine[] {
  let prefix = 0;
  while (
    prefix < previousLines.length
    && prefix < nextLines.length
    && previousLines[prefix] === nextLines[prefix]
  ) {
    prefix += 1;
  }

  let suffix = 0;
  while (
    suffix < previousLines.length - prefix
    && suffix < nextLines.length - prefix
    && previousLines[previousLines.length - 1 - suffix] === nextLines[nextLines.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  const lines: DiffLine[] = [];
  for (let index = 0; index < prefix; index += 1) {
    lines.push({
      kind: "context",
      oldLineNumber: index + 1,
      newLineNumber: index + 1,
      text: previousLines[index] ?? "",
    });
  }
  for (let index = prefix; index < previousLines.length - suffix; index += 1) {
    lines.push({
      kind: "removed",
      oldLineNumber: index + 1,
      newLineNumber: null,
      text: previousLines[index] ?? "",
    });
  }
  for (let index = prefix; index < nextLines.length - suffix; index += 1) {
    lines.push({
      kind: "added",
      oldLineNumber: null,
      newLineNumber: index + 1,
      text: nextLines[index] ?? "",
    });
  }
  for (let index = 0; index < suffix; index += 1) {
    const oldLineNumber = previousLines.length - suffix + index + 1;
    const newLineNumber = nextLines.length - suffix + index + 1;
    lines.push({
      kind: "context",
      oldLineNumber,
      newLineNumber,
      text: previousLines[oldLineNumber - 1] ?? "",
    });
  }
  return lines;
}

function formatDiffLineNumber(value: number | null): string {
  if (value == null) return "";
  return String(value);
}

export function FilePreviewPanel({
  client = null,
  sessionKey,
  path,
  token,
  desktopWidth = 544,
  isClosing = false,
  onResizeStart,
  onGoToDefinition,
  onFindReferences,
  onClose,
}: FilePreviewPanelProps) {
  const { t } = useTranslation();
  const [activePath, setActivePath] = useState(path);
  const [state, setState] = useState<PreviewState>({ status: "loading" });
  const [treeState, setTreeState] = useState<TreeState>({ status: "loading" });
  const [expandedDirs, setExpandedDirs] = useState<Record<string, boolean>>({});
  const [draftContent, setDraftContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isReloading, setIsReloading] = useState(false);
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [externalChange, setExternalChange] = useState<FilePreviewPayload | null>(null);
  const [ignoredExternalRevision, setIgnoredExternalRevision] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [entered, setEntered] = useState(false);
  const [supportsHoverClose, setSupportsHoverClose] = useState(supportsHoverCloseControl);
  const [activeEditorSymbol, setActiveEditorSymbol] = useState<string | null>(null);
  const [editorCursor, setEditorCursor] = useState<{ line: number; column: number } | null>(null);
  const [fileSymbolsState, setFileSymbolsState] = useState<FileSymbolState>({ status: "loading" });
  const [peekState, setPeekState] = useState<PeekState>({ status: "idle" });
  const [backHistory, setBackHistory] = useState<string[]>([]);
  const [forwardHistory, setForwardHistory] = useState<string[]>([]);
  const targetLocation = useMemo(() => parsePathTarget(activePath), [activePath]);
  const normalizedActivePath = targetLocation.path;
  const activePathRef = useRef(activePath);
  const hasUnsavedChanges = state.status === "ready" && draftContent !== state.payload.content;
  const activeSymbolContext = useMemo(
    () => fileSymbolsState.status === "ready" ? resolveSymbolContext(fileSymbolsState.items, editorCursor) : null,
    [editorCursor, fileSymbolsState],
  );
  const outlineItems = useMemo(
    () => fileSymbolsState.status === "ready" && Array.isArray(fileSymbolsState.items) ? fileSymbolsState.items : [],
    [fileSymbolsState],
  );
  const activeContextParts = useMemo(
    () => activeSymbolContext ? [activeSymbolContext.container_name, activeSymbolContext.name].filter(Boolean) as string[] : [],
    [activeSymbolContext],
  );

  const previewErrorMessage = useCallback((error: unknown): string => {
    return error instanceof ApiError
      ? (error.status === 404 && /API route not found/i.test(error.message)
        ? t("filePreview.routeMissing", {
          defaultValue: "File preview needs the latest gateway. Restart teai_builder gateway and try again.",
        })
        : error.message)
      : t("filePreview.failed", { defaultValue: "Could not preview this file." });
  }, [t]);

  useEffect(() => {
    activePathRef.current = activePath;
  }, [activePath]);

  const resetNavigationUiState = useCallback(() => {
    setIsReviewOpen(false);
    setPeekState({ status: "idle" });
    setExternalChange(null);
    setIgnoredExternalRevision(null);
    setSaveError(null);
    setSaveNotice(null);
  }, []);

  const confirmDiscardChanges = useCallback((): boolean => {
    if (!hasUnsavedChanges || typeof window === "undefined" || typeof window.confirm !== "function") return true;
    return window.confirm(
      t("filePreview.unsavedPrompt", {
        defaultValue: "Discard unsaved changes?",
      }),
    );
  }, [hasUnsavedChanges, t]);

  const navigateToPath = useCallback((nextPath: string, history: "push" | "back" | "forward" | "replace" = "push") => {
    if (nextPath === activePathRef.current) return;
    if (!confirmDiscardChanges()) return;
    const currentPath = activePathRef.current;
    if (history === "push") {
      setBackHistory((current) => (currentPath ? [...current, currentPath] : current));
      setForwardHistory([]);
    } else if (history === "back") {
      setBackHistory((current) => current.slice(0, -1));
      setForwardHistory((current) => (currentPath ? [currentPath, ...current] : current));
    } else if (history === "forward") {
      setForwardHistory((current) => current.slice(1));
      setBackHistory((current) => (currentPath ? [...current, currentPath] : current));
    } else {
      setForwardHistory([]);
    }
    setActivePath(nextPath);
    resetNavigationUiState();
  }, [confirmDiscardChanges, resetNavigationUiState]);

  useEffect(() => {
    if (path === activePathRef.current) return;
    const currentPath = activePathRef.current;
    setBackHistory((current) => (currentPath ? [...current, currentPath] : current));
    setForwardHistory([]);
    setActivePath(path);
    resetNavigationUiState();
  }, [path, resetNavigationUiState]);

  useEffect(() => {
    setActiveEditorSymbol(null);
    setEditorCursor(null);
    setPeekState({ status: "idle" });
  }, [activePath, isEditing]);

  useEffect(() => {
    if (state.status !== "ready") return;
    let cancelled = false;
    setFileSymbolsState({ status: "loading" });
    fetchFileSymbols(token, sessionKey, state.payload.path)
      .then((payload) => {
        if (cancelled) return;
        setFileSymbolsState({
          status: "ready",
          items: Array.isArray(payload.items) ? payload.items : [],
        });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setFileSymbolsState({
          status: "error",
          message: error instanceof Error ? error.message : t("filePreview.symbolContextFailed", {
            defaultValue: "Could not load file symbols.",
          }),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [sessionKey, state, t, token]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isEditableEventTarget(event.target)) return;
      if (event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.key === "ArrowLeft") {
        const previousPath = backHistory[backHistory.length - 1];
        if (!previousPath) return;
        event.preventDefault();
        navigateToPath(previousPath, "back");
        return;
      }
      if (event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.key === "ArrowRight") {
        const nextPath = forwardHistory[0];
        if (!nextPath) return;
        event.preventDefault();
        navigateToPath(nextPath, "forward");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [backHistory, forwardHistory, navigateToPath]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => setEntered(true));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(hover: hover) and (pointer: fine)");
    const update = () => setSupportsHoverClose(query.matches);
    update();
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", update);
      return () => query.removeEventListener("change", update);
    }
    query.addListener(update);
    return () => query.removeListener(update);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setTreeState({ status: "loading" });
    fetchWorkspaceTree(token, sessionKey)
      .then((payload) => {
        if (cancelled) return;
        setTreeState({ status: "ready", payload });
        setExpandedDirs((current) => ({
          ...expandForPath(payload.root, normalizedActivePath),
          ...current,
        }));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof ApiError
          ? error.message
          : t("filePreview.treeFailed", { defaultValue: "Could not load the workspace tree." });
        setTreeState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [normalizedActivePath, sessionKey, t, token]);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchFilePreview(token, sessionKey, activePath)
      .then((payload) => {
        if (!cancelled) setState({ status: "ready", payload });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: previewErrorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [activePath, previewErrorMessage, sessionKey, token]);

  useEffect(() => {
    if (treeState.status !== "ready") return;
    setExpandedDirs((current) => ({
      ...expandForPath(treeState.payload.root, normalizedActivePath),
      ...current,
    }));
  }, [normalizedActivePath, treeState]);

  useEffect(() => {
    if (state.status !== "ready") return;
    setDraftContent(state.payload.content);
    setIsEditing(false);
    setIsSaving(false);
    setIsReloading(false);
    setIsReviewOpen(false);
    setExternalChange(null);
    setIgnoredExternalRevision(null);
    setSaveError(null);
  }, [state]);

  const displayPath = state.status === "ready" ? state.payload.display_path : activePath;
  const previewPath = state.status === "ready" ? state.payload.path : displayPath;
  const normalizedPreviewPath = previewPath.replace(/\\/g, "/");
  const hasRootPrefix = normalizedPreviewPath.startsWith("/");
  const { name } = splitFilePath(displayPath);
  const breadcrumbs = useMemo(
    () => normalizedPreviewPath.split("/").filter(Boolean),
    [normalizedPreviewPath],
  );
  const compactBreadcrumbs = useMemo(
    () => (breadcrumbs.length > 2 ? breadcrumbs.slice(-2) : breadcrumbs),
    [breadcrumbs],
  );
  const hasCompactPrefix = breadcrumbs.length > compactBreadcrumbs.length;
  const activeChatId = useMemo(() => {
    if (!sessionKey.startsWith("websocket:")) return null;
    return sessionKey.slice("websocket:".length) || null;
  }, [sessionKey]);
  const canEdit = state.status === "ready"
    && !state.payload.truncated
    && !!client
    && !!activeChatId;
  const editorValue = state.status === "ready" && isEditing ? draftContent : (state.status === "ready" ? state.payload.content : "");
  const isDirty = hasUnsavedChanges;
  const reviewBasePayload = externalChange ?? (state.status === "ready" ? state.payload : null);
  const diffSummary = useMemo(
    () => (reviewBasePayload
      ? summarizeLineDiff(reviewBasePayload.content, draftContent)
      : { added: 0, removed: 0, changed: 0 }),
    [draftContent, reviewBasePayload],
  );
  const hasExternalConflict = !!externalChange;
  const diffHunks = useMemo(
    () => (reviewBasePayload
      ? buildLineDiffHunks(reviewBasePayload.content, draftContent)
      : []),
    [draftContent, reviewBasePayload],
  );
  const renderedDiffLineCount = useMemo(
    () => diffHunks.reduce((count, hunk) => count + hunk.lines.length, 0),
    [diffHunks],
  );
  const visibleDiffHunks = useMemo(() => {
    if (renderedDiffLineCount <= MAX_RENDERED_DIFF_LINES) return diffHunks;
    let remaining = MAX_RENDERED_DIFF_LINES;
    const clipped: DiffHunk[] = [];
    for (const hunk of diffHunks) {
      if (remaining <= 0) break;
      const lines = hunk.lines.slice(0, remaining);
      clipped.push({ lines });
      remaining -= lines.length;
    }
    return clipped;
  }, [diffHunks, renderedDiffLineCount]);
  const locationNotice = useMemo(() => {
    if (state.status !== "ready" || !targetLocation.line) return null;
    const lines = state.payload.content.split("\n");
    const previewLine = lines[targetLocation.line - 1]?.trim() ?? "";
    return {
      line: targetLocation.line,
      column: targetLocation.column,
      preview: previewLine.length > 180 ? `${previewLine.slice(0, 177)}...` : previewLine,
    };
  }, [state, targetLocation.column, targetLocation.line]);

  useEffect(() => {
    if (state.status !== "ready" || state.payload.truncated || typeof window === "undefined") return undefined;
    let cancelled = false;
    const currentPayload = state.payload;
    const refresh = async () => {
      if (isSaving || isReloading) return;
      try {
        const latest = await fetchFilePreview(token, sessionKey, activePath);
        if (cancelled || latest.path !== currentPayload.path) return;
        if (latest.revision === currentPayload.revision) {
          if (externalChange?.revision === latest.revision) setExternalChange(null);
          return;
        }
        if (ignoredExternalRevision && latest.revision === ignoredExternalRevision) return;
        if (!isEditing && !isDirty) {
          setState({ status: "ready", payload: latest });
          setSaveNotice(t("filePreview.externalReloaded", {
            defaultValue: "File changed on disk and was reloaded.",
          }));
          return;
        }
        setExternalChange(latest);
      } catch {
        // Keep background refresh silent; user-facing errors already surface on explicit actions.
      }
    };
    const timer = window.setInterval(() => {
      void refresh();
    }, FILE_PREVIEW_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    activePath,
    externalChange?.revision,
    ignoredExternalRevision,
    isDirty,
    isEditing,
    isReloading,
    isSaving,
    sessionKey,
    state,
    t,
    token,
  ]);

  useEffect(() => {
    if (!isDirty || typeof window === "undefined") return undefined;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  function handleCloseRequest(): void {
    if (!confirmDiscardChanges()) return;
    onClose();
  }

  function handleCancelEdit(): void {
    if (isDirty && !confirmDiscardChanges()) return;
    if (state.status === "ready") setDraftContent(state.payload.content);
    setIsEditing(false);
    setSaveError(null);
    setSaveNotice(null);
  }

  function handleRevert(): void {
    if (state.status !== "ready") return;
    setDraftContent(state.payload.content);
    setIsReviewOpen(false);
    setExternalChange(null);
    setIgnoredExternalRevision(null);
    setSaveError(null);
    setSaveNotice(null);
  }

  function handleSelectFile(nextPath: string): void {
    if (nextPath === normalizedActivePath) return;
    navigateToPath(nextPath, "push");
  }

  function handleNavigateBack(): void {
    const previousPath = backHistory[backHistory.length - 1];
    if (!previousPath) return;
    navigateToPath(previousPath, "back");
  }

  function handleNavigateForward(): void {
    const nextPath = forwardHistory[0];
    if (!nextPath) return;
    navigateToPath(nextPath, "forward");
  }

  function handleKeepDraft(): void {
    if (!externalChange) return;
    setIgnoredExternalRevision(externalChange.revision);
    setExternalChange(null);
    setIsReviewOpen(false);
    setSaveNotice(t("filePreview.keepDraftNotice", {
      defaultValue: "Kept your draft locally. Reload latest disk changes before saving.",
    }));
  }

  function applyLatestPayload(payload: FilePreviewPayload, notice: string): void {
    setState({ status: "ready", payload });
    setDraftContent(payload.content);
    setIsEditing(false);
    setIsReviewOpen(false);
    setExternalChange(null);
    setIgnoredExternalRevision(null);
    setSaveError(null);
    setSaveNotice(notice);
  }

  function handleReloadExternal(): void {
    if (!externalChange) return;
    applyLatestPayload(
      externalChange,
      t("filePreview.externalReloaded", {
        defaultValue: "File changed on disk and was reloaded.",
      }),
    );
  }

  const handleGoToDefinition = useCallback((symbolOverride?: string | null) => {
    if (state.status !== "ready" || !onGoToDefinition) return;
    const symbol = normalizeDefinitionSymbol(symbolOverride ?? activeEditorSymbol);
    if (!symbol) return;
    onGoToDefinition({
      symbol,
      sourcePath: state.payload.path,
    });
  }, [activeEditorSymbol, onGoToDefinition, state]);

  const handleFindReferences = useCallback((symbolOverride?: string | null) => {
    if (state.status !== "ready" || !onFindReferences) return;
    const symbol = normalizeDefinitionSymbol(symbolOverride ?? activeEditorSymbol);
    if (!symbol) return;
    onFindReferences({
      symbol,
      sourcePath: state.payload.path,
    });
  }, [activeEditorSymbol, onFindReferences, state]);

  const handlePeek = useCallback(async (mode: PeekMode, symbolOverride?: string | null) => {
    if (state.status !== "ready") return;
    const symbol = normalizeDefinitionSymbol(symbolOverride ?? activeEditorSymbol);
    if (!symbol) return;
    setPeekState({ status: "loading", mode, symbol });
    try {
      if (mode === "definition") {
        const payload = await fetchWorkspaceSymbolSearch(token, sessionKey, symbol, 8);
        const exact = payload.items.filter((item) => item.name.toLowerCase() === symbol.toLowerCase());
        const ranked = (exact.length > 0 ? exact : payload.items).slice(0, 8).map(symbolPeekItem);
        setPeekState({ status: "ready", mode, symbol, items: ranked });
        return;
      }
      const payload = await fetchWorkspaceReferenceSearch(token, sessionKey, symbol, 8);
      setPeekState({
        status: "ready",
        mode,
        symbol,
        items: payload.items.slice(0, 8).map(referencePeekItem),
      });
    } catch (error) {
      setPeekState({
        status: "error",
        mode,
        symbol,
        message: error instanceof Error ? error.message : t("filePreview.peekFailed", {
          defaultValue: "Could not load peek results.",
        }),
      });
    }
  }, [activeEditorSymbol, sessionKey, state, t, token]);

  const handleOpenPeekResult = useCallback((path: string) => {
    navigateToPath(path, "push");
  }, [navigateToPath]);

  async function handleReload(): Promise<void> {
    if (state.status !== "ready" || isReloading || isSaving) return;
    if (!confirmDiscardChanges()) return;
    setIsReloading(true);
    setIsReviewOpen(false);
    setSaveError(null);
    setSaveNotice(null);
    try {
      const payload = await fetchFilePreview(token, sessionKey, activePath);
      applyLatestPayload(
        payload,
        t("filePreview.reloadSuccess", { defaultValue: "Reloaded latest file from disk." }),
      );
    } catch (error) {
      setSaveError(previewErrorMessage(error));
    } finally {
      setIsReloading(false);
    }
  }

  async function handleSave(): Promise<void> {
    if (!client || !activeChatId || state.status !== "ready" || !isDirty) return;
    setIsSaving(true);
    setSaveError(null);
    setSaveNotice(null);
    try {
      const payload = await client.saveFile(activeChatId, state.payload.path, draftContent, {
        baseRevision: state.payload.revision,
      });
      setState({ status: "ready", payload });
      setDraftContent(payload.content);
      setIsEditing(false);
      setExternalChange(null);
      setIgnoredExternalRevision(null);
      setSaveNotice(t("filePreview.saveSuccess", { defaultValue: "File saved." }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      if (message === "file changed on disk") {
        try {
          const latest = await fetchFilePreview(token, sessionKey, activePath);
          setExternalChange(latest);
          setIsReviewOpen(true);
        } catch {
          // If the latest preview fetch fails, still surface the conflict message.
        }
        setSaveError(t("filePreview.saveConflict", {
          defaultValue: "File changed on disk. Review or reload the latest version before saving.",
        }));
      } else {
        setSaveError(message || t("filePreview.saveFailed", { defaultValue: "Could not save this file." }));
      }
    } finally {
      setIsSaving(false);
    }
  }

  function handleReviewBeforeSave(): void {
    if (!isDirty || isSaving || isReloading) return;
    setIsReviewOpen(true);
    setSaveError(null);
    setSaveNotice(null);
  }

  return (
    <aside
      aria-label={t("filePreview.aria", { defaultValue: "File preview" })}
      style={{
        "--file-preview-width": `${desktopWidth}px`,
        "--file-preview-slot-width": !entered || isClosing ? "0px" : `${desktopWidth}px`,
      } as CSSProperties}
      className={cn(
        "absolute inset-y-0 right-0 z-30 w-[min(92vw,var(--file-preview-slot-width))] overflow-hidden",
        "transition-[width] duration-300 ease-out will-change-[width]",
        "md:relative md:z-auto md:w-[var(--file-preview-slot-width)] md:min-w-0 md:shrink-0",
        isClosing && "pointer-events-none",
      )}
      data-testid="file-preview-panel"
      data-file-preview-panel
    >
      <div
        className={cn(
          "absolute inset-y-0 right-0 flex w-[min(92vw,var(--file-preview-width))] flex-col overflow-hidden md:w-[var(--file-preview-width)]",
          "border-l border-border/70 bg-background shadow-2xl md:shadow-none",
          "transition-[opacity,transform] duration-300 ease-out will-change-transform",
          !entered || isClosing ? "translate-x-full opacity-0" : "translate-x-0 opacity-100",
          "motion-reduce:translate-x-0",
        )}
      >
        {onResizeStart ? (
          <button
            type="button"
            aria-label={t("filePreview.resize", { defaultValue: "Resize file preview" })}
            className={cn(
              "group absolute inset-y-0 left-0 z-20 hidden w-3 -translate-x-1/2 cursor-col-resize touch-none md:flex",
              "items-stretch justify-center focus-visible:outline-none",
            )}
            onPointerDown={onResizeStart}
          >
            <span
              aria-hidden
              className={cn(
                "h-full w-px bg-foreground/25 opacity-0 transition-opacity",
                "group-hover:opacity-100 group-focus-visible:bg-ring group-focus-visible:opacity-100",
              )}
            />
          </button>
        ) : null}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border/60 px-3">
            {supportsHoverClose ? (
              <div
                className={cn(
                  "group inline-flex max-w-full min-w-0 items-center gap-2 rounded-[12px]",
                  "bg-muted/70 px-2.5 py-1.5 text-sm font-medium",
                )}
                title={name || displayPath}
              >
                <button
                  type="button"
                  onClick={handleCloseRequest}
                  className={cn(
                    "relative inline-flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-full",
                    "text-muted-foreground/75 transition-[background-color,color,opacity] duration-150 ease-out",
                    "group-hover:bg-foreground group-hover:text-background group-hover:opacity-100",
                    "group-focus-within:bg-foreground group-focus-within:text-background",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                  aria-label={t("filePreview.close", { defaultValue: "Close file preview" })}
                >
                  <FileText
                    className={cn(
                      "absolute h-4 w-4 transition-all duration-150 ease-out",
                      "opacity-100 group-hover:scale-75 group-hover:opacity-0",
                      "group-focus-within:scale-75 group-focus-within:opacity-0",
                    )}
                    aria-hidden
                  />
                  <X
                    className={cn(
                      "absolute h-3.5 w-3.5 scale-75 opacity-0 transition-all duration-150 ease-out",
                      "group-hover:scale-100 group-hover:opacity-100",
                      "group-focus-within:scale-100 group-focus-within:opacity-100",
                    )}
                    aria-hidden
                  />
                </button>
                <span className="min-w-0 truncate">{name || displayPath}</span>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleCloseRequest}
                  className={cn(
                    "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                    "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                  aria-label={t("filePreview.close", { defaultValue: "Close file preview" })}
                >
                  <X className="h-5 w-5" aria-hidden />
                </button>
                <span className="min-w-0 truncate text-sm font-medium">
                  {name || displayPath}
                </span>
              </>
            )}
            {state.status === "ready" ? (
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  className={cn(
                    "inline-flex h-8 w-8 items-center justify-center rounded-md border border-border/50",
                    "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    backHistory.length === 0 && "cursor-not-allowed opacity-60",
                  )}
                  onClick={handleNavigateBack}
                  disabled={backHistory.length === 0}
                  aria-label={t("filePreview.goBack", { defaultValue: "Go back" })}
                  title={t("filePreview.goBackShortcut", { defaultValue: "Go back (Alt+Left)" })}
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                </button>
                <button
                  type="button"
                  className={cn(
                    "inline-flex h-8 w-8 items-center justify-center rounded-md border border-border/50",
                    "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    forwardHistory.length === 0 && "cursor-not-allowed opacity-60",
                  )}
                  onClick={handleNavigateForward}
                  disabled={forwardHistory.length === 0}
                  aria-label={t("filePreview.goForward", { defaultValue: "Go forward" })}
                  title={t("filePreview.goForwardShortcut", { defaultValue: "Go forward (Alt+Right)" })}
                >
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </button>
                {isDirty ? (
                  <>
                    <span className="rounded-full bg-amber-500/12 px-2.5 py-1 text-[11px] font-medium text-amber-700 dark:text-amber-200">
                      {t("filePreview.unsaved", { defaultValue: "Unsaved changes" })}
                    </span>
                    <span className="hidden rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground sm:inline-flex">
                      {t("filePreview.diffSummary", {
                        defaultValue: "+{{added}} -{{removed}} ~{{changed}} lines",
                        added: diffSummary.added,
                        removed: diffSummary.removed,
                        changed: diffSummary.changed,
                      })}
                    </span>
                  </>
                ) : null}
                {isEditing ? (
                  <>
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        (!activeEditorSymbol || isSaving || isReloading) && "cursor-not-allowed opacity-60",
                      )}
                      onClick={() => { void handlePeek("references"); }}
                      disabled={!activeEditorSymbol || isSaving || isReloading}
                      title={activeEditorSymbol
                        ? t("filePreview.peekReferencesReady", {
                          defaultValue: "Peek references for {{symbol}}",
                          symbol: activeEditorSymbol,
                        })
                        : t("filePreview.peekReferencesHint", {
                          defaultValue: "Place the cursor on a symbol to peek its references.",
                        })}
                    >
                      <Search className="h-3.5 w-3.5" aria-hidden />
                      {t("filePreview.peekReferences", { defaultValue: "Peek references" })}
                    </button>
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        (!activeEditorSymbol || isSaving || isReloading) && "cursor-not-allowed opacity-60",
                      )}
                      onClick={() => { void handlePeek("definition"); }}
                      disabled={!activeEditorSymbol || isSaving || isReloading}
                      title={activeEditorSymbol
                        ? t("filePreview.peekDefinitionReady", {
                          defaultValue: "Peek definition for {{symbol}}",
                          symbol: activeEditorSymbol,
                        })
                        : t("filePreview.peekDefinitionHint", {
                          defaultValue: "Place the cursor on a symbol to peek its definition.",
                        })}
                    >
                      <Eye className="h-3.5 w-3.5" aria-hidden />
                      {t("filePreview.peekDefinition", { defaultValue: "Peek definition" })}
                    </button>
                    {onFindReferences ? (
                      <button
                        type="button"
                        className={cn(
                          "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                          "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          (!activeEditorSymbol || isSaving || isReloading) && "cursor-not-allowed opacity-60",
                        )}
                        onClick={() => handleFindReferences()}
                        disabled={!activeEditorSymbol || isSaving || isReloading}
                        title={activeEditorSymbol
                          ? t("filePreview.findReferencesReady", {
                            defaultValue: "Find references for {{symbol}}",
                            symbol: activeEditorSymbol,
                          })
                          : t("filePreview.findReferencesHint", {
                            defaultValue: "Place the cursor on a symbol to search its references.",
                          })}
                      >
                        <GitBranch className="h-3.5 w-3.5" aria-hidden />
                        {t("filePreview.findReferences", { defaultValue: "Find references" })}
                      </button>
                    ) : null}
                    {onGoToDefinition ? (
                      <button
                        type="button"
                        className={cn(
                          "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                          "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          (!activeEditorSymbol || isSaving || isReloading) && "cursor-not-allowed opacity-60",
                        )}
                        onClick={() => handleGoToDefinition()}
                        disabled={!activeEditorSymbol || isSaving || isReloading}
                        title={activeEditorSymbol
                          ? t("filePreview.goToDefinitionReady", {
                            defaultValue: "Go to definition for {{symbol}}",
                            symbol: activeEditorSymbol,
                          })
                          : t("filePreview.goToDefinitionHint", {
                            defaultValue: "Place the cursor on a symbol to jump to its definition.",
                          })}
                      >
                        <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                        {t("filePreview.goToDefinition", { defaultValue: "Go to definition" })}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      )}
                      onClick={handleCancelEdit}
                      disabled={isSaving}
                    >
                      {t("filePreview.cancelEdit", { defaultValue: "Cancel" })}
                    </button>
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        (!isDirty || isSaving || isReloading) && "cursor-not-allowed opacity-60",
                      )}
                      onClick={handleRevert}
                      disabled={!isDirty || isSaving || isReloading}
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                      {t("filePreview.revert", { defaultValue: "Revert" })}
                    </button>
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        (!isDirty || isSaving || isReloading) && "cursor-not-allowed opacity-60",
                      )}
                      onClick={() => setIsReviewOpen((current) => !current)}
                      disabled={!isDirty || isSaving || isReloading}
                    >
                      <Eye className="h-3.5 w-3.5" aria-hidden />
                      {isReviewOpen
                        ? t("filePreview.hideReview", { defaultValue: "Hide review" })
                        : t("filePreview.reviewChanges", { defaultValue: "Review changes" })}
                    </button>
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                        "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        (isSaving || isReloading) && "cursor-not-allowed opacity-60",
                      )}
                      onClick={() => { void handleReload(); }}
                      disabled={isSaving || isReloading}
                    >
                      {isReloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
                      {isReloading
                        ? t("filePreview.reloading", { defaultValue: "Reloading..." })
                        : t("filePreview.reload", { defaultValue: "Reload" })}
                    </button>
                    <button
                      type="button"
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground",
                        "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        (isSaving || isReloading || !isDirty) && "cursor-not-allowed opacity-60",
                      )}
                      onClick={() => {
                        if (!isReviewOpen) {
                          handleReviewBeforeSave();
                          return;
                        }
                        void handleSave();
                      }}
                      disabled={isSaving || isReloading || !isDirty}
                    >
                      {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
                      {isSaving
                        ? t("filePreview.saving", { defaultValue: "Saving..." })
                        : (isReviewOpen
                          ? t("filePreview.saveAfterReview", { defaultValue: "Save after review" })
                          : t("filePreview.reviewAndSave", { defaultValue: "Review & save" }))}
                    </button>
                  </>
                ) : canEdit ? (
                  <button
                    type="button"
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                      "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    )}
                    onClick={() => {
                      setIsEditing(true);
                      setIsReviewOpen(false);
                      setSaveError(null);
                      setSaveNotice(null);
                    }}
                  >
                    <FilePenLine className="h-3.5 w-3.5" aria-hidden />
                    {t("filePreview.edit", { defaultValue: "Edit" })}
                  </button>
                ) : (
                  <button
                    type="button"
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                      "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      isReloading && "cursor-not-allowed opacity-60",
                    )}
                    onClick={() => { void handleReload(); }}
                    disabled={isReloading}
                  >
                    {isReloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
                    {isReloading
                      ? t("filePreview.reloading", { defaultValue: "Reloading..." })
                      : t("filePreview.reload", { defaultValue: "Reload" })}
                  </button>
                )}
              </div>
            ) : null}
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            <div
              className={cn(
                "flex min-h-10 shrink-0 items-center gap-1.5 overflow-hidden",
                "border-b border-border/45 px-4 text-[13px] text-muted-foreground",
              )}
              title={previewPath}
            >
              <div className="flex min-w-0 items-center gap-1.5">
                {hasCompactPrefix ? (
                  <span className="shrink-0 text-muted-foreground/55">...</span>
                ) : hasRootPrefix ? (
                  <span className="shrink-0 text-muted-foreground/55">/</span>
                ) : null}
                {compactBreadcrumbs.length > 0 ? (
                  compactBreadcrumbs.map((part, index) => (
                    <span key={`${part}-${index}`} className="flex min-w-0 items-center gap-1.5">
                      {index > 0 || hasCompactPrefix || hasRootPrefix ? (
                        <ChevronRight
                          className="h-3 w-3 shrink-0 text-muted-foreground/40"
                          aria-hidden
                        />
                      ) : null}
                      <span
                        className={cn(
                          "min-w-0 truncate",
                          index === compactBreadcrumbs.length - 1
                            ? "font-medium text-foreground"
                            : "max-w-[42vw] shrink text-muted-foreground/76",
                        )}
                      >
                        {part}
                      </span>
                    </span>
                  ))
                ) : (
                  <span className="truncate">{previewPath}</span>
                )}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
              <div className="flex h-full min-h-0">
                <div className="hidden w-60 shrink-0 border-r border-border/50 bg-muted/20 md:flex md:flex-col">
                  <div className="flex h-10 items-center border-b border-border/45 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t("filePreview.workspaceTree", { defaultValue: "Workspace files" })}
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto p-2">
                    {treeState.status === "loading" ? (
                      <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        {t("filePreview.loadingTree", { defaultValue: "Loading files..." })}
                      </div>
                    ) : treeState.status === "error" ? (
                      <div className="px-2 py-2 text-xs text-muted-foreground">{treeState.message}</div>
                    ) : (
                      <div className="space-y-1">
                        <WorkspaceTreeBranch
                          node={treeState.payload.root}
                          activePath={state.status === "ready" ? state.payload.path : normalizedActivePath}
                          expandedDirs={expandedDirs}
                          onToggleDirectory={(dirPath) => {
                            setExpandedDirs((current) => ({
                              ...current,
                              [dirPath]: !current[dirPath],
                            }));
                          }}
                          onSelectFile={handleSelectFile}
                        />
                        {treeState.payload.truncated ? (
                          <div className="px-2 pt-2 text-[11px] text-muted-foreground">
                            {t("filePreview.treeTruncated", {
                              defaultValue: "Tree is trimmed for large workspaces.",
                            })}
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
                <div className="min-h-0 flex-1 overflow-auto">
                  {state.status === "loading" ? (
                    <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                      {t("filePreview.loading", { defaultValue: "Loading preview..." })}
                    </div>
                  ) : state.status === "error" ? (
                    <div className="flex h-full items-center justify-center px-8 text-center text-sm text-muted-foreground">
                      <div className="max-w-sm">
                        <AlertCircle className="mx-auto mb-3 h-5 w-5 text-muted-foreground/70" aria-hidden />
                        <p>{state.message}</p>
                      </div>
                    </div>
                  ) : (
                    <div className="min-h-full">
                      {saveError ? (
                        <div className="mx-4 mt-3 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-200">
                          {saveError}
                        </div>
                      ) : null}
                      {saveNotice ? (
                        <div className="mx-4 mt-3 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-200">
                          {saveNotice}
                        </div>
                      ) : null}
                      {locationNotice ? (
                        <div className="mx-4 mt-3 rounded-md border border-sky-500/25 bg-sky-500/10 px-3 py-2 text-xs text-sky-800 dark:text-sky-100">
                          <div className="font-medium">
                            {t("filePreview.locationNotice", {
                              defaultValue: "Opened from search result at line {{line}}",
                              line: locationNotice.line,
                            })}
                            {locationNotice.column ? `, column ${locationNotice.column}` : ""}
                          </div>
                          {locationNotice.preview ? (
                            <div className="mt-1 font-mono text-[11px] text-sky-700/90 dark:text-sky-100/90">
                              {locationNotice.preview}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      {fileSymbolsState.status === "ready" && outlineItems.length > 0 ? (
                        <div className="mx-4 mt-3 rounded-md border border-border/60 bg-muted/20" data-testid="file-preview-outline">
                          <div className="border-b border-border/50 px-3 py-2">
                            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {t("filePreview.fileOutline", { defaultValue: "File outline" })}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {t("filePreview.fileOutlineHint", {
                                defaultValue: "Jump to classes and functions in the current file.",
                              })}
                            </div>
                          </div>
                          <div className="max-h-44 overflow-auto p-2">
                            <div className="flex flex-wrap gap-2">
                              {outlineItems.map((item) => {
                                const isActiveContext = activeSymbolContext?.path === item.path;
                                return (
                                  <button
                                    key={item.path}
                                    type="button"
                                    className={cn(
                                      "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-xs transition-colors",
                                      isActiveContext
                                        ? "border-primary/35 bg-primary/10 text-primary"
                                        : "border-border/60 bg-background text-foreground hover:bg-muted",
                                    )}
                                    onClick={() => navigateToPath(item.path, "push")}
                                  >
                                    {item.container_name ? (
                                      <span className="text-muted-foreground">
                                        {item.container_name}
                                      </span>
                                    ) : null}
                                    {item.container_name ? <ChevronRight className="h-3 w-3" aria-hidden /> : null}
                                    <span className="font-medium">{item.name}</span>
                                    <span className="text-muted-foreground">
                                      {item.line}:{item.column}
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        </div>
                      ) : null}
                      {isEditing ? (
                        <div className="mx-4 mt-3 rounded-md border border-border/60 bg-muted/20 px-3 py-2" data-testid="file-preview-symbol-context">
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            {t("filePreview.symbolContext", { defaultValue: "Current scope" })}
                          </div>
                          {fileSymbolsState.status === "loading" ? (
                            <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                              {t("filePreview.symbolContextLoading", { defaultValue: "Loading symbol context..." })}
                            </div>
                          ) : fileSymbolsState.status === "error" ? (
                            <div className="mt-1 text-sm text-rose-700 dark:text-rose-200">
                              {fileSymbolsState.message}
                            </div>
                          ) : activeContextParts.length > 0 && activeSymbolContext ? (
                            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm">
                              {activeContextParts.map((part, index) => (
                                <span key={`${part}-${index}`} className="flex items-center gap-1.5">
                                  {index > 0 ? <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50" aria-hidden /> : null}
                                  <span className={cn(
                                    "rounded-full border border-border/60 px-2.5 py-1",
                                    index === activeContextParts.length - 1
                                      ? "bg-background font-medium text-foreground"
                                      : "bg-muted text-muted-foreground",
                                  )}>
                                    {part}
                                  </span>
                                </span>
                              ))}
                              <span className="ml-1 text-xs text-muted-foreground">
                                {activeSymbolContext.line}:{activeSymbolContext.column}
                              </span>
                            </div>
                          ) : (
                            <div className="mt-1 text-sm text-muted-foreground">
                              {t("filePreview.symbolContextEmpty", {
                                defaultValue: "Move the cursor into a symbol to show its scope.",
                              })}
                            </div>
                          )}
                        </div>
                      ) : null}
                      {isEditing && peekState.status !== "idle" ? (
                        <div className="mx-4 mt-3 rounded-md border border-border/60 bg-muted/20" data-testid="file-preview-peek">
                          <div className="flex items-center justify-between gap-3 border-b border-border/50 px-3 py-2">
                            <div className="min-w-0">
                              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                {peekState.mode === "definition"
                                  ? t("filePreview.peekDefinitionPanel", { defaultValue: "Definition peek" })
                                  : t("filePreview.peekReferencesPanel", { defaultValue: "References peek" })}
                              </div>
                              <div className="truncate text-sm font-medium text-foreground">
                                {t("filePreview.peekSymbolLabel", {
                                  defaultValue: "Symbol: {{symbol}}",
                                  symbol: peekState.symbol,
                                })}
                              </div>
                            </div>
                            <button
                              type="button"
                              className={cn(
                                "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                                "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                              )}
                              onClick={() => setPeekState({ status: "idle" })}
                            >
                              {t("filePreview.closePeek", { defaultValue: "Close peek" })}
                            </button>
                          </div>
                          {peekState.status === "loading" ? (
                            <div className="flex items-center gap-2 px-3 py-3 text-sm text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                              {t("filePreview.peekLoading", { defaultValue: "Loading peek results..." })}
                            </div>
                          ) : peekState.status === "error" ? (
                            <div className="px-3 py-3 text-sm text-rose-700 dark:text-rose-200">
                              {peekState.message}
                            </div>
                          ) : peekState.items.length === 0 ? (
                            <div className="px-3 py-3 text-sm text-muted-foreground">
                              {peekState.mode === "definition"
                                ? t("filePreview.peekDefinitionEmpty", { defaultValue: "No matching definitions found." })
                                : t("filePreview.peekReferencesEmpty", { defaultValue: "No matching references found." })}
                            </div>
                          ) : (
                            <div className="divide-y divide-border/40">
                              {peekState.items.map((item) => (
                                <button
                                  key={item.path}
                                  type="button"
                                  className="flex w-full items-start justify-between gap-3 px-3 py-3 text-left transition-colors hover:bg-muted/50"
                                  onClick={() => handleOpenPeekResult(item.path)}
                                >
                                  <span className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-medium text-foreground">
                                      {item.name}
                                    </span>
                                    <span className="block truncate text-xs text-muted-foreground">
                                      {[item.containerName, item.kind].filter(Boolean).join(" • ")}
                                    </span>
                                    <span className="mt-1 block truncate text-xs text-foreground/80">
                                      {item.displayPath}:{item.line}{item.column ? `:${item.column}` : ""}
                                    </span>
                                    {item.preview ? (
                                      <span className="mt-1 block line-clamp-2 font-mono text-[11px] text-foreground/70">
                                        {item.preview}
                                      </span>
                                    ) : null}
                                  </span>
                                  <span className="shrink-0 rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
                                    {t("filePreview.peekJump", { defaultValue: "Jump" })}
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : null}
                      {isEditing && isDirty ? (
                        <div className="mx-4 mt-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                          {t(hasExternalConflict ? "filePreview.conflictSummaryLong" : "filePreview.diffSummaryLong", {
                            defaultValue: hasExternalConflict
                              ? "Disk version vs current draft: +{{added}} added, -{{removed}} removed, ~{{changed}} changed lines."
                              : "Current draft: +{{added}} added, -{{removed}} removed, ~{{changed}} changed lines.",
                            added: diffSummary.added,
                            removed: diffSummary.removed,
                            changed: diffSummary.changed,
                          })}
                        </div>
                      ) : null}
                      {hasExternalConflict ? (
                        <div className="mx-4 mt-3 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-3 text-xs text-amber-800 dark:text-amber-100">
                          <div className="font-medium">
                            {t("filePreview.externalChanged", {
                              defaultValue: "This file changed on disk while you were editing.",
                            })}
                          </div>
                          <div className="mt-1 text-amber-700/90 dark:text-amber-200/90">
                            {t("filePreview.externalChangedDescription", {
                              defaultValue: "Review the incoming disk version, reload it, or keep your current draft locally for now.",
                            })}
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              className={cn(
                                "inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-600/25 px-3 text-xs font-medium",
                                "text-amber-900 transition-colors hover:bg-amber-500/10 dark:text-amber-50",
                              )}
                              onClick={() => setIsReviewOpen(true)}
                            >
                              <Eye className="h-3.5 w-3.5" aria-hidden />
                              {t("filePreview.reviewConflict", { defaultValue: "Review conflict" })}
                            </button>
                            <button
                              type="button"
                              className={cn(
                                "inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-600/25 px-3 text-xs font-medium",
                                "text-amber-900 transition-colors hover:bg-amber-500/10 dark:text-amber-50",
                              )}
                              onClick={handleReloadExternal}
                            >
                              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                              {t("filePreview.reloadLatest", { defaultValue: "Reload latest" })}
                            </button>
                            <button
                              type="button"
                              className={cn(
                                "inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-600/25 px-3 text-xs font-medium",
                                "text-amber-900 transition-colors hover:bg-amber-500/10 dark:text-amber-50",
                              )}
                              onClick={handleKeepDraft}
                            >
                              {t("filePreview.keepDraft", { defaultValue: "Keep draft" })}
                            </button>
                          </div>
                        </div>
                      ) : null}
                      {isEditing && isDirty && isReviewOpen ? (
                        <div className="mx-4 mt-3 overflow-hidden rounded-lg border border-border/60 bg-muted/20">
                          <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-3 py-2">
                            <div className="min-w-0">
                              <div className="text-sm font-medium text-foreground">
                                {t(hasExternalConflict ? "filePreview.conflictReviewTitle" : "filePreview.reviewTitle", {
                                  defaultValue: hasExternalConflict ? "Latest on disk vs draft" : "Saved vs draft",
                                })}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {t(hasExternalConflict ? "filePreview.conflictReviewDescription" : "filePreview.reviewDescription", {
                                  defaultValue: hasExternalConflict
                                    ? "Compare the latest disk version with your current draft before you decide what to keep."
                                    : "Compare the last saved file with the current draft before you save or reload.",
                                })}
                              </div>
                            </div>
                            <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                              <DiffPair added={diffSummary.added} deleted={diffSummary.removed} />
                              <span>
                                {t("filePreview.changedLines", {
                                  defaultValue: "~{{changed}} changed",
                                  changed: diffSummary.changed,
                                })}
                              </span>
                            </div>
                          </div>
                          <div className="border-b border-border/60 bg-background/70 px-3 py-3">
                            <div className="mb-2 flex items-center justify-between gap-3">
                              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                {t("filePreview.diffHunks", { defaultValue: "Line diff" })}
                              </div>
                              <div className="text-[11px] text-muted-foreground">
                                {t("filePreview.diffLinesShown", {
                                  defaultValue: "Showing {{visible}} of {{total}} diff lines",
                                  visible: Math.min(renderedDiffLineCount, MAX_RENDERED_DIFF_LINES),
                                  total: renderedDiffLineCount,
                                })}
                              </div>
                            </div>
                            <div className="space-y-3">
                              {visibleDiffHunks.map((hunk, hunkIndex) => (
                                <div
                                  key={`diff-hunk-${hunkIndex}`}
                                  className="overflow-hidden rounded-md border border-border/50 bg-background"
                                  data-testid="file-preview-diff-hunk"
                                >
                                  <div className="border-b border-border/50 bg-muted/40 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                    {t("filePreview.diffHunk", {
                                      defaultValue: "Change block {{index}}",
                                      index: hunkIndex + 1,
                                    })}
                                  </div>
                                  <div className="overflow-auto">
                                    {hunk.lines.map((line, lineIndex) => (
                                      <div
                                        key={`diff-line-${hunkIndex}-${lineIndex}-${line.oldLineNumber ?? "n"}-${line.newLineNumber ?? "n"}`}
                                        className={cn(
                                          "grid grid-cols-[3.5rem_3.5rem_1.5rem_minmax(0,1fr)] items-start gap-2 px-3 py-1 font-mono text-[12px] leading-5",
                                          line.kind === "added" && "bg-emerald-500/8 text-emerald-900 dark:text-emerald-100",
                                          line.kind === "removed" && "bg-rose-500/8 text-rose-900 dark:text-rose-100",
                                        )}
                                      >
                                        <span className="text-right text-muted-foreground/80">
                                          {formatDiffLineNumber(line.oldLineNumber)}
                                        </span>
                                        <span className="text-right text-muted-foreground/80">
                                          {formatDiffLineNumber(line.newLineNumber)}
                                        </span>
                                        <span
                                          className={cn(
                                            "text-center font-semibold",
                                            line.kind === "added" && "text-emerald-700 dark:text-emerald-200",
                                            line.kind === "removed" && "text-rose-700 dark:text-rose-200",
                                            line.kind === "context" && "text-muted-foreground/70",
                                          )}
                                        >
                                          {line.kind === "added" ? "+" : line.kind === "removed" ? "-" : " "}
                                        </span>
                                        <span className="min-w-0 whitespace-pre-wrap break-words">{line.text || " "}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                            {renderedDiffLineCount > MAX_RENDERED_DIFF_LINES ? (
                              <div className="mt-2 text-[11px] text-muted-foreground">
                                {t("filePreview.diffTruncated", {
                                  defaultValue: "Large diff preview trimmed for readability. Use the side-by-side snapshots below for the full reviewed content.",
                                })}
                              </div>
                            ) : null}
                          </div>
                          <div className="grid gap-3 p-3 xl:grid-cols-2">
                            <div className="min-w-0">
                              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                {t(hasExternalConflict ? "filePreview.externalSnapshot" : "filePreview.savedSnapshot", {
                                  defaultValue: hasExternalConflict ? "Latest on disk" : "Saved file",
                                })}
                              </div>
                              <div className="max-h-72 overflow-auto rounded-md border border-border/50 bg-background">
                                <CodeBlock
                                  language={reviewBasePayload?.language}
                                  code={reviewBasePayload?.content ?? ""}
                                  chrome="none"
                                  showLineNumbers
                                  wrapLongLines={false}
                                />
                              </div>
                            </div>
                            <div className="min-w-0">
                              <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                {t("filePreview.draftSnapshot", { defaultValue: "Current draft" })}
                              </div>
                              <div className="max-h-72 overflow-auto rounded-md border border-border/50 bg-background">
                                <CodeBlock
                                  language={state.payload.language}
                                  code={draftContent}
                                  chrome="none"
                                  showLineNumbers
                                  wrapLongLines={false}
                                />
                              </div>
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/60 px-3 py-3">
                            <button
                              type="button"
                              className={cn(
                                "inline-flex h-8 items-center gap-1.5 rounded-md border border-border/50 px-3 text-xs font-medium",
                                "text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                              )}
                              onClick={() => setIsReviewOpen(false)}
                              disabled={isSaving}
                            >
                              {t("filePreview.hideReview", { defaultValue: "Hide review" })}
                            </button>
                            <button
                              type="button"
                              className={cn(
                                "inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground",
                                "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                isSaving && "cursor-not-allowed opacity-60",
                              )}
                              onClick={() => { void handleSave(); }}
                              disabled={isSaving}
                            >
                              {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
                              {isSaving
                                ? t("filePreview.saving", { defaultValue: "Saving..." })
                                : t("filePreview.saveAfterReview", { defaultValue: "Save after review" })}
                            </button>
                          </div>
                        </div>
                      ) : null}
                      {state.payload.truncated ? (
                        <div className="mx-4 mt-3 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-200">
                          {t("filePreview.truncated", {
                            defaultValue: "Preview is truncated because this file is large.",
                          })}
                        </div>
                      ) : null}
                      {!state.payload.truncated && !client ? (
                        <div className="mx-4 mt-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                          {t("filePreview.editUnavailable", {
                            defaultValue: "Editing is unavailable until the live client is connected.",
                          })}
                        </div>
                      ) : null}
                      {state.payload.language && isEditing ? (
                        <MonacoEditor
                          files={[{ path: state.payload.path, language: state.payload.language }]}
                          value={draftContent}
                          onChange={setDraftContent}
                          onActiveWordChange={setActiveEditorSymbol}
                          onCursorPositionChange={setEditorCursor}
                          onRequestDefinition={handleGoToDefinition}
                          onRequestReferences={handleFindReferences}
                          readOnly={false}
                          height={520}
                        />
                      ) : (
                        <CodeBlock
                          language={state.payload.language}
                          code={editorValue}
                          chrome="none"
                          showLineNumbers
                          wrapLongLines={false}
                          className="min-h-full"
                        />
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
        </div>
      </div>
      </div>
    </aside>
  );
}

function WorkspaceTreeBranch({
  node,
  activePath,
  expandedDirs,
  onToggleDirectory,
  onSelectFile,
  depth = 0,
}: {
  node: WorkspaceTreeNode;
  activePath: string;
  expandedDirs: Record<string, boolean>;
  onToggleDirectory: (path: string) => void;
  onSelectFile: (path: string) => void;
  depth?: number;
}) {
  const isDirectory = node.kind === "directory";
  const isExpanded = isDirectory && expandedDirs[node.path] !== false;
  const children = node.children ?? [];

  if (!isDirectory) {
    return (
      <button
        type="button"
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
          activePath === node.path
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onSelectFile(node.path)}
      >
        <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate">{node.name}</span>
      </button>
    );
  }

  return (
    <div>
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground/85 transition-colors hover:bg-muted/60"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onToggleDirectory(node.path)}
      >
        <ChevronRight
          className={cn("h-3.5 w-3.5 shrink-0 transition-transform", isExpanded && "rotate-90")}
          aria-hidden
        />
        {isExpanded ? (
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        ) : (
          <Folder className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isExpanded ? (
        <div className="space-y-0.5">
          {children.map((child) => (
            <WorkspaceTreeBranch
              key={child.path}
              node={child}
              activePath={activePath}
              expandedDirs={expandedDirs}
              onToggleDirectory={onToggleDirectory}
              onSelectFile={onSelectFile}
              depth={depth + 1}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function expandForPath(root: WorkspaceTreeNode, path: string): Record<string, boolean> {
  const expanded: Record<string, boolean> = {};

  function walk(node: WorkspaceTreeNode): boolean {
    if (node.kind === "file") return node.path === path;
    let matched = node.path === path;
    for (const child of node.children ?? []) {
      matched = walk(child) || matched;
    }
    if (matched) expanded[node.path] = true;
    return matched;
  }

  walk(root);
  return expanded;
}

function parsePathTarget(path: string): { path: string; line: number | null; column: number | null } {
  const segments = path.split(":");
  if (segments.length < 2) return { path, line: null, column: null };

  const maybeColumn = segments[segments.length - 1] ?? "";
  const maybeLine = segments[segments.length - 2] ?? "";
  if (/^\d+$/.test(maybeColumn) && /^\d+$/.test(maybeLine)) {
    return {
      path: segments.slice(0, -2).join(":") || path,
      line: Number.parseInt(maybeLine, 10),
      column: Number.parseInt(maybeColumn, 10),
    };
  }
  if (/^\d+$/.test(maybeColumn)) {
    return {
      path: segments.slice(0, -1).join(":") || path,
      line: Number.parseInt(maybeColumn, 10),
      column: null,
    };
  }
  return { path, line: null, column: null };
}
