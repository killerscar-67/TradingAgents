import { useEffect, useState } from "react";
import type { AnalysisRun } from "../types";
import styles from "./ReportArchives.module.css";

interface Props {
  onOpenRun: (runId: string) => void;
  onNewAnalysis: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Done",
  error: "Failed",
};

const STATUS_CLASS: Record<string, string> = {
  pending: "statusPending",
  running: "statusRunning",
  completed: "statusDone",
  error: "statusError",
};

function formatTimestamp(value: string | null) {
  if (!value) return "Not finished";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ReportArchives({ onOpenRun, onNewAnalysis }: Props) {
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadArchives = async () => {
      try {
        const resp = await fetch("/api/analysis");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!cancelled) setRuns(data.runs ?? []);
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadArchives();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.heading}>Report archives</h1>
          <p className={styles.subheading}>Previous analysis runs saved by the web UI.</p>
        </div>
        <button type="button" className={styles.newBtn} onClick={onNewAnalysis}>
          New analysis
        </button>
      </div>

      {error && <div className={styles.errorBanner} role="alert">{error}</div>}
      {loading && <p className={styles.muted}>Loading archives...</p>}
      {!loading && !error && runs.length === 0 && (
        <p className={styles.muted}>No archived reports yet.</p>
      )}

      <div className={styles.list}>
        {runs.map((run) => (
          <article key={run.run_id} className={styles.row}>
            <div className={styles.primary}>
              <div className={styles.titleLine}>
                <span className={styles.ticker}>{run.ticker}</span>
                <span className={styles.date}>{run.analysis_date}</span>
                <span className={`${styles.statusBadge} ${styles[STATUS_CLASS[run.status]]}`}>
                  {STATUS_LABEL[run.status]}
                </span>
              </div>
              <div className={styles.meta}>
                <span>{run.llm_provider}</span>
                <span>{run.deep_think_llm}</span>
                <span>{run.quick_think_llm}</span>
                <span>{run.execution_mode}</span>
              </div>
              <div className={styles.meta}>
                <span>Created {formatTimestamp(run.created_at)}</span>
                <span>Completed {formatTimestamp(run.completed_at)}</span>
              </div>
            </div>
            <button
              type="button"
              className={styles.openBtn}
              aria-label={`Open report for ${run.ticker}`}
              onClick={() => onOpenRun(run.run_id)}
            >
              Open
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
