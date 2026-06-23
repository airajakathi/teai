/**
 * CanvasPanel – the unified TeaiBuilder Workspace panel.
 *
 * A single, auto-adapting canvas that morphs to display any content type:
 * web apps, mobile previews (with QR code), images, videos, code,
 * terminal output, HTML documents, and markdown.
 *
 * No tabs – one smart view that auto-selects and auto-updates.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import QRCode from "qrcode";
import {
  Code2,
  Copy,
  ExternalLink,
  Globe,
  ImageIcon,
  Monitor,
  MonitorSmartphone,
  RefreshCw,
  RotateCw,
  Smartphone,
  Terminal,
  Trash2,
  Video,
  X,
  FileText,
  Camera,
  Plus,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CanvasItem, CanvasItemType } from "@/hooks/useCanvasContent";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────

export interface CanvasPanelProps {
  isOpen: boolean;
  isClosing: boolean;
  width: number;
  items: CanvasItem[];
  activeId: string | null;
  onSetActiveId: (id: string | null) => void;
  onRemoveItem: (id: string) => void;
  onClearAll: () => void;
  onAddItem: (item: { type: CanvasItemType; content: string; title?: string; lang?: string }) => void;
  onClose: () => void;
  onResizeStart: (e: React.MouseEvent) => void;
  /** Optional: send a message to teai_builder (e.g. for screenshots). */
  onSendToTeaiBuilder?: (text: string) => void;
}

// ── Icon map ───────────────────────────────────────────────────────────────

function typeIcon(type: CanvasItemType, size = 14) {
  const props = { size, strokeWidth: 1.75 };
  switch (type) {
    case "url":         return <Globe {...props} />;
    case "mobile_url":  return <Smartphone {...props} />;
    case "html":        return <Code2 {...props} />;
    case "image":       return <ImageIcon {...props} />;
    case "video":       return <Video {...props} />;
    case "code":        return <Code2 {...props} />;
    case "terminal":    return <Terminal {...props} />;
    case "document":    return <FileText {...props} />;
    case "screenshot":  return <Camera {...props} />;
    default:            return <Monitor {...props} />;
  }
}

function typeLabel(type: CanvasItemType): string {
  switch (type) {
    case "url":         return "Browser";
    case "mobile_url":  return "Mobile";
    case "html":        return "HTML";
    case "image":       return "Image";
    case "video":       return "Video";
    case "code":        return "Code";
    case "terminal":    return "Terminal";
    case "document":    return "Doc";
    case "screenshot":  return "Shot";
    default:            return "View";
  }
}

type BrowserDevice = "desktop" | "tablet" | "mobile";
type MobileDeviceShell = "ios" | "android";
type DeviceOrientation = "portrait" | "landscape";

const BROWSER_DEVICE_WIDTHS: Record<BrowserDevice, number | string> = {
  desktop: "100%",
  tablet: 820,
  mobile: 390,
};

const MOBILE_DEVICE_SHELL_SIZES: Record<MobileDeviceShell, { portrait: { width: number; height: number }; landscape: { width: number; height: number } }> = {
  ios: {
    portrait: { width: 220, height: 440 },
    landscape: { width: 440, height: 220 },
  },
  android: {
    portrait: { width: 240, height: 460 },
    landscape: { width: 460, height: 240 },
  },
};

function clampPreviewZoom(value: number): number {
  return Math.min(2, Math.max(0.5, Number.parseFloat(value.toFixed(2))));
}

function zoomLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

type PreviewLoadState = "loading" | "ready" | "slow" | "error";

const PREVIEW_LOAD_TIMEOUT_MS = 8000;

declare global {
  interface Window {
    __TEAI_EXPO_DEBUG__?: boolean;
  }
}

// #region debug-point A:expo-preview-report
function reportExpoPreviewDebug(
  hypothesisId: "A" | "B" | "C" | "D" | "E",
  location: string,
  msg: string,
  data: Record<string, unknown>,
): void {
  if (typeof window === "undefined" || window.__TEAI_EXPO_DEBUG__ !== true) {
    return;
  }
  fetch("http://127.0.0.1:7777/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sessionId: "expo-white-screen",
      runId: "pre-fix",
      hypothesisId,
      location,
      msg: `[DEBUG] ${msg}`,
      data,
      ts: Date.now(),
    }),
  }).catch(() => undefined);
}
// #endregion

function previewDiagnoseMessage(title: string | undefined, url: string): string {
  const previewLabel = title?.trim() || "the current preview";
  return (
    `Diagnose and fix ${previewLabel}. ` +
    `The workspace preview for ${url} is slow, blank, or failing to load. ` +
    `Open the preview directly, inspect runtime or console errors, fix the underlying app issue, ` +
    `then re-run verification and confirm the preview renders correctly.`
  );
}

async function copyTextToClipboard(value: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  if (typeof window !== "undefined" && typeof window.prompt === "function") {
    window.prompt("Copy this link", value);
  }
}

// ── Sub-views ──────────────────────────────────────────────────────────────

// --- Browser View ---
function BrowserView({
  item,
  onSendToTeaiBuilder,
}: {
  item: CanvasItem;
  onSendToTeaiBuilder?: (text: string) => void;
}) {
  const [url, setUrl] = useState(item.content);
  const [inputVal, setInputVal] = useState(item.content);
  const [previewState, setPreviewState] = useState<PreviewLoadState>("loading");
  const [refreshKey, setRefreshKey] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [device, setDevice] = useState<BrowserDevice>("desktop");
  const [copied, setCopied] = useState(false);
  const [slowPreviewCount, setSlowPreviewCount] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const previousPreviewStateRef = useRef<PreviewLoadState>("loading");

  useEffect(() => {
    setUrl(item.content);
    setInputVal(item.content);
    setPreviewState("loading");
    setRefreshKey(0);
    setZoom(1);
    setSlowPreviewCount(0);
  }, [item.content]);

  useEffect(() => {
    if (previewState === "ready") {
      setSlowPreviewCount(0);
    }
    if (
      previewState === "slow" &&
      previousPreviewStateRef.current !== "slow"
    ) {
      setSlowPreviewCount((current) => current + 1);
    }
    previousPreviewStateRef.current = previewState;
  }, [previewState]);

  useEffect(() => {
    setPreviewState("loading");
    const timeoutId = window.setTimeout(() => {
      setPreviewState((current) => (current === "loading" ? "slow" : current));
    }, PREVIEW_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [url, refreshKey]);

  const navigate = (target: string) => {
    let normalized = target.trim();
    if (normalized && !normalized.match(/^https?:\/\//i)) {
      normalized = `http://${normalized}`;
    }
    setUrl(normalized);
    setInputVal(normalized);
    setPreviewState("loading");
  };

  const reload = () => {
    setPreviewState("loading");
    setRefreshKey((current) => current + 1);
  };

  const browserWidth = BROWSER_DEVICE_WIDTHS[device];
  const browserWidthStyle = typeof browserWidth === "number" ? `${browserWidth}px` : browserWidth;
  const canZoomOut = zoom > 0.5;
  const canZoomIn = zoom < 2;
  const recommendDiagnose = slowPreviewCount >= 2;

  const handleCopy = () => {
    void copyTextToClipboard(url).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }).catch(() => undefined);
  };

  const handleDiagnose = () => {
    onSendToTeaiBuilder?.(previewDiagnoseMessage(item.title, url));
  };

  return (
    <div className="flex flex-col h-full">
      {/* Address bar */}
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-white/10 bg-black/20">
        <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={reload} title="Reload" aria-label="Reload preview">
          <RefreshCw size={12} />
        </Button>
        <div className="hidden items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-1 py-0.5 text-white/60 sm:flex">
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0"
            onClick={() => setZoom((current) => clampPreviewZoom(current - 0.1))}
            title="Zoom out"
            disabled={!canZoomOut}
            aria-label="Zoom out"
          >
            <ZoomOut size={11} />
          </Button>
          <button
            type="button"
            className="min-w-[3rem] rounded px-1 py-0.5 text-[10px] font-medium text-white/75 hover:bg-white/10"
            onClick={() => setZoom(1)}
            title="Reset zoom"
          >
            {zoomLabel(zoom)}
          </button>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0"
            onClick={() => setZoom((current) => clampPreviewZoom(current + 0.1))}
            title="Zoom in"
            disabled={!canZoomIn}
            aria-label="Zoom in"
          >
            <ZoomIn size={11} />
          </Button>
        </div>
        <div className="hidden items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] p-0.5 md:flex">
          {([
            ["desktop", "Desktop", Monitor],
            ["tablet", "Tablet", MonitorSmartphone],
            ["mobile", "Mobile", Smartphone],
          ] as const).map(([value, label, Icon]) => (
            <Button
              key={value}
              variant="ghost"
              size="sm"
              className={cn(
                "h-6 gap-1 px-2 text-[10px] text-white/55 hover:text-white",
                device === value && "bg-white/10 text-white",
              )}
              onClick={() => setDevice(value)}
              title={`${label} preview`}
              aria-label={`${label} preview`}
            >
              <Icon size={11} />
              {label}
            </Button>
          ))}
        </div>
        <input
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && navigate(inputVal)}
          onBlur={() => navigate(inputVal)}
          className="flex-1 min-w-0 h-6 px-2 rounded text-xs bg-white/10 border border-white/10 focus:border-white/30 focus:outline-none text-white/80 placeholder:text-white/30"
          placeholder="http://localhost:3000"
        />
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          onClick={handleCopy}
          title={copied ? "Copied" : "Copy URL"}
          aria-label="Copy preview URL"
        >
          <Copy size={12} />
        </Button>
        <Button
          variant="ghost" size="icon" className="h-6 w-6 shrink-0"
          onClick={() => window.open(url, "_blank")} title="Open in new tab" aria-label="Open preview in new tab"
        >
          <ExternalLink size={12} />
        </Button>
        {previewState === "loading" ? (
          <span className="hidden shrink-0 text-[10px] text-white/45 lg:inline">Loading preview…</span>
        ) : null}
        {previewState === "slow" ? (
          <span className="hidden shrink-0 text-[10px] text-amber-300/80 lg:inline">
            {recommendDiagnose ? "Preview is repeatedly getting stuck" : "Preview is taking longer than expected"}
          </span>
        ) : null}
      </div>

      {/* iframe */}
      <div className="flex-1 relative overflow-auto bg-zinc-950">
        {previewState === "error" ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 p-6 text-center bg-zinc-900">
            <Globe size={40} className="text-white/20" />
            <p className="text-sm text-white/50">
              This preview could not load in the workspace. The app may be blocking iframe
              embedding, failing to start, or stuck during first render.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="text-xs border-white/20 hover:bg-white/10"
                onClick={reload}
              >
                Retry preview
              </Button>
              {onSendToTeaiBuilder ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="text-xs border-white/20 hover:bg-white/10"
                  onClick={handleDiagnose}
                >
                  Diagnose in TeAI Builder
                </Button>
              ) : null}
              <Button
                variant="outline" size="sm"
                className="text-xs border-white/20 hover:bg-white/10"
                onClick={() => window.open(url, "_blank")}
              >
                <ExternalLink size={12} className="mr-1.5" /> Open in new tab
              </Button>
            </div>
          </div>
        ) : (
          <div
            className="relative flex min-h-full min-w-full justify-center p-4"
            data-testid="browser-preview-frame"
            data-preview-device={device}
            data-preview-zoom={zoomLabel(zoom)}
            data-preview-state={previewState}
          >
            {previewState !== "ready" ? (
              <div className="absolute inset-x-4 top-4 z-10 flex justify-center">
                <div className="flex items-center gap-2 rounded-full border border-white/10 bg-black/70 px-3 py-1 text-[11px] text-white/70 shadow-lg backdrop-blur">
                  <span>
                    {previewState === "slow"
                      ? (recommendDiagnose
                        ? "Preview is repeatedly getting stuck. Diagnose is recommended."
                        : "Preview is taking longer than expected.")
                      : "Loading preview…"}
                  </span>
                  {previewState === "slow" ? (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-[10px] text-white/80 hover:text-white"
                        onClick={reload}
                      >
                        Retry
                      </Button>
                      {onSendToTeaiBuilder ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[10px] text-white/80 hover:text-white"
                          onClick={handleDiagnose}
                        aria-label={recommendDiagnose ? "Diagnose recommended" : "Diagnose"}
                        >
                          {recommendDiagnose ? "Diagnose Recommended" : "Diagnose"}
                        </Button>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </div>
            ) : null}
            <div
              className="origin-top"
              style={{
                width: browserWidthStyle,
                minWidth: typeof browserWidth === "number" ? `${browserWidth}px` : undefined,
                height: "100%",
                minHeight: `calc((100vh - 9rem) / ${zoom})`,
                transform: `scale(${zoom})`,
              }}
            >
              <iframe
                key={`${url}-${refreshKey}`}
                ref={iframeRef}
                src={url}
                title="Canvas Preview"
                className="h-full w-full rounded-[18px] border-0 bg-white shadow-2xl"
                sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals allow-downloads allow-presentation"
                onLoad={() => setPreviewState("ready")}
                onError={() => setPreviewState("error")}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Mobile View ---
function MobileView({
  item,
  onSendToTeaiBuilder,
}: {
  item: CanvasItem;
  onSendToTeaiBuilder?: (text: string) => void;
}) {
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [deviceShell, setDeviceShell] = useState<MobileDeviceShell>("ios");
  const [orientation, setOrientation] = useState<DeviceOrientation>("portrait");
  const [zoom, setZoom] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [webPreviewState, setWebPreviewState] = useState<PreviewLoadState>("loading");
  const [slowPreviewCount, setSlowPreviewCount] = useState(0);
  const url = item.content;
  const previousPreviewStateRef = useRef<PreviewLoadState>("loading");

  // exp:// is a native deep link — cannot be loaded in iframe
  const isExpoUrl = url.startsWith("exp://") || url.startsWith("exp+");
  // http(s):// can be shown in iframe
  const isWebUrl = url.startsWith("http://") || url.startsWith("https://");
  const derivedExpoPreviewUrl = isExpoUrl ? url.replace(/^exp(\+[^:]*)?:\/\//, "http://") : null;

  useEffect(() => {
    if (!url) return;
    QRCode.toDataURL(url, {
      width: 220,
      margin: 2,
      color: { light: "#ffffff", dark: "#000000" },
      errorCorrectionLevel: "M",
    })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(null));
  }, [url]);

  useEffect(() => {
    // #region debug-point A:mobile-view-mode
    reportExpoPreviewDebug("A", "CanvasPanel.tsx:MobileView:mode", "Mobile preview mode selected", {
      itemType: item.type,
      originalUrl: url,
      isExpoUrl,
      isWebUrl,
      derivedExpoPreviewUrl,
      title: item.title ?? null,
    });
    // #endregion
  }, [derivedExpoPreviewUrl, isExpoUrl, isWebUrl, item.title, item.type, url]);

  useEffect(() => {
    // #region debug-point B:mobile-preview-shell-state
    reportExpoPreviewDebug("B", "CanvasPanel.tsx:MobileView:shell", "Mobile preview shell state updated", {
      deviceShell,
      orientation,
      zoom: zoomLabel(zoom),
      originalUrl: url,
      derivedExpoPreviewUrl,
    });
    // #endregion
  }, [derivedExpoPreviewUrl, deviceShell, orientation, url, zoom]);

  useEffect(() => {
    setRefreshKey(0);
    setZoom(1);
    setWebPreviewState("loading");
    setSlowPreviewCount(0);
  }, [url]);

  useEffect(() => {
    if (webPreviewState === "ready") {
      setSlowPreviewCount(0);
    }
    if (
      webPreviewState === "slow" &&
      previousPreviewStateRef.current !== "slow"
    ) {
      setSlowPreviewCount((current) => current + 1);
    }
    previousPreviewStateRef.current = webPreviewState;
  }, [webPreviewState]);

  useEffect(() => {
    if (!isWebUrl) return;
    setWebPreviewState("loading");
    const timeoutId = window.setTimeout(() => {
      setWebPreviewState((current) => (current === "loading" ? "slow" : current));
    }, PREVIEW_LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [isWebUrl, url, refreshKey, deviceShell, orientation]);

  const dimensions = MOBILE_DEVICE_SHELL_SIZES[deviceShell][orientation];
  const canZoomOut = zoom > 0.5;
  const canZoomIn = zoom < 2;
  const previewTitle = item.title ?? "Mobile App";
  const recommendDiagnose = slowPreviewCount >= 2;
  const handleRefresh = () => setRefreshKey((current) => current + 1);
  const handleCopy = () => {
    void copyTextToClipboard(url).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }).catch(() => undefined);
  };
  const handleDiagnose = () => {
    onSendToTeaiBuilder?.(previewDiagnoseMessage(item.title, url));
  };
  const mobileFrame = (sourceUrl: string, title: string) => (
    <div className="flex flex-col items-center gap-2 shrink-0">
      <div
        className={cn(
          "relative rounded-[36px] border bg-[#1a1a1a] p-2 shadow-[0_0_0_1px_#555,inset_0_0_8px_rgba(0,0,0,0.5)]",
          orientation === "portrait" ? "rounded-[36px]" : "rounded-[28px]",
        )}
        data-testid="mobile-preview-frame"
        data-mobile-device={deviceShell}
        data-mobile-orientation={orientation}
        data-preview-zoom={zoomLabel(zoom)}
        data-preview-state={webPreviewState}
        style={{
          width: dimensions.width,
          height: dimensions.height,
          transform: `scale(${zoom})`,
          transformOrigin: "top center",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: orientation === "portrait" ? 12 : 8,
            left: "50%",
            transform: "translateX(-50%)",
            width: orientation === "portrait" ? 60 : 44,
            height: 6,
            background: "#333",
            borderRadius: 3,
            zIndex: 10,
          }}
        />
        <div className="h-full w-full overflow-hidden rounded-[28px] bg-white">
          {webPreviewState !== "ready" ? (
            <div className="absolute inset-x-4 top-8 z-10 flex justify-center">
              <div className="flex items-center gap-2 rounded-full border border-black/10 bg-black/70 px-3 py-1 text-[10px] text-white/75 shadow-lg backdrop-blur">
                <span>
                  {webPreviewState === "slow"
                    ? (recommendDiagnose
                      ? "Preview is repeatedly getting stuck. Diagnose is recommended."
                      : "Preview is slow or may be stuck.")
                    : "Loading mobile preview…"}
                </span>
                {webPreviewState === "slow" ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-[10px] text-white/80 hover:text-white"
                      onClick={handleRefresh}
                    >
                      Retry
                    </Button>
                    {onSendToTeaiBuilder ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-[10px] text-white/80 hover:text-white"
                        onClick={handleDiagnose}
                        aria-label={recommendDiagnose ? "Diagnose recommended" : "Diagnose"}
                      >
                        {recommendDiagnose ? "Diagnose Recommended" : "Diagnose"}
                      </Button>
                    ) : null}
                  </>
                ) : null}
              </div>
            </div>
          ) : null}
          <iframe
            key={`${sourceUrl}-${refreshKey}-${deviceShell}-${orientation}`}
            src={sourceUrl}
            title={title}
            style={{ width: "100%", height: "100%", border: "none" }}
            sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
            onLoad={() => {
              // #region debug-point C:mobile-iframe-load
              reportExpoPreviewDebug("C", "CanvasPanel.tsx:MobileView:iframe-load", "Mobile iframe loaded", {
                sourceUrl,
                title,
                originalUrl: url,
                deviceShell,
                orientation,
                zoom: zoomLabel(zoom),
                refreshKey,
              });
              // #endregion
              setWebPreviewState("ready");
            }}
            onError={() => {
              // #region debug-point C:mobile-iframe-error
              reportExpoPreviewDebug("C", "CanvasPanel.tsx:MobileView:iframe-error", "Mobile iframe error", {
                sourceUrl,
                title,
                originalUrl: url,
                deviceShell,
                orientation,
                zoom: zoomLabel(zoom),
                refreshKey,
              });
              // #endregion
              setWebPreviewState("error");
            }}
          />
          {webPreviewState === "error" ? (
            <div className="absolute inset-4 z-20 flex flex-col items-center justify-center gap-2 rounded-[22px] border border-white/10 bg-black/80 px-4 text-center">
              <p className="text-xs font-medium text-white">Mobile preview failed to load</p>
              <p className="text-[10px] leading-relaxed text-white/60">
                The app may not be serving correctly or it may be crashing during first render.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 border-white/20 px-3 text-[10px] hover:bg-white/10"
                  onClick={handleRefresh}
                >
                  Retry preview
                </Button>
                {onSendToTeaiBuilder ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 border-white/20 px-3 text-[10px] hover:bg-white/10"
                    onClick={handleDiagnose}
                  >
                    Diagnose in TeAI Builder
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <span className="text-[11px] text-white/40 font-medium">{title}</span>
    </div>
  );

  const expoNativeFrame = (
    <div className="flex flex-col items-center gap-2 shrink-0">
      <div
        className={cn(
          "relative rounded-[36px] border bg-[#1a1a1a] p-2 shadow-[0_0_0_1px_#555,inset_0_0_8px_rgba(0,0,0,0.5)]",
          orientation === "portrait" ? "rounded-[36px]" : "rounded-[28px]",
        )}
        data-testid="mobile-preview-frame"
        data-mobile-device={deviceShell}
        data-mobile-orientation={orientation}
        data-preview-zoom={zoomLabel(zoom)}
        style={{
          width: dimensions.width,
          height: dimensions.height,
          transform: `scale(${zoom})`,
          transformOrigin: "top center",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: orientation === "portrait" ? 12 : 8,
            left: "50%",
            transform: "translateX(-50%)",
            width: orientation === "portrait" ? 60 : 44,
            height: 6,
            background: "#333",
            borderRadius: 3,
            zIndex: 10,
          }}
        />
        <div className="flex h-full w-full flex-col items-center justify-center gap-3 overflow-hidden rounded-[28px] border border-white/5 bg-[radial-gradient(circle_at_top,_rgba(76,142,247,0.25),_transparent_55%),linear-gradient(180deg,_rgba(15,23,36,0.96),_rgba(9,12,20,1))] px-6 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/5">
            <Smartphone size={26} className="text-white/85" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-semibold text-white">Expo Native Preview</p>
            <p className="text-[11px] leading-relaxed text-white/55">
              TeAI Builder keeps the real `exp://` link for Expo Go instead of embedding
              a misleading white-screen iframe.
            </p>
          </div>
          {derivedExpoPreviewUrl ? (
            <Button
              variant="outline"
              size="sm"
              className="border-white/20 bg-white/5 text-[11px] text-white hover:bg-white/10"
              onClick={() => window.open(derivedExpoPreviewUrl, "_blank")}
              title="Open Expo web mirror"
              aria-label="Open Expo web mirror"
            >
              <Globe size={12} className="mr-1.5" />
              Open Web Mirror
            </Button>
          ) : null}
        </div>
      </div>
      <span className="text-[11px] text-white/40 font-medium">Expo Go / Native Preview</span>
    </div>
  );

  // ── Expo native app view (QR + native handoff) ───────────────────────────
  if (isExpoUrl) {
    return (
      <div className="flex h-full flex-col overflow-hidden" style={{ background: "linear-gradient(160deg, #1a1034 0%, #0f1724 100%)" }}>
        <div className="flex flex-wrap items-center gap-1.5 border-b border-white/10 bg-black/20 px-2 py-1.5">
          <Button variant="ghost" size="icon" className="h-6 w-6 text-white/70 hover:text-white" onClick={handleRefresh} title="Refresh mobile preview" aria-label="Refresh mobile preview">
            <RefreshCw size={12} />
          </Button>
          <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-1 py-0.5 text-white/60">
            <Button variant="ghost" size="icon" className="h-5 w-5 text-white/60 hover:text-white" onClick={() => setZoom((current) => clampPreviewZoom(current - 0.1))} title="Zoom out" disabled={!canZoomOut} aria-label="Zoom out">
              <ZoomOut size={11} />
            </Button>
            <button type="button" className="min-w-[3rem] rounded px-1 py-0.5 text-[10px] font-medium text-white/75 hover:bg-white/10" onClick={() => setZoom(1)} title="Reset zoom">
              {zoomLabel(zoom)}
            </button>
            <Button variant="ghost" size="icon" className="h-5 w-5 text-white/60 hover:text-white" onClick={() => setZoom((current) => clampPreviewZoom(current + 0.1))} title="Zoom in" disabled={!canZoomIn} aria-label="Zoom in">
              <ZoomIn size={11} />
            </Button>
          </div>
          <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] p-0.5">
            {([
              ["ios", "iPhone", Smartphone],
              ["android", "Android", Smartphone],
            ] as const).map(([value, label, Icon]) => (
              <Button
                key={value}
                variant="ghost"
                size="sm"
                className={cn("h-6 gap-1 px-2 text-[10px] text-white/55 hover:text-white", deviceShell === value && "bg-white/10 text-white")}
                onClick={() => setDeviceShell(value)}
                title={`${label} shell`}
                aria-label={`${label} shell`}
              >
                <Icon size={11} />
                {label}
              </Button>
            ))}
          </div>
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-white/60 hover:text-white" onClick={() => setOrientation((current) => current === "portrait" ? "landscape" : "portrait")} title="Rotate device" aria-label="Rotate device">
            <RotateCw size={11} />
            {orientation === "portrait" ? "Portrait" : "Landscape"}
          </Button>
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-white/60 hover:text-white" onClick={handleCopy} title={copied ? "Copied" : "Copy mobile preview link"} aria-label="Copy mobile preview link">
            <Copy size={11} />
            {copied ? "Copied" : "Copy link"}
          </Button>
          <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-white/60 hover:text-white" onClick={() => window.open(url, "_blank")} title="Open mobile preview externally" aria-label="Open mobile preview externally">
            <ExternalLink size={11} />
            Open
          </Button>
        </div>
        <div className="flex items-start justify-center gap-6 overflow-auto p-5">
          {expoNativeFrame}

          {/* QR + branding + steps */}
          <div className="flex flex-col items-center gap-4 pt-2 max-w-[240px]">
          {/* Expo branding */}
            <div className="flex items-center gap-2 self-start">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ background: "linear-gradient(135deg, #4c8ef7, #a259f7)" }}>
                <Smartphone size={18} className="text-white" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">{previewTitle}</p>
                <p className="text-[11px] text-white/40">Real device via Expo Go</p>
              </div>
            </div>

            {/* QR Code */}
            {qrDataUrl ? (
              <div className="flex flex-col items-center gap-2">
                <div className="rounded-2xl overflow-hidden p-3 bg-white shadow-2xl"
                  style={{ boxShadow: "0 0 30px rgba(76,142,247,0.3)" }}>
                  <img src={qrDataUrl} alt="Expo QR Code" width={160} height={160} />
                </div>
                <p className="text-[10px] text-white/40 font-mono px-3 py-1 rounded bg-white/5 border border-white/10 max-w-[230px] truncate">
                  {url}
                </p>
              </div>
            ) : (
              <div className="w-[160px] h-[160px] rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
                <span className="text-white/30 text-xs">Generating QR…</span>
              </div>
            )}

            {/* Steps */}
            <div className="flex flex-col gap-1.5 w-full">
              {[
                ["1", "Install Expo Go", "App Store / Play Store"],
                ["2", "Same WiFi as this PC", "required for connection"],
                ["3", "Scan the QR code", "app opens on your phone"],
              ].map(([n, title, sub]) => (
                <div key={n} className="flex items-start gap-2 p-2 rounded-lg bg-white/5 border border-white/8">
                  <span className="w-4 h-4 rounded-full text-[9px] font-bold flex items-center justify-center shrink-0 mt-0.5"
                    style={{ background: "linear-gradient(135deg, #4c8ef7, #a259f7)", color: "#fff" }}>
                    {n}
                  </span>
                  <div>
                    <p className="text-[11px] text-white/80 font-medium">{title}</p>
                    <p className="text-[10px] text-white/35">{sub}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Web URL view (http/https) — show iframe + QR ─────────────────────────
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-white/10 bg-black/20 px-2 py-1.5">
        <Button variant="ghost" size="icon" className="h-6 w-6 text-white/70 hover:text-white" onClick={handleRefresh} title="Refresh mobile preview" aria-label="Refresh mobile preview">
          <RefreshCw size={12} />
        </Button>
        <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-1 py-0.5 text-white/60">
          <Button variant="ghost" size="icon" className="h-5 w-5 text-white/60 hover:text-white" onClick={() => setZoom((current) => clampPreviewZoom(current - 0.1))} title="Zoom out" disabled={!canZoomOut} aria-label="Zoom out">
            <ZoomOut size={11} />
          </Button>
          <button type="button" className="min-w-[3rem] rounded px-1 py-0.5 text-[10px] font-medium text-white/75 hover:bg-white/10" onClick={() => setZoom(1)} title="Reset zoom">
            {zoomLabel(zoom)}
          </button>
          <Button variant="ghost" size="icon" className="h-5 w-5 text-white/60 hover:text-white" onClick={() => setZoom((current) => clampPreviewZoom(current + 0.1))} title="Zoom in" disabled={!canZoomIn} aria-label="Zoom in">
            <ZoomIn size={11} />
          </Button>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] p-0.5">
          {([
            ["ios", "iPhone", Smartphone],
            ["android", "Android", Smartphone],
          ] as const).map(([value, label, Icon]) => (
            <Button
              key={value}
              variant="ghost"
              size="sm"
              className={cn("h-6 gap-1 px-2 text-[10px] text-white/55 hover:text-white", deviceShell === value && "bg-white/10 text-white")}
              onClick={() => setDeviceShell(value)}
              title={`${label} shell`}
              aria-label={`${label} shell`}
            >
              <Icon size={11} />
              {label}
            </Button>
          ))}
        </div>
        <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-white/60 hover:text-white" onClick={() => setOrientation((current) => current === "portrait" ? "landscape" : "portrait")} title="Rotate device" aria-label="Rotate device">
          <RotateCw size={11} />
          {orientation === "portrait" ? "Portrait" : "Landscape"}
        </Button>
        <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-white/60 hover:text-white" onClick={handleCopy} title={copied ? "Copied" : "Copy mobile preview link"} aria-label="Copy mobile preview link">
          <Copy size={11} />
          {copied ? "Copied" : "Copy link"}
        </Button>
        <Button variant="ghost" size="sm" className="h-6 gap-1 px-2 text-[10px] text-white/60 hover:text-white" onClick={() => window.open(url, "_blank")} title="Open mobile preview externally" aria-label="Open mobile preview externally">
          <ExternalLink size={11} />
          Open
        </Button>
      </div>
      <div className="flex items-start justify-center gap-6 overflow-auto p-4">
      {/* Phone mockup */}
        {isWebUrl ? mobileFrame(url, "Mobile Preview") : (
          <div
            className="flex items-center justify-center rounded-[28px] border border-white/10 bg-black/30 p-6 text-center text-xs text-zinc-400"
            data-testid="mobile-preview-frame"
            data-mobile-device={deviceShell}
            data-mobile-orientation={orientation}
            data-preview-zoom={zoomLabel(zoom)}
          >
            Preview not available for this URL type
          </div>
        )}

        {/* QR + info */}
        <div className="flex flex-col items-center gap-3 pt-4">
          <p className="text-xs text-white/50 text-center max-w-[140px]">Scan to open on mobile</p>
          {qrDataUrl ? (
            <div className="rounded-xl overflow-hidden border-4 border-white">
              <img src={qrDataUrl} alt="QR Code" width={160} height={160} />
            </div>
          ) : (
            <div className="w-[160px] h-[160px] rounded-xl bg-white/10 flex items-center justify-center">
              <span className="text-white/30 text-xs">Generating…</span>
            </div>
          )}
          <Button
            variant="ghost" size="sm" className="h-7 text-xs text-white/60 hover:text-white gap-1.5"
            onClick={() => window.open(url, "_blank")}
          >
            <ExternalLink size={11} /> Open in browser
          </Button>
          <span className="max-w-[180px] truncate text-[11px] text-white/40 font-mono">{url.replace(/^https?:\/\//, "")}</span>
        </div>
      </div>
    </div>
  );
}

// --- HTML View ---
function HtmlView({ item }: { item: CanvasItem }) {
  const content = item.content.trim();
  // Backend signs file paths into `/api/files/<sig>/<payload>`; remote pages
  // come through as http(s) URLs. Anything else is treated as a raw HTML string.
  const isUrl =
    /^https?:\/\//i.test(content) || content.startsWith("/api/");
  const iframeProps = isUrl ? { src: content } : { srcDoc: item.content };

  return (
    <div className="h-full bg-white">
      <iframe
        {...iframeProps}
        title="HTML Preview"
        className="w-full h-full border-0"
        sandbox="allow-scripts allow-forms allow-modals allow-same-origin"
      />
    </div>
  );
}

// --- Image View ---
function ImageView({ item }: { item: CanvasItem }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <div
        className="flex items-center justify-center h-full p-4 bg-zinc-950 cursor-zoom-in"
        onClick={() => setExpanded(true)}
      >
        <img
          src={item.content}
          alt={item.title ?? "Image"}
          className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
        />
      </div>
      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 cursor-zoom-out"
          onClick={() => setExpanded(false)}
        >
          <img
            src={item.content}
            alt={item.title ?? "Image"}
            className="max-w-[95vw] max-h-[95vh] object-contain rounded-lg"
          />
          <button
            className="absolute top-4 right-4 text-white/60 hover:text-white"
            onClick={() => setExpanded(false)}
          >
            <X size={24} />
          </button>
        </div>
      )}
    </>
  );
}

// --- Video View ---
function VideoView({ item }: { item: CanvasItem }) {
  return (
    <div className="flex items-center justify-center h-full bg-black p-4">
      <video
        src={item.content}
        controls
        className="max-w-full max-h-full rounded-lg shadow-2xl"
        style={{ maxHeight: "calc(100% - 2rem)" }}
      >
        <p className="text-white/50 text-sm">
          Your browser does not support this video format.
        </p>
      </video>
    </div>
  );
}

// --- Code View ---
function CodeView({ item }: { item: CanvasItem }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(item.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/10 bg-zinc-900/60">
        <span className="text-xs font-mono text-white/40">{item.lang ?? "code"}</span>
        <button onClick={copy} className="text-[11px] text-white/40 hover:text-white/80 transition-colors">
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        <pre className="p-4 text-sm font-mono text-green-300 leading-relaxed whitespace-pre-wrap break-words bg-zinc-950 min-h-full">
          <code>{item.content}</code>
        </pre>
      </div>
    </div>
  );
}

// --- Terminal View ---
function TerminalView({ item }: { item: CanvasItem }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [item.content]);

  // Very simple ANSI stripping for display (full ANSI would need a library)
  const cleaned = item.content.replace(/\x1B\[[0-9;]*[mGKJHF]/g, "");

  return (
    <div className="flex flex-col h-full bg-zinc-950">
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-white/10 bg-black/40">
        <div className="flex gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500/70" />
          <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/70" />
          <span className="w-2.5 h-2.5 rounded-full bg-green-500/70" />
        </div>
        <span className="ml-2 text-[11px] text-white/30 font-mono">
          {item.title ?? "terminal"}
        </span>
      </div>
      <div className="flex-1 overflow-auto p-4">
        <pre className="text-xs font-mono text-green-400 leading-relaxed whitespace-pre-wrap break-words">
          {cleaned || "(empty output)"}
        </pre>
        <div ref={endRef} />
      </div>
    </div>
  );
}

// --- Document View (Markdown / plain text) ---
function DocumentView({ item }: { item: CanvasItem }) {
  return (
    <div className="flex-1 overflow-auto p-5">
      <div className="max-w-2xl mx-auto">
        <pre className="text-sm text-white/80 leading-relaxed whitespace-pre-wrap font-sans">
          {item.content}
        </pre>
      </div>
    </div>
  );
}

// --- Screenshot Request View ---
function ScreenshotView({ item, onSendToTeaiBuilder }: { item: CanvasItem; onSendToTeaiBuilder?: (t: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center p-8">
      <Camera size={48} className="text-white/20" />
      <div>
        <p className="text-sm text-white/60 font-medium">Screenshot Requested</p>
        <p className="text-xs text-white/35 mt-1 max-w-xs">
          {item.title ?? "TeaiBuilder wants to see the current view."}
        </p>
      </div>
      {onSendToTeaiBuilder && (
        <Button
          variant="outline"
          size="sm"
          className="text-xs border-white/20 hover:bg-white/10"
          onClick={() =>
            onSendToTeaiBuilder(
              `[Screenshot] Current canvas view: ${(item.title ?? item.content) || "no content active"}`,
            )
          }
        >
          <Camera size={12} className="mr-1.5" /> Send canvas state to TeaiBuilder
        </Button>
      )}
    </div>
  );
}

// ── Active item renderer ───────────────────────────────────────────────────

function ActiveItemView({
  item,
  onSendToTeaiBuilder,
}: {
  item: CanvasItem;
  onSendToTeaiBuilder?: (t: string) => void;
}) {
  switch (item.type) {
    case "url":        return <BrowserView item={item} onSendToTeaiBuilder={onSendToTeaiBuilder} />;
    case "mobile_url": return <MobileView item={item} onSendToTeaiBuilder={onSendToTeaiBuilder} />;
    case "html":       return <HtmlView item={item} />;
    case "image":      return <ImageView item={item} />;
    case "video":      return <VideoView item={item} />;
    case "code":       return <CodeView item={item} />;
    case "terminal":   return <TerminalView item={item} />;
    case "document":   return <DocumentView item={item} />;
    case "screenshot": return <ScreenshotView item={item} onSendToTeaiBuilder={onSendToTeaiBuilder} />;
    default:           return <BrowserView item={item} />;
  }
}

// ── Add-URL modal ──────────────────────────────────────────────────────────

function AddUrlBar({
  onAdd,
  onCancel,
}: {
  onAdd: (url: string) => void;
  onCancel: () => void;
}) {
  const [val, setVal] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), []);

  const submit = () => {
    const url = val.trim();
    if (!url) return onCancel();
    onAdd(url.match(/^https?:\/\//i) ? url : `http://${url}`);
  };

  return (
    <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-white/10 bg-zinc-900">
      <Globe size={12} className="text-white/40 shrink-0" />
      <input
        ref={ref}
        type="text"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") onCancel();
        }}
        placeholder="http://localhost:3000"
        className="flex-1 min-w-0 h-6 px-2 rounded text-xs bg-white/10 border border-white/10 focus:border-white/30 focus:outline-none text-white/80 placeholder:text-white/30"
      />
      <button onClick={submit} className="text-[11px] text-emerald-400 hover:text-emerald-300 px-1">Open</button>
      <button onClick={onCancel} className="text-[11px] text-white/40 hover:text-white/60 px-1">✕</button>
    </div>
  );
}

// ── Empty state ────────────────────────────────────────────────────────────

function EmptyState({ onAddUrl }: { onAddUrl: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center p-8 select-none">
      <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center">
        <Monitor size={32} className="text-white/20" />
      </div>
      <div>
        <p className="text-sm text-white/40 font-medium">TeaiBuilder Workspace</p>
        <p className="text-xs text-white/25 mt-1.5 max-w-xs leading-relaxed">
          Apps, images, videos and code will appear here automatically as TeaiBuilder builds things.
        </p>
      </div>
      <Button
        variant="ghost" size="sm"
        className="h-7 text-xs text-white/40 hover:text-white gap-1.5 border border-white/10 hover:bg-white/10"
        onClick={onAddUrl}
      >
        <Globe size={11} /> Open a URL
      </Button>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function CanvasPanel({
  isOpen,
  isClosing,
  width,
  items,
  activeId,
  onSetActiveId,
  onRemoveItem,
  onClearAll,
  onAddItem,
  onClose,
  onResizeStart,
  onSendToTeaiBuilder,
}: CanvasPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [addingUrl, setAddingUrl] = useState(false);
  const navRef = useRef<HTMLDivElement>(null);

  // Animate in/out
  useLayoutEffect(() => {
    if (isOpen && !isClosing) {
      requestAnimationFrame(() => setVisible(true));
    } else if (isClosing) {
      setVisible(false);
    }
  }, [isOpen, isClosing]);

  const activeItem = items.find((i) => i.id === activeId) ?? items[items.length - 1] ?? null;
  const activeIndex = items.findIndex((i) => i.id === activeItem?.id);

  const goPrev = () => {
    if (activeIndex > 0) onSetActiveId(items[activeIndex - 1].id);
  };
  const goNext = () => {
    if (activeIndex < items.length - 1) onSetActiveId(items[activeIndex + 1].id);
  };

  const handleAddUrl = (url: string) => {
    onAddItem({ type: "url", content: url, title: url });
    setAddingUrl(false);
  };

  const handleSendScreenshot = useCallback(() => {
    if (!onSendToTeaiBuilder) return;
    if (activeItem) {
      if (activeItem.type === "image") {
        onSendToTeaiBuilder(`Here is the image I see in the workspace: ${activeItem.content}`);
      } else if (activeItem.type === "terminal" || activeItem.type === "code") {
        onSendToTeaiBuilder(`Here is the current ${activeItem.type} output in the workspace:\n\`\`\`\n${activeItem.content.slice(0, 3000)}\n\`\`\``);
      } else if (activeItem.type === "url" || activeItem.type === "mobile_url") {
        onSendToTeaiBuilder(`Capture and review ${activeItem.content}: call screenshot(url="${activeItem.content}"), show the result with canvas(type="image", content="<path>"), then analyze it and fix anything wrong.`);
      } else {
        onSendToTeaiBuilder(`What do you see in the workspace canvas? Current item: ${activeItem.title ?? activeItem.type} - ${activeItem.content.slice(0, 200)}`);
      }
    }
  }, [activeItem, onSendToTeaiBuilder]);

  if (!isOpen && !isClosing) return null;

  return (
    <>
      {/* Resize handle */}
      <div
        className="absolute top-0 bottom-0 w-1 cursor-col-resize z-20 hover:bg-white/20 transition-colors"
        style={{ left: 0 }}
        onMouseDown={onResizeStart}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className="flex flex-col h-full bg-zinc-900 border-l border-white/10 overflow-hidden relative"
        style={{
          width,
          transform: visible ? "translateX(0)" : "translateX(100%)",
          opacity: visible ? 1 : 0,
          transition: "transform 220ms ease, opacity 220ms ease",
        }}
      >
        {/* ── Top bar ── */}
        <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-white/10 bg-black/30 shrink-0">
          {/* Title */}
          <div className="flex items-center gap-1.5 shrink-0 mr-1">
            <Monitor size={13} className="text-white/40" />
            <span className="text-[11px] font-medium text-white/40 hidden sm:block">Workspace</span>
          </div>

          {/* Nav arrows */}
          {items.length > 1 && (
            <>
              <button
                onClick={goPrev}
                disabled={activeIndex <= 0}
                className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10 disabled:opacity-30 text-white/50"
              >
                <ChevronLeft size={12} />
              </button>
              <button
                onClick={goNext}
                disabled={activeIndex >= items.length - 1}
                className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10 disabled:opacity-30 text-white/50"
              >
                <ChevronRight size={12} />
              </button>
            </>
          )}

          {/* Pills nav */}
          <div
            ref={navRef}
            className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none"
          >
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => onSetActiveId(item.id)}
                className={cn(
                  "flex items-center gap-1 shrink-0 h-5 px-1.5 rounded text-[11px] transition-colors group relative",
                  item.id === activeItem?.id
                    ? "bg-white/15 text-white/90"
                    : "text-white/40 hover:text-white/70 hover:bg-white/10",
                )}
                title={item.title ?? item.content.slice(0, 60)}
              >
                {typeIcon(item.type, 11)}
                <span className="max-w-[80px] truncate">
                  {item.title ?? typeLabel(item.type)}
                </span>
                <span
                  className="ml-0.5 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer hover:text-red-400"
                  onClick={(e) => { e.stopPropagation(); onRemoveItem(item.id); }}
                >
                  <X size={9} />
                </span>
              </button>
            ))}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-0.5 shrink-0">
            {/* Add URL */}
            <button
              onClick={() => setAddingUrl(true)}
              className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10 text-white/40 hover:text-white/70"
              title="Open URL in workspace"
            >
              <Plus size={12} />
            </button>
            {/* Send to teai_builder */}
            {onSendToTeaiBuilder && activeItem && (
              <button
                onClick={handleSendScreenshot}
                className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10 text-white/40 hover:text-white/70"
                title="Send current view to TeaiBuilder"
              >
                <Camera size={12} />
              </button>
            )}
            {/* Clear all */}
            {items.length > 0 && (
              <button
                onClick={onClearAll}
                className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10 text-white/40 hover:text-red-400"
                title="Clear workspace"
              >
                <Trash2 size={11} />
              </button>
            )}
            {/* More / item count */}
            {items.length > 0 && (
              <span className="text-[10px] text-white/25 px-1 font-mono">
                {activeIndex + 1}/{items.length}
              </span>
            )}
            {/* Close */}
            <button
              onClick={onClose}
              className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10 text-white/40 hover:text-white/70"
            >
              <X size={12} />
            </button>
          </div>
        </div>

        {/* ── URL input bar ── */}
        {addingUrl && (
          <AddUrlBar onAdd={handleAddUrl} onCancel={() => setAddingUrl(false)} />
        )}

        {/* ── Main content ── */}
        <div className="flex-1 overflow-hidden relative">
          {activeItem ? (
            <ActiveItemView item={activeItem} onSendToTeaiBuilder={onSendToTeaiBuilder} />
          ) : (
            <EmptyState onAddUrl={() => setAddingUrl(true)} />
          )}
        </div>

        {/* ── Bottom info bar (when item is active) ── */}
        {activeItem && (
          <div className="flex items-center gap-2 px-3 py-1 border-t border-white/8 bg-black/20 shrink-0">
            <span className="flex items-center gap-1 text-[10px] text-white/25 font-mono truncate flex-1 min-w-0">
              {typeIcon(activeItem.type, 10)}
              <span className="truncate">{activeItem.content.slice(0, 80)}</span>
            </span>
            {activeItem.source === "tool" && (
              <span className="text-[9px] text-emerald-400/50 shrink-0">● live</span>
            )}
          </div>
        )}
      </div>
    </>
  );
}
