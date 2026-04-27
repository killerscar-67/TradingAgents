import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WorkflowProvider } from "../contexts/WorkflowContext";
import { Sidebar } from "./Sidebar";

function renderSidebar() {
  return render(
    <WorkflowProvider>
      <Sidebar />
    </WorkflowProvider>
  );
}

describe("Sidebar", () => {
  it("renders all 8 nav items", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: /market/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /screening/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /batch analysis/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /strategy/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /backtest/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /history/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /journal/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /settings/i })).toBeInTheDocument();
  });

  it("highlights the active item", () => {
    renderSidebar();
    const marketBtn = screen.getByRole("button", { name: /market/i });
    expect(marketBtn).toHaveAttribute("aria-current", "page");
  });

  it("changes active item when clicked", () => {
    renderSidebar();
    const settingsBtn = screen.getByRole("button", { name: /settings/i });
    fireEvent.click(settingsBtn);
    expect(settingsBtn).toHaveAttribute("aria-current", "page");
  });

  it("renders Run full workflow button", () => {
    renderSidebar();
    expect(screen.getByRole("button", { name: /run full workflow/i })).toBeInTheDocument();
  });
});
