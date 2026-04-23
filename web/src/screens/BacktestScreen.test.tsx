import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { WorkflowProvider, useWorkflow } from "../contexts/WorkflowContext";
import { BacktestScreen } from "./BacktestScreen";
import type { TradePlan } from "../types";

vi.mock("../components/TradingChart", () => ({
  TradingChart: () => <div data-testid="trading-chart" />,
}));

const mockPlan: TradePlan = {
  batch_id: "batch-001",
  date: "2026-01-01",
  entries: [],
  exposure: { gross: 0, net: 0, long_count: 0, short_count: 0 },
  status: "contract_ready",
};

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {}

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  static reset() {
    MockEventSource.instances = [];
  }
}

function installEventSource() {
  MockEventSource.reset();
  vi.stubGlobal("EventSource", MockEventSource);
}

function stubFetch(options?: {
  postResponse?: Record<string, unknown>;
  getResponse?: Record<string, unknown>;
}) {
  const postResponse = options?.postResponse ?? {
    backtest_id: "bt-001",
    strategy_id: "strat-001",
    start_date: "2025-01-01",
    end_date: "2026-01-01",
    status: "completed",
    result: {
      summary: {
        total_return_pct: 12.5,
        trade_count: 6,
        win_rate: 0.5,
      },
      equity_curve: [100000, 101500, 112500],
      per_symbol: [
        {
          symbol: "AAPL",
          sharpe_ratio: 1.23,
          max_drawdown_pct: 0.08,
          trades: [],
        },
      ],
      execution_mode: "quant_strict",
    },
  };
  const getResponse = options?.getResponse ?? postResponse;
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/backtests" && init?.method === "POST") {
      return { ok: true, json: async () => postResponse };
    }
    if (url === "/api/backtests/bt-001" && !init) {
      return { ok: true, json: async () => getResponse };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  installEventSource();
  return mock;
}

function WithStrategy({ children }: { children: React.ReactNode }) {
  const { setStrategyId } = useWorkflow();
  return (
    <>
      <button onClick={() => setStrategyId("strat-001", mockPlan)}>Set strategy</button>
      {children}
    </>
  );
}

function renderScreen() {
  return render(
    <WorkflowProvider>
      <WithStrategy>
        <BacktestScreen />
      </WithStrategy>
    </WorkflowProvider>
  );
}

describe("BacktestScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows empty state when no strategy", () => {
    render(
      <WorkflowProvider>
        <BacktestScreen />
      </WorkflowProvider>
    );
    expect(screen.getByText(/build a strategy/i)).toBeInTheDocument();
  });

  it("renders config form when strategy is set", () => {
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set strategy/i })); });
    expect(screen.getByLabelText(/start date/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run backtest/i })).toBeInTheDocument();
  });

  it("execution mode field shows quant_strict", () => {
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set strategy/i })); });
    expect(screen.getByDisplayValue("quant_strict")).toBeInTheDocument();
  });

  it("POSTs only supported backtest fields and renders returned KPIs", async () => {
    const mock = stubFetch();
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set strategy/i })); });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /run backtest/i })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/backtests",
        expect.objectContaining({
          method: "POST",
          body: expect.not.stringContaining("execution_mode"),
        })
      )
    );
    expect(screen.getByText("12.5%")).toBeInTheDocument();
    expect(screen.getByText("1.23")).toBeInTheDocument();
  });

  it("re-fetches persisted backtest details after terminal SSE", async () => {
    const mock = stubFetch({
      postResponse: {
        backtest_id: "bt-001",
        strategy_id: "strat-001",
        start_date: "2025-01-01",
        end_date: "2026-01-01",
        status: "running",
        result: {
          summary: {
            total_return_pct: 0,
            trade_count: 0,
            win_rate: 0,
          },
          equity_curve: [100000],
          per_symbol: [],
          execution_mode: "quant_strict",
        },
      },
      getResponse: {
        backtest_id: "bt-001",
        strategy_id: "strat-001",
        start_date: "2025-01-01",
        end_date: "2026-01-01",
        status: "completed",
        result: {
          summary: {
            total_return_pct: 12.5,
            trade_count: 6,
            win_rate: 0.5,
          },
          equity_curve: [100000, 101500, 112500],
          per_symbol: [
            {
              symbol: "AAPL",
              sharpe_ratio: 1.23,
              max_drawdown_pct: 0.08,
              trades: [],
            },
          ],
          execution_mode: "quant_strict",
        },
      },
    });
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set strategy/i })); });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    act(() => {
      MockEventSource.instances[0].emit({
        type: "backtest_status",
        backtest_id: "bt-001",
        status: "completed",
        timestamp: 1,
      });
    });

    await waitFor(() => expect(mock).toHaveBeenCalledWith("/api/backtests/bt-001"));
    expect(screen.getByText("12.5%")).toBeInTheDocument();
    expect(screen.getByText("1.23")).toBeInTheDocument();
  });
});
