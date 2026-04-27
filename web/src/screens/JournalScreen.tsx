import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiUrl } from "../apiBase";
import type { JournalDecision, JournalReport } from "../types";
import styles from "./JournalScreen.module.css";

type ReportKind = "strategy" | "actor" | "phase" | "variant";

const REPORT_KINDS: ReportKind[] = ["strategy", "actor", "phase", "variant"];

export function JournalScreen() {
  const [decisions, setDecisions] = useState<JournalDecision[]>([]);
  const [reportKind, setReportKind] = useState<ReportKind>("strategy");
  const [report, setReport] = useState<JournalReport | null>(null);
  const [activeDecision, setActiveDecision] = useState<JournalDecision | null>(null);
  const [fillPrice, setFillPrice] = useState("");
  const [size, setSize] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl("/api/journal/decisions?limit=50"))
      .then((r) => (r.ok ? r.json() : { decisions: [] }))
      .then((data) => {
        if (!cancelled) setDecisions(data.decisions ?? []);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl(`/api/journal/reports?by=${reportKind}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch(() => {
        if (!cancelled) setReport(null);
      });
    return () => { cancelled = true; };
  }, [reportKind]);

  const openAction = (decision: JournalDecision) => {
    setActiveDecision(decision);
    setFillPrice(decision.entry == null ? "" : String(decision.entry));
    setSize("");
    setToast(null);
  };

  const saveAction = async () => {
    if (!activeDecision) return;
    const resp = await fetch(apiUrl("/api/journal/actions"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision_id: activeDecision.id,
        actor: "human",
        taken: true,
        fill_price: fillPrice ? Number(fillPrice) : null,
        size: size ? Number(size) : null,
      }),
    });
    if (resp.ok) {
      setToast("Action recorded.");
      setActiveDecision(null);
    } else {
      setToast("Could not record action.");
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Journal</h1>
      </header>

      <div className={styles.layout}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <h2>Recent decisions</h2>
          </div>
          {loading ? (
            <div className={styles.empty}>Loading…</div>
          ) : decisions.length === 0 ? (
            <div className={styles.empty}>No journal decisions yet.</div>
          ) : (
            <div className={styles.table}>
              {decisions.map((decision) => (
                <div key={decision.id} className={styles.row}>
                  <span className={styles.symbol}>{decision.symbol}</span>
                  <span>{decision.setup_name || decision.strategy_tag || "unknown setup"}</span>
                  <span>{decision.bias || "no-trade"}</span>
                  <span>{decision.session_phase || "-"}</span>
                  <button
                    type="button"
                    aria-label={`Log action for ${decision.symbol}`}
                    onClick={() => openAction(decision)}
                  >
                    Log action
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <h2>Reports</h2>
            <select
              aria-label="Journal report"
              value={reportKind}
              onChange={(e) => setReportKind(e.target.value as ReportKind)}
            >
              {REPORT_KINDS.map((kind) => (
                <option key={kind} value={kind}>{kind}</option>
              ))}
            </select>
          </div>
          <div className={styles.report}>
            {report?.rows?.length ? (
              <table>
                <thead>
                  <tr>
                    {Object.keys(report.rows[0]).map((key) => <th key={key}>{key}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((row, index) => (
                    <tr key={index}>
                      {Object.entries(row).map(([key, value]) => <td key={key}>{value}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : report ? (
              <ReactMarkdown>{report.markdown}</ReactMarkdown>
            ) : (
              <p>No report available.</p>
            )}
          </div>
        </section>
      </div>

      {activeDecision && (
        <div className={styles.dialogBackdrop}>
          <div className={styles.dialog} role="dialog" aria-modal="true">
            <h2>Log action</h2>
            <p>{activeDecision.symbol} · {activeDecision.setup_name || "setup"}</p>
            <label>
              Fill price
              <input
                value={fillPrice}
                onChange={(e) => setFillPrice(e.target.value)}
                inputMode="decimal"
              />
            </label>
            <label>
              Size
              <input
                value={size}
                onChange={(e) => setSize(e.target.value)}
                inputMode="decimal"
              />
            </label>
            <div className={styles.dialogActions}>
              <button type="button" onClick={() => setActiveDecision(null)}>Cancel</button>
              <button type="button" onClick={saveAction}>Save action</button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className={styles.toast}>{toast}</div>}
    </div>
  );
}
