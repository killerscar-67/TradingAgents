import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { WorkflowProvider, useWorkflow } from "../contexts/WorkflowContext";
import { StrategyScreen } from "./StrategyScreen";

function stubFetch() {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/strategies/from-batch" && init?.method === "POST") {
      return {
        ok: true,
        json: async () => ({
          strategy_id: "strat-001",
          status: "ready",
          trades: [
            {
              symbol: "AAPL",
              side: "buy",
              direction: "long",
              quantity: 50,
              entry_price: 200.0,
              stop_price: 190.0,
              target_price: 220.0,
              notional: 10_000,
              rating: "BUY",
              analysis_run_id: "run-001",
            },
          ],
          exposure: {
            gross_exposure_pct: 10.0,
            net_exposure_pct: 10.0,
          },
          request: {
            batch_id: "batch-001",
            portfolio_size: 100_000,
          },
        }),
      };
    }
    if (url === "/api/broker/futu/stage" && init?.method === "POST") {
      return { ok: true, json: async () => ({ status: "staged" }) };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function WithBatchId({ children }: { children: React.ReactNode }) {
  const { setBatchId } = useWorkflow();
  return (
    <>
      <button onClick={() => setBatchId("batch-001")}>Set batch</button>
      {children}
    </>
  );
}

function renderScreen() {
  return render(
    <WorkflowProvider>
      <WithBatchId>
        <StrategyScreen />
      </WithBatchId>
    </WorkflowProvider>
  );
}

describe("StrategyScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows empty state when no batch", () => {
    render(
      <WorkflowProvider>
        <StrategyScreen />
      </WorkflowProvider>
    );
    expect(screen.getByText(/run a batch analysis first/i)).toBeInTheDocument();
  });

  it("renders trade table after loading plan", async () => {
    stubFetch();
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set batch/i })); });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate strategy/i })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: /generate strategy/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });

  it("Futu dialog shows confirmation text", async () => {
    stubFetch();
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set batch/i })); });
    fireEvent.click(screen.getByRole("button", { name: /generate strategy/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /send to futu/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/staged, not placed/i)).toBeInTheDocument();
  });

  it("POSTs strategy-backed orders when confirmed", async () => {
    const mock = stubFetch();
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set batch/i })); });
    fireEvent.click(screen.getByRole("button", { name: /generate strategy/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /send to futu/i }));
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/broker/futu/stage",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"strategy_id":"strat-001"'),
        })
      )
    );
    expect(mock).toHaveBeenCalledWith(
      "/api/broker/futu/stage",
      expect.objectContaining({
        body: expect.any(String),
      })
    );
    const stageCall = mock.mock.calls.find(([url]) => url === "/api/broker/futu/stage");
    const stageBody = JSON.parse(String(stageCall?.[1]?.body ?? "{}"));
    expect(stageBody.orders[0]).toMatchObject({
      symbol: "AAPL",
      side: "buy",
      quantity: 50,
      entry_price: 200,
    });
  });

  it("renders R:R, portfolio controls, notes, and copy/export actions", async () => {
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    stubFetch();
    renderScreen();
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set batch/i })); });
    fireEvent.click(screen.getByRole("button", { name: /generate strategy/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText("R:R")).toBeInTheDocument();
    expect(screen.getByText("2.00")).toBeInTheDocument();
    expect(screen.getByLabelText(/portfolio size/i)).toHaveValue(100000);
    expect(screen.getByLabelText(/risk per trade/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/notes for aapl/i), { target: { value: "wait for open" } });
    fireEvent.click(screen.getByRole("button", { name: /^copy$/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("wait for open")));
    expect(screen.getByRole("button", { name: /export csv/i })).toBeInTheDocument();
  });
});
