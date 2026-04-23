import { useEffect, useRef, useState } from "react";
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

    const fetchOverview = async () => {
      try {
        const resp = await fetch("/api/market/overview");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data: MarketOverview = await resp.json();
        if (!cancelled) {
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

    fetchOverview();

    const connectWs = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/market/live`);
      wsRef.current = ws;

      ws.onopen = () => { if (!cancelled) setLive(true); };

      ws.onmessage = (e) => {
        if (cancelled) return;
        try {
          const message: MarketLiveMessage = JSON.parse(e.data);
          if (message.type === "market_snapshot" && message.payload) {
            setOverview(message.payload);
            return;
          }
          const patch = message as Partial<MarketOverview>;
          setOverview((prev) => (prev ? { ...prev, ...patch } : prev));
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          setLive(false);
          // reconnect after 5 seconds
          setTimeout(connectWs, 5000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connectWs();

    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, []);

  return { overview, loading, error, live };
}
