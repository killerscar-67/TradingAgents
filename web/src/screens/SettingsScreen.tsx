import { useState, useEffect } from "react";
import { useSettings } from "../hooks/useSettings";
import { useModels } from "../hooks/useModels";
import type { AppSettings } from "../types";
import styles from "./SettingsScreen.module.css";

const HOME_MARKETS = [
  { label: "US – S&P 500", value: "US" },
  { label: "HK – Hang Seng", value: "HK" },
  { label: "JP – Nikkei 225", value: "JP" },
];

const OUTPUT_LANGUAGES = [
  { label: "English", value: "English" },
  { label: "繁體中文 (Traditional Chinese)", value: "Traditional Chinese" },
  { label: "简体中文 (Simplified Chinese)", value: "Simplified Chinese" },
  { label: "日本語 (Japanese)", value: "Japanese" },
  { label: "한국어 (Korean)", value: "Korean" },
];

export function SettingsScreen() {
  const { settings, loading, error, saving, updateSettings } = useSettings();
  const { providerOptions, getModelOptions, isCustomProvider } = useModels();
  const [draft, setDraft] = useState<Partial<AppSettings>>({});
  const [saved, setSaved] = useState(false);
  const [brokerStatus, setBrokerStatus] = useState<string | null>(null);

  useEffect(() => {
    if (settings) setDraft(settings);
  }, [settings]);

  const handleChange = (key: keyof AppSettings, value: string | number | boolean) => {
    setDraft((prev) => {
      const next = { ...prev, [key]: value };
      // When provider changes, reset model selections to first available option
      if (key === "llm_provider") {
        const deepOpts = getModelOptions(String(value), "deep");
        const quickOpts = getModelOptions(String(value), "quick");
        if (deepOpts.length) next.deep_think_llm = deepOpts[0].value;
        if (quickOpts.length) next.quick_think_llm = quickOpts[0].value;
      }
      return next;
    });
    setSaved(false);
  };

  const testFutuConnection = async () => {
    setBrokerStatus("Testing...");
    try {
      const resp = await fetch("/api/broker/futu/ping", { method: "POST" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setBrokerStatus("Connection ready");
    } catch (e) {
      setBrokerStatus(`Connection failed: ${String(e)}`);
    }
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
              <select
                id="llm_provider"
                className={styles.input}
                value={draft.llm_provider ?? ""}
                onChange={(e) => handleChange("llm_provider", e.target.value)}
              >
                {providerOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.value}</option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="deep_think_llm">Deep-think model</label>
              {isCustomProvider(draft.llm_provider ?? "") ? (
                <input
                  id="deep_think_llm"
                  className={styles.input}
                  placeholder="Enter model name"
                  value={draft.deep_think_llm ?? ""}
                  onChange={(e) => handleChange("deep_think_llm", e.target.value)}
                />
              ) : (
                <select
                  id="deep_think_llm"
                  className={styles.input}
                  value={draft.deep_think_llm ?? ""}
                  onChange={(e) => handleChange("deep_think_llm", e.target.value)}
                >
                  {getModelOptions(draft.llm_provider ?? "", "deep").map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              )}
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="quick_think_llm">Quick model</label>
              {isCustomProvider(draft.llm_provider ?? "") ? (
                <input
                  id="quick_think_llm"
                  className={styles.input}
                  placeholder="Enter model name"
                  value={draft.quick_think_llm ?? ""}
                  onChange={(e) => handleChange("quick_think_llm", e.target.value)}
                />
              ) : (
                <select
                  id="quick_think_llm"
                  className={styles.input}
                  value={draft.quick_think_llm ?? ""}
                  onChange={(e) => handleChange("quick_think_llm", e.target.value)}
                >
                  {getModelOptions(draft.llm_provider ?? "", "quick").map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              )}
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
              <select
                id="home_market"
                className={styles.input}
                value={draft.home_market ?? "US"}
                onChange={(e) => handleChange("home_market", e.target.value)}
              >
                {HOME_MARKETS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="output_language">Output language</label>
              <select
                id="output_language"
                className={styles.input}
                value={draft.output_language ?? "English"}
                onChange={(e) => handleChange("output_language", e.target.value)}
              >
                {OUTPUT_LANGUAGES.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Workflow Defaults</h2>
          <div className={styles.fieldGrid}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="top_n">Top N</label>
              <input
                id="top_n"
                type="number"
                min={1}
                max={50}
                className={styles.input}
                value={draft.top_n ?? settings?.top_n ?? 10}
                onChange={(e) => handleChange("top_n", Number(e.target.value))}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="score_floor">Score floor</label>
              <input
                id="score_floor"
                type="number"
                min={0}
                max={1}
                step={0.05}
                className={styles.input}
                value={draft.score_floor ?? settings?.score_floor ?? 0.6}
                onChange={(e) => handleChange("score_floor", Number(e.target.value))}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="risk_per_trade_pct">Risk per trade (%)</label>
              <input
                id="risk_per_trade_pct"
                type="number"
                min={0}
                max={5}
                step={0.25}
                className={styles.input}
                value={draft.risk_per_trade_pct ?? settings?.risk_per_trade_pct ?? 1}
                onChange={(e) => handleChange("risk_per_trade_pct", Number(e.target.value))}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="portfolio_size">Portfolio size</label>
              <input
                id="portfolio_size"
                type="number"
                min={0}
                className={styles.input}
                value={draft.portfolio_size ?? settings?.portfolio_size ?? 100000}
                onChange={(e) => handleChange("portfolio_size", Number(e.target.value))}
              />
            </div>
            <label className={styles.checkboxField}>
              <input
                type="checkbox"
                checked={Boolean(draft.allow_shorts ?? settings?.allow_shorts)}
                onChange={(e) => handleChange("allow_shorts", e.target.checked)}
              />
              Allow shorts
            </label>
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Broker (Futu/OpenD)</h2>
          <div className={styles.fieldGrid}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="futu_host">Futu host</label>
              <input
                id="futu_host"
                className={styles.input}
                value={draft.futu_host ?? settings?.futu_host ?? "127.0.0.1"}
                onChange={(e) => handleChange("futu_host", e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="futu_port">Futu port</label>
              <input
                id="futu_port"
                type="number"
                className={styles.input}
                value={draft.futu_port ?? settings?.futu_port ?? 11111}
                onChange={(e) => handleChange("futu_port", Number(e.target.value))}
              />
            </div>
          </div>
          <div className={styles.brokerActions}>
            <button type="button" className={styles.secondaryBtn} onClick={testFutuConnection}>
              Test connection
            </button>
            {brokerStatus && <span className={styles.brokerStatus}>{brokerStatus}</span>}
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Watchlists &amp; Presets</h2>
          <p className={styles.note}>
            Strategy preset storage is planned for a future release.
          </p>
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
