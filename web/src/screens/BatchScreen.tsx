import { useState, useEffect, useRef } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useBatchEvents } from "../hooks/useBatchEvents";
import { RunDetail } from "../components/RunDetail";
import { InheritedChip } from "../components/InheritedChip";
import { Dialog } from "../components/Dialog";
import { apiUrl } from "../apiBase";
import type { BatchItem } from "../types";
import styles from "./BatchScreen.module.css";

const TERMINAL_BATCH_STATUSES = new Set(["completed", "error", "partial_failure", "stopped", "not_found"]);

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

type TradingStyle = "swing" | "daytrade";

const INTRADAY_INTERVALS = ["1m", "5m", "15m", "30m", "1h"];

export function BatchScreen() {
  const { basket, basketId, setBatchId, updateBatchResult, batchId, batchResults, setScreen, autoAdvance } = useWorkflow();
  const [symbols, setSymbols] = useState<string[]>(basket?.symbols ?? []);
  const [inputVal, setInputVal] = useState("");
  const [tradingStyle, setTradingStyle] = useState<TradingStyle>("swing");
  const [intradayInterval, setIntradayInterval] = useState("5m");
  const [tradeDatetime, setTradeDatetime] = useState("");
  const [batchStarted, setBatchStarted] = useState(false);
  const [batchStatus, setBatchStatus] = useState<string | null>(null);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmStopOpen, setConfirmStopOpen] = useState(false);
  const [latestPhase, setLatestPhase] = useState<Record<string, string>>({});
  const [eventStreamRestartKey, setEventStreamRestartKey] = useState(0);
  const lastProcessedEventIndex = useRef(0);
  const feedRef = useRef<HTMLDivElement>(null);

  const { events, done } = useBatchEvents(batchStarted ? batchId : null, eventStreamRestartKey);

  useEffect(() => {
    let cancelled = false;
    if (!batchId || batchStarted) {
      return () => {
        cancelled = true;
      };
    }

    void fetch(apiUrl(`/api/batches/${batchId}`))
      .then(async (resp) => {
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        return resp.json();
      })
      .then((data) => {
        if (cancelled || !data?.batch) {
          return;
        }
        const batch = data.batch as {
          symbols?: string[];
          items?: Array<{ symbol?: string; run_id?: string | null; status?: string; rating?: string | null; error?: string | null }>;
          events?: Array<{ symbol?: string; phase?: string }>;
          status?: string;
        };
        setSymbols(batch.symbols ?? []);
        setLatestPhase(() => {
          const next: Record<string, string> = {};
          for (const event of batch.events ?? []) {
            if (event.symbol && event.phase) {
              next[event.symbol] = event.phase;
            }
          }
          return next;
        });
        for (const item of batch.items ?? []) {
          if (!item?.symbol) continue;
          updateBatchResult(item.symbol, {
            ticker: item.symbol,
            run_id: item.run_id ?? null,
            status: normalizeBatchStatus(item.status),
            rating: item.rating ?? null,
            error: item.error ?? null,
          });
        }
        setBatchStatus(batch.status ?? null);
        setBatchStarted(true);
        setError(null);
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setError(String(fetchError));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [batchId, batchStarted, updateBatchResult]);

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
      if (event.type === "batch_status" && event.status) {
        setBatchStatus(event.status);
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
      const body: Record<string, unknown> = { symbols, trading_style: tradingStyle };
      if (basketId) body.basket_id = basketId;
      if (tradingStyle === "daytrade") {
        body.intraday_interval = intradayInterval;
        if (tradeDatetime) body.trade_datetime = tradeDatetime;
      }
      const resp = await fetch(apiUrl("/api/batches"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setBatchId(data.batch_id);
      setBatchStatus(data.status ?? null);
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
    await fetch(apiUrl(`/api/batches/${batchId}/stop`), { method: "POST" });
    setBatchStatus("stopped");
    setBatchStarted(false);
    setConfirmStopOpen(false);
  };

  const startNewBatch = () => {
    setBatchId(null);
    setBatchStarted(false);
    setBatchStatus(null);
    setLatestPhase({});
    setEventStreamRestartKey(0);
    setError(null);
    setInputVal("");
    setTradingStyle("swing");
    setIntradayInterval("5m");
    setTradeDatetime("");
    setSymbols(basket?.symbols ?? []);
  };

  const retryTicker = async (symbol: string) => {
    if (!batchId) return;
    updateBatchResult(symbol, {
      ticker: symbol,
      run_id: null,
      status: "queued",
      rating: null,
      error: null,
    });
    setBatchStatus("running");
    setLatestPhase((prev) => {
      const next = { ...prev };
      delete next[symbol];
      return next;
    });
    setBatchStarted(true);

    const resp = await fetch(apiUrl(`/api/batches/${batchId}/items/${symbol}/retry`), { method: "POST" });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    setEventStreamRestartKey((value) => value + 1);
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
  const isTerminalBatch = batchStatus ? TERMINAL_BATCH_STATUSES.has(batchStatus.toLowerCase()) : done;

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
        {batchStarted && (
          <button className={styles.addBtn} type="button" onClick={startNewBatch}>
            Start new batch
          </button>
        )}
        {batchStarted && !isTerminalBatch && (
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

          <div className={styles.styleRow}>
            {(["swing", "daytrade"] as TradingStyle[]).map((s) => (
              <button
                key={s}
                type="button"
                className={`${styles.styleBtn} ${tradingStyle === s ? styles.styleBtnActive : ""}`}
                onClick={() => setTradingStyle(s)}
              >
                {s === "swing" ? "Swing" : "Daytrade"}
              </button>
            ))}
          </div>

          {tradingStyle === "daytrade" && (
            <div className={styles.intradayFields}>
              <div>
                <label className={styles.fieldLabel} htmlFor="intraday-interval">Interval</label>
                <select
                  id="intraday-interval"
                  className={styles.fieldInput}
                  value={intradayInterval}
                  onChange={(e) => setIntradayInterval(e.target.value)}
                >
                  {INTRADAY_INTERVALS.map((iv) => (
                    <option key={iv} value={iv}>{iv}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={styles.fieldLabel} htmlFor="trade-datetime">
                  Trade datetime (optional, e.g. 2026-04-27 09:30)
                </label>
                <input
                  id="trade-datetime"
                  type="text"
                  className={styles.fieldInput}
                  placeholder="YYYY-MM-DD HH:MM"
                  value={tradeDatetime}
                  onChange={(e) => setTradeDatetime(e.target.value)}
                />
              </div>
            </div>
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
