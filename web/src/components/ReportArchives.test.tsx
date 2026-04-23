import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ReportArchives } from "./ReportArchives";

describe("ReportArchives", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists archived analysis runs and reopens a selected report", async () => {
    const onOpenRun = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        runs: [
          {
            run_id: "run-1",
            ticker: "NVDA",
            analysis_date: "2026-04-22",
            selected_analysts: ["market", "news"],
            execution_mode: "llm_assisted",
            llm_provider: "openai",
            deep_think_llm: "gpt-5.4",
            quick_think_llm: "gpt-5.4-mini",
            created_at: "2026-04-22T11:00:00Z",
            status: "completed",
            started_at: "2026-04-22T11:00:01Z",
            completed_at: "2026-04-22T11:05:00Z",
            report_sections: { market_report: "NVDA report" },
            report_paths: {},
            stats: {},
            errors: [],
            final_order_intent: null,
          },
        ],
      }),
    }));

    render(<ReportArchives onOpenRun={onOpenRun} onNewAnalysis={vi.fn()} />);

    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("2026-04-22")).toBeInTheDocument();
    expect(screen.getByText(/gpt-5\.4-mini/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open report for nvda/i }));

    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-1"));
  });
});
