import { useWorkflow } from "../contexts/WorkflowContext";
import type { Screen } from "../types";
import styles from "./Sidebar.module.css";

interface NavItem {
  screen: Screen;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { screen: "market", label: "Market", icon: "◈" },
  { screen: "screen", label: "Screening", icon: "⊞" },
  { screen: "batch", label: "Batch Analysis", icon: "⊟" },
  { screen: "strategy", label: "Strategy", icon: "◉" },
  { screen: "backtest", label: "Backtest", icon: "⊕" },
  { screen: "history", label: "History", icon: "☰" },
  { screen: "journal", label: "Journal", icon: "□" },
  { screen: "settings", label: "Settings", icon: "⊙" },
];

export function Sidebar() {
  const { screen, setScreen, setAutoAdvance } = useWorkflow();

  const runFullWorkflow = () => {
    setAutoAdvance(true);
    setScreen("market");
  };

  return (
    <nav className={styles.sidebar} aria-label="Main navigation">
      <div className={styles.brand}>
        <span className={styles.brandMark}>TA</span>
        <span className={styles.brandName}>TradingAgents</span>
      </div>

      <ul className={styles.navList}>
        {NAV_ITEMS.map((item) => (
          <li key={item.screen}>
            <button
              className={`${styles.navItem} ${screen === item.screen ? styles.navItemActive : ""}`}
              onClick={() => setScreen(item.screen, { userInitiated: true })}
              aria-current={screen === item.screen ? "page" : undefined}
            >
              <span className={styles.navIcon}>{item.icon}</span>
              <span className={styles.navLabel}>{item.label}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className={styles.footer}>
        <button className={styles.workflowBtn} onClick={runFullWorkflow}>
          Run full workflow
        </button>
      </div>
    </nav>
  );
}
