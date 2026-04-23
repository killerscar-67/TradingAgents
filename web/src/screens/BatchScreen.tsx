import { useState, useEffect, useRef } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useBatchEvents } from "../hooks/useBatchEvents";
import { RunDetail } from "../components/RunDetail";
import { InheritedChip } from "../components/InheritedChip";
import type { BatchItem } from "../types";
import styles from "./BatchScreen.module.css";

function normalizeBatchStatus(status?: string): BatchItem["status"] {
  switch ((status ?? "").toLowerCase()) {
    case "completed":
      return "completed";
    case "running":
      return "running";
    case "failed":
    case "error":
    case "partial_failure":
      return "error";
    default:
      return "queued";
  }
}

export function BatchScreen() {
  const { basket, setBatchId, updateBatchResult, batchId, batchResults } = useWorkflow();
  const [symbols, setSymbols] = useState<string[]>(basket?.symbols ?? []);
  const [inputVal, setInputVal] = useState("");
  const [batchStarted, setBatchStarted] = useState(false);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastProcessedEventIndex = useRef(0);

  const { events } = useBatchEvents(batchStarted ? batchId : null);

  useEffect(() => {
    if (events.length < lastProcessedEventIndex.current) {
      lastProcessedEventIndex.current = 0;
    }

    const pendingEvents = events.slice(lastProcessedEventIndex.current);
    lastProcessedEventIndex.current = events.length;

    for (const event of pendingEvents) {
      if (!event.symbol || !event.status) continue;
      updateBatchResult(event.symbol, {
        ticker: event.symbol,
        run_id: event.run_id ?? null,
        status: normalizeBatchStatus(event.status),
        rating: event.rating ?? null,
        error: event.error ?? null,
      });
    }
  }, [events, updateBatchResult]);

  useEffect(() => {
    lastProcessedEventIndex.current = 0;
  }, [batchId]);

  const addSymbol = () => {
    const s = inputVal.trim().toUpperCase();
    if (s && !symbols.includes(s)) {
      setSymbols((prev) => [...prev, s]);
    }
    setInputVal("");
  };

  const removeSymbol = (s: string) => {
    setSymbols((prev) => prev.filter((x) => x !== s));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addSymbol();
    }
  };

  const startBatch = async () => {
    setError(null);
    try {
      const resp = await fetch("/api/batches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setBatchId(data.batch_id);
      for (const item of data.items ?? []) {
        if (!item?.symbol) continue;
        updateBatchResult(item.symbol, {
          ticker: item.symbol,
          run_id: item.run_id ?? null,
          status: normalizeBatchStatus(item.status),
          rating: item.rating ?? null,
          error: item.error ?? null,
        });
      }
      setBatchStarted(true);
    } catch (e) {
      setError(String(e));
    }
  };

  if (detailRunId) {
    return <RunDetail runId={detailRunId} onBack={() => setDetailRunId(null)} />;
  }

  const resultsList = Object.values(batchResults);
  const hasPartialFailure = resultsList.some((r) => r.status === "error");

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Batch Analysis</h1>
        {basket && (
          <InheritedChip
            label={`${basket.symbols.length} tickers (from Screening)`}
          />
        )}
      </header>

      {!batchStarted ? (
        <div className={styles.preStart}>
          {symbols.length === 0 && (
            <p className={styles.hint}>
              Add tickers below or run Screening first to build a basket.
            </p>
          )}

          <div className={styles.tickerList}>
            {symbols.map((s) => (
              <div key={s} className={styles.tickerRow}>
                <span className={styles.tickerName}>{s}</span>
                <button
                  className={styles.removeBtn}
                  onClick={() => removeSymbol(s)}
                  aria-label={`Remove ${s}`}
                >×</button>
              </div>
            ))}
          </div>

          <div className={styles.addRow}>
            <input
              className={styles.addInput}
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="AAPL, SHOP.TO…"
              aria-label="Add ticker"
            />
            <button className={styles.addBtn} type="button" onClick={addSymbol}>
              Add
            </button>
          </div>

          {error && <div className={styles.error}>{error}</div>}

          <button
            className={styles.startBtn}
            disabled={symbols.length === 0}
            onClick={startBatch}
          >
            Start batch analysis
          </button>
        </div>
      ) : (
        <div className={styles.cards}>
          {hasPartialFailure && (
            <div className={styles.partialFailure}>
              Some tickers failed. Successful results are still available below.
            </div>
          )}
          {symbols.map((sym) => {
            const item = batchResults[sym];
            const status = item?.status ?? "queued";
            return (
              <div
                key={sym}
                className={`${styles.card} ${item?.run_id ? styles.cardClickable : ""}`}
                onClick={() => item?.run_id && setDetailRunId(item.run_id)}
              >
                <div className={styles.cardHeader}>
                  <span className={styles.cardTicker}>{sym}</span>
                  <span className={`${styles.cardStatus} ${styles["cardStatus_" + status]}`}>
                    {status}
                  </span>
                </div>
                {item?.rating && (
                  <div className={styles.cardRating}>{item.rating}</div>
                )}
                {item?.error && (
                  <div className={styles.cardError}>{item.error}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
