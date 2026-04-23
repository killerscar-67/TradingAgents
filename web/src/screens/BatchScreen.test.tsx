import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WorkflowProvider } from "../contexts/WorkflowContext";
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
});
