import { useState, useEffect, useRef } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useBatchEvents } from "../hooks/useBatchEvents";
import { RunDetail } from "../components/RunDetail";
import { InheritedChip } from "../components/InheritedChip";
import { Dialog } from "../components/Dialog";
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
  const { basket, setBatchId, updateBatchResult, batchId, batchResults, setScreen, autoAdvance } = useWorkflow();
  const [symbols, setSymbols] = useState<string[]>(basket?.symbols ?? []);
  const [inputVal, setInputVal] = useState("");
  const [batchStarted, setBatchStarted] = useState(false);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmStopOpen, setConfirmStopOpen] = useState(false);
  const [latestPhase, setLatestPhase] = useState<Record<string, string>>({});
  const lastProcessedEventIndex = useRef(0);
  const feedRef = useRef<HTMLDivElement>(null);

  const { events, done } = useBatchEvents(batchStarted ? batchId : null);

  useEffect(() => {
    if (events.length < lastProcessedEventIndex.current) {
      lastProcessedEventIndex.current = 0;
    }

    const pendingEvents = events.slice(lastProcessedEventIndex.current);
    lastProcessedEventIndex.current = events.length;

    for (const event of pendingEvents) {
      if (event.symbol && event.phase) {
        setLatestPhase((prev) => ({ ...prev, [event.symbol as string]: event.phase as string }));
      }
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

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [events]);

  useEffect(() => {
    if (autoAdvance && done) {
      setScreen("strategy");
    }
  }, [autoAdvance, done, setScreen]);

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

  const stopBatch = async () => {
    if (!batchId) return;
    await fetch(`/api/batches/${batchId}/stop`, { method: "POST" });
    setBatchStarted(false);
    setConfirmStopOpen(false);
  };

  const retryTicker = async (symbol: string) => {
    if (!batchId) return;
    await fetch(`/api/batches/${batchId}/items/${symbol}/retry`, { method: "POST" });
  };

  const skipTicker = (symbol: string) => {
    setSymbols((prev) => prev.filter((item) => item !== symbol));
  };

  if (detailRunId) {
    return <RunDetail runId={detailRunId} onBack={() => setDetailRunId(null)} />;
  }

  const resultsList = Object.values(batchResults);
  const hasPartialFailure = resultsList.some((r) => r.status === "error");
  const readyCount = resultsList.filter((r) => r.status === "completed").length;
  const feedEvents = events.slice(-50);

  const formatEventTime = (timestamp?: number | string) => {
    if (timestamp === undefined || timestamp === null || timestamp === "") {
      return "--:--:--";
    }
    const date = typeof timestamp === "number"
      ? new Date(timestamp > 10_000_000_000 ? timestamp : timestamp * 1000)
      : new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
      return "--:--:--";
    }
    return date.toLocaleTimeString();
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Batch Analysis</h1>
        {basket && (
          <InheritedChip
            label={`${basket.symbols.length} tickers (from Screening)`}
          />
        )}
        {batchStarted && !done && (
          <button className={styles.stopBtn} type="button" onClick={() => setConfirmStopOpen(true)}>
            Stop all
          </button>
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
        <div className={styles.runningArea}>
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
                  {latestPhase[sym] && (
                    <div className={styles.cardPhase}>Phase: {latestPhase[sym]}</div>
                  )}
                  {item?.rating && (
                    <div className={styles.cardRating}>{item.rating}</div>
                  )}
                  {item?.error && (
                    <div className={styles.cardError}>{item.error}</div>
                  )}
                  {status === "error" && (
                    <div className={styles.cardActions}>
                      <button
                        className={styles.retryBtn}
                        type="button"
                        aria-label={`Retry ${sym}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          void retryTicker(sym);
                        }}
                      >
                        Retry
                      </button>
                      <button
                        className={styles.skipBtn}
                        type="button"
                        aria-label={`Skip ${sym}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          skipTicker(sym);
                        }}
                      >
                        Skip
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className={styles.feedLog} ref={feedRef} aria-label="Batch live feed">
            {feedEvents.length === 0 ? (
              <div className={styles.feedEntry}>Waiting for batch events...</div>
            ) : (
              feedEvents.map((event, index) => (
                <div className={styles.feedEntry} key={`${event.sequence ?? index}-${event.timestamp ?? index}`}>
                  [{formatEventTime(event.timestamp)}] {event.symbol ?? "BATCH"} - {event.type}:{" "}
                  {event.status ?? event.rating ?? event.error ?? ""}
                </div>
              ))
            )}
          </div>

          {readyCount > 0 && (
            <div className={styles.progressiveCta}>
              <span>{readyCount} ready</span>
              <button type="button" onClick={() => setScreen("strategy")}>
                View strategy ({readyCount} ready)
              </button>
            </div>
          )}
        </div>
      )}
      <Dialog
        open={confirmStopOpen}
        title="Stop batch analysis"
        onConfirm={stopBatch}
        onCancel={() => setConfirmStopOpen(false)}
      >
        Stop all running and queued ticker analyses in this batch?
      </Dialog>
    </div>
  );
}
