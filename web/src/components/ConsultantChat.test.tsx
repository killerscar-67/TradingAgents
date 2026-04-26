import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ConsultantChat } from "./ConsultantChat";

describe("ConsultantChat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows idle message when disabled=true", () => {
    render(<ConsultantChat runId="run-1" disabled={true} />);
    expect(screen.getByText(/available once the analysis/i)).toBeInTheDocument();
    // No send button rendered when disabled
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
  });

  it("input and button rendered when not disabled", () => {
    render(<ConsultantChat runId="run-1" disabled={false} />);
    expect(screen.getByPlaceholderText(/ask about/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toBeInTheDocument();
  });

  it("renders assistant answer after successful API call", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        answer: "Because fundamentals are strong.",
        observations: ["Revenue up 20%"],
        follow_up_questions: ["What about macro risk?"],
        referenced_context_keys: [],
        error: null,
      }),
    }));

    render(<ConsultantChat runId="run-1" disabled={false} />);
    fireEvent.change(screen.getByPlaceholderText(/ask about/i), {
      target: { value: "Why BUY?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(screen.getByText((_, el) =>
        el?.tagName === "PRE" && (el.textContent ?? "").includes("Because fundamentals are strong.")
      )).toBeInTheDocument()
    );
    expect(screen.getByText((_, el) =>
      el?.tagName === "PRE" && (el.textContent ?? "").includes("Revenue up 20%")
    )).toBeInTheDocument();
    expect(screen.getByText((_, el) =>
      el?.tagName === "PRE" && (el.textContent ?? "").includes("What about macro risk")
    )).toBeInTheDocument();
  });

  it("renders error state on API error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Run not found" }),
    }));

    render(<ConsultantChat runId="run-1" disabled={false} />);
    fireEvent.change(screen.getByPlaceholderText(/ask about/i), {
      target: { value: "Hello?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(screen.getByText(/Run not found/)).toBeInTheDocument()
    );
  });
});
