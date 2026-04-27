import { useEffect, useRef, useState } from "react";
import { apiUrl, apiWsUrl } from "../apiBase";
import type { MarketOverview } from "../types";

interface MarketLiveMessage {
  type?: string;
  payload?: MarketOverview;
}

export function useMarketOverview() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connectTimer: ReturnType<typeof setTimeout> | null = null;

    const fetchOverview = async () => {
      try {
        const resp = await fetch(apiUrl("/api/market/overview"));
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data: MarketOverview = await resp.json();
        if (!cancelled) {
          setError(null);
          setOverview(data);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      }
    };

    const connectWs = () => {
      const ws = new WebSocket(apiWsUrl("/api/market/live"));
      wsRef.current = ws;

      ws.onopen = () => { if (!cancelled) setLive(true); };

      ws.onmessage = (e) => {
        if (cancelled) return;
        try {
          const message: MarketLiveMessage = JSON.parse(e.data);
          if (message.type === "market_snapshot" && message.payload) {
            setError(null);
            setOverview(message.payload);
            return;
          }
          const patch = message as Partial<MarketOverview>;
          setError(null);
          setOverview((prev) => (prev ? { ...prev, ...patch } : prev));
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          setLive(false);
          // reconnect after 5 seconds
          reconnectTimer = setTimeout(connectWs, 5000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    void fetchOverview().then(() => {
      if (!cancelled) {
        connectTimer = setTimeout(connectWs, 0);
      }
    });

    return () => {
      cancelled = true;
      if (connectTimer) clearTimeout(connectTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, []);

  return { overview, loading, error, live };
}
