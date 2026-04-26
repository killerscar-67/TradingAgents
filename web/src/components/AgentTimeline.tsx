import { useEffect, useRef } from "react";
import type { AgentStatuses } from "../types";
import styles from "./AgentTimeline.module.css";

interface Props {
  statuses: AgentStatuses;
  runStatus: string;
}

interface Phase {
  label: string;
  agents: string[];
}

const PHASES: Phase[] = [
  { label: "Market analyst — pulling price history and indicators", agents: ["Market Analyst"] },
  { label: "News analyst — gathering headlines", agents: ["News Analyst"] },
  { label: "Social analyst — reading sentiment", agents: ["Social Analyst"] },
  { label: "Fundamentals analyst — pulling financials", agents: ["Fundamentals Analyst"] },
  { label: "Researchers debating — bull vs. bear", agents: ["Bull Researcher", "Bear Researcher"] },
  { label: "Research manager — weighing the arguments", agents: ["Research Manager"] },
  { label: "Trader — drafting a proposal", agents: ["Trader"] },
  { label: "Risk team — aggressive, neutral, and conservative review", agents: ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"] },
  { label: "Portfolio manager — final call", agents: ["Portfolio Manager"] },
  { label: "Done. Compiling the report…", agents: [] },
];

type PhaseStatus = "pending" | "active" | "done";

function getPhaseStatus(phase: Phase, statuses: AgentStatuses, runStatus: string): PhaseStatus {
  if (phase.agents.length === 0) {
    return runStatus === "completed" ? "done" : "pending";
  }
  const agentStatuses = phase.agents.map((a) => statuses[a]);
  if (agentStatuses.every((s) => s === "completed")) return "done";
  if (agentStatuses.some((s) => s === "in_progress" || s === "completed")) return "active";
  return "pending";
}

export function AgentTimeline({ statuses, runStatus }: Props) {
  const hasStarted =
    Object.keys(statuses).length > 0 ||
    runStatus === "running" ||
    runStatus === "completed" ||
    runStatus === "error";
  const activeRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [statuses]);

  if (!hasStarted) {
    return (
      <div className={styles.wrap}>
        <p className={styles.empty}>
          No analyses yet.<br />
          Pick a ticker and date above, then hit Run analysis. Results will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <ol className={styles.list}>
        {PHASES.map((phase, i) => {
          const status = getPhaseStatus(phase, statuses, runStatus);
          return (
            <li
              key={i}
              ref={status === "active" ? activeRef : null}
              className={
                status === "done"
                  ? styles.phaseDone
                  : status === "active"
                  ? styles.phaseActive
                  : styles.phasePending
              }
            >
              <span className={styles.phaseIcon} aria-hidden>
                {status === "done" ? "✓" : status === "active" ? "◎" : "○"}
              </span>
              <span className={styles.phaseLabel}>{phase.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
