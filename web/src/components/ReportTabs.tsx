import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import styles from "./ReportTabs.module.css";

interface Tab {
  id: string;
  label: string;
  key: string | string[];
}

const TABS: Tab[] = [
  { id: "market", label: "Market", key: "market_report" },
  { id: "social", label: "Social", key: "sentiment_report" },
  { id: "news", label: "News", key: "news_report" },
  { id: "fundamentals", label: "Fundamentals", key: "fundamentals_report" },
  { id: "research", label: "Research", key: ["investment_debate_bull_history", "investment_debate_bear_history", "investment_debate_judge_decision"] },
  { id: "trader", label: "Trader", key: "trader_investment_plan" },
  { id: "risk", label: "Risk", key: ["risk_debate_aggressive_history", "risk_debate_conservative_history", "risk_debate_neutral_history", "risk_debate_judge_decision"] },
  { id: "portfolio", label: "Portfolio", key: "final_trade_decision" },
];

interface Props {
  sections: Record<string, string>;
  orderIntent: Record<string, unknown> | null;
}

function getContent(sections: Record<string, string>, key: string | string[]): string {
  if (Array.isArray(key)) {
    return key
      .filter((k) => sections[k])
      .map((k) => sections[k])
      .join("\n\n---\n\n");
  }
  return sections[key] ?? "";
}

function getInitialTab(sections: Record<string, string>, orderIntent: Record<string, unknown> | null): string {
  const firstWithContent = TABS.find((tab) => getContent(sections, tab.key));
  if (firstWithContent) {
    return firstWithContent.id;
  }
  return orderIntent ? "order" : "market";
}

export function ReportTabs({ sections, orderIntent }: Props) {
  const [active, setActive] = useState(() => getInitialTab(sections, orderIntent));

  const allTabs: Tab[] = [
    ...TABS,
    ...(orderIntent ? [{ id: "order", label: "Order intent", key: [] as string[] }] : []),
  ];

  useEffect(() => {
    const activeTab = allTabs.find((tab) => tab.id === active);
    const activeContent = activeTab ? getContent(sections, activeTab.key) : "";
    if (!activeContent) {
      const nextActive = getInitialTab(sections, orderIntent);
      if (nextActive !== active) {
        setActive(nextActive);
      }
    }
  }, [active, allTabs, orderIntent, sections]);

  return (
    <div className={styles.wrap}>
      <div className={styles.tabBar}>
        {allTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActive(tab.id)}
            className={active === tab.id ? styles.tabActive : styles.tab}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className={styles.content}>
        {active === "order" && orderIntent ? (
          <pre className={styles.orderJson}>{JSON.stringify(orderIntent, null, 2)}</pre>
        ) : (
          (() => {
            const tab = TABS.find((t) => t.id === active);
            if (!tab) return null;
            const content = getContent(sections, tab.key);
            return content ? (
              <ReactMarkdown>{content}</ReactMarkdown>
            ) : (
              <p className={styles.empty}>No content yet — this section will fill in as the analysis runs.</p>
            );
          })()
        )}
      </div>
    </div>
  );
}
