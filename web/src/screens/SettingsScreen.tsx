import { useState, useEffect } from "react";
import { useSettings } from "../hooks/useSettings";
import type { AppSettings } from "../types";
import styles from "./SettingsScreen.module.css";

export function SettingsScreen() {
  const { settings, loading, error, saving, updateSettings } = useSettings();
  const [draft, setDraft] = useState<Partial<AppSettings>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) setDraft(settings);
  }, [settings]);

  const handleChange = (key: keyof AppSettings, value: string | number) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    await updateSettings(draft);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.empty}>Loading settings…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.page}>
        <div className={styles.errorMsg}>Couldn't load settings: {error}</div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Settings</h1>
        {saved && <span className={styles.savedBadge}>Saved</span>}
      </header>

      <form onSubmit={handleSave} className={styles.form}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>LLM</h2>
          <div className={styles.fieldGrid}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="llm_provider">Provider</label>
              <input
                id="llm_provider"
                className={styles.input}
                value={draft.llm_provider ?? ""}
                onChange={(e) => handleChange("llm_provider", e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="deep_think_llm">Deep-think model</label>
              <input
                id="deep_think_llm"
                className={styles.input}
                value={draft.deep_think_llm ?? ""}
                onChange={(e) => handleChange("deep_think_llm", e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="quick_think_llm">Quick model</label>
              <input
                id="quick_think_llm"
                className={styles.input}
                value={draft.quick_think_llm ?? ""}
                onChange={(e) => handleChange("quick_think_llm", e.target.value)}
              />
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Execution</h2>
          <div className={styles.fieldGrid}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="execution_mode">Mode</label>
              <select
                id="execution_mode"
                className={styles.input}
                value={draft.execution_mode ?? "llm_assisted"}
                onChange={(e) => handleChange("execution_mode", e.target.value)}
              >
                <option value="llm_assisted">LLM-assisted</option>
                <option value="quant_strict">Quant-strict</option>
              </select>
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="max_debate_rounds">Max debate rounds</label>
              <input
                id="max_debate_rounds"
                type="number"
                min={1}
                max={10}
                className={styles.input}
                value={draft.max_debate_rounds ?? 1}
                onChange={(e) => handleChange("max_debate_rounds", Number(e.target.value))}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="max_risk_discuss_rounds">Max risk rounds</label>
              <input
                id="max_risk_discuss_rounds"
                type="number"
                min={1}
                max={10}
                className={styles.input}
                value={draft.max_risk_discuss_rounds ?? 1}
                onChange={(e) => handleChange("max_risk_discuss_rounds", Number(e.target.value))}
              />
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Market</h2>
          <div className={styles.fieldGrid}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="home_market">Home market</label>
              <input
                id="home_market"
                className={styles.input}
                value={draft.home_market ?? "US"}
                onChange={(e) => handleChange("home_market", e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="output_language">Output language</label>
              <input
                id="output_language"
                className={styles.input}
                value={draft.output_language ?? "en"}
                onChange={(e) => handleChange("output_language", e.target.value)}
              />
            </div>
          </div>
        </section>

        <div className={styles.actions}>
          <button type="submit" className={styles.saveBtn} disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      </form>
    </div>
  );
}
