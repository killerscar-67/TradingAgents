import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunForm } from "./RunForm";

const modelCatalog = {
  providers: {
    openai: {
      custom: false,
      deep: [{ label: "GPT-5.4 - Frontier", value: "gpt-5.4" }],
      quick: [{ label: "GPT-5.4 Mini - Fast", value: "gpt-5.4-mini" }],
    },
    anthropic: {
      custom: false,
      deep: [{ label: "Claude Opus 4.6", value: "claude-opus-4-6" }],
      quick: [{ label: "Claude Sonnet 4.6", value: "claude-sonnet-4-6" }],
    },
    azure: {
      custom: true,
      deep: [],
      quick: [],
    },
  },
};

function stubFetch(postResponse = { run_id: "abc-123", status: "pending" }) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/models") {
      return {
        ok: true,
        json: async () => modelCatalog,
      };
    }
    if (url === "/api/analysis" && init?.method === "POST") {
      return {
        ok: true,
        json: async () => postResponse,
      };
    }
    return {
      ok: false,
      json: async () => ({ detail: `Unexpected request: ${url}` }),
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("RunForm", () => {
  const onRunCreated = vi.fn();

  beforeEach(() => {
    onRunCreated.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders ticker input and submit button", () => {
    render(<RunForm onRunCreated={onRunCreated} />);
    expect(screen.getByPlaceholderText(/AAPL, SHOP\.TO/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run analysis/i })).toBeInTheDocument();
  });

  it("calls POST /api/analysis and invokes onRunCreated", async () => {
    const fetchMock = stubFetch();

    render(<RunForm onRunCreated={onRunCreated} />);
    fireEvent.change(screen.getByPlaceholderText(/AAPL, SHOP\.TO/), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze aapl/i }));

    await waitFor(() => expect(onRunCreated).toHaveBeenCalledWith("abc-123"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/analysis",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("submits daytrade controls with intraday defaults", async () => {
    const fetchMock = stubFetch();

    render(<RunForm onRunCreated={onRunCreated} />);
    fireEvent.change(screen.getByPlaceholderText(/AAPL, SHOP\.TO/), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: /daytrade/i }));

    const interval = screen.getByLabelText(/intraday interval/i);
    expect((interval as HTMLSelectElement).value).toBe("5m");
    expect(screen.getByRole("checkbox", { name: /intraday market/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /news/i })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: /fundamentals/i })).not.toBeInTheDocument();

    fireEvent.change(interval, { target: { value: "15m" } });
    fireEvent.change(screen.getByLabelText(/trade datetime/i), {
      target: { value: "2026-04-23T10:15" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analyze aapl/i }));

    await waitFor(() => expect(onRunCreated).toHaveBeenCalledWith("abc-123"));
    const [, init] = fetchMock.mock.calls.find(([url]) => url === "/api/analysis") ?? [];
    const payload = JSON.parse(String(init?.body));
    expect(payload.trading_style).toBe("daytrade");
    expect(payload.selected_analysts).toEqual(["intraday_market", "news"]);
    expect(payload.intraday_interval).toBe("15m");
    expect(payload.trade_datetime).toBe("2026-04-23T10:15");
  });

  it("shows error when API returns non-ok", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/models") {
        return {
          ok: true,
          json: async () => modelCatalog,
        };
      }
      if (url === "/api/analysis" && init?.method === "POST") {
        return {
          ok: false,
          json: async () => ({ detail: "Invalid ticker" }),
        };
      }
      return {
        ok: false,
        json: async () => ({ detail: `Unexpected request: ${url}` }),
      };
    }));

    render(<RunForm onRunCreated={onRunCreated} />);
    fireEvent.change(screen.getByPlaceholderText(/AAPL, SHOP\.TO/), { target: { value: "???" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getByText(/can't find that ticker/i)).toBeInTheDocument());
    expect(onRunCreated).not.toHaveBeenCalled();
  });

  it("disables submit when no analysts selected", async () => {
    render(<RunForm onRunCreated={onRunCreated} />);
    // Uncheck all analysts by label text
    ["Market", "Social / sentiment", "News", "Fundamentals"].forEach((label) => {
      const cb = screen.getByRole("checkbox", { name: new RegExp(label, "i") });
      if ((cb as HTMLInputElement).checked) fireEvent.click(cb);
    });
    // Button text is "Run analysis" when ticker is empty
    expect(screen.getByRole("button", { name: /run analysis/i })).toBeDisabled();
  });

  it("uses provider-specific dropdowns for model selection", async () => {
    stubFetch();

    render(<RunForm onRunCreated={onRunCreated} />);
    fireEvent.click(screen.getByRole("button", { name: /advanced settings/i }));

    const deepModel = await screen.findByRole("combobox", { name: /deep-think model/i });
    const quickModel = screen.getByRole("combobox", { name: /quick model/i });

    expect((deepModel as HTMLSelectElement).value).toBe("gpt-5.4");
    expect((quickModel as HTMLSelectElement).value).toBe("gpt-5.4-mini");

    fireEvent.change(screen.getByRole("combobox", { name: /provider/i }), {
      target: { value: "anthropic" },
    });

    await waitFor(() => {
      expect((deepModel as HTMLSelectElement).value).toBe("claude-opus-4-6");
      expect((quickModel as HTMLSelectElement).value).toBe("claude-sonnet-4-6");
    });
  });
});
