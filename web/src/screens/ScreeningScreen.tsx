import { useMemo, useState } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { InheritedChip } from "../components/InheritedChip";
import type { ScreeningResult, BasketData } from "../types";
import styles from "./ScreeningScreen.module.css";

function getResultEntryMode(result: ScreeningResult): string {
  return result.suggested_entry_mode ?? result.entry_mode ?? "auto";
}

function getResultRegimeLabel(result: ScreeningResult): string {
  return result.regime?.label ?? result.regime_label ?? "Unknown";
}

function getResultSignal(result: ScreeningResult): string {
  return result.signal ?? result.status ?? "";
}

export function ScreeningScreen() {
  const { regime, setBasket, setScreen, autoAdvance } = useWorkflow();
  const [results, setResults] = useState<ScreeningResult[]>([]);
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set());
  const [runId, setRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState(0.6);
  const [maxResults, setMaxResults] = useState(20);
  const [universe, setUniverse] = useState(regime?.home_market ?? "US");
  const [strategyFilter, setStrategyFilter] = useState("all");
  const [toggles, setToggles] = useState({
    allowShorts: false,
    liquidOnly: false,
    earningsClean: false,
    technicalConfirmed: false,
  });

  const displayedResults = useMemo(() => {
    if (strategyFilter === "all") return results;
    return results.filter((result) => getResultEntryMode(result).toLowerCase() === strategyFilter);
  }, [results, strategyFilter]);

  const selectedDisplayedCount = displayedResults.filter((result) => selectedSymbols.has(result.symbol)).length;
  const allDisplayedSelected = displayedResults.length > 0 && selectedDisplayedCount === displayedResults.length;

  const handleRun = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/screening/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          universe,
          strategy: strategyFilter === "all" ? "auto" : strategyFilter,
          min_score: minScore,
          top_n: maxResults,
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const nextResults = data.results ?? [];
      setRunId(data.run_id);
      setResults(nextResults);
      setSelectedSymbols(new Set(nextResults.map((result: ScreeningResult) => result.symbol)));
      if (autoAdvance && data.run_id && nextResults.length > 0) {
        const basket: BasketData = {
          screening_run_id: data.run_id,
          symbols: nextResults.map((result: ScreeningResult) => result.symbol),
          regime: regime ?? null,
          created_at: new Date().toISOString(),
          status: "ready",
        };
        setBasket(basket);
        setScreen("batch");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleBuildBasket = () => {
    if (!runId || results.length === 0) return;
    const symbols = results
      .map((result) => result.symbol)
      .filter((symbol) => selectedSymbols.has(symbol));
    if (symbols.length === 0) return;
    const basket: BasketData = {
      screening_run_id: runId,
      symbols,
      regime: regime ?? null,
      created_at: new Date().toISOString(),
      status: "ready",
    };
    setBasket(basket);
    setScreen("batch");
  };

  const handleAddRemove = (symbol: string) => {
    setResults((prev) =>
      prev.some((r) => r.symbol === symbol)
        ? prev.filter((r) => r.symbol !== symbol)
        : prev
    );
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      next.delete(symbol);
      return next;
    });
  };

  const toggleSymbol = (symbol: string) => {
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const toggleAllDisplayed = () => {
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      if (allDisplayedSelected) {
        for (const result of displayedResults) next.delete(result.symbol);
      } else {
        for (const result of displayedResults) next.add(result.symbol);
      }
      return next;
    });
  };

  const selectedCount = selectedSymbols.size;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Screening</h1>
        {regime && (
          <InheritedChip label={`Regime: ${regime.label} (from Market)`} />
        )}
      </header>

      <form onSubmit={handleRun} className={styles.form}>
        <div className={styles.formRow}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="universe">Universe</label>
            <select
              id="universe"
              className={styles.input}
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
            >
              <option value="US">US</option>
              <option value="CA">CA</option>
              <option value="HK">HK</option>
              <option value="UK">UK</option>
              <option value="JP">JP</option>
            </select>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="min-score">Min score</label>
            <input
              id="min-score"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className={styles.input}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="max-results">Max results</label>
            <input
              id="max-results"
              type="number"
              min={1}
              max={100}
              value={maxResults}
              onChange={(e) => setMaxResults(Number(e.target.value))}
              className={styles.input}
            />
          </div>
          <button type="submit" className={styles.runBtn} disabled={loading}>
            {loading ? "Running…" : "Run screen"}
          </button>
        </div>
        <div className={styles.filterRow}>
          <div className={styles.strategyRadios}>
            {[
              ["all", "All"],
              ["breakout", "Breakout"],
              ["mean_reversion", "Mean reversion"],
            ].map(([value, label]) => (
              <label key={value} className={styles.inlineChoice}>
                <input
                  type="radio"
                  name="strategy-filter"
                  value={value}
                  checked={strategyFilter === value}
                  onChange={() => setStrategyFilter(value)}
                />
                {label}
              </label>
            ))}
          </div>
          <div className={styles.filterCheckboxes}>
            <label className={styles.inlineChoice}>
              <input
                type="checkbox"
                checked={toggles.allowShorts}
                onChange={(e) => setToggles((prev) => ({ ...prev, allowShorts: e.target.checked }))}
              />
              Allow shorts
            </label>
            <label className={styles.inlineChoice}>
              <input
                type="checkbox"
                checked={toggles.liquidOnly}
                onChange={(e) => setToggles((prev) => ({ ...prev, liquidOnly: e.target.checked }))}
              />
              Liquid only
            </label>
            <label className={styles.inlineChoice}>
              <input
                type="checkbox"
                checked={toggles.earningsClean}
                onChange={(e) => setToggles((prev) => ({ ...prev, earningsClean: e.target.checked }))}
              />
              Earnings clean
            </label>
            <label className={styles.inlineChoice}>
              <input
                type="checkbox"
                checked={toggles.technicalConfirmed}
                onChange={(e) => setToggles((prev) => ({ ...prev, technicalConfirmed: e.target.checked }))}
              />
              Technical confirmed
            </label>
          </div>
        </div>
        {error && <div className={styles.error}>{error}</div>}
      </form>

      {results.length > 0 ? (
        <div className={styles.resultsArea}>
          <div className={styles.resultsHeader}>
            <span className={styles.resultsCount}>{displayedResults.length} results</span>
            <button className={styles.basketBtn} onClick={handleBuildBasket}>
              Send to Batch →
            </button>
          </div>
          <div className={styles.resultsLayout}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.th}>
                    <input
                      type="checkbox"
                      aria-label="Select all results"
                      checked={allDisplayedSelected}
                      onChange={toggleAllDisplayed}
                    />
                  </th>
                  <th className={styles.th}>Symbol</th>
                  <th className={styles.th}>Score</th>
                  <th className={styles.th}>Regime</th>
                  <th className={styles.th}>Entry mode</th>
                  <th className={styles.th}>Signal</th>
                  <th className={styles.th}></th>
                </tr>
              </thead>
              <tbody>
                {displayedResults.map((r) => (
                  <tr key={r.symbol} className={styles.tr}>
                    <td className={styles.td}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${r.symbol}`}
                        checked={selectedSymbols.has(r.symbol)}
                        onChange={() => toggleSymbol(r.symbol)}
                      />
                    </td>
                    <td className={styles.td + " " + styles.symbol}>{r.symbol}</td>
                    <td className={styles.td}>{r.score.toFixed(2)}</td>
                    <td className={styles.td}>{getResultRegimeLabel(r)}</td>
                    <td className={styles.td}>{getResultEntryMode(r)}</td>
                    <td className={styles.td}>{getResultSignal(r)}</td>
                    <td className={styles.td}>
                      <button
                        className={styles.removeBtn}
                        onClick={() => handleAddRemove(r.symbol)}
                        aria-label={`Remove ${r.symbol}`}
                      >x</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <aside className={styles.basketPanel}>
              <div className={styles.basketCount}>{selectedCount} selected</div>
              <div className={styles.basketMeta}>{selectedCount * 8} min estimated</div>
              <button
                className={styles.basketBtn}
                type="button"
                disabled={selectedCount === 0}
                onClick={handleBuildBasket}
              >
                Send {selectedCount} tickers to Batch →
              </button>
            </aside>
          </div>
        </div>
      ) : (
        <div className={styles.empty}>
          Run a screen to see results, or paste your own tickers.
        </div>
      )}
    </div>
  );
}
