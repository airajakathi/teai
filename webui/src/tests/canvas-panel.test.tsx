import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CanvasPanel } from "@/components/CanvasPanel";
import type { CanvasItem } from "@/hooks/useCanvasContent";

function renderCanvas(
  item: CanvasItem,
  options?: { onSendToTeaiBuilder?: (text: string) => void },
) {
  return render(
    <CanvasPanel
      isOpen
      isClosing={false}
      width={560}
      items={[item]}
      activeId={item.id}
      onSetActiveId={() => {}}
      onRemoveItem={() => {}}
      onClearAll={() => {}}
      onAddItem={() => {}}
      onClose={() => {}}
      onResizeStart={() => {}}
      onSendToTeaiBuilder={options?.onSendToTeaiBuilder}
    />,
  );
}

describe("CanvasPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("open", vi.fn());
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("<html><body>ok</body></html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("supports zoom, device presets, refresh, copy, and open actions for browser previews", async () => {
    renderCanvas({
      id: "url-preview",
      type: "url",
      content: "http://localhost:3000",
      title: "Local app",
      addedAt: 1,
      source: "tool",
    });

    const browserFrame = screen.getByTestId("browser-preview-frame");
    expect(browserFrame).toHaveAttribute("data-preview-device", "desktop");
    expect(browserFrame).toHaveAttribute("data-preview-zoom", "100%");
    expect(browserFrame).toHaveAttribute("data-preview-state", "loading");

    fireEvent.load(screen.getByTitle("Canvas Preview"));
    await waitFor(() => {
      expect(browserFrame).toHaveAttribute("data-preview-state", "ready");
    });

    fireEvent.click(screen.getByRole("button", { name: /mobile preview/i }));
    fireEvent.click(screen.getByRole("button", { name: /zoom in/i }));

    await waitFor(() => {
      expect(browserFrame).toHaveAttribute("data-preview-device", "mobile");
      expect(browserFrame).toHaveAttribute("data-preview-zoom", "110%");
    });

    fireEvent.click(screen.getByRole("button", { name: /copy preview url/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("http://localhost:3000");
    });

    fireEvent.click(screen.getByRole("button", { name: /open preview in new tab/i }));
    expect(window.open).toHaveBeenCalledWith("http://localhost:3000", "_blank");

    const iframe = screen.getByTitle("Canvas Preview");
    const firstKey = iframe.getAttribute("src");
    fireEvent.click(screen.getByRole("button", { name: /reload/i }));
    expect(screen.getByTitle("Canvas Preview")).toHaveAttribute("src", firstKey);
  });

  it("supports mobile device preview controls including rotate, zoom, copy, and external open", async () => {
    renderCanvas({
      id: "mobile-preview",
      type: "mobile_url",
      content: "https://example.com/mobile",
      title: "Mobile app",
      addedAt: 1,
      source: "tool",
    });

    const mobileFrame = screen.getByTestId("mobile-preview-frame");
    expect(mobileFrame).toHaveAttribute("data-mobile-device", "ios");
    expect(mobileFrame).toHaveAttribute("data-mobile-orientation", "portrait");
    expect(mobileFrame).toHaveAttribute("data-preview-zoom", "100%");
    expect(mobileFrame).toHaveAttribute("data-preview-state", "loading");

    fireEvent.load(screen.getByTitle("Mobile Preview"));
    await waitFor(() => {
      expect(mobileFrame).toHaveAttribute("data-preview-state", "ready");
    });

    fireEvent.click(screen.getByRole("button", { name: /android shell/i }));
    fireEvent.click(screen.getByRole("button", { name: /rotate device/i }));
    fireEvent.click(screen.getByRole("button", { name: /zoom in/i }));

    await waitFor(() => {
      expect(mobileFrame).toHaveAttribute("data-mobile-device", "android");
      expect(mobileFrame).toHaveAttribute("data-mobile-orientation", "landscape");
      expect(mobileFrame).toHaveAttribute("data-preview-zoom", "110%");
    });

    fireEvent.click(screen.getByRole("button", { name: /copy mobile preview link/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("https://example.com/mobile");
    });

    fireEvent.click(screen.getByRole("button", { name: /open mobile preview externally/i }));
    expect(window.open).toHaveBeenCalledWith("https://example.com/mobile", "_blank");
  });

  it("keeps exp:// previews in native Expo mode and offers a separate web-mirror action", async () => {
    renderCanvas({
      id: "expo-preview",
      type: "mobile_url",
      content: "exp://192.168.0.178:8081",
      title: "Expo app",
      addedAt: 1,
      source: "tool",
    });

    const mobileFrame = screen.getByTestId("mobile-preview-frame");
    expect(mobileFrame).toHaveAttribute("data-mobile-device", "ios");
    expect(screen.getByText("Expo Native Preview")).toBeInTheDocument();
    expect(screen.queryByTitle("Live App Preview")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open expo web mirror/i }));
    expect(window.open).toHaveBeenCalledWith("http://192.168.0.178:8081", "_blank");
  });

  it("shows a clear browser preview slow-state when the iframe stays blank too long", async () => {
    vi.useFakeTimers();
    const sendToTeaiBuilder = vi.fn();

    renderCanvas({
      id: "url-preview-error",
      type: "url",
      content: "http://localhost:3000",
      title: "Broken app",
      addedAt: 1,
      source: "tool",
    }, { onSendToTeaiBuilder: sendToTeaiBuilder });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });

    expect(screen.getByTestId("browser-preview-frame")).toHaveAttribute("data-preview-state", "slow");
    expect(screen.getAllByText(/preview is taking longer than expected/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Diagnose" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /reload/i }));
    expect(screen.getByTestId("browser-preview-frame")).toHaveAttribute("data-preview-state", "loading");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });

    expect(screen.getByText(/preview is repeatedly getting stuck\. diagnose is recommended/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Diagnose recommended" }));
    expect(sendToTeaiBuilder).toHaveBeenCalledWith(
      expect.stringContaining("Diagnose and fix Broken app."),
    );
  });

  it("shows a clear mobile preview slow-state when the iframe stays blank too long", async () => {
    vi.useFakeTimers();
    const sendToTeaiBuilder = vi.fn();

    renderCanvas({
      id: "mobile-preview-error",
      type: "mobile_url",
      content: "https://example.com/mobile",
      title: "Broken mobile app",
      addedAt: 1,
      source: "tool",
    }, { onSendToTeaiBuilder: sendToTeaiBuilder });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });

    expect(screen.getByTestId("mobile-preview-frame")).toHaveAttribute("data-preview-state", "slow");
    expect(screen.getByText(/preview is slow or may be stuck/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Diagnose" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByTestId("mobile-preview-frame")).toHaveAttribute("data-preview-state", "loading");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });

    expect(screen.getByText(/preview is repeatedly getting stuck\. diagnose is recommended/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Diagnose recommended" }));
    expect(sendToTeaiBuilder).toHaveBeenCalledWith(
      expect.stringContaining("Diagnose and fix Broken mobile app."),
    );
  });

  it("resets browser stuck escalation after a successful load", async () => {
    vi.useFakeTimers();

    renderCanvas({
      id: "url-preview-reset",
      type: "url",
      content: "http://localhost:3000",
      title: "Recovering app",
      addedAt: 1,
      source: "tool",
    }, { onSendToTeaiBuilder: vi.fn() });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });
    fireEvent.click(screen.getByRole("button", { name: /reload/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });
    expect(screen.getByRole("button", { name: "Diagnose recommended" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.load(screen.getByTitle("Canvas Preview"));
    });
    expect(screen.getByTestId("browser-preview-frame")).toHaveAttribute("data-preview-state", "ready");

    fireEvent.click(screen.getByRole("button", { name: /reload/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });

    expect(screen.getByRole("button", { name: "Diagnose" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Diagnose recommended" })).not.toBeInTheDocument();
  });

  it("resets mobile stuck escalation after a successful load", async () => {
    vi.useFakeTimers();

    renderCanvas({
      id: "mobile-preview-reset",
      type: "mobile_url",
      content: "https://example.com/mobile",
      title: "Recovering mobile app",
      addedAt: 1,
      source: "tool",
    }, { onSendToTeaiBuilder: vi.fn() });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });
    fireEvent.click(screen.getByRole("button", { name: /refresh mobile preview/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });
    expect(screen.getByRole("button", { name: "Diagnose recommended" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.load(screen.getByTitle("Mobile Preview"));
    });
    expect(screen.getByTestId("mobile-preview-frame")).toHaveAttribute("data-preview-state", "ready");

    fireEvent.click(screen.getByRole("button", { name: /refresh mobile preview/i }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8100);
    });

    expect(screen.getByRole("button", { name: "Diagnose" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Diagnose recommended" })).not.toBeInTheDocument();
  });
});
