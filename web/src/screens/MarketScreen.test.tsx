import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { WorkflowProvider } from "../contexts/WorkflowContext";
import { MarketScreen } from "./MarketScreen";

const contractReadyOverview = {
  regime: {
    label: "Bull — Momentum",
    trend: "up",
    breadth: "strong",
    volatility: "low",
    home_market: "US",
    as_of: "2026-01-01",
    status: "contract_ready",
  },
  indices: [
    { symbol: "SPY", name: "S&P 500", price: 500.0, change_pct: 0.5, status: "contract_ready" },
  ],
  breadth: { advancing: 300, declining: 150, unchanged: 50 },
  status: "contract_ready",
};

function stubFetch(response = contractReadyOverview) {
  const mock = vi.fn(async (url: string) => {
    const path = new URL(url, "http://127.0.0.1").pathname + new URL(url, "http://127.0.0.1").search;
    if (path === "/api/market/overview") {
      return { ok: true, json: async () => response };
    }
    if (path.startsWith("/api/market/chart")) {
      return { ok: true, json: async () => ({ points: [{ time: 1, value: 500 }, { time: 2, value: 505 }] }) };
    }
    if (path === "/api/market/sectors") {
      return {
        ok: true,
        json: async () => ({
          sectors: [
            { symbol: "XLK", name: "Technology", change_pct: 1.2 },
            { symbol: "XLE", name: "Energy", change_pct: -0.8 },
          ],
        }),
      };
    }
    if (path === "/api/market/calendar?days=7") {
      return {
        ok: true,
        json: async () => ({
          events: [
            { date: "2026-01-02", name: "CPI", impact: "H" },
            { date: "2026-01-03", name: "Minor data", impact: "L" },
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
    stubFetch();
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
    await waitFor(() => expect(screen.getByText("300")).toBeInTheDocument());
    expect(screen.getByText("150")).toBeInTheDocument();
  });

  it("shows live indicator element", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText(/live|delayed/i)).toBeInTheDocument());
  });

  it("connects live market websocket to the backend origin during Vite dev", async () => {
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
    renderScreen();
    await waitFor(() => expect(instances[0]?.url).toBe("ws://127.0.0.1:8000/api/market/live"));
  });

  it("renders home-index chart controls, sector heatmap, and economic calendar", async () => {
    stubFetch();
    renderScreen();
    await waitFor(() => expect(screen.getByText("XLK")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "1D" })).toBeInTheDocument();
    expect(screen.getByText("XLE")).toBeInTheDocument();
    expect(screen.getByText("CPI")).toBeInTheDocument();
    expect(screen.queryByText("Minor data")).not.toBeInTheDocument();
  });
});
