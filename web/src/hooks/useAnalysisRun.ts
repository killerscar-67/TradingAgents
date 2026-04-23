import { useEffect, useRef, useState } from "react";
import type { AnalysisRun } from "../types";

export function useAnalysisRun(runId: string | null) {
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!runId) return;

    const fetchRun = async () => {
      try {
        const resp = await fetch(`/api/analysis/${runId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data: AnalysisRun = await resp.json();
        setRun(data);
        if (data.status === "completed" || data.status === "error") {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch (e) {
        setError(String(e));
      }
    };

    fetchRun();
    intervalRef.current = setInterval(fetchRun, 2000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [runId]);

  return { run, error };
}
