import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SettingsScreen } from "./SettingsScreen";

const STUB_MODELS = {
  providers: {
    openai: {
      custom: false,
      deep: [{ label: "GPT-5.4", value: "gpt-5.4" }],
      quick: [{ label: "GPT-5.4 Mini", value: "gpt-5.4-mini" }],
    },
    anthropic: {
      custom: false,
      deep: [{ label: "Claude Opus 4.6", value: "claude-opus-4-6" }],
      quick: [{ label: "Claude Sonnet 4.6", value: "claude-sonnet-4-6" }],
    },
    azure: { custom: true, deep: [], quick: [] },
    openrouter: { custom: true, deep: [], quick: [] },
  },
};

function stubFetch() {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/models") {
      return { ok: true, json: async () => STUB_MODELS };
    }
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
          top_n: 10,
          score_floor: 0.65,
          risk_per_trade_pct: 1,
          portfolio_size: 100000,
          allow_shorts: false,
          futu_host: "127.0.0.1",
          futu_port: 11111,
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
            top_n: 10,
            score_floor: 0.65,
            risk_per_trade_pct: 1,
            portfolio_size: 100000,
            allow_shorts: false,
            futu_host: "127.0.0.1",
            futu_port: 11111,
          },
        }),
      };
    }
    if (url === "/api/broker/futu/ping" && init?.method === "POST") {
      return { ok: true, json: async () => ({ status: "ok" }) };
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

  it("renders workflow defaults, broker, and watchlist sections", async () => {
    const mock = stubFetch();
    render(<SettingsScreen />);
    await waitFor(() => expect(screen.getByText(/workflow defaults/i)).toBeInTheDocument());
    expect(screen.getByLabelText(/top n/i)).toHaveValue(10);
    expect(screen.getByLabelText(/score floor/i)).toHaveValue(0.65);
    expect(screen.getByLabelText(/risk per trade/i)).toHaveValue(1);
    expect(screen.getByLabelText(/portfolio size/i)).toHaveValue(100000);
    expect(screen.getByLabelText(/allow shorts/i)).not.toBeChecked();
    expect(screen.getByText(/broker/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        "/api/broker/futu/ping",
        expect.objectContaining({ method: "POST" })
      )
    );
    expect(screen.getByText(/watchlists/i)).toBeInTheDocument();
  });
});
