import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReportTabs } from "./ReportTabs";

describe("ReportTabs", () => {
  it("shows 'no content yet' when sections empty", () => {
    render(<ReportTabs sections={{}} orderIntent={null} />);
    expect(screen.getByText(/no content yet/i)).toBeInTheDocument();
  });

  it("renders market report content in Market tab", () => {
    render(
      <ReportTabs
        sections={{ market_report: "Bullish on AAPL." }}
        orderIntent={null}
      />
    );
    expect(screen.getByText("Bullish on AAPL.")).toBeInTheDocument();
  });

  it("switches to trader tab on click", () => {
    render(
      <ReportTabs
        sections={{
          market_report: "Market content",
          trader_investment_plan: "Trader plan: buy 100 shares.",
        }}
        orderIntent={null}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /trader/i }));
    expect(screen.getByText("Trader plan: buy 100 shares.")).toBeInTheDocument();
  });

  it("shows Order tab when orderIntent is provided", () => {
    render(
      <ReportTabs
        sections={{}}
        orderIntent={{ rating: "BUY", blocked: false }}
      />
    );
    expect(screen.getByRole("button", { name: /order/i })).toBeInTheDocument();
  });

  it("renders order intent JSON in Order tab", () => {
    render(
      <ReportTabs
        sections={{}}
        orderIntent={{ rating: "BUY", blocked: false }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /order/i }));
    expect(screen.getByText(/"rating": "BUY"/)).toBeInTheDocument();
  });
});
