import { useEffect, useState } from "react";
import { apiUrl } from "../apiBase";

export interface BatchEvent {
  type: string;
  batch_id?: string;
  symbol?: string;
  run_id?: string;
  status?: string;
  rating?: string;
  error?: string;
  phase?: string;
  counts?: Record<string, number>;
  sequence?: number;
  timestamp?: number | string;
}

export function useBatchEvents(batchId: string | null, restartKey = 0) {
  const [events, setEvents] = useState<BatchEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!batchId) {
      setEvents([]);
      setConnected(false);
      setDone(false);
      return;
    }

    setEvents([]);
    setDone(false);

    const es = new EventSource(apiUrl(`/api/batches/${batchId}/events`));

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const event: BatchEvent = JSON.parse(e.data);
        setEvents((prev) => [...prev, event]);
        if (
          event.type === "batch_status"
          && ["completed", "error", "partial_failure", "not_found"].includes(event.status ?? "")
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
  }, [batchId, restartKey]);

  return { events, connected, done };
}
