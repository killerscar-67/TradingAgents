import { useCallback, useEffect, useRef, useState } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useMarketOverview } from "../hooks/useMarketOverview";
import { apiUrl } from "../apiBase";
import { TradingChart, type ChartSession, type LinePoint, type OhlcBar } from "../components/TradingChart";
import styles from "./MarketScreen.module.css";

interface SectorChange {
  symbol: string;
  label?: string;
  change_pct: number;
}

interface CalendarEvent {
  date: string;
  name: string;
  impact: string;
}

type ChartInterval = "15m" | "4h" | "1D" | "1W" | "1M";

interface ChartPayload {
  bars?: OhlcBar[];
  points?: LinePoint[];
  has_more?: boolean;
}

const CHART_INTERVALS: ChartInterval[] = ["15m", "4h", "1D", "1W", "1M"];
const CHART_LIMITS: Record<ChartInterval, number> = {
  "15m": 104,
  "4h": 90,
  "1D": 160,
  "1W": 104,
  "1M": 72,
};
const CHART_INITIAL_VISIBLE_BARS: Record<ChartInterval, number> = {
  "15m": 52,
  "4h": 36,
  "1D": 60,
  "1W": 52,
  "1M": 24,
};

function isIntradayInterval(interval: ChartInterval): boolean {
  return interval === "15m" || interval === "4h";
}

function supportsEtSessionTiming(symbol: string): boolean {
  return !symbol.endsWith(".TO") && !symbol.endsWith(".HK");
}

function mergeOlderSeries<T extends { time: number }>(current: T[], older: T[]): T[] {
  if (!older.length) {
    return current;
  }
  const existingTimes = new Set(current.map((item) => item.time));
  const merged = [...older.filter((item) => !existingTimes.has(item.time)), ...current];
  return merged.sort((left, right) => left.time - right.time);
}

function homeIndexForMarket(market: string): string {
  switch (market) {
    case "CA":
      return "XIU.TO";
    case "HK":
      return "2800.HK";
    case "JP":
      return "EWJ";
    case "UK":
      return "EWU";
    default:
      return "SPY";
  }
}

export function MarketScreen() {
  const { setRegime, autoAdvance, setScreen } = useWorkflow();
  const { overview, loading, error, live } = useMarketOverview();
  const [chartInterval, setChartInterval] = useState<ChartInterval>("1D");
  const [chartSession, setChartSession] = useState<ChartSession>("regular");
  const [chartMode, setChartMode] = useState<"candlestick" | "line">("candlestick");
  const [indexChart, setIndexChart] = useState<LinePoint[]>([]);
  const [indexBars, setIndexBars] = useState<OhlcBar[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartLoadingMore, setChartLoadingMore] = useState(false);
  const [chartHasMore, setChartHasMore] = useState(false);
  const mountedRef = useRef(true);
  const baseChartRequestRef = useRef(0);
  const backfillChartRequestRef = useRef(0);
  const overviewHomeMarket = (overview as { home_market?: string } | null)?.home_market ?? overview?.regime?.home_market ?? "US";
  const tradeDate = (overview as { trade_date?: string } | null)?.trade_date;
  const chartSymbol = homeIndexForMarket(overviewHomeMarket);
  const hasOverview = Boolean(overview);
  const intradayChart = isIntradayInterval(chartInterval);
  const sessionTimingSupported = intradayChart && supportsEtSessionTiming(chartSymbol);
  const sectors: SectorChange[] = overview?.sectors ?? [];
  const calendar = (overview?.events ?? []).filter((event: CalendarEvent) =>
    ["H", "M", "HIGH", "MEDIUM"].includes(String(event.impact).toUpperCase())
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (overview?.regime) {
      setRegime(overview.regime);
      if (autoAdvance) {
        setScreen("screen");
      }
    }
  }, [autoAdvance, overview?.regime, setRegime, setScreen]);

  useEffect(() => {
    if (sessionTimingSupported) {
      return;
    }
    setChartSession("regular");
  }, [sessionTimingSupported]);

  const fetchChartChunk = useCallback(
    async (before?: number) => {
      if (!hasOverview) {
        return;
      }

      const loadingOlder = typeof before === "number";
      const requestId = loadingOlder ? ++backfillChartRequestRef.current : ++baseChartRequestRef.current;
      const params = new URLSearchParams({
        symbol: chartSymbol,
        interval: chartInterval,
        limit: String(CHART_LIMITS[chartInterval]),
      });

      if (sessionTimingSupported) {
        params.set("session", chartSession);
      }

      if (tradeDate) {
        params.set("trade_date", tradeDate);
      }
      if (loadingOlder) {
        params.set("before", String(before));
        setChartLoadingMore(true);
      } else {
        setChartLoadingMore(false);
        setChartLoading(true);
      }

      try {
        const response = await fetch(apiUrl(`/api/market/chart?${params.toString()}`));
        const payload: ChartPayload = response.ok
          ? await response.json()
          : { bars: [], points: [], has_more: false };

        if (
          !mountedRef.current ||
          (loadingOlder ? requestId !== backfillChartRequestRef.current : requestId !== baseChartRequestRef.current)
        ) {
          return;
        }

        const nextBars = payload.bars ?? [];
        const nextPoints = payload.points ?? [];

        if (loadingOlder) {
          setIndexBars((current) => mergeOlderSeries(current, nextBars));
          setIndexChart((current) => mergeOlderSeries(current, nextPoints));
        } else {
          setIndexBars(nextBars);
          setIndexChart(nextPoints);
        }

        setChartHasMore(Boolean(payload.has_more));
      } catch {
        if (
          !mountedRef.current ||
          (loadingOlder ? requestId !== backfillChartRequestRef.current : requestId !== baseChartRequestRef.current)
        ) {
          return;
        }

        if (!loadingOlder) {
          setIndexBars([]);
          setIndexChart([]);
          setChartHasMore(false);
        }
      } finally {
        if (!mountedRef.current) {
          return;
        }

        if (loadingOlder) {
          setChartLoadingMore(false);
        } else {
          setChartLoading(false);
        }
      }
    },
    [chartInterval, chartSession, chartSymbol, hasOverview, sessionTimingSupported, tradeDate]
  );

  useEffect(() => {
    if (!hasOverview) {
      return;
    }
    void fetchChartChunk();
  }, [fetchChartChunk, hasOverview, chartSymbol, tradeDate]);

  const handleLoadMore = useCallback(
    (oldestTime: number) => {
      if (chartLoading || chartLoadingMore || !chartHasMore) {
        return;
      }
      void fetchChartChunk(oldestTime);
    },
    [chartHasMore, chartLoading, chartLoadingMore, fetchChartChunk]
  );

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>Loading market data…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>Markets are closed. Showing last session.</div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Market Overview</h1>
        <div className={styles.liveIndicator}>
          <span className={`${styles.liveDot} ${live ? styles.liveDotActive : ""}`} />
          <span className={styles.liveLabel}>{live ? "Live" : "Delayed"}</span>
        </div>
      </header>

      {overview ? (
        <div className={styles.body}>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Regime</h2>
            <div className={styles.regimeCard}>
              <div className={styles.regimeLabel}>{overview.regime.label}</div>
              <div className={styles.regimeMeta}>
                <span>Confidence: {overview.regime.confidence}%</span>
                <span>Entry: {overview.regime.suggested_entry_mode}</span>
                <span>Event Risk: {overview.regime.event_risk_flag ? "Elevated" : "Normal"}</span>
              </div>
              <div className={styles.regimeDate}>As of {tradeDate ?? "latest session"}</div>
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Indices</h2>
            <div className={styles.indexGrid}>
              {overview.indices.map((idx) => (
                <div key={idx.symbol} className={styles.indexTile}>
                  <div className={styles.indexSymbol}>{idx.symbol}</div>
                  <div className={styles.indexName}>{idx.label}</div>
                  <div className={styles.indexPrice}>{idx.price.toFixed(2)}</div>
                  <div className={`${styles.indexChange} ${idx.change_pct >= 0 ? styles.positive : styles.negative}`}>
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct.toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>{chartSymbol} trend</h2>
              <div className={styles.chartControlStack}>
                {sessionTimingSupported ? (
                  <div className={styles.chartModeGroup} aria-label="Trading session">
                    <button
                      type="button"
                      aria-pressed={chartSession === "regular"}
                      className={`${styles.chartModeBtn} ${chartSession === "regular" ? styles.chartModeBtnActive : ""}`}
                      onClick={() => setChartSession("regular")}
                    >
                      Regular
                    </button>
                    <button
                      type="button"
                      aria-pressed={chartSession === "extended"}
                      className={`${styles.chartModeBtn} ${chartSession === "extended" ? styles.chartModeBtnActive : ""}`}
                      onClick={() => setChartSession("extended")}
                    >
                      Extended
                    </button>
                  </div>
                ) : intradayChart ? (
                  <div className={styles.sessionHint}>Session timing unavailable for this market</div>
                ) : (
                  <div className={styles.sessionHint}>Session timing appears on intraday charts</div>
                )}
                <div className={styles.chartModeGroup} aria-label="Chart type">
                  <button
                    type="button"
                    aria-pressed={chartMode === "candlestick"}
                    className={`${styles.chartModeBtn} ${chartMode === "candlestick" ? styles.chartModeBtnActive : ""}`}
                    onClick={() => setChartMode("candlestick")}
                  >
                    Candles
                  </button>
                  <button
                    type="button"
                    aria-pressed={chartMode === "line"}
                    className={`${styles.chartModeBtn} ${chartMode === "line" ? styles.chartModeBtnActive : ""}`}
                    onClick={() => setChartMode("line")}
                  >
                    Line
                  </button>
                </div>
              </div>
            </div>
            <TradingChart
              mode={chartMode}
              bars={indexBars}
              lineData={indexChart}
              timeframe={chartInterval}
              onTimeframeChange={(nextInterval) => setChartInterval(nextInterval as ChartInterval)}
              intervalOptions={CHART_INTERVALS}
              initialVisibleBars={CHART_INITIAL_VISIBLE_BARS[chartInterval]}
              canLoadMore={chartHasMore}
              loadingMore={chartLoadingMore}
              onLoadMore={handleLoadMore}
              loading={chartLoading && indexBars.length === 0 && indexChart.length === 0}
              session={chartSession}
              showSessionTiming={sessionTimingSupported}
              height={220}
            />
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Sectors</h2>
            <div className={styles.sectorGrid}>
              {sectors.map((sector) => {
                const intensity = Math.min(Math.abs(sector.change_pct) / 3, 1);
                const background = sector.change_pct >= 0
                  ? `rgba(22, 163, 74, ${0.18 + intensity * 0.35})`
                  : `rgba(220, 38, 38, ${0.18 + intensity * 0.35})`;
                return (
                  <div key={sector.symbol} className={styles.sectorTile} style={{ background }}>
                    <span>{sector.label ?? sector.symbol}</span>
                    <strong className={sector.change_pct >= 0 ? styles.positive : styles.negative}>
                      {sector.change_pct >= 0 ? "+" : ""}{sector.change_pct.toFixed(2)}%
                    </strong>
                  </div>
                );
              })}
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Economic calendar</h2>
            <div className={styles.calendarList}>
              {calendar.map((event) => (
                <div key={`${event.date}-${event.name}`} className={styles.calendarEvent}>
                  <span>{event.date}</span>
                  <strong>{event.name}</strong>
                  <span className={styles.impactBadge}>{event.impact}</span>
                </div>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Breadth</h2>
            <div className={styles.breadthRow}>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue + " " + styles.positive}>{overview.breadth.pct_above_50d.toFixed(1)}%</span>
                <span className={styles.breadthLabel}>Above 50D</span>
              </div>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue}>{overview.breadth.advance_decline_ratio.toFixed(2)}</span>
                <span className={styles.breadthLabel}>A/D Ratio</span>
              </div>
              <div className={styles.breadthItem}>
                <span className={`${styles.breadthValue} ${overview.breadth.new_highs_minus_lows >= 0 ? styles.positive : styles.negative}`}>
                  {overview.breadth.new_highs_minus_lows >= 0 ? "+" : ""}{overview.breadth.new_highs_minus_lows}
                </span>
                <span className={styles.breadthLabel}>NH-NL</span>
              </div>
            </div>
            <div className={styles.regimeDate}>{overview.breadth.headline}</div>
          </section>
        </div>
      ) : (
        <div className={styles.empty}>Markets are closed. Showing last session.</div>
      )}
    </div>
  );
}
