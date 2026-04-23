import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { HistoryScreen } from "./HistoryScreen";

function stubFetch() {
  const mock = vi.fn(async (url: string) => {
    if (url === "/api/history") {
      return {
        ok: true,
        json: async () => ({
          items: [
            {
              id: "strategy-001",
              type: "strategy_plan",
              title: "Breakout v2",
              status: "ready",
              created_at: "2026-01-01T00:00:00Z",
              completed_at: "2026-01-01T00:15:00Z",
              home_market: "US",
              workflow_session_id: "session-001",
              summary: "4 trades · gross 42%",
            },
          ],
        }),
      };
    }
    return { ok: false, json: async () => ({ items: [] }) };
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("HistoryScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders history items from the backend envelope", async () => {
    stubFetch();
    render(<HistoryScreen />);
    await waitFor(() => expect(screen.getByText("Breakout v2")).toBeInTheDocument());
    expect(screen.getByText("strategy plan")).toBeInTheDocument();
    expect(screen.getByText("4 trades · gross 42%")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
  });
});
