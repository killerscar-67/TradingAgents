import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { WorkflowProvider, useWorkflow } from "../contexts/WorkflowContext";
import { BatchScreen } from "./BatchScreen";

const batchResponse = { batch_id: "batch-001", status: "contract_ready" };

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

function stubFetch() {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/batches" && init?.method === "POST") {
      return { ok: true, json: async () => batchResponse };
    }
    if (url === "/api/batches/batch-001" && !init?.method) {
      return {
        ok: true,
        json: async () => ({
          status: "ready",
          batch: {
            batch_id: "batch-001",
            status: "completed",
            symbols: ["AMD"],
            items: [{ symbol: "AMD", run_id: "run-amd", status: "completed", rating: "BUY" }],
            events: [{ type: "batch_item", symbol: "AMD", status: "completed", timestamp: 1 }],
          },
        }),
      };
    }
    if (url === "/api/batches/batch-001/stop" && init?.method === "POST") {
      return { ok: true, json: async () => ({ status: "stopped" }) };
    }
    if (url === "/api/batches/batch-001/items/AMD/rerun" && init?.method === "POST") {
      return { ok: true, json: async () => ({ status: "queued" }) };
    }
    if (url === "/api/batches/batch-001/items/AMD/resume-step" && init?.method === "POST") {
      return {
        ok: false,
        status: 409,
        json: async () => ({
          detail: "Retry from interrupted step is not supported yet after 'Research'. This workflow does not persist resumable graph checkpoints, so use rerun full analysis instead.",
        }),
      };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  MockEventSource.reset();
  vi.stubGlobal("EventSource", MockEventSource);
  return mock;
}

function renderScreen() {
  return render(
    <WorkflowProvider>
      <BatchScreen />
    </WorkflowProvider>
  );
}

describe("BatchScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows hint text when ticker list is empty", () => {
    renderScreen();
    expect(screen.getByText(/add tickers below or run screening/i)).toBeInTheDocument();
  });

  it("Start batch analysis button is disabled when list is empty", () => {
    renderScreen();
    expect(screen.getByRole("button", { name: /start batch analysis/i })).toBeDisabled();
  });

  it("adds a symbol via input", () => {
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("adds a symbol via Enter key", () => {
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "TSLA" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("TSLA")).toBeInTheDocument();
  });

  it("removes a symbol", () => {
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /remove aapl/i }));
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });

  it("enables Start button when list has items", () => {
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "NVDA" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    expect(screen.getByRole("button", { name: /start batch analysis/i })).not.toBeDisabled();
  });

  it("calls POST /api/batches when Start is clicked", async () => {
    const mock = stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "GOOG" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(mock).toHaveBeenCalledWith(
      "/api/batches",
      expect.objectContaining({ method: "POST" })
    ));
  });

  it("submits daytrade batches with extended hours enabled by default", async () => {
    const mock = stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "GOOG" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /daytrade/i }));

    expect(screen.getByRole("checkbox", { name: /extended hours/i })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));

    await waitFor(() => expect(mock).toHaveBeenCalledWith(
      "/api/batches",
      expect.objectContaining({ method: "POST" })
    ));
    const [, init] = mock.mock.calls.find(([url]) => url === "/api/batches") ?? [];
    const payload = JSON.parse(String(init?.body));
    expect(payload.trading_style).toBe("daytrade");
    expect(payload.include_extended_hours).toBe(true);
  });

  it("shows progress cards after batch starts", async () => {
    stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AMD" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(screen.getByText("AMD")).toBeInTheDocument());
    expect(screen.getByText("queued")).toBeInTheDocument();
  });

  it("processes every batch item event in a burst", async () => {
    stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.change(input, { target: { value: "MSFT" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    MockEventSource.instances[0].emit({
      type: "batch_item",
      batch_id: "batch-001",
      symbol: "AAPL",
      run_id: "run-aapl",
      status: "completed",
      rating: "BUY",
      timestamp: 1,
    });
    MockEventSource.instances[0].emit({
      type: "batch_item",
      batch_id: "batch-001",
      symbol: "MSFT",
      run_id: "run-msft",
      status: "completed",
      rating: "SELL",
      timestamp: 2,
    });

    await waitFor(() => expect(screen.getAllByText("completed")).toHaveLength(2));
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
  });

  it("shows phase names and a live event feed", async () => {
    stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AMD" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    MockEventSource.instances[0].emit({
      type: "agent_status",
      batch_id: "batch-001",
      symbol: "AMD",
      run_id: "run-amd",
      status: "running",
      phase: "Research",
      timestamp: 1,
    });
    await waitFor(() => expect(screen.getByText(/phase: research/i)).toBeInTheDocument());
    expect(screen.getByText(/amd.*agent_status.*running/i)).toBeInTheDocument();
  });

  it("formats ISO batch event timestamps without Invalid Date", async () => {
    stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "META" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    MockEventSource.instances[0].emit({
      type: "batch_item",
      batch_id: "batch-001",
      symbol: "META",
      run_id: "run-meta",
      status: "failed",
      timestamp: "2026-04-23T14:00:00Z",
    });

    await waitFor(() => expect(screen.getByText(/meta.*batch_item.*failed/i)).toBeInTheDocument());
    expect(screen.queryByText(/invalid date/i)).not.toBeInTheDocument();
  });

  it("confirms Stop all before posting the stop request", async () => {
    const mock = stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AMD" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /stop all/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /stop all/i }));
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/batches/batch-001/stop",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("offers rerun-full and skip actions for failed tickers", async () => {
    const mock = stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AMD" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    MockEventSource.instances[0].emit({
      type: "batch_item",
      batch_id: "batch-001",
      symbol: "AMD",
      run_id: "run-amd",
      status: "error",
      error: "failed",
      timestamp: 1,
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /rerun full amd/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /rerun full amd/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/batches/batch-001/items/AMD/rerun",
        expect.objectContaining({ method: "POST" })
      )
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: /skip amd/i })).not.toBeInTheDocument());
  });

  it("shows a clear message when resume-step is unavailable", async () => {
    const mock = stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AMD" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    MockEventSource.instances[0].emit({
      type: "agent_status",
      batch_id: "batch-001",
      symbol: "AMD",
      run_id: "run-amd",
      status: "running",
      phase: "Research",
      timestamp: 1,
    });
    MockEventSource.instances[0].emit({
      type: "batch_item",
      batch_id: "batch-001",
      symbol: "AMD",
      run_id: "run-amd",
      status: "error",
      error: "failed",
      timestamp: 2,
    });

    await waitFor(() => expect(screen.getByRole("button", { name: /resume amd step/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /resume amd step/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/batches/batch-001/items/AMD/resume-step",
        expect.objectContaining({ method: "POST" })
      )
    );
    await waitFor(() => expect(screen.getByText(/retry from interrupted step is not supported yet/i)).toBeInTheDocument());
  });

  it("allows skipping a failed ticker before retrying", async () => {
    stubFetch();
    renderScreen();
    const input = screen.getByRole("textbox", { name: /add ticker/i });
    fireEvent.change(input, { target: { value: "AMD" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    fireEvent.click(screen.getByRole("button", { name: /start batch analysis/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    MockEventSource.instances[0].emit({
      type: "batch_item",
      batch_id: "batch-001",
      symbol: "AMD",
      run_id: "run-amd",
      status: "error",
      error: "failed",
      timestamp: 1,
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /skip amd/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /skip amd/i }));
    expect(screen.queryByText("AMD")).not.toBeInTheDocument();
  });

  it("hydrates an existing saved batch from its id", async () => {
    stubFetch();

    function SeedBatchId() {
      const { setBatchId } = useWorkflow();
      useEffect(() => {
        setBatchId("batch-001");
      }, [setBatchId]);
      return null;
    }

    render(
      <WorkflowProvider>
        <SeedBatchId />
        <BatchScreen />
      </WorkflowProvider>
    );

    await waitFor(() => expect(screen.getByText("AMD")).toBeInTheDocument());
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start batch analysis/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /stop all/i })).not.toBeInTheDocument();
  });

  it("shows a quick update action for completed saved daytrade ticker results", async () => {
    const mock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/batches/batch-001" && !init?.method) {
        return {
          ok: true,
          json: async () => ({
            status: "ready",
            batch: {
              batch_id: "batch-001",
              status: "completed",
              request: { trading_style: "daytrade", intraday_interval: "5m", include_extended_hours: true },
              symbols: ["AMD"],
              items: [{ symbol: "AMD", run_id: "run-amd", status: "completed", rating: "BUY" }],
              events: [{ type: "batch_item", symbol: "AMD", status: "completed", timestamp: 1 }],
            },
          }),
        };
      }
      if (url === "/api/batches/batch-001/items/AMD/rerun" && init?.method === "POST") {
        return { ok: true, json: async () => ({ status: "queued" }) };
      }
      return { ok: false, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", mock);
    MockEventSource.reset();
    vi.stubGlobal("EventSource", MockEventSource);

    function SeedBatchId() {
      const { setBatchId } = useWorkflow();
      useEffect(() => {
        setBatchId("batch-001");
      }, [setBatchId]);
      return null;
    }

    render(
      <WorkflowProvider>
        <SeedBatchId />
        <BatchScreen />
      </WorkflowProvider>
    );

    await waitFor(() => expect(screen.getByRole("button", { name: /quick update amd/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /quick update amd/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/batches/batch-001/items/AMD/rerun",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("shows Quick update button inside the ticker detail view for daytrade batches", async () => {
    const mock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/batches/batch-001" && !init?.method) {
        return {
          ok: true,
          json: async () => ({
            status: "ready",
            batch: {
              batch_id: "batch-001",
              status: "completed",
              request: { trading_style: "daytrade", intraday_interval: "5m", include_extended_hours: true },
              symbols: ["AMD"],
              items: [{ symbol: "AMD", run_id: "run-amd", status: "completed", rating: "BUY" }],
              events: [{ type: "batch_item", symbol: "AMD", status: "completed", timestamp: 1 }],
            },
          }),
        };
      }
      if (url === "/api/analysis/run-amd") {
        return {
          ok: true,
          json: async () => ({
            run_id: "run-amd",
            ticker: "AMD",
            analysis_date: "2026-04-27",
            selected_analysts: ["intraday_market", "news"],
            execution_mode: "llm_assisted",
            llm_provider: "openai",
            deep_think_llm: "gpt-5.4",
            quick_think_llm: "gpt-5.4-mini",
            created_at: "2026-04-27T14:00:00Z",
            status: "completed",
            started_at: null,
            completed_at: null,
            report_sections: {},
            report_paths: {},
            stats: {},
            errors: [],
            final_order_intent: null,
            trading_style: "daytrade",
            intraday_interval: "5m",
            trade_datetime: null,
            session_phase: null,
            data_session_date: null,
            intraday_decisions: [],
          }),
        };
      }
      if (url === "/api/analysis/run-amd/events") {
        return { ok: true, json: async () => ({ events: [] }) };
      }
      if (url === "/api/batches/batch-001/items/AMD/rerun" && init?.method === "POST") {
        return { ok: true, json: async () => ({ status: "queued" }) };
      }
      return { ok: false, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", mock);
    MockEventSource.reset();
    vi.stubGlobal("EventSource", MockEventSource);

    function SeedBatchId() {
      const { setBatchId } = useWorkflow();
      useEffect(() => {
        setBatchId("batch-001");
      }, [setBatchId]);
      return null;
    }

    render(
      <WorkflowProvider>
        <SeedBatchId />
        <BatchScreen />
      </WorkflowProvider>
    );

    // Open the detail view by clicking the AMD card
    await waitFor(() => expect(screen.getByText("AMD")).toBeInTheDocument());
    fireEvent.click(screen.getByText("AMD"));

    // Quick update button should appear in the RunDetail header
    await waitFor(() => expect(screen.getByRole("button", { name: /quick update/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /quick update/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/batches/batch-001/items/AMD/rerun",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  it("allows clearing the current batch view to start a new batch", async () => {
    stubFetch();

    function SeedBatchId() {
      const { setBatchId } = useWorkflow();
      useEffect(() => {
        setBatchId("batch-001");
      }, [setBatchId]);
      return null;
    }

    render(
      <WorkflowProvider>
        <SeedBatchId />
        <BatchScreen />
      </WorkflowProvider>
    );

    await waitFor(() => expect(screen.getByText("AMD")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /start new batch/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /start batch analysis/i })).toBeInTheDocument());
    expect(screen.queryByText("BUY")).not.toBeInTheDocument();
  });

  it("clears stopped-batch error state and reconnects when rerunning a ticker", async () => {
    const mock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/batches/batch-001" && !init?.method) {
        return {
          ok: true,
          json: async () => ({
            status: "ready",
            batch: {
              batch_id: "batch-001",
              status: "stopped",
              symbols: ["AMD"],
              items: [{ symbol: "AMD", run_id: "run-amd", status: "failed", error: "Batch stopped before this ticker completed." }],
              events: [{ type: "batch_status", status: "stopped", timestamp: 1 }],
            },
          }),
        };
      }
      if (url === "/api/batches/batch-001/items/AMD/rerun" && init?.method === "POST") {
        return { ok: true, json: async () => ({ status: "queued" }) };
      }
      return { ok: false, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", mock);
    MockEventSource.reset();
    vi.stubGlobal("EventSource", MockEventSource);

    function SeedBatchId() {
      const { setBatchId } = useWorkflow();
      useEffect(() => {
        setBatchId("batch-001");
      }, [setBatchId]);
      return null;
    }

    render(
      <WorkflowProvider>
        <SeedBatchId />
        <BatchScreen />
      </WorkflowProvider>
    );

    await waitFor(() => expect(screen.getByText(/batch stopped before this ticker completed/i)).toBeInTheDocument());
    expect(MockEventSource.instances).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /rerun full amd/i }));
    await waitFor(() => expect(mock).toHaveBeenCalledWith(
      "/api/batches/batch-001/items/AMD/rerun",
      expect.objectContaining({ method: "POST" })
    ));
    await waitFor(() => expect(screen.queryByText(/batch stopped before this ticker completed/i)).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("queued")).toBeInTheDocument());
    expect(MockEventSource.instances).toHaveLength(2);
  });
});
