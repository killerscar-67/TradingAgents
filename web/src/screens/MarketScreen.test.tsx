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
    if (url === "/api/market/overview") {
      return { ok: true, json: async () => response };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  // Stub WebSocket to avoid connection errors
  vi.stubGlobal("WebSocket", class {
    onopen: (() => void) | null = null;
    onmessage: ((e: MessageEvent) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
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
});
