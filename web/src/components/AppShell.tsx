import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { useWorkflow } from "../contexts/WorkflowContext";
import styles from "./AppShell.module.css";

const SCREEN_LABELS: Record<string, string> = {
  market: "Market",
  screen: "Screening",
  batch: "Batch Analysis",
  strategy: "Strategy",
  backtest: "Backtest",
};

interface Props {
  children: ReactNode;
}

export function AppShell({ children }: Props) {
  const { autoAdvance, setAutoAdvance, screen } = useWorkflow();

  return (
    <div className={styles.shell}>
      <Sidebar />
      <div className={`${styles.content} ${autoAdvance ? styles.contentWithBanner : ""}`}>
        {autoAdvance && (
          <div className={styles.autoAdvanceBanner}>
            <span className={styles.bannerContent}>
              Auto-advance on — workflow will proceed through {SCREEN_LABELS[screen] ?? screen} automatically
            </span>
            <button type="button" onClick={() => setAutoAdvance(false)}>
              Stop auto-advance
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
