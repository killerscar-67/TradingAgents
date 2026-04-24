import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HistoryScreen } from "./HistoryScreen";
import { WorkflowProvider } from "../contexts/WorkflowContext";

function stubFetch(items = [
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
  {
    id: "legacy-001",
    type: "legacy_analysis",
    title: "AAPL analysis",
    status: "completed",
    created_at: "2026-01-02T00:00:00Z",
    completed_at: "2026-01-02T00:15:00Z",
    home_market: "US",
    workflow_session_id: null,
    summary: "BUY",
  },
]) {
  const mock = vi.fn(async (url: string) => {
    if (url === "/api/history") {
      return {
        ok: true,
        json: async () => ({ items }),
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

  it("shows record time for history items", async () => {
    stubFetch([
      {
        id: "run-1",
        type: "analysis_run",
        title: "AAPL",
        status: "completed",
        created_at: "2026-04-24T13:05:00Z",
        completed_at: "2026-04-24T13:37:00Z",
        home_market: "US",
        workflow_session_id: "session-1",
        summary: "Completed run",
      },
    ]);

    render(<HistoryScreen />);

    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(
      screen.getByText(
        new Date("2026-04-24T13:37:00Z").toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
        })
      )
    ).toBeInTheDocument();
  });

  it("filters history by search, type, and status and renders secondary actions", async () => {
    stubFetch();
    render(
      <WorkflowProvider>
        <HistoryScreen />
      </WorkflowProvider>
    );
    await waitFor(() => expect(screen.getByText("Breakout v2")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/search history/i), { target: { value: "aapl" } });
    expect(screen.queryByText("Breakout v2")).not.toBeInTheDocument();
    expect(screen.getByText("AAPL analysis")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/type filter/i), { target: { value: "strategy_plan" } });
    expect(screen.queryByText("AAPL analysis")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/search history/i), { target: { value: "" } });
    expect(screen.getByText("Breakout v2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-run breakout v2/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export breakout v2/i })).toBeInTheDocument();
  });
});
