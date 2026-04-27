import { useCallback, useEffect, useRef, useState } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { TradingChart } from "../components/TradingChart";
import { InheritedChip } from "../components/InheritedChip";
import { Dialog } from "../components/Dialog";
import { apiUrl } from "../apiBase";
import type { OhlcBar, PriceLine } from "../components/TradingChart";
import type { TradePlan } from "../types";
import styles from "./StrategyScreen.module.css";

interface StrategyResponse {
  strategy_id: string;
  status: string;
  trades?: Array<{
    symbol: string;
    side: "buy" | "sell";
    direction: "long" | "short";
    quantity: number;
    entry_price: number;
    stop_price: number;
    target_price: number;
    notional: number;
    rating: string;
    analysis_run_id?: string | null;
  }>;
  exposure?: {
    gross_exposure_pct?: number;
    net_exposure_pct?: number;
  };
  request?: {
    batch_id?: string;
    portfolio_size?: number;
  };
}

function mapStrategyResponseToTradePlan(data: StrategyResponse): TradePlan {
  const portfolioSize = Number(data.request?.portfolio_size ?? 100_000);
  const entries: TradePlan["entries"] = (data.trades ?? []).map((trade) => ({
    ticker: trade.symbol,
    side: trade.side,
    quantity: Number(trade.quantity ?? 0),
    direction: trade.direction === "short" ? "SHORT" : "LONG",
    entry: Number(trade.entry_price ?? 0),
    stop: Number(trade.stop_price ?? 0),
    target: Number(trade.target_price ?? 0),
    size_pct: portfolioSize > 0
      ? (Number(trade.notional ?? 0) / portfolioSize) * 100
      : 0,
    rating: trade.rating,
    run_id: trade.analysis_run_id ?? "",
  }));

  return {
    batch_id: data.request?.batch_id ?? "",
    date: new Date().toISOString().split("T")[0],
    entries,
    exposure: {
      gross: Number(data.exposure?.gross_exposure_pct ?? 0),
      net: Number(data.exposure?.net_exposure_pct ?? 0),
      long_count: entries.filter((entry) => entry.direction === "LONG").length,
      short_count: entries.filter((entry) => entry.direction === "SHORT").length,
    },
    status: data.status,
  };
}

export function StrategyScreen() {
  const { batchId, strategyId, tradePlan, setStrategyId, setScreen, autoAdvance } = useWorkflow();
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [stagingEntry, setStagingEntry] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [portfolioSize, setPortfolioSize] = useState(100_000);
  const [riskPct, setRiskPct] = useState(1);
  const [allowShorts, setAllowShorts] = useState(true);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [chartBars, setChartBars] = useState<OhlcBar[]>([]);
  const [chartLines, setChartLines] = useState<PriceLine[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const chartRequestRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchTickerChart = useCallback(async (ticker: string, entry: number, stop: number, target: number) => {
    const id = ++chartRequestRef.current;
    setChartLoading(true);
    setChartBars([]);
    try {
      const resp = await fetch(apiUrl(`/api/market/chart?symbol=${encodeURIComponent(ticker)}&interval=1D&limit=90`));
      if (!mountedRef.current || id !== chartRequestRef.current) return;
      if (resp.ok) {
        const data = await resp.json();
        setChartBars(data.bars ?? []);
      }
      setChartLines([
        { price: entry, color: "#22c55e", label: "Entry" },
        { price: stop, color: "#ef4444", label: "Stop" },
        { price: target, color: "#3b82f6", label: "Target" },
      ]);
    } catch {
      if (mountedRef.current && id === chartRequestRef.current) {
        setChartBars([]);
      }
    } finally {
      if (mountedRef.current && id === chartRequestRef.current) {
        setChartLoading(false);
      }
    }
  }, []);

  const handleRowClick = (ticker: string, entry: number, stop: number, target: number) => {
    setSelectedTicker(ticker);
    void fetchTickerChart(ticker, entry, stop, target);
  };

  const handleLoadPlan = async () => {
    if (!batchId) return;
    setLoadingPlan(true);
    setError(null);
    try {
      const resp = await fetch(apiUrl("/api/strategies/from-batch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          batch_id: batchId,
          portfolio_size: portfolioSize,
          risk_per_trade: riskPct / 100,
          allow_shorts: allowShorts,
          horizon: "intraday",
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: StrategyResponse = await resp.json();
      const plan = mapStrategyResponseToTradePlan(data);
      setPortfolioSize(Number(data.request?.portfolio_size ?? portfolioSize));
      setStrategyId(data.strategy_id, plan);
      if (autoAdvance) {
        setScreen("backtest");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingPlan(false);
    }
  };

  const openFutuDialog = (ticker: string) => {
    setStagingEntry(ticker);
    setDialogOpen(true);
  };

  const handleFutuConfirm = async () => {
    setDialogOpen(false);
    if (!tradePlan || !stagingEntry || !strategyId) return;
    try {
      const entry = tradePlan.entries.find((e) => e.ticker === stagingEntry);
      if (!entry) {
        throw new Error(`Unknown staged symbol ${stagingEntry}`);
      }
      const resp = await fetch(apiUrl("/api/broker/futu/stage"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: strategyId,
          orders: [
            {
              symbol: entry.ticker,
              side: entry.side,
              quantity: entry.quantity,
              entry_price: entry.entry,
            },
          ],
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setToast(`Staged ${stagingEntry} in Futu — review inside the app before submitting.`);
      setTimeout(() => setToast(null), 4000);
    } catch (e) {
      setToast(`Error staging: ${String(e)}`);
      setTimeout(() => setToast(null), 4000);
    }
  };

  const calculateRr = (entry: TradePlan["entries"][number]): number => {
    const reward = entry.direction === "LONG"
      ? entry.target - entry.entry
      : entry.entry - entry.target;
    const risk = entry.direction === "LONG"
      ? entry.entry - entry.stop
      : entry.stop - entry.entry;
    if (risk <= 0) return 0;
    return reward / risk;
  };

  const displaySizePct = (entry: TradePlan["entries"][number]): number => {
    const stopDistance = Math.abs(entry.entry - entry.stop);
    if (portfolioSize <= 0) return 0;
    return (stopDistance * entry.quantity / portfolioSize) * 100;
  };

  const csvString = () => {
    const rows = [
      "Ticker,Direction,Entry,Stop,Target,Size%,R:R,Rating,Notes",
      ...(tradePlan?.entries ?? []).map((entry) => [
        entry.ticker,
        entry.direction,
        entry.entry.toFixed(2),
        entry.stop.toFixed(2),
        entry.target.toFixed(2),
        displaySizePct(entry).toFixed(2),
        calculateRr(entry).toFixed(2),
        entry.rating,
        `"${(notes[entry.ticker] ?? "").replace(/"/g, '""')}"`,
      ].join(",")),
    ];
    return rows.join("\n");
  };

  const copyCsv = async () => {
    await navigator.clipboard?.writeText(csvString());
    setToast("Copied strategy CSV.");
    setTimeout(() => setToast(null), 3000);
  };

  const exportCsv = () => {
    const blob = new Blob([csvString()], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "strategy-plan.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  if (!batchId) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <h1 className={styles.title}>Strategy</h1>
        </header>
        <div className={styles.empty}>Run a batch analysis first to generate a trade plan.</div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Strategy</h1>
        {batchId && (
          <InheritedChip
            label={`Setups from batch · ${new Date().toLocaleDateString()}`}
          />
        )}
      </header>

      {error && <div className={styles.error}>{error}</div>}
      {toast && <div className={styles.toast}>{toast}</div>}

      {!tradePlan ? (
        <div className={styles.loadArea}>
          <div className={styles.portfolioInputs}>
            <div className={styles.inputRow}>
              <label htmlFor="portfolio-size">Portfolio size ($)</label>
              <input
                id="portfolio-size"
                type="number"
                min={1}
                value={portfolioSize}
                onChange={(e) => setPortfolioSize(Number(e.target.value))}
              />
            </div>
            <div className={styles.inputRow}>
              <label htmlFor="risk-per-trade">Risk per trade (%)</label>
              <input
                id="risk-per-trade"
                type="number"
                min={0}
                max={5}
                step={0.25}
                value={riskPct}
                onChange={(e) => setRiskPct(Number(e.target.value))}
              />
              <span>Max loss ${((portfolioSize * riskPct) / 100).toFixed(0)}</span>
            </div>
            <label className={styles.inputRow}>
              <input
                type="checkbox"
                checked={allowShorts}
                onChange={(e) => setAllowShorts(e.target.checked)}
              />
              Allow shorts
            </label>
          </div>
          <button className={styles.loadBtn} onClick={handleLoadPlan} disabled={loadingPlan}>
            {loadingPlan ? "Loading plan…" : "Generate strategy from batch"}
          </button>
        </div>
      ) : (
        <div className={styles.planArea}>
          <div className={styles.exposure}>
            <div className={styles.exposureItem}>
              <span className={styles.exposureValue}>{tradePlan.exposure.gross.toFixed(1)}%</span>
              <span className={styles.exposureLabel}>Gross</span>
            </div>
            <div className={styles.exposureItem}>
              <span className={styles.exposureValue}>{tradePlan.exposure.net.toFixed(1)}%</span>
              <span className={styles.exposureLabel}>Net</span>
            </div>
            <div className={styles.exposureItem}>
              <span className={styles.exposureValue}>{tradePlan.exposure.long_count}</span>
              <span className={styles.exposureLabel}>Long</span>
            </div>
            <div className={styles.exposureItem}>
              <span className={styles.exposureValue}>{tradePlan.exposure.short_count}</span>
              <span className={styles.exposureLabel}>Short</span>
            </div>
          </div>

          <div className={styles.chartArea}>
            {selectedTicker ? (
              <>
                <div className={styles.chartLabel}>{selectedTicker} — daily</div>
                <TradingChart
                  mode="candlestick"
                  bars={chartBars}
                  priceLines={chartLines}
                  height={200}
                  loading={chartLoading}
                />
              </>
            ) : (
              <div className={styles.chartPlaceholder}>
                Click a row to load the ticker chart
              </div>
            )}
          </div>

          <div className={styles.portfolioInputs}>
            <div className={styles.inputRow}>
              <label htmlFor="portfolio-size">Portfolio size ($)</label>
              <input
                id="portfolio-size"
                type="number"
                min={1}
                value={portfolioSize}
                onChange={(e) => setPortfolioSize(Number(e.target.value))}
              />
            </div>
            <div className={styles.inputRow}>
              <label htmlFor="risk-per-trade">Risk per trade (%)</label>
              <input
                id="risk-per-trade"
                type="number"
                min={0}
                max={5}
                step={0.25}
                value={riskPct}
                onChange={(e) => setRiskPct(Number(e.target.value))}
              />
              <span>Max loss ${((portfolioSize * riskPct) / 100).toFixed(0)}</span>
            </div>
            <div className={styles.actionBtns}>
              <button type="button" onClick={copyCsv}>Copy</button>
              <button type="button" onClick={exportCsv}>Export CSV</button>
            </div>
          </div>

          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.th}>Ticker</th>
                <th className={styles.th}>Direction</th>
                <th className={styles.th}>Entry</th>
                <th className={styles.th}>Stop</th>
                <th className={styles.th}>Target</th>
                <th className={styles.th}>Size %</th>
                <th className={styles.th}>R:R</th>
                <th className={styles.th}>Rating</th>
                <th className={styles.th}>Notes</th>
                <th className={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {tradePlan.entries.map((entry) => (
                <tr
                  key={entry.ticker}
                  className={`${styles.tr} ${selectedTicker === entry.ticker ? styles.trSelected : ""}`}
                  onClick={() => handleRowClick(entry.ticker, entry.entry, entry.stop, entry.target)}
                  style={{ cursor: "pointer" }}
                >
                  <td className={`${styles.td} ${styles.symbol}`}>{entry.ticker}</td>
                  <td className={`${styles.td} ${entry.direction === "LONG" ? styles.long : styles.short}`}>
                    {entry.direction}
                  </td>
                  <td className={styles.td}>{entry.entry.toFixed(2)}</td>
                  <td className={styles.td}>{entry.stop.toFixed(2)}</td>
                  <td className={styles.td}>{entry.target.toFixed(2)}</td>
                  <td className={styles.td}>{displaySizePct(entry).toFixed(1)}%</td>
                  <td className={styles.td}>{calculateRr(entry).toFixed(2)}</td>
                  <td className={styles.td}>{entry.rating}</td>
                  <td className={styles.td}>
                    <input
                      className={styles.notesInput}
                      aria-label={`Notes for ${entry.ticker}`}
                      value={notes[entry.ticker] ?? ""}
                      onChange={(e) => setNotes((prev) => ({ ...prev, [entry.ticker]: e.target.value }))}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className={styles.td}>
                    <button
                      className={styles.futuBtn}
                      onClick={(e) => { e.stopPropagation(); openFutuDialog(entry.ticker); }}
                    >
                      Send to Futu
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <button className={styles.backtestBtn} onClick={() => setScreen("backtest")}>
            Run backtest →
          </button>
        </div>
      )}

      <Dialog
        open={dialogOpen}
        title="Stage order in Futu"
        onConfirm={handleFutuConfirm}
        onCancel={() => setDialogOpen(false)}
      >
        Stage {stagingEntry ? `1 order (${stagingEntry})` : "order"} in your Futu account? These are
        staged, not placed — you'll still need to review and submit inside Futu.
      </Dialog>
    </div>
  );
}
