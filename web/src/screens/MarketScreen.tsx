import { useEffect } from "react";
import { useWorkflow } from "../contexts/WorkflowContext";
import { useMarketOverview } from "../hooks/useMarketOverview";
import styles from "./MarketScreen.module.css";

export function MarketScreen() {
  const { setRegime } = useWorkflow();
  const { overview, loading, error, live } = useMarketOverview();

  useEffect(() => {
    if (overview?.regime) {
      setRegime(overview.regime);
    }
  }, [overview?.regime, setRegime]);

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>Loading market data…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>Markets are closed. Showing last session.</div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Market Overview</h1>
        <div className={styles.liveIndicator}>
          <span className={`${styles.liveDot} ${live ? styles.liveDotActive : ""}`} />
          <span className={styles.liveLabel}>{live ? "Live" : "Delayed"}</span>
        </div>
      </header>

      {overview ? (
        <div className={styles.body}>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Regime</h2>
            <div className={styles.regimeCard}>
              <div className={styles.regimeLabel}>{overview.regime.label}</div>
              <div className={styles.regimeMeta}>
                <span>Trend: {overview.regime.trend}</span>
                <span>Breadth: {overview.regime.breadth}</span>
                <span>Volatility: {overview.regime.volatility}</span>
              </div>
              <div className={styles.regimeDate}>As of {overview.regime.as_of}</div>
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Indices</h2>
            <div className={styles.indexGrid}>
              {overview.indices.map((idx) => (
                <div key={idx.symbol} className={styles.indexTile}>
                  <div className={styles.indexSymbol}>{idx.symbol}</div>
                  <div className={styles.indexName}>{idx.name}</div>
                  <div className={styles.indexPrice}>{idx.price.toFixed(2)}</div>
                  <div className={`${styles.indexChange} ${idx.change_pct >= 0 ? styles.positive : styles.negative}`}>
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct.toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Breadth</h2>
            <div className={styles.breadthRow}>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue + " " + styles.positive}>{overview.breadth.advancing}</span>
                <span className={styles.breadthLabel}>Advancing</span>
              </div>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue + " " + styles.negative}>{overview.breadth.declining}</span>
                <span className={styles.breadthLabel}>Declining</span>
              </div>
              <div className={styles.breadthItem}>
                <span className={styles.breadthValue}>{overview.breadth.unchanged}</span>
                <span className={styles.breadthLabel}>Unchanged</span>
              </div>
            </div>
          </section>
        </div>
      ) : (
        <div className={styles.empty}>Markets are closed. Showing last session.</div>
      )}
    </div>
  );
}
