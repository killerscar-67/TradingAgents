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

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

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
        {run?.trading_style && (
          <span className={styles.metaChip}>{run.trading_style}</span>
        )}
        {run?.intraday_interval && (
          <span className={styles.metaChip}>{run.intraday_interval}</span>
        )}
        {run?.session_phase && (
          <span className={styles.metaChip}>{run.session_phase}</span>
        )}
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
          {run?.trading_style === "daytrade" && run.intraday_decisions.length > 0 && (
            <section className={styles.intradayPanel} aria-label="Intraday setup">
              <div className={styles.intradayHeader}>
                <h2>Intraday Setup</h2>
                <span>{run.trade_datetime ?? run.data_session_date ?? run.analysis_date}</span>
              </div>
              <div className={styles.setupGrid}>
                {run.intraday_decisions.map((decision, index) => (
                  <article key={`${decision.variant ?? "decision"}-${index}`} className={styles.setupCard}>
                    <div className={styles.setupTop}>
                      <strong>{decision.setup_name || "Unnamed setup"}</strong>
                      <span>{decision.bias || "no-trade"}</span>
                    </div>
                    <div className={styles.levels}>
                      <span>Entry {formatValue(decision.entry)}</span>
                      <span>Stop {formatValue(decision.stop)}</span>
                      <span>Target {formatValue(decision.target1)}</span>
                      {decision.target2 !== undefined && decision.target2 !== null && (
                        <span>Target 2 {formatValue(decision.target2)}</span>
                      )}
                    </div>
                    <p>{decision.rationale || "No rationale recorded."}</p>
                    {decision.invalidation && (
                      <p className={styles.invalidation}>Invalidation: {decision.invalidation}</p>
                    )}
                    <div className={styles.setupMeta}>
                      <span>{decision.variant || "default"}</span>
                      <span>{decision.confidence || "confidence n/a"}</span>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
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
