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

  const grouped = groupByDate(items);
  const dates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>History</h1>
      </header>

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
                  const rowContent = (
                    <>
                      <span className={styles.runTicker}>{item.title}</span>
                      <span className={styles.runMode}>{formatHistoryType(item.type)}</span>
                      <span className={styles.runProvider}>
                        {item.summary || item.home_market || item.workflow_session_id || item.id}
                      </span>
                      <span className={`${styles.runStatus} ${styles["runStatus_" + statusClass]}`}>
                        {item.status}
                      </span>
                    </>
                  );

                  if (item.type === "legacy_analysis") {
                    return (
                      <button
                        key={item.id}
                        className={styles.runRow}
                        onClick={() => setDetailRunId(item.id)}
                      >
                        {rowContent}
                      </button>
                    );
                  }

                  return (
                    <div key={item.id} className={styles.runRow}>
                      {rowContent}
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
