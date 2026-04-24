import { useEffect, useState } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useMarketOverview } from "../hooks/useMarketOverview";
import { TradingChart, type LinePoint } from "../components/TradingChart";
import styles from "./MarketScreen.module.css";

interface SectorChange {
  symbol: string;
  name?: string;
  change_pct: number;
}

interface CalendarEvent {
  date: string;
  name: string;
  impact: string;
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
  const [chartTf, setChartTf] = useState("1D");
  const [indexChart, setIndexChart] = useState<LinePoint[]>([]);
  const [sectors, setSectors] = useState<SectorChange[]>([]);
  const [calendar, setCalendar] = useState<CalendarEvent[]>([]);

  useEffect(() => {
    if (overview?.regime) {
      setRegime(overview.regime);
      if (autoAdvance) {
        setScreen("screen");
      }
    }
  }, [autoAdvance, overview?.regime, setRegime, setScreen]);

  useEffect(() => {
    if (!overview?.regime) return;
    let cancelled = false;
    const homeIndex = homeIndexForMarket(overview.regime.home_market);

    const fetchMarketPanels = async () => {
      try {
        const [chartResp, sectorsResp, calendarResp] = await Promise.all([
          fetch(`/api/market/chart?symbol=${encodeURIComponent(homeIndex)}&period=${chartTf}`),
          fetch("/api/market/sectors"),
          fetch("/api/market/calendar?days=7"),
        ]);
        const [chartData, sectorsData, calendarData] = await Promise.all([
          chartResp.ok ? chartResp.json() : Promise.resolve({ points: [] }),
          sectorsResp.ok ? sectorsResp.json() : Promise.resolve({ sectors: [] }),
          calendarResp.ok ? calendarResp.json() : Promise.resolve({ events: [] }),
        ]);
        if (cancelled) return;
        const points = Array.isArray(chartData) ? chartData : chartData.points ?? [];
        setIndexChart(points);
        setSectors(sectorsData.sectors ?? []);
        setCalendar(
          (calendarData.events ?? []).filter((event: CalendarEvent) =>
            ["H", "M", "HIGH", "MEDIUM"].includes(String(event.impact).toUpperCase())
          )
        );
      } catch {
        if (!cancelled) {
          setIndexChart([]);
          setSectors([]);
          setCalendar([]);
        }
      }
    };

    fetchMarketPanels();
    return () => {
      cancelled = true;
    };
  }, [chartTf, overview?.regime]);

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
                <span>Trend: {overview.regime.trend}</span>
                <span>Breadth: {overview.regime.breadth}</span>
                <span>Volatility: {overview.regime.volatility}</span>
              </div>
              <div className={styles.regimeDate}>As of {overview.regime.as_of}</div>
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Indices</h2>
            <div className={styles.indexGrid}>
              {overview.indices.map((idx) => (
                <div key={idx.symbol} className={styles.indexTile}>
                  <div className={styles.indexSymbol}>{idx.symbol}</div>
                  <div className={styles.indexName}>{idx.name}</div>
                  <div className={styles.indexPrice}>{idx.price.toFixed(2)}</div>
                  <div className={`${styles.indexChange} ${idx.change_pct >= 0 ? styles.positive : styles.negative}`}>
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct.toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{homeIndexForMarket(overview.regime.home_market)} trend</h2>
            <TradingChart
              mode="line"
              lineData={indexChart}
              timeframe={chartTf}
              onTimeframeChange={setChartTf}
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
                    <span>{sector.symbol}</span>
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
                <span className={styles.breadthValue + " " + styles.positive}>{overview.breadth.advancing}</span>
                <span className={styles.breadthLabel}>Advancing</span>
              </div>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue + " " + styles.negative}>{overview.breadth.declining}</span>
                <span className={styles.breadthLabel}>Declining</span>
              </div>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue}>{overview.breadth.unchanged}</span>
                <span className={styles.breadthLabel}>Unchanged</span>
              </div>
            </div>
          </section>
        </div>
      ) : (
        <div className={styles.empty}>Markets are closed. Showing last session.</div>
      )}
    </div>
  );
}
