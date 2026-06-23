import type { ToolProgressEvent, UIMessage, WorkspaceProblemItem } from "@/lib/types";

interface RuntimeProblemCandidate {
  item: WorkspaceProblemItem;
  rank: number;
}

const TOOL_SOURCE_LABELS: Record<string, string> = {
  run_cli_app: "runtime-cli",
  mcp: "runtime-mcp",
};

const TEST_HINT_PATTERNS: Array<{ pattern: RegExp; source: string }> = [
  { pattern: /\bpytest\b/i, source: "runtime-pytest" },
  { pattern: /\bvitest\b/i, source: "runtime-vitest" },
  { pattern: /\bjest\b/i, source: "runtime-jest" },
  { pattern: /\btsc\b/i, source: "runtime-tsc" },
  { pattern: /\bnpm\s+(run\s+)?test\b/i, source: "runtime-test" },
];

function toolEventName(event: ToolProgressEvent): string {
  return typeof (event as { function?: { name?: unknown } }).function?.name === "string"
    ? String((event as { function?: { name?: unknown } }).function?.name)
    : typeof event.name === "string"
      ? event.name
      : "";
}

function parseToolEventArguments(event: ToolProgressEvent): unknown {
  const fnArgs = (event as { function?: { arguments?: unknown } }).function?.arguments;
  const raw = fnArgs ?? event.arguments;
  if (typeof raw !== "string") return raw ?? {};
  if (!raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { args: [raw] };
  }
}

function toolErrorText(event: ToolProgressEvent): string {
  const error = event.error;
  if (typeof error === "string" && error.trim()) return error.trim();
  if (error && typeof error === "object") {
    try {
      return JSON.stringify(error);
    } catch {
      return String(error);
    }
  }
  const result = event.result;
  if (typeof result === "string" && result.trim()) return result.trim();
  return "";
}

function toolSource(name: string, text: string, args: unknown): string {
  const loweredText = text.toLowerCase();
  const argsText = (() => {
    if (typeof args === "string") return args.toLowerCase();
    if (!args || typeof args !== "object") return "";
    try {
      return JSON.stringify(args).toLowerCase();
    } catch {
      return "";
    }
  })();
  for (const candidate of TEST_HINT_PATTERNS) {
    if (candidate.pattern.test(loweredText) || candidate.pattern.test(argsText)) return candidate.source;
  }
  return TOOL_SOURCE_LABELS[name] ?? `runtime-${name || "tool"}`;
}

function pathWithinWorkspace(path: string, workspaceRoot: string | null): boolean {
  if (!workspaceRoot) return true;
  return path === workspaceRoot || path.startsWith(`${workspaceRoot}/`);
}

function resolveProblemPath(rawPath: string, workspaceRoot: string | null): string | null {
  const trimmed = rawPath.trim().replace(/^["']|["']$/g, "");
  if (!trimmed) return null;
  const slashNormalized = trimmed.replace(/\\/g, "/");
  if (slashNormalized.startsWith("/")) {
    return pathWithinWorkspace(slashNormalized, workspaceRoot) ? slashNormalized : null;
  }
  if (!workspaceRoot) return slashNormalized;
  return `${workspaceRoot.replace(/\/+$/, "")}/${slashNormalized.replace(/^\.?\//, "")}`;
}

function extractPathMatches(text: string): Array<{ path: string; line: number; column: number }> {
  const matches: Array<{ path: string; line: number; column: number }> = [];
  const seen = new Set<string>();

  const patterns = [
    /(?:^|\s)([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+):(\d+):(\d+)/g,
    /(?:^|\s)([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+):(\d+)/g,
    /File "([^"]+)", line (\d+)(?:, in [^\n]+)?/g,
  ];

  for (const pattern of patterns) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      const rawPath = match[1] ?? "";
      const line = Number.parseInt(match[2] ?? "1", 10);
      const column = pattern === patterns[0]
        ? Number.parseInt(match[3] ?? "1", 10)
        : 1;
      const key = `${rawPath}:${line}:${column}`;
      if (seen.has(key)) continue;
      seen.add(key);
      matches.push({
        path: rawPath,
        line: Number.isFinite(line) && line > 0 ? line : 1,
        column: Number.isFinite(column) && column > 0 ? column : 1,
      });
      if (matches.length >= 12) return matches;
    }
  }

  return matches;
}

function previewFromError(text: string): string {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines[0] ?? "Runtime failure";
}

function messageFromError(name: string, text: string): string {
  const preview = previewFromError(text);
  if (!name) return preview;
  return `${name} failed: ${preview}`;
}

function problemRank(source: string, message: string, path: string, line: number): number {
  let score = 240;
  if (source.includes("pytest") || source.includes("vitest") || source.includes("test")) score += 35;
  if (source.includes("tsc")) score += 28;
  if (source.includes("cli")) score += 18;
  if (/assert|failed|error|exception/i.test(message)) score += 16;
  score -= Math.min(path.split("/").length, 8) * 3;
  score -= Math.min(line, 400) / 20;
  return Math.round(score);
}

function problemsFromToolEvent(
  event: ToolProgressEvent,
  workspaceRoot: string | null,
): RuntimeProblemCandidate[] {
  if (event.phase !== "error") return [];
  const text = toolErrorText(event);
  if (!text) return [];

  const name = toolEventName(event);
  const args = parseToolEventArguments(event);
  const source = toolSource(name, text, args);
  const extracted = extractPathMatches(text);
  const items: RuntimeProblemCandidate[] = [];
  const seen = new Set<string>();

  for (const match of extracted) {
    const resolved = resolveProblemPath(match.path, workspaceRoot);
    if (!resolved) continue;
    const displayPath = workspaceRoot && resolved.startsWith(`${workspaceRoot}/`)
      ? resolved.slice(workspaceRoot.length + 1)
      : resolved;
    const preview = previewFromError(text);
    const message = messageFromError(name, text);
    const pathWithLocation = `${resolved}:${match.line}:${match.column}`;
    if (seen.has(pathWithLocation)) continue;
    seen.add(pathWithLocation);
    items.push({
      rank: problemRank(source, message, displayPath, match.line),
      item: {
        path: pathWithLocation,
        display_path: displayPath,
        name: displayPath.split("/").pop() || displayPath,
        message,
        severity: "error",
        source,
        line: match.line,
        column: match.column,
        preview,
        score: 0,
      },
    });
  }

  if (items.length > 0) return items;

  const fallbackPath = typeof args === "object" && args && !Array.isArray(args)
    ? (typeof (args as Record<string, unknown>).path === "string"
      ? resolveProblemPath((args as Record<string, unknown>).path as string, workspaceRoot)
      : null)
    : null;
  if (!fallbackPath) return [];
  const displayPath = workspaceRoot && fallbackPath.startsWith(`${workspaceRoot}/`)
    ? fallbackPath.slice(workspaceRoot.length + 1)
    : fallbackPath;
  const preview = previewFromError(text);
  const message = messageFromError(name, text);
  return [{
    rank: problemRank(source, message, displayPath, 1),
    item: {
      path: `${fallbackPath}:1:1`,
      display_path: displayPath,
      name: displayPath.split("/").pop() || displayPath,
      message,
      severity: "error",
      source,
      line: 1,
      column: 1,
      preview,
      score: 0,
    },
  }];
}

export function collectRuntimeProblems(
  messages: UIMessage[],
  workspaceRoot?: string | null,
): WorkspaceProblemItem[] {
  const ranked: RuntimeProblemCandidate[] = [];
  const seen = new Set<string>();

  for (const message of messages) {
    if (message.kind !== "trace") continue;
    for (const event of message.toolEvents ?? []) {
      for (const candidate of problemsFromToolEvent(event, workspaceRoot ?? null)) {
        const key = `${candidate.item.path}|${candidate.item.message}`;
        if (seen.has(key)) continue;
        seen.add(key);
        ranked.push(candidate);
      }
    }
  }

  ranked.sort((left, right) => (
    right.rank - left.rank
    || left.item.display_path.length - right.item.display_path.length
    || left.item.line - right.item.line
    || left.item.message.localeCompare(right.item.message)
  ));

  return ranked.map(({ rank, item }) => ({ ...item, score: rank }));
}
