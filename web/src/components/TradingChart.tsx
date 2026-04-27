import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./TradingChart.module.css";

export interface OhlcBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface PriceLine {
  price: number;
  color: string;
  label?: string;
}

export interface ChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowDown" | "arrowUp";
  text?: string;
}

export interface LinePoint {
  time: number;
  value: number;
}

export type ChartSession = "regular" | "extended";

interface SessionBandDecoration {
  key: string;
  left: number;
  width: number;
  kind: "premarket" | "afterhours";
}

interface SessionBoundaryDecoration {
  key: string;
  left: number;
  kind: "open" | "close";
}

interface SessionDecorations {
  bands: SessionBandDecoration[];
  boundaries: SessionBoundaryDecoration[];
}

interface Props {
  bars?: OhlcBar[];
  mode?: "candlestick" | "line";
  lineData?: LinePoint[];
  priceLines?: PriceLine[];
  markers?: ChartMarker[];
  height?: number;
  loading?: boolean;
  timeframe?: string;
  onTimeframeChange?: (tf: string) => void;
  intervalOptions?: string[];
  initialVisibleBars?: number;
  canLoadMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: (oldestTime: number) => void;
  session?: ChartSession;
  showSessionTiming?: boolean;
}

const DEFAULT_INTERVALS = ["15m", "4h", "1D", "1W", "1M"];
const LOAD_MORE_THRESHOLD = 10;
const INTRADAY_INTERVALS = new Set(["15m", "4h"]);
const EMPTY_DECORATIONS: SessionDecorations = { bands: [], boundaries: [] };
const ET_DAY_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const ET_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const ET_INTRADAY_LABEL_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function unixFromChartTime(time: unknown): number | null {
  if (typeof time === "number" && Number.isFinite(time)) {
    return time;
  }
  if (time && typeof time === "object") {
    const businessDay = time as { year?: number; month?: number; day?: number };
    if (
      typeof businessDay.year === "number" &&
      typeof businessDay.month === "number" &&
      typeof businessDay.day === "number"
    ) {
      return Math.floor(Date.UTC(businessDay.year, businessDay.month - 1, businessDay.day) / 1000);
    }
  }
  return null;
}

function formatIntradayTick(time: unknown): string {
  const unix = unixFromChartTime(time);
  if (unix === null) {
    return "";
  }
  return ET_INTRADAY_LABEL_FORMATTER.format(new Date(unix * 1000));
}

function getEtDayKey(timestamp: number): string {
  return ET_DAY_FORMATTER.format(new Date(timestamp * 1000));
}

function getEtMinutes(timestamp: number): number {
  const parts = ET_TIME_FORMATTER.formatToParts(new Date(timestamp * 1000));
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? "0");
  return hour * 60 + minute;
}

function classifySessionPeriod(timestamp: number): "premarket" | "regular" | "afterhours" {
  const minutes = getEtMinutes(timestamp);
  if (minutes < (9 * 60) + 30) {
    return "premarket";
  }
  if (minutes < 16 * 60) {
    return "regular";
  }
  return "afterhours";
}

function buildSessionDecorations(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart: any,
  times: number[],
): SessionDecorations {
  const timeScale = chart?.timeScale?.();
  if (!timeScale || typeof timeScale.timeToCoordinate !== "function" || times.length === 0) {
    return EMPTY_DECORATIONS;
  }

  const entries = times
    .map((time) => ({
      time,
      dateKey: getEtDayKey(time),
      kind: classifySessionPeriod(time),
      coordinate: timeScale.timeToCoordinate(time as unknown as import("lightweight-charts").UTCTimestamp),
    }))
    .filter((entry) => typeof entry.coordinate === "number" && Number.isFinite(entry.coordinate));

  if (!entries.length) {
    return EMPTY_DECORATIONS;
  }

  const points = entries.map((entry, index) => {
    const current = Number(entry.coordinate);
    const prev = index > 0 ? Number(entries[index - 1].coordinate) : null;
    const next = index < entries.length - 1 ? Number(entries[index + 1].coordinate) : null;
    const leftPadding = prev === null ? Math.max(((next ?? current + 16) - current) / 2, 8) : (current - prev) / 2;
    const rightPadding = next === null ? Math.max((current - (prev ?? current - 16)) / 2, 8) : (next - current) / 2;

    return {
      ...entry,
      coordinate: current,
      leftEdge: current - leftPadding,
      rightEdge: current + rightPadding,
    };
  });

  const bands: SessionBandDecoration[] = [];
  let activeBand: SessionBandDecoration | null = null;

  for (const point of points) {
    if (point.kind === "regular") {
      if (activeBand) {
        bands.push(activeBand);
        activeBand = null;
      }
      continue;
    }

    if (activeBand && activeBand.kind === point.kind && activeBand.key.startsWith(point.dateKey)) {
      activeBand.width = Math.max(0, point.rightEdge - activeBand.left);
      continue;
    }

    if (activeBand) {
      bands.push(activeBand);
    }

    activeBand = {
      key: `${point.dateKey}-${point.kind}`,
      kind: point.kind,
      left: point.leftEdge,
      width: Math.max(0, point.rightEdge - point.leftEdge),
    };
  }

  if (activeBand) {
    bands.push(activeBand);
  }

  const sessionEdges = new Map<string, { open?: number; close?: number }>();
  for (const point of points) {
    const day = sessionEdges.get(point.dateKey) ?? {};
    if (point.kind === "regular" && day.open === undefined) {
      day.open = point.leftEdge;
    }
    if (point.kind === "afterhours" && day.close === undefined) {
      day.close = point.leftEdge;
    }
    sessionEdges.set(point.dateKey, day);
  }

  const boundaries: SessionBoundaryDecoration[] = [];
  for (const [dateKey, edge] of sessionEdges.entries()) {
    if (typeof edge.open === "number") {
      boundaries.push({ key: `${dateKey}-open`, kind: "open", left: edge.open });
    }
    if (typeof edge.close === "number") {
      boundaries.push({ key: `${dateKey}-close`, kind: "close", left: edge.close });
    }
  }

  return { bands, boundaries };
}

export function TradingChart({
  bars,
  mode = "candlestick",
  lineData,
  priceLines,
  markers,
  height = 300,
  loading = false,
  timeframe = "1D",
  onTimeframeChange,
  intervalOptions,
  initialVisibleBars = 60,
  canLoadMore = false,
  loadingMore = false,
  onLoadMore,
  session = "regular",
  showSessionTiming = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const priceLineRefs = useRef<any[]>([]);
  const latestBarsRef = useRef<OhlcBar[]>(bars ?? []);
  const latestLineRef = useRef<LinePoint[]>(lineData ?? []);
  const latestPriceLinesRef = useRef<PriceLine[]>(priceLines ?? []);
  const latestMarkersRef = useRef<ChartMarker[]>(markers ?? []);
  const modeRef = useRef(mode);
  const dataTimesRef = useRef<number[]>([]);
  const hasInitializedViewportRef = useRef(false);
  const loadTriggerTimeRef = useRef<number | null>(null);
  const onLoadMoreRef = useRef(onLoadMore);
  const canLoadMoreRef = useRef(canLoadMore);
  const loadingMoreRef = useRef(loadingMore);
  const sessionRef = useRef(session);
  const showSessionTimingRef = useRef(showSessionTiming);
  const timeframeRef = useRef(timeframe);
  const [sessionDecorations, setSessionDecorations] = useState<SessionDecorations>(EMPTY_DECORATIONS);
  const hasData = mode === "line" ? !!lineData?.length : !!bars?.length;
  const intervals = intervalOptions ?? DEFAULT_INTERVALS;

  latestBarsRef.current = bars ?? [];
  latestLineRef.current = lineData ?? [];
  latestPriceLinesRef.current = priceLines ?? [];
  latestMarkersRef.current = markers ?? [];
  modeRef.current = mode;
  onLoadMoreRef.current = onLoadMore;
  canLoadMoreRef.current = canLoadMore;
  loadingMoreRef.current = loadingMore;
  sessionRef.current = session;
  showSessionTimingRef.current = showSessionTiming;
  timeframeRef.current = timeframe;

  const updateSessionDecorations = useCallback(() => {
    const chart = chartRef.current;
    const isOverlayEnabled =
      showSessionTimingRef.current &&
      sessionRef.current === "extended" &&
      INTRADAY_INTERVALS.has(timeframeRef.current);

    if (!chart || !isOverlayEnabled) {
      setSessionDecorations(EMPTY_DECORATIONS);
      return;
    }

    const times = latestBarsRef.current.length
      ? latestBarsRef.current.map((bar) => bar.time)
      : latestLineRef.current.map((point) => point.time);
    setSessionDecorations(buildSessionDecorations(chart, times));
  }, []);

  const applyOverlays = useCallback(() => {
    const series = seriesRef.current;
    if (!series) {
      return;
    }

    for (const existingPriceLine of priceLineRefs.current) {
      series.removePriceLine?.(existingPriceLine);
    }
    priceLineRefs.current = [];

    for (const priceLine of latestPriceLinesRef.current) {
      const createdPriceLine = series.createPriceLine({
        price: priceLine.price,
        color: priceLine.color,
        lineWidth: 1,
        lineStyle: 2,
        title: priceLine.label ?? "",
      });
      priceLineRefs.current.push(createdPriceLine);
    }

    series.setMarkers(
      latestMarkersRef.current.map((marker) => ({
        time: marker.time as unknown as import("lightweight-charts").UTCTimestamp,
        position: marker.position,
        shape: marker.shape,
        color: marker.shape === "arrowUp" ? "#4ade80" : "#f87171",
        text: marker.text ?? "",
      }))
    );
  }, []);

  const applyData = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) {
      return;
    }

    const nextData = modeRef.current === "line" ? latestLineRef.current : latestBarsRef.current;
    const nextTimes = nextData.map((point) => point.time);
    const previousTimes = dataTimesRef.current;
    const timeScale = chart.timeScale();
    const previousRange = timeScale.getVisibleLogicalRange?.() ?? null;

    if (modeRef.current === "line") {
      series.setData(
        latestLineRef.current.map((point) => ({
          time: point.time as unknown as import("lightweight-charts").UTCTimestamp,
          value: point.value,
        }))
      );
    } else {
      series.setData(
        latestBarsRef.current.map((bar) => ({
          time: bar.time as unknown as import("lightweight-charts").UTCTimestamp,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        }))
      );
    }

    dataTimesRef.current = nextTimes;

    if (!nextTimes.length) {
      updateSessionDecorations();
      return;
    }

    if (!hasInitializedViewportRef.current) {
      const from = Math.max(0, nextTimes.length - initialVisibleBars);
      timeScale.setVisibleLogicalRange?.({ from, to: nextTimes.length + 1 });
      hasInitializedViewportRef.current = true;
      updateSessionDecorations();
      return;
    }

    const didPrependOlderBars =
      previousTimes.length > 0 &&
      nextTimes.length > previousTimes.length &&
      nextTimes[nextTimes.length - 1] === previousTimes[previousTimes.length - 1] &&
      nextTimes[0] !== previousTimes[0];

    if (didPrependOlderBars && previousRange) {
      const delta = nextTimes.length - previousTimes.length;
      timeScale.setVisibleLogicalRange?.({
        from: previousRange.from + delta,
        to: previousRange.to + delta,
      });
    }

    if (loadTriggerTimeRef.current !== null && nextTimes[0] !== loadTriggerTimeRef.current) {
      loadTriggerTimeRef.current = null;
    }

    updateSessionDecorations();
  }, [initialVisibleBars, updateSessionDecorations]);

  useEffect(() => {
    if (!containerRef.current || !hasData) return;

    let disposed = false;
    let cleanup = () => undefined;

    import("lightweight-charts").then(({ createChart, ColorType }) => {
      if (!containerRef.current || disposed) return;

      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height,
        layout: {
          background: { type: ColorType.Solid, color: "#0f1117" },
          textColor: "#94a3b8",
        },
        grid: {
          vertLines: { color: "#1e293b" },
          horzLines: { color: "#1e293b" },
        },
        timeScale: {
          borderColor: "#334155",
          ...(INTRADAY_INTERVALS.has(timeframeRef.current)
            ? { tickMarkFormatter: formatIntradayTick }
            : {}),
        },
        rightPriceScale: {
          borderColor: "#334155",
        },
      });
      chartRef.current = chart;
      dataTimesRef.current = [];
      hasInitializedViewportRef.current = false;
      loadTriggerTimeRef.current = null;

      const series = mode === "line"
        ? chart.addLineSeries({
            color: "#60a5fa",
            lineWidth: 2,
          })
        : chart.addCandlestickSeries({
            upColor: "#4ade80",
            downColor: "#f87171",
            borderUpColor: "#4ade80",
            borderDownColor: "#f87171",
            wickUpColor: "#4ade80",
            wickDownColor: "#f87171",
          });
      seriesRef.current = series;

      const handleVisibleRangeChange = (range: { from: number; to: number } | null) => {
        const times = dataTimesRef.current;
        updateSessionDecorations();
        if (
          !range ||
          !times.length ||
          !canLoadMoreRef.current ||
          loadingMoreRef.current ||
          !onLoadMoreRef.current
        ) {
          return;
        }

        if (range.from > LOAD_MORE_THRESHOLD) {
          return;
        }

        const oldestTime = times[0];
        if (loadTriggerTimeRef.current === oldestTime) {
          return;
        }

        loadTriggerTimeRef.current = oldestTime;
        onLoadMoreRef.current(oldestTime);
      };

      chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      applyData();
      applyOverlays();

      cleanup = () => {
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
        for (const existingPriceLine of priceLineRefs.current) {
          series.removePriceLine?.(existingPriceLine);
        }
        priceLineRefs.current = [];
        chart.remove();
        chartRef.current = null;
        seriesRef.current = null;
        dataTimesRef.current = [];
        hasInitializedViewportRef.current = false;
        loadTriggerTimeRef.current = null;
        setSessionDecorations(EMPTY_DECORATIONS);
      };
    });

    return () => {
      disposed = true;
      cleanup();
    };
  }, [applyData, applyOverlays, hasData, height, mode]);

  useEffect(() => {
    if (!hasData) {
      return;
    }
    applyData();
  }, [applyData, bars, hasData, lineData]);

  useEffect(() => {
    applyOverlays();
  }, [applyOverlays, markers, priceLines]);

  useEffect(() => {
    if (!hasData) {
      setSessionDecorations(EMPTY_DECORATIONS);
      return;
    }
    updateSessionDecorations();
  }, [bars, hasData, lineData, session, showSessionTiming, timeframe, updateSessionDecorations]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    const intraday = INTRADAY_INTERVALS.has(timeframe);
    chart.applyOptions({
      timeScale: {
        tickMarkFormatter: intraday ? formatIntradayTick : undefined,
      },
    });
  }, [timeframe]);

  const controls = onTimeframeChange ? (
    <div className={styles.controls} aria-label="Chart interval">
      {intervals.map((tf) => (
        <button
          key={tf}
          type="button"
          className={`${styles.tfBtn} ${timeframe === tf ? styles.tfBtnActive : ""}`}
          onClick={() => onTimeframeChange(tf)}
        >
          {tf}
        </button>
      ))}
    </div>
  ) : null;
  const showSessionOverlay =
    showSessionTiming &&
    session === "extended" &&
    INTRADAY_INTERVALS.has(timeframe) &&
    (sessionDecorations.bands.length > 0 || sessionDecorations.boundaries.length > 0);
  const sessionLegend = showSessionOverlay ? (
    <div className={styles.sessionLegend} aria-label="Session timing legend">
      <span className={styles.sessionLegendItem}>
        <span className={`${styles.sessionSwatch} ${styles.sessionSwatchPremarket}`} />
        Pre-market
      </span>
      <span className={styles.sessionLegendItem}>
        <span className={`${styles.sessionSwatch} ${styles.sessionSwatchRegular}`} />
        Regular session
      </span>
      <span className={styles.sessionLegendItem}>
        <span className={`${styles.sessionSwatch} ${styles.sessionSwatchAfterhours}`} />
        After-hours
      </span>
    </div>
  ) : null;

  if (loading) {
    return (
      <>
        {controls}
        {sessionLegend}
        <div className={styles.placeholder} style={{ height }}>
          <span className={styles.placeholderText}>Loading chart...</span>
        </div>
      </>
    );
  }

  if (!hasData) {
    return (
      <>
        {controls}
        {sessionLegend}
        <div className={styles.placeholder} style={{ height }}>
          <span className={styles.placeholderText}>Chart will load when data is available</span>
        </div>
      </>
    );
  }

  return (
    <>
      {controls}
      {sessionLegend}
      <div className={styles.chartFrame} style={{ height }}>
        <div ref={containerRef} className={styles.chart} style={{ height }} />
        {showSessionOverlay ? (
          <div className={styles.sessionOverlay} data-testid="session-timing-overlay" aria-hidden="true">
            {sessionDecorations.bands.map((band) => (
              <div
                key={band.key}
                className={`${styles.sessionBand} ${
                  band.kind === "premarket" ? styles.sessionBandPremarket : styles.sessionBandAfterhours
                }`}
                style={{ left: `${band.left}px`, width: `${band.width}px` }}
              />
            ))}
            {sessionDecorations.boundaries.map((boundary) => (
              <div
                key={boundary.key}
                className={`${styles.sessionBoundary} ${
                  boundary.kind === "open" ? styles.sessionBoundaryOpen : styles.sessionBoundaryClose
                }`}
                style={{ left: `${boundary.left}px` }}
              />
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}
