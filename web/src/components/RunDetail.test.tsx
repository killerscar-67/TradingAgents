import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RunDetail } from "./RunDetail";

describe("RunDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders daytrade metadata and structured intraday decisions", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/analysis/run-1") {
        return {
          ok: true,
          json: async () => ({
            run_id: "run-1",
            ticker: "AAPL",
            analysis_date: "2026-04-23",
            selected_analysts: ["intraday_market", "news"],
            execution_mode: "llm_assisted",
            llm_provider: "openai",
            deep_think_llm: "gpt-5.4",
            quick_think_llm: "gpt-5.4-mini",
            created_at: "2026-04-23T14:00:00Z",
            status: "completed",
            started_at: "2026-04-23T14:00:01Z",
            completed_at: "2026-04-23T14:01:00Z",
            report_sections: { market_report: "VWAP reclaim is active." },
            report_paths: {},
            stats: {},
            errors: [],
            final_order_intent: null,
            trading_style: "daytrade",
            intraday_interval: "15m",
            trade_datetime: "2026-04-23T10:15:00-04:00",
            session_phase: "regular",
            data_session_date: "2026-04-23",
            intraday_decisions: [{
              variant: "default",
              setup_name: "VWAP reclaim",
              bias: "long",
              entry: 101.5,
              stop: 100.7,
              target1: 103,
              confidence: "medium",
              invalidation: "Lose VWAP",
              rationale: "Price reclaimed VWAP with volume.",
            }],
          }),
        };
      }
      return { ok: true, json: async () => ({ sections: {} }) };
    }));

    render(<RunDetail runId="run-1" onBack={() => {}} />);

    await waitFor(() => expect(screen.getByText("Intraday Setup")).toBeInTheDocument());
    expect(screen.getByText("daytrade")).toBeInTheDocument();
    expect(screen.getByText("15m")).toBeInTheDocument();
    expect(screen.getByText("regular")).toBeInTheDocument();
    expect(screen.getByText("VWAP reclaim")).toBeInTheDocument();
    expect(screen.getByText(/Price reclaimed VWAP with volume/i)).toBeInTheDocument();
    expect(screen.getByText(/Entry 101.5/i)).toBeInTheDocument();
  });
});
