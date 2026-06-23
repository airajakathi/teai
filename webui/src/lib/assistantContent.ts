const INTERNAL_TOOL_MARKUP_RE = /<tool_call>|<function=[^>\n]+>|<parameter=[^>\n]+>/i;

/**
 * Drop internal tool-call markup that some providers occasionally leak into the
 * assistant's visible text channel. If there is visible prose before the tool
 * block, keep that prose and discard the leaked internal payload.
 */
export function sanitizeAssistantVisibleContent(content: string | null | undefined): string {
  if (typeof content !== "string" || content.length === 0) return "";
  const match = INTERNAL_TOOL_MARKUP_RE.exec(content);
  if (!match) return content;
  return content.slice(0, match.index).replace(/\s+$/g, "");
}

/** Collapse preview whitespace after removing internal tool markup. */
export function sanitizePreviewText(content: string | null | undefined): string {
  return sanitizeAssistantVisibleContent(content).replace(/\s+/g, " ").trim();
}

export function isSanitizedAssistantMessageEmpty(content: string | null | undefined): boolean {
  return sanitizeAssistantVisibleContent(content).trim().length === 0;
}
