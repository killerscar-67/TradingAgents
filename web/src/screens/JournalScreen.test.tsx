import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { JournalScreen } from "./JournalScreen";

function stubJournalFetch() {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/journal/decisions?limit=50") {
      return {
        ok: true,
        json: async () => ({
          status: "ready",
          decisions: [{
            id: 42,
            created_at: "2026-04-23T14:00:00Z",
            trade_datetime: "2026-04-23T10:15:00-04:00",
            symbol: "AAPL",
            trading_style: "daytrade",
            session_phase: "regular",
            setup_name: "VWAP reclaim",
            bias: "long",
            entry: 101.5,
            stop: 100.7,
            target1: 103,
            confidence: "medium",
            rationale: "Price reclaimed VWAP.",
          }],
        }),
      };
    }
    if (url === "/api/journal/reports?by=strategy") {
      return {
        ok: true,
        json: async () => ({
          status: "ready",
          by: "strategy",
          markdown: "| Strategy | Trades |\n|---|---:|\n| VWAP reclaim | 1 |",
          rows: [{ Strategy: "VWAP reclaim", Trades: "1" }],
        }),
      };
    }
    if (url === "/api/journal/actions" && init?.method === "POST") {
      return { ok: true, json: async () => ({ status: "ready", action_id: 7 }) };
    }
    return { ok: false, json: async () => ({ detail: `Unexpected ${url}` }) };
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("JournalScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders journal decisions and strategy report", async () => {
    stubJournalFetch();
    render(<JournalScreen />);

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getAllByText("VWAP reclaim").length).toBeGreaterThan(0);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("long")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("logs a human action against a decision", async () => {
    const fetchMock = stubJournalFetch();
    render(<JournalScreen />);

    await waitFor(() => expect(screen.getByRole("button", { name: /log action for aapl/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /log action for aapl/i }));
    fireEvent.change(screen.getByLabelText(/fill price/i), { target: { value: "101.5" } });
    fireEvent.change(screen.getByLabelText(/size/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /save action/i }));

    await waitFor(() => expect(screen.getByText(/action recorded/i)).toBeInTheDocument());
    const [, init] = fetchMock.mock.calls.find(([url]) => url === "/api/journal/actions") ?? [];
    const payload = JSON.parse(String(init?.body));
    expect(payload.decision_id).toBe(42);
    expect(payload.actor).toBe("human");
    expect(payload.fill_price).toBe(101.5);
    expect(payload.size).toBe(10);
  });
});
