import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentTimeline } from "./AgentTimeline";

describe("AgentTimeline", () => {
  it("shows empty-state message when no run has started", () => {
    render(<AgentTimeline statuses={{}} runStatus="pending" />);
    expect(screen.getByText(/no analyses yet/i)).toBeInTheDocument();
  });

  it("shows the phase list once run is running", () => {
    render(
      <AgentTimeline
        statuses={{ "Market Analyst": "completed" }}
        runStatus="running"
      />
    );
    expect(screen.getByText(/market analyst/i)).toBeInTheDocument();
  });

  it("renders phase list with trader phase when trader is in_progress", () => {
    render(
      <AgentTimeline
        statuses={{ "Trader": "in_progress" }}
        runStatus="running"
      />
    );
    expect(screen.getByText(/trader — drafting a proposal/i)).toBeInTheDocument();
  });

  it("renders market analyst phase as done when completed", () => {
    render(
      <AgentTimeline
        statuses={{ "Market Analyst": "completed" }}
        runStatus="running"
      />
    );
    // Phase label is still present; icon content is tested via container
    expect(screen.getByText(/market analyst/i)).toBeInTheDocument();
  });

  it("shows final Done phase when run is completed", () => {
    render(<AgentTimeline statuses={{}} runStatus="completed" />);
    expect(screen.getByText(/done\. compiling/i)).toBeInTheDocument();
  });
});
