import { useState, useEffect } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useBacktestEvents } from "../hooks/useBacktestEvents";
import { TradingChart } from "../components/TradingChart";
import { InheritedChip } from "../components/InheritedChip";
import { apiUrl } from "../apiBase";
import type { BacktestRun } from "../types";
import styles from "./BacktestScreen.module.css";

interface BacktestTradePayload {
  symbol: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  entry_timestamp: string;
  exit_timestamp: string;
  net_pnl: number;
  exit_reason: string;
  bars?: number;
}

interface BacktestSymbolPayload {
  symbol: string;
  sharpe_ratio?: number;
  max_drawdown_pct?: number;
  trades?: BacktestTradePayload[];
}

interface BacktestApiResponse {
  backtest_id: string;
  strategy_id: string;
  start_date: string;
  end_date: string;
  execution_mode?: "quant_strict";
  status: "queued" | "running" | "completed" | "error";
  result?: {
    summary?: {
      total_return_pct?: number;
      trade_count?: number;
      win_rate?: number;
      sharpe_ratio?: number;
      max_drawdown_pct?: number;
    };
    equity_curve?: number[];
    per_symbol?: BacktestSymbolPayload[];
    execution_mode?: "quant_strict";
  };
}

function toPercent(value: number | undefined): number {
  const numeric = Number(value ?? 0);
  return Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
}

function computeSharpeRatio(values: number[]): number {
  if (values.length < 2) return 0;
  const returns: number[] = [];
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous === 0) continue;
    returns.push((current - previous) / previous);
  }
  if (returns.length < 2) return 0;
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const variance = returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / returns.length;
  if (variance <= 0) return 0;
  return (mean / Math.sqrt(variance)) * Math.sqrt(26 * 252);
}

function computeMaxDrawdownPct(values: number[]): number {
  let peak = values[0] ?? 0;
  let maxDrawdown = 0;

  for (const value of values) {
    if (value > peak) peak = value;
    if (peak > 0) {
      maxDrawdown = Math.max(maxDrawdown, ((peak - value) / peak) * 100);
    }
  }

  return maxDrawdown;
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function computeReturns(values: number[]): number[] {
  const returns: number[] = [];
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous !== 0) returns.push((current - previous) / previous);
  }
  return returns;
}

function daysBetween(startDate: string, endDate: string): number {
  const start = new Date(startDate).getTime();
  const end = new Date(endDate).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 0;
  return Math.max(1, Math.round((end - start) / 86_400_000));
}

function computeSortino(values: number[]): number {
  const returns = computeReturns(values);
  if (returns.length === 0) return 0;
  const mean = average(returns);
  const downside = returns.filter((value) => value < 0);
  if (downside.length === 0) return 0;
  const downsideStd = Math.sqrt(
    downside.reduce((sum, value) => sum + value ** 2, 0) / downside.length
  );
  if (downsideStd <= 0) return 0;
  return (mean / downsideStd) * Math.sqrt(252);
}

function computeProfitFactor(pnls: number[]): number {
  const positive = pnls.filter((value) => value > 0).reduce((sum, value) => sum + value, 0);
  const negative = pnls.filter((value) => value < 0).reduce((sum, value) => sum + value, 0);
  if (negative === 0) return positive > 0 ? positive : 0;
  return positive / Math.abs(negative);
}

function mapBacktestResponseToRun(data: BacktestApiResponse): BacktestRun {
  const result = data.result ?? {};
  const summary = result.summary ?? {};
  const equityValues = (result.equity_curve ?? []).map((value) => Number(value));
  const perSymbol = result.per_symbol ?? [];
  const sharpeFromSymbols = average(
    perSymbol
      .map((item) => Number(item.sharpe_ratio))
      .filter((value) => Number.isFinite(value))
  );
  const maxDrawdownFromSymbols = Math.max(
    0,
    ...perSymbol
      .map((item) => toPercent(item.max_drawdown_pct))
      .filter((value) => Number.isFinite(value))
  );
  const sharpeFallback = perSymbol.length === 1
    ? Number(perSymbol[0].sharpe_ratio ?? 0)
    : (equityValues.length > 1 ? computeSharpeRatio(equityValues) : sharpeFromSymbols);
  const maxDrawdownFallback = perSymbol.length === 1
    ? toPercent(perSymbol[0].max_drawdown_pct)
    : (equityValues.length > 1 ? computeMaxDrawdownPct(equityValues) : maxDrawdownFromSymbols);

  const tradeLog = perSymbol.flatMap((item) =>
    (item.trades ?? []).map((trade) => ({
      date: trade.exit_timestamp,
      ticker: trade.symbol,
      direction: trade.direction.toUpperCase(),
      entry: Number(trade.entry_price ?? 0),
      exit: Number(trade.exit_price ?? 0),
      pnl_pct: Number.isFinite(Number(trade.net_pnl)) ? Number(trade.net_pnl) : null,
      status: trade.exit_reason,
      bars: trade.bars,
    }))
  );
  const totalReturnPct = Number(summary.total_return_pct ?? 0);
  const holdBars = tradeLog
    .map((trade) => Number(trade.bars))
    .filter((value) => Number.isFinite(value));

  return {
    backtest_id: data.backtest_id,
    strategy_id: data.strategy_id,
    start_date: data.start_date,
    end_date: data.end_date,
    execution_mode: result.execution_mode ?? data.execution_mode ?? "quant_strict",
    status: data.status,
    kpi: {
      total_return_pct: totalReturnPct,
      sharpe: Number(summary.sharpe_ratio ?? sharpeFallback),
      max_drawdown_pct: Number(
        summary.max_drawdown_pct !== undefined
          ? toPercent(summary.max_drawdown_pct)
          : maxDrawdownFallback
      ),
      win_rate_pct: toPercent(summary.win_rate),
      num_trades: Number(summary.trade_count ?? 0),
      cagr_pct: ((1 + totalReturnPct / 100) ** (365 / daysBetween(data.start_date, data.end_date)) - 1) * 100,
      sortino: computeSortino(equityValues),
      profit_factor: computeProfitFactor(
        tradeLog
          .map((trade) => Number(trade.pnl_pct))
          .filter((value) => Number.isFinite(value))
      ),
      avg_hold_bars: average(holdBars),
    },
    trade_log: tradeLog,
    equity_curve: equityValues.map((value, index) => ({
      time: index,
      value,
    })),
  };
}

export function BacktestScreen() {
  const { strategyId, tradePlan, backtestId, setBacktestId, autoAdvance, setScreen } = useWorkflow();
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().split("T")[0];
  });
  const [endDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [run, setRun] = useState<BacktestRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { events, done } = useBacktestEvents(backtestId);

  useEffect(() => {
    if (!done || !backtestId) return;

    let cancelled = false;

    const fetchResult = async () => {
      try {
        const resp = await fetch(apiUrl(`/api/backtests/${backtestId}`));
        if (!resp.ok) return;
        const data: BacktestApiResponse = await resp.json();
        if (!cancelled) {
          setRun(mapBacktestResponseToRun(data));
        }
      } catch {
        // ignore
      }
    };

    fetchResult();

    return () => {
      cancelled = true;
    };
  }, [done, backtestId]);

  useEffect(() => {
    if (autoAdvance && run?.status === "completed") {
      setScreen("history");
    }
  }, [autoAdvance, run?.status, setScreen]);

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setRun(null);
    try {
      const resp = await fetch(apiUrl("/api/backtests"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_id: strategyId,
          start_date: startDate,
          end_date: endDate,
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: BacktestApiResponse = await resp.json();
      setBacktestId(data.backtest_id);
      setRun(mapBacktestResponseToRun(data));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const symbolEvents = events.filter((event) => event.type === "backtest_symbol");
  const completedSymbols = new Set(
    symbolEvents
      .filter((event) => event.status === "completed" && event.symbol)
      .map((event) => event.symbol as string)
  );
  const expectedSymbols = Math.max(1, tradePlan?.entries.length ?? 0);
  const latestSymbolEvent = symbolEvents[symbolEvents.length - 1];
  const progress = Math.min(completedSymbols.size / expectedSymbols, 1);
  const progressLabel = latestSymbolEvent?.symbol
    ? `${latestSymbolEvent.status === "completed" ? "Completed" : "Running"} ${latestSymbolEvent.symbol}`
    : "Running backtest…";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Backtest</h1>
        {strategyId && (
          <InheritedChip label="Strategy: Today's plan (from Strategy)" />
        )}
      </header>

      {!strategyId ? (
        <div className={styles.empty}>
          Build a strategy in Strategy, or load a saved preset.
        </div>
      ) : (
        <div className={styles.body}>
          <form onSubmit={handleStart} className={styles.form}>
            <div className={styles.formRow}>
              <div className={styles.field}>
                <label className={styles.label} htmlFor="start-date">Start date</label>
                <input
                  id="start-date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className={styles.input}
                />
              </div>
              <div className={styles.field}>
                <label className={styles.label}>End date</label>
                <input type="date" value={endDate} readOnly className={styles.input} />
              </div>
              <div className={styles.field}>
                <label className={styles.label}>Execution mode</label>
                <input type="text" value="quant_strict" readOnly className={styles.input} />
              </div>
              <button type="submit" className={styles.runBtn} disabled={loading || !!backtestId}>
                {loading ? "Starting…" : "Run backtest"}
              </button>
            </div>
            {error && <div className={styles.error}>{error}</div>}
          </form>

          {backtestId && !run && (
            <div className={styles.progress}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
              <span className={styles.progressLabel}>
                {progressLabel}
              </span>
            </div>
          )}

          {run?.kpi && (
            <div className={styles.kpiGrid}>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{run.kpi.total_return_pct.toFixed(1)}%</div>
                <div className={styles.kpiLabel}>Total return</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{run.kpi.sharpe.toFixed(2)}</div>
                <div className={styles.kpiLabel}>Sharpe</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{run.kpi.max_drawdown_pct.toFixed(1)}%</div>
                <div className={styles.kpiLabel}>Max drawdown</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{run.kpi.win_rate_pct.toFixed(1)}%</div>
                <div className={styles.kpiLabel}>Win rate</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{run.kpi.num_trades}</div>
                <div className={styles.kpiLabel}>Trades</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{(run.kpi.cagr_pct ?? 0).toFixed(2)}%</div>
                <div className={styles.kpiLabel}>CAGR</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{(run.kpi.sortino ?? 0).toFixed(2)}</div>
                <div className={styles.kpiLabel}>Sortino</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{(run.kpi.profit_factor ?? 0).toFixed(2)}</div>
                <div className={styles.kpiLabel}>Profit factor</div>
              </div>
              <div className={styles.kpiCard}>
                <div className={styles.kpiValue}>{(run.kpi.avg_hold_bars ?? 0).toFixed(1)}</div>
                <div className={styles.kpiLabel}>Avg hold</div>
              </div>
            </div>
          )}

          <TradingChart mode="line" lineData={run?.equity_curve} height={280} loading={loading} />

          {run && (
            <section className={styles.tradeLog}>
              <h2 className={styles.sectionTitle}>Trade log</h2>
              {run.trade_log.length === 0 ? (
                <div className={styles.emptyLog}>No individual trades available.</div>
              ) : (
                <table className={styles.tradeTable}>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Ticker</th>
                      <th>Dir</th>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>P&amp;L%</th>
                      <th>Bars</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.trade_log.map((trade, index) => (
                      <tr key={`${trade.ticker}-${trade.date}-${index}`}>
                        <td>{trade.date?.slice(0, 10)}</td>
                        <td>{trade.ticker}</td>
                        <td>{trade.direction}</td>
                        <td>{trade.entry.toFixed(2)}</td>
                        <td>{trade.exit === null ? "-" : trade.exit.toFixed(2)}</td>
                        <td>{trade.pnl_pct === null ? "-" : trade.pnl_pct.toFixed(2)}</td>
                        <td>{trade.bars ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
