import { useEffect, useState } from "react";
import type { ModelCatalog } from "../types";
import styles from "./RunForm.module.css";
import { Tooltip } from "./Tooltip";

interface Props {
  onRunCreated: (runId: string) => void;
  onViewArchives?: () => void;
}

const SWING_ANALYSTS = ["market", "social", "news", "fundamentals"];
const DAYTRADE_ANALYSTS = ["intraday_market", "news"];
const ANALYST_LABELS: Record<string, string> = {
  market: "Market",
  intraday_market: "Intraday market",
  social: "Social / sentiment",
  news: "News",
  fundamentals: "Fundamentals",
};
const INTRADAY_INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"];
const FALLBACK_MODEL_CATALOG: ModelCatalog = {
  providers: {
    openai: {
      custom: false,
      deep: [{ label: "GPT-5.4 - Latest frontier, 1M context", value: "gpt-5.4" }],
      quick: [{ label: "GPT-5.4 Mini - Fast, strong coding and tool use", value: "gpt-5.4-mini" }],
    },
    anthropic: {
      custom: false,
      deep: [{ label: "Claude Opus 4.6 - Most intelligent", value: "claude-opus-4-6" }],
      quick: [{ label: "Claude Sonnet 4.6 - Balanced speed and intelligence", value: "claude-sonnet-4-6" }],
    },
    google: {
      custom: false,
      deep: [{ label: "Gemini 3.1 Pro - Reasoning-first", value: "gemini-3.1-pro-preview" }],
      quick: [{ label: "Gemini 3 Flash - Next-gen fast", value: "gemini-3-flash-preview" }],
    },
    azure: { custom: true, deep: [], quick: [] },
    xai: {
      custom: false,
      deep: [{ label: "Grok 4 - Flagship model", value: "grok-4-0709" }],
      quick: [{ label: "Grok 4.1 Fast - Speed optimized", value: "grok-4-1-fast-non-reasoning" }],
    },
    deepseek: {
      custom: false,
      deep: [{ label: "DeepSeek V3.2 (thinking)", value: "deepseek-reasoner" }],
      quick: [{ label: "DeepSeek V3.2", value: "deepseek-chat" }],
    },
    qwen: {
      custom: false,
      deep: [{ label: "Qwen 3.6 Plus", value: "qwen3.6-plus" }],
      quick: [{ label: "Qwen 3.5 Flash", value: "qwen3.5-flash" }],
    },
    glm: {
      custom: false,
      deep: [{ label: "GLM-5.1", value: "glm-5.1" }],
      quick: [{ label: "GLM-4.7", value: "glm-4.7" }],
    },
    ollama: {
      custom: false,
      deep: [{ label: "GLM-4.7-Flash:latest (30B, local)", value: "glm-4.7-flash:latest" }],
      quick: [{ label: "Qwen3:latest (8B, local)", value: "qwen3:latest" }],
    },
    openrouter: { custom: true, deep: [], quick: [] },
  },
};

const FIELD_TIPS: Record<string, string> = {
  ticker: "The stock symbol. For non-US exchanges, add a suffix — e.g., SHOP.TO (Toronto), VOD.L (London), 9984.T (Tokyo), 0005.HK (Hong Kong).",
  date: 'The date the analysis is run “as of.” Agents only see data available up to end of this day — useful for backtests.',
  mode_llm: "The model reads the full debate and picks the final rating. More nuanced, but results can vary between runs.",
  mode_quant: "A fixed rule — the quant signal — decides the rating. Same inputs always give the same output. Best for backtesting.",
  deep_model: "Used for slow, careful reasoning (researcher debates, risk review). Pick your most capable model here.",
  quick_model: "Used for fast, simple tasks (extracting the final rating, summarizing). A cheaper model is fine.",
};

function formatError(raw: string): string {
  const msg = raw.replace(/^Error:\s*/, "");
  if (/ticker/i.test(msg) || /symbol/i.test(msg))
    return `Can't find that ticker. Double-check the symbol. For non-US stocks, include the exchange — e.g., SHOP.TO (Toronto), VOD.L (London), 9984.T (Tokyo).`;
  if (/api key/i.test(msg) || /authentication/i.test(msg))
    return "API key missing or invalid. Add it in Settings → Providers, then run again.";
  if (/rate limit/i.test(msg))
    return "Hit a rate limit. Wait about 60 seconds, or switch providers in Settings → Providers.";
  if (/future date/i.test(msg))
    return "Analysis date must be today or earlier. Markets haven't closed yet for the date you picked.";
  if (/timeout/i.test(msg))
    return 'The model took too long. Try a lighter "quick think" model in Advanced settings, or reduce debate rounds.';
  return msg;
}

export function RunForm({ onRunCreated, onViewArchives }: Props) {
  const today = new Date().toISOString().split("T")[0];
  const [ticker, setTicker] = useState("");
  const [date, setDate] = useState(today);
  const [tradingStyle, setTradingStyle] = useState<"swing" | "daytrade">("swing");
  const [analysts, setAnalysts] = useState<string[]>(SWING_ANALYSTS);
  const [intradayInterval, setIntradayInterval] = useState("5m");
  const [tradeDateTime, setTradeDateTime] = useState(`${today}T09:30`);
  const [provider, setProvider] = useState("openai");
  const [deepModel, setDeepModel] = useState("gpt-5.4");
  const [quickModel, setQuickModel] = useState("gpt-5.4-mini");
  const [modelCatalog, setModelCatalog] = useState<ModelCatalog>(FALLBACK_MODEL_CATALOG);
  const [mode, setMode] = useState("llm_assisted");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const providerOptions = modelCatalog.providers[provider] ?? FALLBACK_MODEL_CATALOG.providers.openai;
  const providers = Object.keys(modelCatalog.providers);

  useEffect(() => {
    let cancelled = false;

    const loadModels = async () => {
      try {
        const resp = await fetch("/api/models");
        if (!resp.ok) return;
        const catalog: ModelCatalog = await resp.json();
        if (cancelled || !catalog.providers || Object.keys(catalog.providers).length === 0) return;
        setModelCatalog(catalog);

        const nextProvider = catalog.providers.openai ? "openai" : Object.keys(catalog.providers)[0];
        const options = catalog.providers[nextProvider];
        setProvider(nextProvider);
        if (!options.custom) {
          setDeepModel(options.deep[0]?.value ?? "");
          setQuickModel(options.quick[0]?.value ?? "");
        }
      } catch {
        // Keep static fallback options when the catalog endpoint is unavailable.
      }
    };

    loadModels();

    return () => {
      cancelled = true;
    };
  }, []);

  const toggleAnalyst = (a: string) => {
    setAnalysts((prev) =>
      prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]
    );
  };

  const changeTradingStyle = (nextStyle: "swing" | "daytrade") => {
    setTradingStyle(nextStyle);
    if (nextStyle === "daytrade") {
      setAnalysts(DAYTRADE_ANALYSTS);
      setMode("llm_assisted");
      setTradeDateTime(`${date}T09:30`);
    } else {
      setAnalysts(SWING_ANALYSTS);
    }
  };

  const changeProvider = (nextProvider: string) => {
    setProvider(nextProvider);
    const options = modelCatalog.providers[nextProvider];
    if (!options) return;
    if (options.custom) {
      setDeepModel("");
      setQuickModel("");
      return;
    }
    setDeepModel(options.deep[0]?.value ?? "");
    setQuickModel(options.quick[0]?.value ?? "");
  };

  const ctaLabel = submitting
    ? "Starting…"
    : ticker.trim()
    ? `Analyze ${ticker.trim().toUpperCase()}`
    : "Run analysis";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const resp = await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.trim().toUpperCase(),
          analysis_date: date,
          selected_analysts: analysts,
          execution_mode: mode,
          llm_provider: provider,
          deep_think_llm: deepModel,
          quick_think_llm: quickModel,
          trading_style: tradingStyle,
          intraday_interval: tradingStyle === "daytrade" ? intradayInterval : undefined,
          trade_datetime: tradingStyle === "daytrade" ? tradeDateTime : undefined,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json();
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      const { run_id } = await resp.json();
      onRunCreated(run_id);
    } catch (err) {
      setError(formatError(String(err)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        {onViewArchives && (
          <div className={styles.topActions}>
            <button type="button" className={styles.archiveLink} onClick={onViewArchives}>
              Report archives
            </button>
          </div>
        )}
        <div className={styles.intro}>
          <h1 className={styles.heading}>Ready to analyze.</h1>
          <p className={styles.subheading}>
            Enter a ticker and a date to get started. Five analyst teams will research
            fundamentals, news, sentiment, and price action, then debate a recommendation.
          </p>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          {error && (
            <div className={styles.errorBanner} role="alert">
              {error}
            </div>
          )}

          <div className={styles.row}>
            <div className={styles.field}>
              <label className={styles.label}>
                Ticker <Tooltip text={FIELD_TIPS.ticker} />
              </label>
              <input
                className={styles.input}
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="AAPL, SHOP.TO, 9984.T…"
                autoFocus
                required
              />
            </div>

            <div className={styles.field}>
              <label className={styles.label}>
                As-of date <Tooltip text={FIELD_TIPS.date} />
              </label>
              <input
                className={styles.input}
                type="date"
                value={date}
                onChange={(e) => {
                  setDate(e.target.value);
                  if (tradingStyle === "daytrade") {
                    setTradeDateTime(`${e.target.value}T09:30`);
                  }
                }}
                required
              />
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Trading style</label>
            <div className={styles.segmented}>
              <button
                type="button"
                className={tradingStyle === "swing" ? styles.segmentActive : styles.segment}
                onClick={() => changeTradingStyle("swing")}
              >
                Swing
              </button>
              <button
                type="button"
                className={tradingStyle === "daytrade" ? styles.segmentActive : styles.segment}
                onClick={() => changeTradingStyle("daytrade")}
              >
                Daytrade
              </button>
            </div>
          </div>

          {tradingStyle === "daytrade" && (
            <div className={styles.row}>
              <div className={styles.field}>
                <label className={styles.label} htmlFor="intraday-interval">
                  Intraday interval
                </label>
                <select
                  id="intraday-interval"
                  className={styles.input}
                  value={intradayInterval}
                  onChange={(e) => setIntradayInterval(e.target.value)}
                >
                  {INTRADAY_INTERVALS.map((interval) => (
                    <option key={interval} value={interval}>{interval}</option>
                  ))}
                </select>
              </div>
              <div className={styles.field}>
                <label className={styles.label} htmlFor="trade-datetime">
                  Trade datetime
                </label>
                <input
                  id="trade-datetime"
                  className={styles.input}
                  type="datetime-local"
                  value={tradeDateTime}
                  onChange={(e) => setTradeDateTime(e.target.value)}
                  required
                />
              </div>
            </div>
          )}

          <div className={styles.field}>
            <label className={styles.label}>Analyst teams</label>
            <div className={styles.checkboxRow}>
              {(tradingStyle === "daytrade" ? DAYTRADE_ANALYSTS : SWING_ANALYSTS).map((a) => (
                <label key={a} className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    checked={analysts.includes(a)}
                    onChange={() => toggleAnalyst(a)}
                  />
                  {ANALYST_LABELS[a]}
                </label>
              ))}
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>
              Execution mode{" "}
              <Tooltip text={mode === "llm_assisted" ? FIELD_TIPS.mode_llm : FIELD_TIPS.mode_quant} />
            </label>
            <div className={styles.segmented}>
              <button
                type="button"
                className={mode === "llm_assisted" ? styles.segmentActive : styles.segment}
                onClick={() => setMode("llm_assisted")}
              >
                LLM-assisted
              </button>
              <button
                type="button"
                className={mode === "quant_strict" ? styles.segmentActive : styles.segment}
                onClick={() => setMode("quant_strict")}
              >
                Quant-strict
              </button>
            </div>
          </div>

          <button
            type="button"
            className={styles.advancedToggle}
            onClick={() => setShowAdvanced((v) => !v)}
          >
            {showAdvanced ? "▾" : "▸"} Advanced settings
          </button>

          {showAdvanced && (
            <div className={styles.advanced}>
              <div className={styles.row}>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="provider">
                    Provider
                  </label>
                  <select
                    id="provider"
                    className={styles.input}
                    value={provider}
                    onChange={(e) => changeProvider(e.target.value)}
                  >
                    {providers.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
              </div>
              <div className={styles.row}>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="deep-model">
                    Deep-think model <Tooltip text={FIELD_TIPS.deep_model} />
                  </label>
                  {providerOptions.custom ? (
                    <input
                      id="deep-model"
                      className={styles.input}
                      value={deepModel}
                      onChange={(e) => setDeepModel(e.target.value)}
                      placeholder="Deployment or model ID"
                    />
                  ) : (
                    <select
                      id="deep-model"
                      className={styles.input}
                      value={deepModel}
                      onChange={(e) => setDeepModel(e.target.value)}
                    >
                      {providerOptions.deep.map((m) => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                      ))}
                    </select>
                  )}
                </div>
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="quick-model">
                    Quick model <Tooltip text={FIELD_TIPS.quick_model} />
                  </label>
                  {providerOptions.custom ? (
                    <input
                      id="quick-model"
                      className={styles.input}
                      value={quickModel}
                      onChange={(e) => setQuickModel(e.target.value)}
                      placeholder="Deployment or model ID"
                    />
                  ) : (
                    <select
                      id="quick-model"
                      className={styles.input}
                      value={quickModel}
                      onChange={(e) => setQuickModel(e.target.value)}
                    >
                      {providerOptions.quick.map((m) => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                      ))}
                    </select>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className={styles.actions}>
            <button
              type="submit"
              className={styles.primaryBtn}
              disabled={submitting || analysts.length === 0 || !deepModel.trim() || !quickModel.trim()}
            >
              {ctaLabel}
            </button>
            <p className={styles.timeEstimate}>
              Usually 2–4 minutes depending on the models you picked.
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
