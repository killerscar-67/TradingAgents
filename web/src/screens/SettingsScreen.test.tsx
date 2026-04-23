import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SettingsScreen } from "./SettingsScreen";

function stubFetch() {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/settings" && !init) {
      return {
        ok: true,
        json: async () => ({
          llm_provider: "openai",
          deep_think_llm: "gpt-5.4",
          quick_think_llm: "gpt-5.4-mini",
          execution_mode: "llm_assisted",
          home_market: "US",
          max_debate_rounds: 2,
          max_risk_discuss_rounds: 2,
          output_language: "en",
          status: "ready",
        }),
      };
    }
    if (url === "/api/settings" && init?.method === "PUT") {
      return {
        ok: true,
        json: async () => ({
          status: "ready",
          values: {
            llm_provider: "anthropic",
            deep_think_llm: "gpt-5.4",
            quick_think_llm: "gpt-5.4-mini",
            execution_mode: "llm_assisted",
            home_market: "US",
            max_debate_rounds: 2,
            max_risk_discuss_rounds: 2,
            output_language: "en",
          },
        }),
      };
    }
    return { ok: false, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("SettingsScreen", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("wraps updates in the backend values envelope", async () => {
    const mock = stubFetch();
    render(<SettingsScreen />);
    await waitFor(() => expect(screen.getByDisplayValue("openai")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/provider/i), {
      target: { value: "anthropic" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          method: "PUT",
          body: expect.stringContaining('"values":'),
        })
      )
    );
    expect(screen.getByText(/saved/i)).toBeInTheDocument();
  });
});
