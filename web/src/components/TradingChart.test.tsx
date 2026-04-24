import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TradingChart, type OhlcBar } from "./TradingChart";

const timeScaleState: {
  handler: ((range: { from: number; to: number } | null) => void) | null;
} = {
  handler: null,
};

const mockTimeScale = {
  getVisibleLogicalRange: vi.fn(() => ({ from: 30, to: 90 })),
  setVisibleLogicalRange: vi.fn(),
  timeToCoordinate: vi.fn((time: number) => time),
  subscribeVisibleLogicalRangeChange: vi.fn((handler: (range: { from: number; to: number } | null) => void) => {
    timeScaleState.handler = handler;
  }),
  unsubscribeVisibleLogicalRangeChange: vi.fn(),
};

function createMockSeries() {
  return {
    createPriceLine: vi.fn(() => ({})),
    removePriceLine: vi.fn(),
    setData: vi.fn(),
    setMarkers: vi.fn(),
  };
}

const mockCandlestickSeries = createMockSeries();
const mockLineSeries = createMockSeries();
const mockCreateChart = vi.fn(() => ({
  addCandlestickSeries: vi.fn(() => mockCandlestickSeries),
  addLineSeries: vi.fn(() => mockLineSeries),
  remove: vi.fn(),
  timeScale: vi.fn(() => mockTimeScale),
}));

vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  createChart: mockCreateChart,
  __triggerVisibleRange: (range: { from: number; to: number } | null) => {
    timeScaleState.handler?.(range);
  },
}));

function makeBars(count = 120): OhlcBar[] {
  return Array.from({ length: count }, (_, index) => ({
    time: index + 1,
    open: 100 + index,
    high: 101 + index,
    low: 99 + index,
    close: 100.5 + index,
  }));
}

describe("TradingChart", () => {
  beforeEach(() => {
    timeScaleState.handler = null;
    mockCreateChart.mockClear();
    mockTimeScale.getVisibleLogicalRange.mockClear();
    mockTimeScale.setVisibleLogicalRange.mockClear();
    mockTimeScale.timeToCoordinate.mockClear();
    mockTimeScale.subscribeVisibleLogicalRangeChange.mockClear();
    mockTimeScale.unsubscribeVisibleLogicalRangeChange.mockClear();
    mockCandlestickSeries.createPriceLine.mockClear();
    mockCandlestickSeries.removePriceLine.mockClear();
    mockCandlestickSeries.setData.mockClear();
    mockCandlestickSeries.setMarkers.mockClear();
    mockLineSeries.createPriceLine.mockClear();
    mockLineSeries.removePriceLine.mockClear();
    mockLineSeries.setData.mockClear();
    mockLineSeries.setMarkers.mockClear();
  });

  it("requests older data when the visible range reaches the left edge", async () => {
    const bars = makeBars();
    const onLoadMore = vi.fn();

    render(
      <TradingChart
        bars={bars}
        mode="candlestick"
        canLoadMore
        initialVisibleBars={40}
        onLoadMore={onLoadMore}
      />
    );

    const charts = await import("lightweight-charts");
    await waitFor(() => expect(mockCreateChart).toHaveBeenCalledTimes(1));

    (charts as unknown as { __triggerVisibleRange: (range: { from: number; to: number } | null) => void }).__triggerVisibleRange({
      from: 5,
      to: 45,
    });

    await waitFor(() => expect(onLoadMore).toHaveBeenCalledWith(bars[0].time));
  });

  it("does not re-request the same oldest bar until new data arrives", async () => {
    const onLoadMore = vi.fn();

    render(
      <TradingChart
        bars={makeBars()}
        mode="candlestick"
        canLoadMore
        initialVisibleBars={40}
        onLoadMore={onLoadMore}
      />
    );

    const charts = await import("lightweight-charts");
    await waitFor(() => expect(mockCreateChart).toHaveBeenCalledTimes(1));

    (charts as unknown as { __triggerVisibleRange: (range: { from: number; to: number } | null) => void }).__triggerVisibleRange({
      from: 5,
      to: 45,
    });
    (charts as unknown as { __triggerVisibleRange: (range: { from: number; to: number } | null) => void }).__triggerVisibleRange({
      from: 4,
      to: 44,
    });

    await waitFor(() => expect(onLoadMore).toHaveBeenCalledTimes(1));
  });

  it("renders session timing overlays for extended intraday charts", async () => {
    const bars: OhlcBar[] = [
      { time: 1776758400, open: 100, high: 101, low: 99, close: 100.5 },
      { time: 1776772800, open: 100.5, high: 101.5, low: 100, close: 101 },
      { time: 1776797400, open: 101, high: 102, low: 100.5, close: 101.8 },
      { time: 1776820800, open: 101.8, high: 102.1, low: 101.2, close: 101.6 },
      { time: 1776828000, open: 101.6, high: 102.4, low: 101.4, close: 102.1 },
    ];

    render(
      <TradingChart
        bars={bars}
        mode="candlestick"
        timeframe="15m"
        session="extended"
        showSessionTiming
      />
    );

    await waitFor(() => expect(mockCreateChart).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText(/session timing legend/i)).toBeInTheDocument();
    expect(screen.getByText("Pre-market")).toBeInTheDocument();
    expect(screen.getByText("After-hours")).toBeInTheDocument();
    expect(screen.getByTestId("session-timing-overlay").children.length).toBeGreaterThan(0);
  });
});
