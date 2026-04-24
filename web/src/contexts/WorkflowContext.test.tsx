import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { WorkflowProvider, useWorkflow } from "./WorkflowContext";
import type { BasketData } from "../types";

const testBasket: BasketData = {
  screening_run_id: "run-1",
  symbols: ["AAPL", "MSFT"],
  regime: null,
  created_at: "2026-01-01T00:00:00Z",
  status: "ready",
};

function BasketSetter() {
  const { setBasket } = useWorkflow();
  return (
    <button onClick={() => setBasket(testBasket)}>Set basket</button>
  );
}

function BasketDisplay() {
  const { basket } = useWorkflow();
  return <div data-testid="basket">{basket ? basket.symbols.join(",") : "none"}</div>;
}

describe("WorkflowContext", () => {
  it("initial screen is market", () => {
    render(
      <WorkflowProvider>
        <BasketDisplay />
      </WorkflowProvider>
    );
    expect(screen.getByTestId("basket")).toHaveTextContent("none");
  });

  it("setBasket in one render is visible via useWorkflow", () => {
    render(
      <WorkflowProvider>
        <BasketSetter />
        <BasketDisplay />
      </WorkflowProvider>
    );
    expect(screen.getByTestId("basket")).toHaveTextContent("none");
    act(() => { fireEvent.click(screen.getByRole("button", { name: /set basket/i })); });
    expect(screen.getByTestId("basket")).toHaveTextContent("AAPL,MSFT");
  });

  it("setScreen changes the active screen", () => {
    function ScreenDisplay() {
      const { screen, setScreen } = useWorkflow();
      return (
        <>
          <div data-testid="screen">{screen}</div>
          <button onClick={() => setScreen("settings")}>Go settings</button>
        </>
      );
    }
    render(
      <WorkflowProvider>
        <ScreenDisplay />
      </WorkflowProvider>
    );
    expect(screen.getByTestId("screen")).toHaveTextContent("market");
    act(() => { fireEvent.click(screen.getByRole("button", { name: /go settings/i })); });
    expect(screen.getByTestId("screen")).toHaveTextContent("settings");
  });

  it("tracks auto-advance and disables it on user-initiated navigation", () => {
    function AutoAdvanceDisplay() {
      const { autoAdvance, setAutoAdvance, setScreen } = useWorkflow();
      return (
        <>
          <div data-testid="auto">{String(autoAdvance)}</div>
          <button onClick={() => setAutoAdvance(true)}>Enable auto</button>
          <button onClick={() => setScreen("settings", { userInitiated: true })}>Manual settings</button>
          <button onClick={() => setScreen("batch")}>Program batch</button>
        </>
      );
    }
    render(
      <WorkflowProvider>
        <AutoAdvanceDisplay />
      </WorkflowProvider>
    );
    expect(screen.getByTestId("auto")).toHaveTextContent("false");
    act(() => { fireEvent.click(screen.getByRole("button", { name: /enable auto/i })); });
    expect(screen.getByTestId("auto")).toHaveTextContent("true");
    act(() => { fireEvent.click(screen.getByRole("button", { name: /program batch/i })); });
    expect(screen.getByTestId("auto")).toHaveTextContent("true");
    act(() => { fireEvent.click(screen.getByRole("button", { name: /manual settings/i })); });
    expect(screen.getByTestId("auto")).toHaveTextContent("false");
  });
});
