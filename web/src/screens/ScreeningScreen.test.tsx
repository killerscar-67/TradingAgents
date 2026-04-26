import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WorkflowProvider } from "../contexts/WorkflowContext";
import { ScreeningScreen } from "./ScreeningScreen";

const screeningResponse = {
  run_id: "scr-001",
  results: [
    { symbol: "AAPL", score: 0.85, regime_label: "Bull", entry_mode: "breakout", status: "contract_ready" },
    { symbol: "MSFT", score: 0.72, regime_label: "Bull", entry_mode: "breakout", status: "contract_ready" },
  ],
  status: "contract_ready",
};

function stubFetch() {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/screening/runs" && init?.method === "POST") {
      return { ok: true, json: async () => screeningResponse };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderScreen() {
  return render(
    <WorkflowProvider>
      <ScreeningScreen />
    </WorkflowProvider>
  );
}

describe("ScreeningScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows empty state before running", () => {
    renderScreen();
    expect(screen.getByText(/run a screen to see results/i)).toBeInTheDocument();
  });

  it("submits POST /api/screening/runs", async () => {
    const mock = stubFetch();
    renderScreen();
    fireEvent.click(screen.getByRole("button", { name: /run screen/i }));
    await waitFor(() => expect(mock).toHaveBeenCalledWith(
      "/api/screening/runs",
      expect.objectContaining({ method: "POST" })
    ));
  });

  it("displays results after run", async () => {
    stubFetch();
    renderScreen();
    fireEvent.click(screen.getByRole("button", { name: /run screen/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText("MSFT")).toBeInTheDocument();
  });

  it("remove button removes a result from the list", async () => {
    stubFetch();
    renderScreen();
    fireEvent.click(screen.getByRole("button", { name: /run screen/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /remove aapl/i }));
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
  });

  it("selects result rows for the basket and updates the basket panel", async () => {
    stubFetch();
    renderScreen();
    fireEvent.click(screen.getByRole("button", { name: /run screen/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /select aapl/i }));
    expect(screen.getByText(/1 selected/i)).toBeInTheDocument();
    expect(screen.getByText(/8 min/i)).toBeInTheDocument();
  });

  it("posts selected universe and exposes strategy filters", async () => {
    const mock = stubFetch();
    renderScreen();
    fireEvent.change(screen.getByLabelText(/universe/i), { target: { value: "HK" } });
    fireEvent.click(screen.getByRole("radio", { name: /breakout/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /liquid only/i }));
    fireEvent.click(screen.getByRole("button", { name: /run screen/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/screening/runs",
        expect.objectContaining({
          body: expect.stringContaining('"home_market":"HK"'),
        })
      )
    );
  });
});
