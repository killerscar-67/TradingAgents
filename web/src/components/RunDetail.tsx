import { useMemo } from "react";
import type { AgentStatuses } from "../types";
import { useSSE } from "../hooks/useSSE";
import { useAnalysisRun } from "../hooks/useAnalysisRun";
import { AgentTimeline } from "./AgentTimeline";
import { ReportTabs } from "./ReportTabs";
import { ConsultantChat } from "./ConsultantChat";
import styles from "./RunDetail.module.css";

interface Props {
  runId: string;
  onBack: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Starting…",
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

export function RunDetail({ runId, onBack }: Props) {
  const { run, error } = useAnalysisRun(runId);
  const { events } = useSSE(runId);

  const agentStatuses = useMemo<AgentStatuses>(() => {
    const statuses: AgentStatuses = {};
    for (const event of events) {
      if (event.type === "agent_status") {
        const { agent, status } = event.payload as { agent: string; status: "pending" | "in_progress" | "completed" };
        statuses[agent] = status;
      }
    }
    return statuses;
  }, [events]);

  const liveReportSections = useMemo<Record<string, string>>(() => {
    const sections: Record<string, string> = {};
    for (const event of events) {
      if (event.type === "report_section") {
        const { key, content } = event.payload as { key: string; content: string };
        sections[key] = content;
      }
    }
    return sections;
  }, [events]);

  const reportSections = run
    ? { ...liveReportSections, ...run.report_sections }
    : liveReportSections;

  const hasContext = Object.keys(reportSections).length > 0;
  const runStatus = run?.status ?? "pending";

  if (error) {
    return (
      <div className={styles.errorPage}>
        <button className={styles.backBtn} onClick={onBack}>← New analysis</button>
        <p className={styles.errorMsg}>Couldn't load this run: {error}</p>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <button className={styles.backBtn} onClick={onBack}>← New analysis</button>
        <span className={styles.ticker}>{run?.ticker ?? "…"}</span>
        <span className={styles.date}>{run?.analysis_date}</span>
        {run && (
          <span className={`${styles.statusBadge} ${styles[STATUS_CLASS[run.status]]}`}>
            {STATUS_LABEL[run.status]}
          </span>
        )}
        {run?.errors && run.errors.length > 0 && (
          <span className={styles.headerError}>{run.errors[0]}</span>
        )}
      </header>

      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <AgentTimeline statuses={agentStatuses} runStatus={runStatus} />
        </aside>

        <main className={styles.center}>
          <ReportTabs
            sections={reportSections}
            orderIntent={run?.final_order_intent ?? null}
          />
        </main>

        <aside className={styles.consultant}>
          <ConsultantChat runId={runId} disabled={!hasContext} />
        </aside>
      </div>
    </div>
  );
}
