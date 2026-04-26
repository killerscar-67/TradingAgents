import { useEffect, useState } from "react";
import { apiUrl } from "../apiBase";
import type { AppSettings } from "../types";

// Backend stores settings nested; frontend uses a flat shape.
// Handles both nested backend format and flat legacy/test format.
function flattenSettings(raw: Record<string, unknown>): AppSettings {
  const wd = (raw.workflow_defaults ?? {}) as Record<string, unknown>;
  const broker = (raw.broker ?? {}) as Record<string, unknown>;
  const futu = (broker.futu ?? {}) as Record<string, unknown>;

  // Prefer nested keys, fall back to flat keys (legacy / test stubs).
  const topN = wd.top_n !== undefined ? Number(wd.top_n) : Number(raw.top_n ?? 20);
  const scoreFloor = wd.min_score !== undefined ? Number(wd.min_score) : Number(raw.score_floor ?? 0.65);
  // Backend decimal (0.01) → %; flat stubs already send percentage integers.
  const rawRisk = wd.risk_per_trade !== undefined
    ? Number(wd.risk_per_trade) * 100
    : Number(raw.risk_per_trade_pct ?? 1);
  const portfolioSize = wd.portfolio_size !== undefined
    ? Number(wd.portfolio_size)
    : Number(raw.portfolio_size ?? 100_000);
  const allowShorts = wd.allow_shorts !== undefined
    ? Boolean(wd.allow_shorts)
    : Boolean(raw.allow_shorts ?? true);
  const futuHost = futu.host !== undefined ? String(futu.host) : String(raw.futu_host ?? "127.0.0.1");
  const futuPort = futu.port !== undefined ? Number(futu.port) : Number(raw.futu_port ?? 11111);

  return {
    llm_provider: String(raw.llm_provider ?? ""),
    deep_think_llm: String(raw.deep_think_llm ?? ""),
    quick_think_llm: String(raw.quick_think_llm ?? ""),
    execution_mode: String(raw.execution_mode ?? "llm_assisted"),
    home_market: String(raw.home_market ?? "US"),
    max_debate_rounds: Number(raw.max_debate_rounds ?? 1),
    max_risk_discuss_rounds: Number(raw.max_risk_discuss_rounds ?? 1),
    output_language: String(raw.output_language ?? "English"),
    top_n: topN,
    score_floor: scoreFloor,
    risk_per_trade_pct: rawRisk,
    portfolio_size: portfolioSize,
    allow_shorts: allowShorts,
    futu_host: futuHost,
    futu_port: futuPort,
    status: String(raw.status ?? "ready"),
  };
}

function nestSettings(flat: Partial<AppSettings>): Record<string, unknown> {
  const nested: Record<string, unknown> = {};
  const topKeys = [
    "llm_provider", "deep_think_llm", "quick_think_llm",
    "execution_mode", "home_market", "max_debate_rounds",
    "max_risk_discuss_rounds", "output_language",
  ] as const;
  for (const key of topKeys) {
    if (flat[key] !== undefined) nested[key] = flat[key];
  }
  const wd: Record<string, unknown> = {};
  if (flat.top_n !== undefined) wd.top_n = flat.top_n;
  if (flat.score_floor !== undefined) wd.min_score = flat.score_floor;
  if (flat.risk_per_trade_pct !== undefined) wd.risk_per_trade = flat.risk_per_trade_pct / 100;
  if (flat.portfolio_size !== undefined) wd.portfolio_size = flat.portfolio_size;
  if (flat.allow_shorts !== undefined) wd.allow_shorts = flat.allow_shorts;
  if (Object.keys(wd).length > 0) nested.workflow_defaults = wd;

  const futu: Record<string, unknown> = {};
  if (flat.futu_host !== undefined) futu.host = flat.futu_host;
  if (flat.futu_port !== undefined) futu.port = flat.futu_port;
  if (Object.keys(futu).length > 0) nested.broker = { futu };

  return nested;
}

export function useSettings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchSettings = async () => {
      try {
        const resp = await fetch(apiUrl("/api/settings"));
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const raw: Record<string, unknown> = await resp.json();
        if (!cancelled) {
          setSettings(flattenSettings(raw));
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      }
    };
    fetchSettings();
    return () => { cancelled = true; };
  }, []);

  const updateSettings = async (patch: Partial<AppSettings>) => {
    setSaving(true);
    try {
      const values = nestSettings(patch);
      const resp = await fetch(apiUrl("/api/settings"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const updated: { status: string; values: Record<string, unknown> } = await resp.json();
      setSettings(flattenSettings({ ...updated.values, status: updated.status }));
      setError(null);
    } catch (e) {
      setError(String(e));
      throw e;
    } finally {
      setSaving(false);
    }
  };

  return { settings, loading, error, saving, updateSettings };
}
