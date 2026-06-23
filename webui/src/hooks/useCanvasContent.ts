/**
 * Manages the canvas workspace panel content.
 *
 * Items come from two sources:
 *  1. Auto-detected from assistant messages (local URLs, images, videos).
 *  2. Explicit `canvas()` tool calls (dispatched as `teai_builder:canvas` CustomEvents).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { UIMessage } from "@/lib/types";

// ── Types ──────────────────────────────────────────────────────────────────

export type CanvasItemType =
  | "url"
  | "mobile_url"
  | "html"
  | "image"
  | "video"
  | "code"
  | "terminal"
  | "document"
  | "screenshot";

export interface CanvasItem {
  id: string;
  type: CanvasItemType;
  /** URL, file path, code string, HTML string, markdown text, etc. */
  content: string;
  title?: string;
  /** Language for code items (e.g. "python", "javascript"). */
  lang?: string;
  addedAt: number;
  /** "auto" = detected from message text/media; "tool" = explicit canvas() call. */
  source: "auto" | "tool";
}

export interface CanvasState {
  items: CanvasItem[];
  activeId: string | null;
  hasContent: boolean;
}

// ── Constants ──────────────────────────────────────────────────────────────

const LOCAL_URL_RE =
  /https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+(?:\/[^\s)"'`\]]*)?/g;

// ── Helpers ────────────────────────────────────────────────────────────────

function extractLocalUrls(text: string, now: number): CanvasItem[] {
  const matches = text.match(LOCAL_URL_RE);
  if (!matches) return [];
  return [...new Set(matches)].map((url) => ({
    id: `auto-url-${url}`,
    type: "url" as CanvasItemType,
    content: url,
    title: url,
    addedAt: now,
    source: "auto" as const,
  }));
}

function isValidCanvasType(t: unknown): t is CanvasItemType {
  return (
    t === "url" ||
    t === "mobile_url" ||
    t === "html" ||
    t === "image" ||
    t === "video" ||
    t === "code" ||
    t === "terminal" ||
    t === "document" ||
    t === "screenshot"
  );
}

// ── Main hook ──────────────────────────────────────────────────────────────

/**
 * @param messages  Live message list from `useTeaiBuilderStream`.
 * @param chatId    Current chat ID – used to filter canvas events to this chat.
 */
export interface CanvasRestoreItem {
  type: string;
  content: string;
  title?: string;
  lang?: string;
}

const EMPTY_RESTORE_ITEMS: CanvasRestoreItem[] = [];

export function useCanvasContent(
  messages: UIMessage[],
  chatId: string | null,
  restoreItems: CanvasRestoreItem[] = EMPTY_RESTORE_ITEMS,
): CanvasState & {
  setActiveId: (id: string | null) => void;
  removeItem: (id: string) => void;
  clearAll: () => void;
  addItem: (item: Omit<CanvasItem, "id" | "addedAt" | "source">) => void;
} {
  const [items, setItems] = useState<CanvasItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Reset on chat switch
  useEffect(() => {
    setItems([]);
    setActiveId(null);
    seenIdsRef.current.clear();
  }, [chatId]);

  // --- Restore persisted canvas items (history reload) ---
  useEffect(() => {
    if (!restoreItems.length) return;
    const now = Date.now();
    for (const raw of restoreItems) {
      if (!isValidCanvasType(raw.type)) continue;
      const content = typeof raw.content === "string" ? raw.content : "";
      if (!content) continue;
      // Match the live tool-event dedupe key so a later live push won't double-add.
      const id = `tool-${raw.type}-${content.slice(0, 120)}`;
      if (seenIdsRef.current.has(id)) continue;
      seenIdsRef.current.add(id);
      setItems((prev) => {
        if (prev.some((p) => p.id === id)) return prev;
        return [
          ...prev,
          {
            id,
            type: raw.type as CanvasItemType,
            content,
            title: typeof raw.title === "string" ? raw.title : undefined,
            lang: typeof raw.lang === "string" ? raw.lang : undefined,
            addedAt: now,
            source: "tool" as const,
          },
        ];
      });
      setActiveId((prev) => prev ?? id);
    }
  }, [restoreItems]);

  // --- Auto-detect from messages ---
  const autoItems = useMemo<CanvasItem[]>(() => {
    const result: CanvasItem[] = [];
    const seenUrls = new Set<string>();
    const seenMedia = new Set<string>();

    for (const message of messages) {
      if (message.role !== "assistant") continue;
      const now = message.createdAt ?? Date.now();

      // Scan text for local server URLs
      if (message.content) {
        for (const item of extractLocalUrls(message.content, now)) {
          if (!seenUrls.has(item.content)) {
            seenUrls.add(item.content);
            result.push(item);
          }
        }
      }

      // Collect image / video attachments
      if (message.media) {
        for (const att of message.media) {
          if (!att.url || seenMedia.has(att.url)) continue;
          seenMedia.add(att.url);
          if (att.kind === "image") {
            result.push({
              id: `auto-img-${att.url}`,
              type: "image",
              content: att.url,
              title: att.name ?? "Image",
              addedAt: now,
              source: "auto",
            });
          } else if (att.kind === "video") {
            result.push({
              id: `auto-vid-${att.url}`,
              type: "video",
              content: att.url,
              title: att.name ?? "Video",
              addedAt: now,
              source: "auto",
            });
          }
        }
      }

      // Also check inline image data URLs
      if (message.images) {
        for (const img of message.images) {
          if (!img.url || seenMedia.has(img.url)) continue;
          seenMedia.add(img.url);
          result.push({
            id: `auto-img-inline-${img.url.slice(0, 40)}`,
            type: "image",
            content: img.url,
            title: img.name ?? "Image",
            addedAt: now,
            source: "auto",
          });
        }
      }
    }

    return result;
  }, [messages]);

  // --- Merge auto items into state (avoid re-adding known ones) ---
  useEffect(() => {
    for (const item of autoItems) {
      if (!seenIdsRef.current.has(item.id)) {
        seenIdsRef.current.add(item.id);
        setItems((prev) => {
          // don't add duplicates
          if (prev.some((p) => p.id === item.id)) return prev;
          return [...prev, item];
        });
        setActiveId((prev) => prev ?? item.id);
      }
    }
  }, [autoItems]);

  // --- Listen for canvas tool events ---
  useEffect(() => {
    const handler = (e: Event) => {
      const ev = e as CustomEvent<{ chatId: string; data: unknown }>;
      if (!ev.detail || ev.detail.chatId !== chatId) return;
      const raw = ev.detail.data as Record<string, unknown> | null;
      if (!raw) return;

      const type = raw.type;
      if (!isValidCanvasType(type)) return;

      const content = typeof raw.content === "string" ? raw.content : "";
      const title = typeof raw.title === "string" ? raw.title : undefined;
      const lang = typeof raw.lang === "string" ? raw.lang : undefined;

      const now = Date.now();
      // For deduplication: same type+content = same item (tool may send
      // multiple progress events for the same artifact).
      const dedupeKey = `tool-${type}-${content.slice(0, 120)}`;

      setItems((prev) => {
        if (prev.some((p) => p.id === dedupeKey)) return prev;
        seenIdsRef.current.add(dedupeKey);
        const newItem: CanvasItem = {
          id: dedupeKey,
          type,
          content,
          title,
          lang,
          addedAt: now,
          source: "tool",
        };
        return [...prev, newItem];
      });
      // New tool-pushed items always become the active item
      setActiveId(dedupeKey);
    };

    window.addEventListener("teai_builder:canvas", handler);
    return () => window.removeEventListener("teai_builder:canvas", handler);
  }, [chatId]);

  const removeItem = (id: string) => {
    seenIdsRef.current.delete(id);
    setItems((prev) => {
      const next = prev.filter((p) => p.id !== id);
      return next;
    });
    setActiveId((prev) => {
      if (prev !== id) return prev;
      const next = items.filter((p) => p.id !== id);
      return next.length > 0 ? next[next.length - 1].id : null;
    });
  };

  const clearAll = () => {
    seenIdsRef.current.clear();
    setItems([]);
    setActiveId(null);
  };

  const addItem = (partial: Omit<CanvasItem, "id" | "addedAt" | "source">) => {
    const id = `manual-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const item: CanvasItem = { ...partial, id, addedAt: Date.now(), source: "tool" };
    seenIdsRef.current.add(id);
    setItems((prev) => [...prev, item]);
    setActiveId(id);
  };

  return {
    items,
    activeId,
    hasContent: items.length > 0,
    setActiveId,
    removeItem,
    clearAll,
    addItem,
  };
}
