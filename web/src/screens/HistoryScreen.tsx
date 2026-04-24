import { useEffect, useState } from "react";
import { RunDetail } from "../components/RunDetail";
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

export function HistoryScreen() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/history")
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((data: HistoryResponse) => {
        if (!cancelled) setItems(data.items ?? []);
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

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
                  return (
                    <div key={item.id} className={styles.runRow}>
                      <span className={styles.runTicker}>{item.title}</span>
                      <span className={styles.runMode}>{formatHistoryType(item.type)}</span>
                      <span className={styles.runProvider}>
                        {item.summary || item.home_market || item.workflow_session_id || item.id}
                      </span>
                      <span className={`${styles.runStatus} ${styles["runStatus_" + statusClass]}`}>
                        {item.status}
                      </span>
                      <span className={styles.actions}>
                        {item.type === "legacy_analysis" && (
                          <button type="button" onClick={() => setDetailRunId(item.id)}>
                            View
                          </button>
                        )}
                        <button type="button" aria-label={`Re-run ${item.title}`}>
                          Re-run
                        </button>
                        <button
                          type="button"
                          aria-label={`Export ${item.title}`}
                          onClick={() => window.open(`/api/runs/${item.id}/report`)}
                        >
                          Export
                        </button>
                        {item.type === "legacy_analysis" && (
                          <button type="button">
                            Backtest again
                          </button>
                        )}
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
