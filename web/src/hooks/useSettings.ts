import { useEffect, useState } from "react";
import type { AppSettings } from "../types";

interface SettingsUpdateResponse {
  status: string;
  values: Omit<AppSettings, "status">;
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
        const resp = await fetch("/api/settings");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data: AppSettings = await resp.json();
        if (!cancelled) {
          setSettings(data);
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
      const values = { ...patch };
      delete values.status;
      const resp = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const updated: SettingsUpdateResponse = await resp.json();
      setSettings({ ...updated.values, status: updated.status });
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
