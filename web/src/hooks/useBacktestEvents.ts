import { useEffect, useState } from "react";
import { apiUrl } from "../apiBase";

export interface BacktestEvent {
  type: string;
  backtest_id: string;
  symbol?: string;
  status?: string;
  trade_count?: number;
  execution_mode?: string;
  progress?: number;
  message?: string;
  sequence?: number;
  timestamp: number;
}

export function useBacktestEvents(backtestId: string | null) {
  const [events, setEvents] = useState<BacktestEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!backtestId) {
      setEvents([]);
      setConnected(false);
      setDone(false);
      return;
    }

    setEvents([]);
    setDone(false);

    const es = new EventSource(apiUrl(`/api/backtests/${backtestId}/events`));

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const event: BacktestEvent = JSON.parse(e.data);
        setEvents((prev) => [...prev, event]);
        if (
          event.type === "backtest_status"
          && ["completed", "error", "not_found"].includes(event.status ?? "")
        ) {
          setDone(true);
          es.close();
          setConnected(false);
        }
      } catch {
        // ignore malformed events
      }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [backtestId]);

  return { events, connected, done };
}
