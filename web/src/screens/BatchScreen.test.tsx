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
    if (url === "/api/batches/batch-001/items/AMD/retry" && init?.method === "POST") {
      return { ok: true, json: async () => ({ status: "queued" }) };
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

  it("offers retry and skip actions for failed tickers", async () => {
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
    await waitFor(() => expect(screen.getByRole("button", { name: /retry amd/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /retry amd/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/batches/batch-001/items/AMD/retry",
        expect.objectContaining({ method: "POST" })
      )
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: /skip amd/i })).not.toBeInTheDocument());
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

  it("clears stopped-batch error state and reconnects when retrying a ticker", async () => {
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
      if (url === "/api/batches/batch-001/items/AMD/retry" && init?.method === "POST") {
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
    fireEvent.click(screen.getByRole("button", { name: /retry amd/i }));
    await waitFor(() => expect(mock).toHaveBeenCalledWith(
      "/api/batches/batch-001/items/AMD/retry",
      expect.objectContaining({ method: "POST" })
    ));
    await waitFor(() => expect(screen.queryByText(/batch stopped before this ticker completed/i)).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("queued")).toBeInTheDocument());
    expect(MockEventSource.instances).toHaveLength(2);
  });
});
