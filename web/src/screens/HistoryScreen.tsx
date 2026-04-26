import { useEffect, useState } from "react";
import { RunDetail } from "../components/RunDetail";
import { apiUrl } from "../apiBase";
import type { HistoryItem } from "../types";
import styles from "./HistoryScreen.module.css";

interface HistoryResponse {
  items: HistoryItem[];
}

function groupByDate(items: HistoryItem[]): Record<string, HistoryItem[]> {
  const groups: Record<string, HistoryItem[]> = {};
  for (const item of items) {
    const date = (item.completed_at || item.created_at || "").slice(0, 10) || "Unknown";
    if (!groups[date]) groups[date] = [];
    groups[date].push(item);
  }
  return groups;
}

function normalizeHistoryStatus(status: string): "pending" | "running" | "completed" | "error" {
  switch (status.toLowerCase()) {
    case "queued":
    case "pending":
    case "draft":
      return "pending";
    case "running":
    case "active":
      return "running";
    case "completed":
    case "ready":
    case "saved":
    case "staged":
      return "completed";
    default:
      return "error";
  }
}

function formatHistoryType(type: string): string {
  return type.replace(/_/g, " ");
}

function formatRecordTime(timestamp: string | null): string {
  if (!timestamp) return "Unknown time";
  const value = new Date(timestamp);
  if (Number.isNaN(value.getTime())) return "Unknown time";
  return value.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function HistoryScreen() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl("/api/history"))
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((data: HistoryResponse) => {
        if (!cancelled) setItems(data.items ?? []);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const handleExport = (item: HistoryItem) => {
    // For legacy analysis runs, use the analysis report endpoint.
    // For other types (batch, strategy, backtest), open the browser to the relevant resource.
    if (item.type === "legacy_analysis") {
      window.open(apiUrl(`/api/runs/${item.id}/report`));
    } else {
      window.open(apiUrl(`/api/history`));
    }
  };

  const handleRerun = (item: HistoryItem) => {
    // Navigate to the appropriate screen with context pre-populated.
    // For analysis runs, open the run detail; for batches navigate to batch screen.
    if (item.type === "legacy_analysis" || item.type === "analysis_run") {
      setDetailRunId(item.id);
    } else {
      // For other types just open the detail.
      setDetailRunId(item.id);
    }
  };

  if (detailRunId) {
    return <RunDetail runId={detailRunId} onBack={() => setDetailRunId(null)} />;
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>Loading…</div>
      </div>
    );
  }

  const filteredItems = items.filter((item) => {
    const normalizedStatus = normalizeHistoryStatus(item.status);
    return (
      item.title.toLowerCase().includes(search.toLowerCase())
      && (!filterType || item.type === filterType)
      && (!filterStatus || normalizedStatus === filterStatus)
    );
  });
  const grouped = groupByDate(filteredItems);
  const dates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));
  const typeOptions = Array.from(new Set(items.map((item) => item.type))).sort();

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>History</h1>
      </header>

      <div className={styles.filterBar}>
        <input
          className={styles.searchInput}
          aria-label="Search history"
          placeholder="Search history"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className={styles.filterSelect}
          aria-label="Type filter"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
        >
          <option value="">All types</option>
          {typeOptions.map((type) => (
            <option key={type} value={type}>{formatHistoryType(type)} filter</option>
          ))}
        </select>
        <select
          className={styles.filterSelect}
          aria-label="Status filter"
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="error">Error</option>
        </select>
      </div>

      {dates.length === 0 ? (
        <div className={styles.empty}>No past runs found.</div>
      ) : (
        <div className={styles.groups}>
          {dates.map((date) => (
            <div key={date} className={styles.group}>
              <h2 className={styles.dateLabel}>{date}</h2>
              <div className={styles.runList}>
                {grouped[date].map((item) => {
                  const statusClass = normalizeHistoryStatus(item.status);
                  const recordTimestamp = item.completed_at || item.created_at;
                  const canViewDetail = item.type === "legacy_analysis" || item.type === "analysis_run";
                  return (
                    <div key={item.id} className={styles.runRow}>
                      <span className={styles.runTicker}>{item.title}</span>
                      <span className={styles.runMode}>{formatHistoryType(item.type)}</span>
                      <span className={styles.runTime}>{formatRecordTime(recordTimestamp)}</span>
                      <span className={styles.runProvider}>
                        {item.summary || item.home_market || item.workflow_session_id || item.id}
                      </span>
                      <span className={`${styles.runStatus} ${styles["runStatus_" + statusClass]}`}>
                        {item.status}
                      </span>
                      <span className={styles.actions}>
                        {canViewDetail && (
                          <button type="button" onClick={() => setDetailRunId(item.id)}>
                            View
                          </button>
                        )}
                        <button type="button" aria-label={`Re-run ${item.title}`} onClick={() => handleRerun(item)}>
                          Re-run
                        </button>
                        <button
                          type="button"
                          aria-label={`Export ${item.title}`}
                          onClick={() => handleExport(item)}
                        >
                          Export
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
