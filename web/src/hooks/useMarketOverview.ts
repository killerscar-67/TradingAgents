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
const WS_RECONNECT_BASE_DELAY_MS = 5_000;
const WS_RECONNECT_MAX_DELAY_MS = 60_000;
const overviewCache = new Map<string, CachedOverviewEntry>();

function reconnectDelayMs(attempt: number): number {
  return Math.min(WS_RECONNECT_BASE_DELAY_MS * (2 ** Math.max(attempt - 1, 0)), WS_RECONNECT_MAX_DELAY_MS);
}

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
    let reconnectAttempt = 0;
    const cacheKey = homeMarket.toUpperCase();
    const abortController = new AbortController();

    const scheduleReconnect = () => {
      if (cancelled || reconnectTimer) {
        return;
      }
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        return;
      }
      reconnectAttempt += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWs();
      }, reconnectDelayMs(reconnectAttempt));
    };

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

      ws.onopen = () => {
        reconnectAttempt = 0;
        if (!cancelled) {
          setLive(true);
        }
      };

      ws.onmessage = (e) => {
        if (cancelled) return;
        try {
          const message: MarketLiveMessage = JSON.parse(e.data);
          if (message.type === "market_snapshot" && message.payload) {
            overviewCache.set(cacheKey, { payload: message.payload, fetchedAt: Date.now() });
            setError(null);
            setOverview(message.payload);
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null;
        }
        if (!cancelled) {
          setLive(false);
          scheduleReconnect();
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    const handleVisibilityChange = () => {
      if (cancelled || typeof document === "undefined") {
        return;
      }
      if (document.visibilityState === "hidden" && reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
        return;
      }
      if (document.visibilityState === "visible" && !wsRef.current && !reconnectTimer) {
        connectWs();
      }
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibilityChange);
    }

    void fetchOverview().then(() => {
      if (!cancelled) {
        connectTimer = setTimeout(connectWs, 0);
      }
    });

    return () => {
      cancelled = true;
      abortController.abort();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibilityChange);
      }
      if (connectTimer) clearTimeout(connectTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [homeMarket]);

  return { overview, loading, error, live };
}
