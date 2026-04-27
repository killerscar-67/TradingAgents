import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkflowProvider } from "../contexts/WorkflowContext";
import { MarketScreen } from "./MarketScreen";
import type { MarketOverview } from "../types";

const contractReadyOverview: MarketOverview = {
  home_market: "US",
  trade_date: "2026-01-01",
  regime: {
    label: "Bull — Momentum",
    confidence: 82,
    suggested_entry_mode: "breakout",
    event_risk_flag: false,
  },
  indices: [
    { symbol: "SPY", label: "S&P 500", price: 500.0, change_pct: 0.5 },
  ],
  breadth: {
    pct_above_50d: 64.5,
    pct_above_200d: 58.2,
    new_highs_minus_lows: 18,
    advance_decline_ratio: 1.67,
    mcclellan_oscillator: 12.4,
    headline: "Broad participation",
  },
  sectors: [
    { symbol: "XLK", label: "Technology", change_pct: 1.2 },
    { symbol: "XLE", label: "Energy", change_pct: -0.8 },
  ],
  events: [
    { date: "2026-01-02", name: "CPI", impact: "H" },
    { date: "2026-01-03", name: "Minor data", impact: "L" },
  ],
  calendar_status: {
    provider: "fmp",
    state: "ready",
    message: null,
  },
  finance_events: [
    { date: "2026-01-07", symbol: "AAPL", name: "Earnings", event_type: "earnings" },
    { date: "2026-01-15", symbol: "MSFT", name: "Earnings", event_type: "earnings" },
  ],
  finance_calendar_status: {
    provider: "fmp",
    state: "ready",
    message: null,
  },
  status: "ready",
};

function stubFetch(response = contractReadyOverview) {
  const mock = vi.fn(async (url: string) => {
    const path = new URL(url, "http://127.0.0.1").pathname + new URL(url, "http://127.0.0.1").search;
    if (path === "/api/market/overview") {
      return { ok: true, json: async () => response };
    }
    if (path.startsWith("/api/market/chart")) {
      return {
        ok: true,
        json: async () => ({
          interval: new URL(url, "http://127.0.0.1").searchParams.get("interval") ?? "1D",
          has_more: true,
          points: [{ time: 1, value: 500 }, { time: 2, value: 505 }],
          bars: [
            { time: 1, open: 495, high: 502, low: 492, close: 500 },
            { time: 2, open: 500, high: 507, low: 498, close: 505 },
          ],
        }),
      };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  // Stub WebSocket to avoid connection errors
  vi.stubGlobal("WebSocket", class {
    url: string;
    onopen: (() => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(url: string) { this.url = url; }
    close() {}
  });
  return mock;
}

function stubPendingFetch() {
  const mock = vi.fn(() => new Promise(() => {}));
  vi.stubGlobal("fetch", mock);
  vi.stubGlobal("WebSocket", class {
    url: string;
    onopen: (() => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(url: string) { this.url = url; }
    close() {}
  });
  return mock;
}

function renderScreen() {
  return render(
    <WorkflowProvider>
      <MarketScreen />
    </WorkflowProvider>
  );
}

describe("MarketScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows loading state initially", () => {
    stubPendingFetch();
    renderScreen();
    expect(screen.getByText(/loading market data/i)).toBeInTheDocument();
  });

  it("renders regime label after data loads", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText(/bull.*momentum/i)).toBeInTheDocument());
  });

  it("does not update workflow state during render", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText(/bull.*momentum/i)).toBeInTheDocument());
    expect(errorSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("Cannot update a component while rendering a different component")
    );
    errorSpy.mockRestore();
  });

  it("renders index tiles", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText("SPY")).toBeInTheDocument());
    expect(screen.getByText("+0.50%")).toBeInTheDocument();
  });

  it("renders breadth numbers", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText("64.5%")).toBeInTheDocument());
    expect(screen.getByText("1.67")).toBeInTheDocument();
    expect(screen.getByText("+18")).toBeInTheDocument();
    expect(screen.getByText("Broad participation")).toBeInTheDocument();
  });

  it("shows live indicator element", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText(/live|delayed/i)).toBeInTheDocument());
  });

  it("connects live market websocket through the current app origin", async () => {
    const instances: Array<{ url: string }> = [];
    stubFetch();
    vi.stubGlobal("location", {
      port: "5173",
      protocol: "http:",
      hostname: "127.0.0.1",
      origin: "http://127.0.0.1:5173",
      href: "http://127.0.0.1:5173/",
    });
    vi.stubGlobal("WebSocket", class {
      url: string;
      onopen: (() => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(url: string) {
        this.url = url;
        instances.push(this);
      }
      close() {}
    });
    renderScreen();
    await waitFor(() => expect(instances[0]?.url).toBe("ws://127.0.0.1:5173/api/market/live"));
  });

  it("does not construct a websocket when cleanup runs before deferred connect", () => {
    vi.useFakeTimers();
    const instances: Array<{ url: string }> = [];
    stubFetch();
    vi.stubGlobal("WebSocket", class {
      url: string;
      onopen: (() => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(url: string) {
        this.url = url;
        instances.push(this);
      }
      close() {}
    });
    const { unmount } = renderScreen();
    unmount();
    act(() => {
      vi.runOnlyPendingTimers();
    });
    expect(instances).toHaveLength(0);
    vi.useRealTimers();
  });

  it("renders a merged monthly market calendar with colored event types", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText("Technology")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "15m" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "4h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1D" })).toBeInTheDocument();
    expect(screen.getByText(/session timing appears on intraday charts/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Candles" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Line" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("CPI")).toBeInTheDocument();
    expect(screen.getByText("Market calendar")).toBeInTheDocument();
    expect(screen.getByText("Macro high")).toBeInTheDocument();
    expect(screen.getByText("Macro medium")).toBeInTheDocument();
    expect(screen.getAllByText("Earnings").length).toBeGreaterThan(0);
    expect(screen.getByText("January 2026")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.queryByText("Minor data")).not.toBeInTheDocument();
  });

  it("lets the user change calendar months", async () => {
    stubFetch({
      ...contractReadyOverview,
      events: [
        ...(contractReadyOverview.events ?? []),
        { date: "2025-12-18", name: "FOMC", impact: "H" },
        { date: "2026-02-12", name: "PPI", impact: "M" },
      ],
      finance_events: [
        ...(contractReadyOverview.finance_events ?? []),
        { date: "2026-02-04", symbol: "AMZN", name: "Earnings", event_type: "earnings" },
      ],
    });
    renderScreen();

    await waitFor(() => expect(screen.getByText("January 2026")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Prev month" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next month" })).toBeEnabled();

    await userEvent.setup().click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByText("February 2026")).toBeInTheDocument();
    expect(screen.getByText("AMZN")).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Prev month" }));
    await userEvent.setup().click(screen.getByRole("button", { name: "Prev month" }));
    expect(screen.getByText("December 2025")).toBeInTheDocument();
    expect(screen.getByText("FOMC")).toBeInTheDocument();
  });

  it("shows a clear calendar empty state when the provider is unavailable", async () => {
    stubFetch({
      ...contractReadyOverview,
      events: [],
      calendar_status: {
        provider: "fmp",
        state: "unavailable",
        message: "Economic calendar unavailable. Set FMP_API_KEY to load upcoming events.",
      },
      finance_events: [],
      finance_calendar_status: {
        provider: "fmp",
        state: "unavailable",
        message: "Financial calendar unavailable. Set FMP_API_KEY to load upcoming events.",
      },
    });
    renderScreen();

    await waitFor(() =>
      expect(screen.getByText(/economic calendar unavailable\. set fmp_api_key to load upcoming events\./i)).toBeInTheDocument()
    );
  });

  it("does not make extra market panel requests outside the overview payload", async () => {
    const mockFetch = stubFetch();
    renderScreen();

    await waitFor(() => expect(screen.getByText("Technology")).toBeInTheDocument());
    expect(
      mockFetch.mock.calls.some(([url]) => String(url).includes("/api/market/sectors"))
    ).toBe(false);
    expect(
      mockFetch.mock.calls.some(([url]) => String(url).includes("/api/market/calendar"))
    ).toBe(false);
  });

  it("renders the current regime contract fields", async () => {
    stubFetch();
    renderScreen();

    await waitFor(() => expect(screen.getByText("Confidence: 82%")).toBeInTheDocument());
    expect(screen.getByText("Entry: breakout")).toBeInTheDocument();
    expect(screen.getByText("Event Risk: Normal")).toBeInTheDocument();
    expect(screen.getByText(/as of 2026-01-01/i)).toBeInTheDocument();
  });

  it("does not expose ET session controls for markets without ET trading sessions", async () => {
    const mockFetch = stubFetch({
      ...contractReadyOverview,
      home_market: "CA",
      regime: {
        ...contractReadyOverview.regime,
      },
    });
    renderScreen();

    await waitFor(() =>
      expect(
        mockFetch.mock.calls.some(
          ([url]) => String(url).includes("/api/market/chart?") && String(url).includes("symbol=XIU.TO")
        )
      ).toBe(true)
    );

    await userEvent.setup().click(screen.getByRole("button", { name: "15m" }));

    await waitFor(() => expect(screen.getByText(/session timing unavailable for this market/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Regular" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Extended" })).not.toBeInTheDocument();
    expect(
      mockFetch.mock.calls.some(
        ([url]) => String(url).includes("/api/market/chart?") && String(url).includes("symbol=XIU.TO") && String(url).includes("session=")
      )
    ).toBe(false);
  });

  it("does not reset the chart on websocket snapshots when symbol and trade date stay the same", async () => {
    const mockFetch = stubFetch();
    const sockets: Array<{
      onopen: (() => void) | null;
      onmessage: ((e: MessageEvent) => void) | null;
      onclose: (() => void) | null;
      onerror: (() => void) | null;
      close: () => void;
      url: string;
    }> = [];

    vi.stubGlobal("WebSocket", class {
      url: string;
      onopen: (() => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(url: string) {
        this.url = url;
        sockets.push(this);
      }
      close() {}
    });

    renderScreen();
    await waitFor(() =>
      expect(
        mockFetch.mock.calls.filter(([url]) => String(url).includes("/api/market/chart?")).length
      ).toBe(1)
    );

    await act(async () => {
      sockets[0]?.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "market_snapshot",
            payload: {
              ...contractReadyOverview,
              regime: {
                ...contractReadyOverview.regime,
                confidence: 79,
              },
            },
          }),
        })
      );
    });

    await waitFor(() => expect(screen.getByText("Confidence: 79%")).toBeInTheDocument());
    expect(
      mockFetch.mock.calls.filter(([url]) => String(url).includes("/api/market/chart?")).length
    ).toBe(1);
  });

  it("recovers from an initial overview fetch failure when a websocket snapshot arrives", async () => {
    const sockets: Array<{
      onopen: (() => void) | null;
      onmessage: ((e: MessageEvent) => void) | null;
      onclose: (() => void) | null;
      onerror: (() => void) | null;
      close: () => void;
      url: string;
    }> = [];

    const mockFetch = vi.fn(async (url: string) => {
      const path = new URL(url, "http://127.0.0.1").pathname + new URL(url, "http://127.0.0.1").search;
      if (path === "/api/market/overview") {
        throw new Error("network lost");
      }
      if (path.startsWith("/api/market/chart")) {
        return {
          ok: true,
          json: async () => ({
            interval: "1D",
            has_more: false,
            points: [{ time: 1, value: 500 }],
            bars: [{ time: 1, open: 495, high: 502, low: 492, close: 500 }],
          }),
        };
      }
      return { ok: false, json: async () => ({}) };
    });

    vi.stubGlobal("fetch", mockFetch);
    vi.stubGlobal("WebSocket", class {
      url: string;
      onopen: (() => void) | null = null;
      onmessage: ((e: MessageEvent) => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(url: string) {
        this.url = url;
        sockets.push(this);
      }
      close() {}
    });

    renderScreen();
    await waitFor(() => expect(screen.getByText(/markets are closed\. showing last session\./i)).toBeInTheDocument());

    await act(async () => {
      sockets[0]?.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "market_snapshot",
            payload: contractReadyOverview,
          }),
        })
      );
    });

    await waitFor(() => expect(screen.getByText(/bull.*momentum/i)).toBeInTheDocument());
    expect(screen.queryByText(/markets are closed\. showing last session\./i)).not.toBeInTheDocument();
  });

  it("lets the user toggle between candle and line charts", async () => {
    const user = userEvent.setup();
    stubFetch();
    renderScreen();

    const candlesButton = await screen.findByRole("button", { name: "Candles" });
    const lineButton = screen.getByRole("button", { name: "Line" });

    expect(candlesButton).toHaveAttribute("aria-pressed", "true");
    expect(lineButton).toHaveAttribute("aria-pressed", "false");

    await user.click(lineButton);

    expect(candlesButton).toHaveAttribute("aria-pressed", "false");
    expect(lineButton).toHaveAttribute("aria-pressed", "true");
  });

  it("requests chart data for the selected interval and intraday session", async () => {
    const user = userEvent.setup();
    const mockFetch = stubFetch();
    renderScreen();

    await waitFor(() =>
      expect(
        mockFetch.mock.calls.some(
          ([url]) => String(url).includes("/api/market/chart?") && String(url).includes("interval=1D")
        )
      ).toBe(true)
    );

    await user.click(screen.getByRole("button", { name: "4h" }));

    await waitFor(() =>
      expect(
        mockFetch.mock.calls.some(
          ([url]) =>
            String(url).includes("/api/market/chart?") &&
            String(url).includes("interval=4h") &&
            String(url).includes("session=regular")
        )
      ).toBe(true)
    );

    expect(screen.getByRole("button", { name: "Regular" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Extended" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "Extended" }));

    await waitFor(() =>
      expect(
        mockFetch.mock.calls.some(
          ([url]) =>
            String(url).includes("/api/market/chart?") &&
            String(url).includes("interval=4h") &&
            String(url).includes("session=extended")
        )
      ).toBe(true)
    );
  });
});
