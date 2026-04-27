import { useEffect, useRef, useState } from "react";
import { apiUrl, apiWsUrl } from "../apiBase";
import type { MarketOverview } from "../types";

interface MarketLiveMessage {
  type?: string;
  payload?: MarketOverview;
}

interface CachedOverviewEntry {
  fetchedAt: number;
  payload: MarketOverview;
}

const OVERVIEW_CACHE_TTL_MS = 30_000;
const overviewCache = new Map<string, CachedOverviewEntry>();

export function __resetMarketOverviewCache(): void {
  overviewCache.clear();
}

export function useMarketOverview(homeMarket = "US") {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connectTimer: ReturnType<typeof setTimeout> | null = null;
    const cacheKey = homeMarket.toUpperCase();
    const abortController = new AbortController();

    const fetchOverview = async () => {
      const cached = overviewCache.get(cacheKey);
      if (cached && (Date.now() - cached.fetchedAt) < OVERVIEW_CACHE_TTL_MS) {
        if (!cancelled) {
          setOverview(cached.payload);
          setError(null);
          setLoading(false);
        }
        return;
      }

      try {
        const resp = await fetch(apiUrl(`/api/market/overview?home_market=${encodeURIComponent(cacheKey)}`), {
          signal: abortController.signal,
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data: MarketOverview = await resp.json();
        overviewCache.set(cacheKey, { payload: data, fetchedAt: Date.now() });
        if (!cancelled) {
          setError(null);
          setOverview(data);
          setLoading(false);
        }
      } catch (e) {
        if (abortController.signal.aborted) {
          return;
        }
        if (!cancelled) {
          setError(String(e));
          setLoading(false);
        }
      }
    };

    const connectWs = () => {
      const ws = new WebSocket(apiWsUrl(`/api/market/live?home_market=${encodeURIComponent(cacheKey)}`));
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
      abortController.abort();
      if (connectTimer) clearTimeout(connectTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [homeMarket]);

  return { overview, loading, error, live };
}
