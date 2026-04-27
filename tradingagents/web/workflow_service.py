"""Deterministic Phase 11 workflow services."""

from __future__ import annotations

import os
import json
import logging
import threading
import calendar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import yfinance as yf
import yfinance.utils as yf_utils

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.interface import get_intraday_bars
from tradingagents.quant.backtest import run_backtest, run_trade_plan_backtest
from tradingagents.quant.contracts import EntryEngine, EntrySignal
from tradingagents.quant.risk import compute_stops, size_position
from tradingagents.quant.walkforward import run_walk_forward
from tradingagents.web import runner


_cancelled_batches: set = set()
_cancelled_lock = threading.Lock()
_thread_cls = threading.Thread  # test-injectable; patching threading.Thread globally breaks anyio
_batch_state_locks: Dict[str, threading.Lock] = {}
_batch_state_locks_lock = threading.Lock()
_LOGGER = logging.getLogger(__name__)
_calendar_response_cache: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
_calendar_rate_limit_cooldowns: Dict[Tuple[str, str, str, str, str], float] = {}
_calendar_response_cache_lock = threading.Lock()
_CALENDAR_CACHE_TTL_SECONDS = 900.0
_CALENDAR_EMPTY_CACHE_TTL_SECONDS = 60.0
_CALENDAR_RATE_LIMIT_COOLDOWN_SECONDS = 600.0
_calendar_cache_disk_loaded = False


class CalendarProviderCooldownError(RuntimeError):
    def __init__(self, provider_name: str, retry_after_seconds: float):
        self.provider_name = provider_name
        self.retry_after_seconds = max(int(retry_after_seconds), 1)
        super().__init__(
            f"{provider_name} rate-limited; cooling down for {self.retry_after_seconds}s before the next refresh attempt"
        )


def cancel_batch(batch_id: str) -> None:
    with _cancelled_lock:
        _cancelled_batches.add(batch_id)


def resume_batch(batch_id: str) -> None:
    with _cancelled_lock:
        _cancelled_batches.discard(batch_id)


def _is_cancelled(batch_id: str) -> bool:
    with _cancelled_lock:
        return batch_id in _cancelled_batches


def _get_batch_state_lock(batch_id: str) -> threading.Lock:
    with _batch_state_locks_lock:
        lock = _batch_state_locks.get(batch_id)
        if lock is None:
            lock = threading.Lock()
            _batch_state_locks[batch_id] = lock
        return lock


def _batch_worker_limit(payload: Dict[str, Any], settings: Dict[str, Any], item_count: int) -> int:
    raw_value = (
        payload.get("max_concurrent")
        or settings.get("batch_max_concurrency")
        or os.getenv("TRADINGAGENTS_BATCH_MAX_CONCURRENCY")
        or 2
    )
    try:
        requested = int(raw_value)
    except (TypeError, ValueError):
        requested = 2
    return max(1, min(requested, max(item_count, 1)))


def _thread_is_alive(thread: Any) -> bool:
    checker = getattr(thread, "is_alive", None)
    if callable(checker):
        return bool(checker())
    return False


def _join_thread(thread: Any, timeout: Optional[float] = None) -> None:
    joiner = getattr(thread, "join", None)
    if callable(joiner):
        if timeout is None:
            joiner()
        else:
            joiner(timeout)


def _reap_finished_threads(threads: List[Any]) -> List[Any]:
    active: List[Any] = []
    for thread in threads:
        if _thread_is_alive(thread):
            active.append(thread)
        else:
            _join_thread(thread)
    return active


MARKET_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "US": {
        "tiles": [
            {"symbol": "^GSPC", "label": "S&P 500", "role": "broad"},
            {"symbol": "^NDX", "label": "NASDAQ 100", "role": "growth"},
            {"symbol": "^RUT", "label": "Russell 2000", "role": "second_tier"},
            {"symbol": "^VIX", "label": "VIX", "role": "volatility"},
        ],
        "vol_symbol": "^VIX",
        "credit_symbols": ("HYG", "IEF"),
        "sector_proxies": [
            ("XLK", "Technology"),
            ("XLE", "Energy"),
            ("XLF", "Financials"),
            ("XLV", "Healthcare"),
            ("XLP", "Staples"),
        ],
        "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "JPM", "XOM", "UNH", "COST"],
    },
    "HK": {
        "tiles": [
            {"symbol": "^HSI", "label": "Hang Seng", "role": "broad"},
            {"symbol": "3033.HK", "label": "HS Tech", "role": "growth"},
            {"symbol": "^HSCE", "label": "HSCEI", "role": "second_tier"},
            {"symbol": "^VHSI", "label": "VHSI", "role": "volatility"},
        ],
        "vol_symbol": "^VHSI",
        "credit_symbols": None,
        "sector_proxies": [
            ("0700.HK", "Technology"),
            ("2318.HK", "Financials"),
            ("1299.HK", "Insurance"),
            ("0005.HK", "Banks"),
            ("0388.HK", "Exchange"),
        ],
        "universe": ["0700.HK", "9988.HK", "1299.HK", "3690.HK", "1810.HK", "2318.HK", "0388.HK", "0005.HK", "0762.HK", "1211.HK"],
    },
    "JP": {
        "tiles": [
            {"symbol": "^N225", "label": "Nikkei 225", "role": "broad"},
            {"symbol": "1306.T", "label": "TOPIX", "role": "growth"},
            {"symbol": "2516.T", "label": "TSE Growth", "role": "second_tier"},
        ],
        "vol_symbol": None,
        "credit_symbols": None,
        "sector_proxies": [
            ("7203.T", "Autos"),
            ("8035.T", "Semis"),
            ("6758.T", "Consumer Tech"),
            ("9432.T", "Telecom"),
            ("8306.T", "Banks"),
        ],
        "universe": ["7203.T", "6758.T", "9984.T", "9432.T", "8306.T", "7974.T", "6861.T", "8001.T", "8035.T", "6954.T"],
    },
}

UNIVERSE_ALIASES = {
    "s&p 500": ("US", MARKET_DEFINITIONS["US"]["universe"]),
    "sp500": ("US", MARKET_DEFINITIONS["US"]["universe"]),
    "hsi": ("HK", MARKET_DEFINITIONS["HK"]["universe"]),
    "hang seng": ("HK", MARKET_DEFINITIONS["HK"]["universe"]),
    "nikkei 225": ("JP", MARKET_DEFINITIONS["JP"]["universe"]),
}

YFINANCE_UNAVAILABLE_SYMBOLS = {"^VHSI"}
DEFAULT_CHART_INTERVAL = "1D"
MAX_CHART_LIMIT = 400
CHART_INTERVAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "15m": {
        "kind": "intraday",
        "fetch_interval": "15m",
        "default_limit": 104,
        "lookback_days": 20,
        "session": "regular",
    },
    "4h": {
        "kind": "intraday",
        "fetch_interval": "4h",
        "default_limit": 90,
        "lookback_days": 260,
        "session": "regular",
    },
    "1D": {
        "kind": "daily",
        "default_limit": 160,
        "lookback_days": 420,
    },
    "1W": {
        "kind": "daily",
        "default_limit": 104,
        "lookback_days": 1600,
        "resample_rule": "W-FRI",
    },
    "1M": {
        "kind": "daily",
        "default_limit": 72,
        "lookback_days": 3200,
        "resample_rule": "ME",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_breadth() -> Dict[str, Any]:
    return {
        "pct_above_50d": 0.0,
        "pct_above_200d": 0.0,
        "new_highs_minus_lows": 0,
        "advance_decline_ratio": 0.0,
        "mcclellan_oscillator": 0.0,
        "headline": "Breadth unavailable",
    }


def _neutral_regime() -> Dict[str, Any]:
    return {
        "label": "Choppy / range-bound",
        "confidence": 0,
        "suggested_entry_mode": "auto",
        "event_risk_flag": False,
        "inputs": {},
    }


def _json_safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _history_series(history: pd.DataFrame, field: str) -> pd.Series:
    """Return a numeric OHLCV field from flat or yfinance multi-index columns."""
    if history.empty:
        return pd.Series(dtype=float)

    data: Any
    if isinstance(history.columns, pd.MultiIndex):
        data = None
        for level in range(history.columns.nlevels):
            if field in history.columns.get_level_values(level):
                data = history.xs(field, axis=1, level=level)
                break
        if data is None:
            return pd.Series(dtype=float)
    elif field in history:
        data = history[field]
    else:
        return pd.Series(dtype=float)

    if isinstance(data, pd.DataFrame):
        if data.empty or data.shape[1] == 0:
            return pd.Series(dtype=float)
        data = data.iloc[:, 0]
    return pd.to_numeric(data, errors="coerce").dropna()


def _market_for_symbol(symbol: str, default_market: str = "US") -> str:
    upper = symbol.upper()
    if upper.endswith(".HK"):
        return "HK"
    if upper.endswith(".T"):
        return "JP"
    return default_market


def _resolve_screening_market(universe: str, home_market: str) -> str:
    key = (universe or "").strip().lower()
    market_code = (universe or "").strip().upper()
    if market_code in MARKET_DEFINITIONS:
        return market_code
    if key in UNIVERSE_ALIASES:
        market, _ = UNIVERSE_ALIASES[key]
        return market
    fallback = home_market.upper()
    return fallback if fallback in MARKET_DEFINITIONS else "US"


def _resolve_screening_universe(universe: str, custom_symbols: List[str], home_market: str) -> Tuple[str, List[str]]:
    if custom_symbols:
        return "CUSTOM", [symbol.strip().upper() for symbol in custom_symbols if symbol.strip()]
    key = (universe or "").strip().lower()
    market_code = (universe or "").strip().upper()
    if key in UNIVERSE_ALIASES:
        _, symbols = UNIVERSE_ALIASES[key]
        return universe, list(symbols)
    if market_code in MARKET_DEFINITIONS:
        return market_code, list(MARKET_DEFINITIONS[market_code]["universe"])
    market = home_market.upper() if home_market.upper() in MARKET_DEFINITIONS else "US"
    return universe or market, list(MARKET_DEFINITIONS[market]["universe"])


def _normalize_chart_interval(interval: Optional[str]) -> str:
    value = (interval or DEFAULT_CHART_INTERVAL).strip()
    aliases = {
        "15m": "15m",
        "4h": "4h",
        "1d": "1D",
        "1D": "1D",
        "1w": "1W",
        "1W": "1W",
        "1m": "1M",
        "1M": "1M",
    }
    normalized = aliases.get(value, aliases.get(value.lower()))
    if normalized is None:
        raise ValueError(f"interval must be one of {sorted(CHART_INTERVAL_CONFIG)!r}")
    return normalized


def _coerce_chart_limit(interval: str, limit: Optional[int]) -> int:
    default = int(CHART_INTERVAL_CONFIG[interval]["default_limit"])
    if limit is None:
        return default
    try:
        resolved = int(limit)
    except (TypeError, ValueError):
        return default
    return max(10, min(MAX_CHART_LIMIT, resolved))


def _chart_anchor_dt(trade_date: Optional[str], before: Optional[int]) -> datetime:
    if before is not None:
        return datetime.fromtimestamp(int(before), tz=timezone.utc).replace(tzinfo=None)
    raw_date = trade_date or date.today().isoformat()
    try:
        return datetime.fromisoformat(raw_date).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError(f"Invalid trade_date {raw_date!r}; expected ISO date format YYYY-MM-DD") from exc


def _normalize_time_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = frame.copy()
    index = pd.to_datetime(normalized.index)
    tz = getattr(index, "tz", None)
    if tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    normalized.index = index
    return normalized.sort_index()


def _history_to_ohlc_frame(history: pd.DataFrame) -> pd.DataFrame:
    frame = pd.concat(
        [
            _history_series(history, "Open").rename("open"),
            _history_series(history, "High").rename("high"),
            _history_series(history, "Low").rename("low"),
            _history_series(history, "Close").rename("close"),
        ],
        axis=1,
    ).dropna(subset=["open", "high", "low", "close"])
    return _normalize_time_index(frame)


def _download_yfinance_daily(tickers: str | List[str], start: str, end: str, *, threads: bool) -> pd.DataFrame:
    logger = yf_utils.get_yf_logger()
    previous_level = logger.level
    try:
        # yfinance logs transient partial-batch misses as "possibly delisted" before callers can retry.
        logger.setLevel(logging.CRITICAL + 1)
        downloaded = yf.download(
            tickers,
            start=start,
            end=end,
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=threads,
            timeout=10,
        )
    finally:
        logger.setLevel(previous_level)
    return downloaded if isinstance(downloaded, pd.DataFrame) else pd.DataFrame()


def _extract_symbol_history(downloaded: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if downloaded.empty:
        return pd.DataFrame()
    if isinstance(downloaded.columns, pd.MultiIndex):
        if symbol in downloaded.columns.get_level_values(0):
            frame = downloaded.xs(symbol, axis=1, level=0, drop_level=True)
        elif symbol in downloaded.columns.get_level_values(downloaded.columns.nlevels - 1):
            frame = downloaded.xs(symbol, axis=1, level=downloaded.columns.nlevels - 1, drop_level=True)
        else:
            return pd.DataFrame()
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    return downloaded


def _has_close_history(history: pd.DataFrame) -> bool:
    return not _history_series(history, "Close").empty


def _resample_ohlc_frame(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    resampled = frame.resample(rule, closed="right", label="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
    )
    return resampled.dropna(subset=["open", "high", "low", "close"])


def _serialize_chart_payload(
    symbol: str,
    interval: str,
    limit: int,
    frame: pd.DataFrame,
) -> Dict[str, Any]:
    bars: List[Dict[str, Any]] = []
    points: List[Dict[str, Any]] = []
    for timestamp, row in frame.iterrows():
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        unix_time = int(ts.timestamp())
        close = round(float(row["close"]), 4)
        points.append({"time": unix_time, "value": close})
        bars.append(
            {
                "time": unix_time,
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": close,
            }
        )

    oldest_time = bars[0]["time"] if bars else None
    newest_time = bars[-1]["time"] if bars else None
    return {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
        "has_more": False,
        "oldest_time": oldest_time,
        "newest_time": newest_time,
        "points": points,
        "bars": bars,
    }


def _download_daily_history(symbols: Iterable[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    ordered_symbols = list(dict.fromkeys(symbols))
    result: Dict[str, pd.DataFrame] = {}
    active_symbols: List[str] = []
    for symbol in ordered_symbols:
        if symbol in YFINANCE_UNAVAILABLE_SYMBOLS:
            result[symbol] = pd.DataFrame()
        else:
            active_symbols.append(symbol)

    if not active_symbols:
        return result

    downloaded = _download_yfinance_daily(
        active_symbols[0] if len(active_symbols) == 1 else active_symbols,
        start,
        end,
        threads=True,
    )
    for symbol in active_symbols:
        result[symbol] = _extract_symbol_history(downloaded, symbol) if len(active_symbols) > 1 else downloaded

    missing_symbols = [symbol for symbol in active_symbols if not _has_close_history(result.get(symbol, pd.DataFrame()))]
    for symbol in missing_symbols:
        retry_frame = _download_yfinance_daily(symbol, start, end, threads=False)
        if _has_close_history(retry_frame):
            result[symbol] = retry_frame
    return result


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _compute_adx(history: pd.DataFrame, period: int = 14) -> float:
    if history.empty or len(history) < period + 2:
        return 0.0
    high = _history_series(history, "High")
    low = _history_series(history, "Low")
    close = _history_series(history, "Close")
    if len(high) < period + 2 or len(low) < period + 2 or len(close) < period + 2:
        return 0.0
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr = _true_range(high, low, close).ewm(alpha=1 / period, adjust=False).mean()
    safe_atr = atr.replace(0, float("nan"))
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / safe_atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / safe_atr
    denominator = (plus_di + minus_di).replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / denominator
    adx = dx.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return round(float(0.0 if pd.isna(adx) else adx), 4)


def _compute_breadth(universe_histories: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    pct_above_50 = 0
    pct_above_200 = 0
    advancers = 0
    decliners = 0
    new_highs = 0
    new_lows = 0
    breadth_series: List[float] = []
    valid = 0

    for history in universe_histories.values():
        if history.empty or len(history) < 40:
            continue
        close = _history_series(history, "Close")
        if len(close) < 2:
            continue
        valid += 1
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else close.rolling(min(50, len(close))).mean().iloc[-1]
        latest = float(close.iloc[-1])
        if latest > float(sma50):
            pct_above_50 += 1
        if latest > float(sma200):
            pct_above_200 += 1
        daily_change = float(close.iloc[-1] - close.iloc[-2])
        if daily_change > 0:
            advancers += 1
        elif daily_change < 0:
            decliners += 1
        window = close.iloc[-min(252, len(close)) :]
        if latest >= float(window.max()):
            new_highs += 1
        if latest <= float(window.min()):
            new_lows += 1

        returns = close.diff().fillna(0.0)
        breadth_series.append(1.0 if daily_change > 0 else -1.0 if daily_change < 0 else 0.0)
        breadth_series.extend(float(v) for v in returns.tail(20))

    if valid == 0:
        return _empty_breadth()

    breadth = pd.Series(breadth_series, dtype=float)
    ema19 = breadth.ewm(span=19, adjust=False).mean().iloc[-1] if not breadth.empty else 0.0
    ema39 = breadth.ewm(span=39, adjust=False).mean().iloc[-1] if not breadth.empty else 0.0
    pct50 = round(100.0 * pct_above_50 / valid, 2)
    pct200 = round(100.0 * pct_above_200 / valid, 2)
    ratio = round(advancers / max(decliners, 1), 4)
    headline = "Broad participation" if pct50 > 60 else "Narrow participation" if pct50 < 40 else "Mixed breadth"
    return {
        "pct_above_50d": pct50,
        "pct_above_200d": pct200,
        "new_highs_minus_lows": new_highs - new_lows,
        "advance_decline_ratio": ratio,
        "mcclellan_oscillator": round(float(ema19 - ema39), 4),
        "headline": headline,
    }


def _classify_regime(
    *,
    benchmark_history: pd.DataFrame,
    volatility_history: Optional[pd.DataFrame],
    breadth: Dict[str, Any],
    credit_change_pct: Optional[float],
) -> Dict[str, Any]:
    if benchmark_history.empty or len(benchmark_history) < 60:
        return {
            "label": "Choppy / range-bound",
            "confidence": 0,
            "suggested_entry_mode": "auto",
            "event_risk_flag": False,
            "inputs": {},
        }

    close = _history_series(benchmark_history, "Close")
    if close.empty:
        return {
            "label": "Choppy / range-bound",
            "confidence": 0,
            "suggested_entry_mode": "auto",
            "event_risk_flag": False,
            "inputs": {},
        }
    latest = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1] if len(close) >= 200 else close.rolling(min(50, len(close))).mean().iloc[-1])
    adx = _compute_adx(benchmark_history)

    vix_level = None
    vix_slope = None
    if volatility_history is not None and not volatility_history.empty:
        vol_close = _history_series(volatility_history, "Close")
        if not vol_close.empty:
            vix_level = float(vol_close.iloc[-1])
            if len(vol_close) > 20:
                base = float(vol_close.iloc[-21])
                if base:
                    vix_slope = round(((vix_level / base) - 1.0) * 100.0, 4)

    scores = {
        "trending": 0.0,
        "risk_off": 0.0,
        "squeeze": 0.0,
        "bull": 0.0,
        "bear": 0.0,
    }
    if adx >= 25:
        scores["trending"] += 2.0
    elif adx < 20:
        scores["squeeze"] += 1.0
    if latest > sma50:
        scores["bull"] += 1.5
    else:
        scores["bear"] += 1.5
    if latest > sma200:
        scores["bull"] += 1.0
    else:
        scores["bear"] += 1.0

    pct_above_50d = _json_safe_float(breadth.get("pct_above_50d"))
    nh_nl = _json_safe_float(breadth.get("new_highs_minus_lows"))
    if pct_above_50d > 60:
        scores["bull"] += 1.0
    elif pct_above_50d < 40:
        scores["bear"] += 1.0
    else:
        scores["squeeze"] += 0.5
    if nh_nl < 0:
        scores["bear"] += 0.5
    elif nh_nl > 0:
        scores["bull"] += 0.5

    if vix_level is not None:
        if vix_level > 30:
            scores["risk_off"] += 3.0
        elif vix_level >= 20:
            scores["risk_off"] += 1.5
        elif vix_level < 15:
            scores["bull"] += 0.5
    if vix_slope is not None and vix_slope > 5:
        scores["risk_off"] += 1.5
    if credit_change_pct is not None and credit_change_pct <= -2.0:
        scores["risk_off"] += 3.0

    if scores["risk_off"] >= 3.0:
        label = "Risk-off"
        suggested = "auto"
    elif scores["trending"] >= 2.0 and scores["bull"] >= scores["bear"]:
        label = "Trending bull"
        suggested = "breakout"
    elif scores["trending"] >= 2.0 and scores["bear"] > scores["bull"]:
        label = "Trending bear"
        suggested = "breakout"
    elif scores["squeeze"] >= 1.0 and adx < 20 and 40 <= pct_above_50d <= 60:
        label = "Squeeze / pre-breakout"
        suggested = "breakout"
    else:
        label = "Choppy / range-bound"
        suggested = "mean_reversion"

    winning_score = max(scores.values()) if scores else 0.0
    total_score = sum(max(v, 0.0) for v in scores.values()) or 1.0
    confidence = max(0, min(100, round(100 * winning_score / total_score)))
    return {
        "label": label,
        "confidence": confidence,
        "suggested_entry_mode": suggested,
        "event_risk_flag": False,
        "inputs": {
            "adx14": round(adx, 4),
            "price": round(latest, 4),
            "sma50": round(sma50, 4),
            "sma200": round(sma200, 4),
            "vix_level": None if vix_level is None else round(vix_level, 4),
            "vix_slope_20d_pct": vix_slope,
            "pct_above_50d": pct_above_50d,
            "new_highs_minus_lows": nh_nl,
            "credit_change_pct_20d": credit_change_pct,
        },
    }


def _fetch_calendar_events(provider: str, regions: Iterable[str], start_date: str, end_date: str) -> List[Dict[str, Any]]:
    if provider != "fmp":
        return []
    api_key = os.getenv("FMP_API_KEY", "").strip()
    if not api_key:
        return []
    params = urlencode({"from": start_date, "to": end_date, "apikey": api_key})
    url = f"https://financialmodelingprep.com/stable/economic-calendar?{params}"
    with urlopen(url, timeout=5) as response:
        payload = response.read().decode("utf-8")
    data = pd.read_json(payload)
    if data.empty:
        return []
    allowed = {region.upper() for region in regions}
    records: List[Dict[str, Any]] = []
    for row in data.to_dict(orient="records"):
        impact = str(row.get("impact", "")).lower()
        region = str(row.get("country", "")).upper()
        if impact not in {"medium", "high"}:
            continue
        if region and region not in allowed:
            continue
        raw_timestamp = row.get("date")
        timestamp = str(raw_timestamp) if raw_timestamp is not None else ""
        records.append(
            {
                "date": timestamp[:10],
                "name": row.get("event") or row.get("name"),
                "impact": impact,
                "region": region or None,
            }
        )
    return records


def _fetch_finance_calendar_events(provider: str, symbols: Iterable[str], start_date: str, end_date: str) -> List[Dict[str, Any]]:
    normalized_provider = str(provider or "finnhub").lower()
    allowed = {symbol.upper() for symbol in symbols}

    if normalized_provider == "fmp":
        api_key = os.getenv("FMP_API_KEY", "").strip()
        if not api_key:
            return []
        params = urlencode({"from": start_date, "to": end_date, "apikey": api_key})
        url = f"https://financialmodelingprep.com/stable/earnings-calendar?{params}"
        with urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
        data = pd.read_json(payload)
        if data.empty:
            return []
        records: List[Dict[str, Any]] = []
        for row in data.to_dict(orient="records"):
            symbol = str(row.get("symbol", "")).upper()
            if symbol not in allowed:
                continue
            raw_date = row.get("date")
            if raw_date is None:
                continue
            records.append(
                {
                    "date": str(raw_date)[:10],
                    "symbol": symbol,
                    "name": "Earnings",
                    "event_type": "earnings",
                }
            )
        return records

    if normalized_provider != "finnhub":
        return []

    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        return []
    params = urlencode({"from": start_date, "to": end_date, "token": api_key})
    url = f"https://finnhub.io/api/v1/calendar/earnings?{params}"
    with urlopen(url, timeout=5) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        return []
    earnings_rows = data.get("earningsCalendar")
    if not isinstance(earnings_rows, list):
        return []
    records: List[Dict[str, Any]] = []
    for row in earnings_rows:
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in allowed:
            continue
        raw_date = row.get("date")
        if raw_date is None:
            continue
        records.append(
            {
                "date": str(raw_date)[:10],
                "symbol": symbol,
                "name": "Earnings",
                "event_type": "earnings",
            }
        )
    return records


def _normalize_calendar_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for event in events:
        raw_date = event.get("date") or event.get("timestamp")
        raw_name = event.get("name") or event.get("title")
        if not raw_date or not raw_name:
            continue
        normalized.append(
            {
                "date": str(raw_date)[:10],
                "name": str(raw_name),
                "impact": str(event.get("impact", "")),
                "region": event.get("region"),
            }
        )
    return normalized


def _normalize_finance_calendar_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for event in events:
        raw_date = event.get("date") or event.get("timestamp")
        raw_symbol = event.get("symbol")
        if not raw_date or not raw_symbol:
            continue
        normalized.append(
            {
                "date": str(raw_date)[:10],
                "symbol": str(raw_symbol).upper(),
                "name": str(event.get("name") or event.get("event_type") or "Earnings"),
                "event_type": str(event.get("event_type") or "earnings"),
            }
        )
    return normalized


def _month_window(as_of_date: str) -> Tuple[str, str]:
    target = datetime.fromisoformat(as_of_date).date()
    month_start = target.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    current_month_end = target.replace(day=calendar.monthrange(target.year, target.month)[1])
    next_month_start = current_month_end + timedelta(days=1)
    next_month_end = next_month_start.replace(day=calendar.monthrange(next_month_start.year, next_month_start.month)[1])
    return previous_month_start.isoformat(), (next_month_end + timedelta(days=1)).isoformat()


def _calendar_cache_path() -> Path:
    configured = os.getenv("TRADINGAGENTS_WEB_CALENDAR_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    base_dir = Path(DEFAULT_CONFIG.get("data_cache_dir", os.path.join(Path.home(), ".tradingagents", "cache"))).expanduser()
    return base_dir / "web" / "calendar_cache.json"


def _serialize_calendar_cache_key(cache_key: Tuple[str, str, str, str, str]) -> str:
    return "|".join(cache_key)


def _deserialize_calendar_cache_key(raw_key: str) -> Optional[Tuple[str, str, str, str, str]]:
    parts = raw_key.split("|", 4)
    if len(parts) != 5:
        return None
    return tuple(parts)  # type: ignore[return-value]


def _persist_calendar_cache_locked() -> None:
    cache_path = _calendar_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": {
            _serialize_calendar_cache_key(cache_key): {
                "events": list(entry.get("events", [])),
                "fetched_at": float(entry.get("fetched_at", 0.0)),
            }
            for cache_key, entry in _calendar_response_cache.items()
            if entry.get("events")
        },
        "cooldowns": {
            _serialize_calendar_cache_key(cache_key): float(cooldown_until)
            for cache_key, cooldown_until in _calendar_rate_limit_cooldowns.items()
        },
    }
    temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temp_path.replace(cache_path)


def _ensure_calendar_cache_loaded() -> None:
    global _calendar_cache_disk_loaded
    with _calendar_response_cache_lock:
        if _calendar_cache_disk_loaded:
            return
        _calendar_cache_disk_loaded = True
        cache_path = _calendar_cache_path()
        if not cache_path.exists():
            return
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            _LOGGER.warning("Failed to load calendar cache from disk: %s", exc)
            return

        entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
        for raw_key, entry in entries.items():
            cache_key = _deserialize_calendar_cache_key(str(raw_key))
            if not cache_key or not isinstance(entry, dict):
                continue
            events = entry.get("events", [])
            fetched_at = entry.get("fetched_at", 0.0)
            if isinstance(events, list) and events:
                _calendar_response_cache[cache_key] = {
                    "events": list(events),
                    "fetched_at": float(fetched_at or 0.0),
                }

        cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
        now = time()
        for raw_key, cooldown_until in cooldowns.items():
            cache_key = _deserialize_calendar_cache_key(str(raw_key))
            if not cache_key:
                continue
            try:
                parsed = float(cooldown_until)
            except (TypeError, ValueError):
                continue
            if parsed > now:
                _calendar_rate_limit_cooldowns[cache_key] = parsed


def _store_calendar_payload(cache_key: Tuple[str, str, str, str, str], events: List[Dict[str, Any]], fetched_at: float) -> None:
    with _calendar_response_cache_lock:
        _calendar_response_cache[cache_key] = {
            "events": list(events),
            "fetched_at": fetched_at,
        }
        _calendar_rate_limit_cooldowns.pop(cache_key, None)
        _persist_calendar_cache_locked()


def _set_calendar_cooldown(cache_key: Tuple[str, str, str, str, str], cooldown_until: float) -> None:
    with _calendar_response_cache_lock:
        _calendar_rate_limit_cooldowns[cache_key] = cooldown_until
        _persist_calendar_cache_locked()


def _get_calendar_cooldown_remaining(cache_key: Tuple[str, str, str, str, str], now: float) -> Optional[float]:
    _ensure_calendar_cache_loaded()
    with _calendar_response_cache_lock:
        cooldown_until = _calendar_rate_limit_cooldowns.get(cache_key)
        if cooldown_until is None:
            return None
        remaining = cooldown_until - now
        if remaining <= 0:
            _calendar_rate_limit_cooldowns.pop(cache_key, None)
            _persist_calendar_cache_locked()
            return None
        return remaining


def _get_cached_calendar_payload(
    cache_key: Tuple[str, str, str, str, str],
    fetcher,
) -> List[Dict[str, Any]]:
    _ensure_calendar_cache_loaded()
    now = time()
    with _calendar_response_cache_lock:
        cached = _calendar_response_cache.get(cache_key)
        if cached:
            ttl_seconds = _CALENDAR_CACHE_TTL_SECONDS if cached.get("events") else _CALENDAR_EMPTY_CACHE_TTL_SECONDS
            if (now - float(cached.get("fetched_at", 0.0))) < ttl_seconds:
                return list(cached.get("events", []))

    cooldown_remaining = _get_calendar_cooldown_remaining(cache_key, now)
    if cooldown_remaining is not None:
        raise CalendarProviderCooldownError(cache_key[1], cooldown_remaining)

    try:
        events = fetcher()
    except HTTPError as exc:
        if exc.code == 429:
            _set_calendar_cooldown(cache_key, now + _CALENDAR_RATE_LIMIT_COOLDOWN_SECONDS)
        raise

    _store_calendar_payload(cache_key, list(events), now)
    return list(events)


def _peek_cached_calendar_payload(cache_key: Tuple[str, str, str, str, str]) -> Optional[List[Dict[str, Any]]]:
    _ensure_calendar_cache_loaded()
    with _calendar_response_cache_lock:
        cached = _calendar_response_cache.get(cache_key)
        if not cached:
            return None
        return list(cached.get("events", []))


def _calendar_status(
    provider: str,
    events: List[Dict[str, Any]],
    *,
    label: str,
    empty_message: str,
    unavailable_message: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_provider = str(provider or "fmp").lower()
    if unavailable_message:
        return {
            "provider": normalized_provider,
            "state": "unavailable",
            "message": unavailable_message,
        }
    expected_api_key = None
    if normalized_provider == "fmp":
        expected_api_key = "FMP_API_KEY"
    elif normalized_provider == "finnhub":
        expected_api_key = "FINNHUB_API_KEY"
    if expected_api_key and not os.getenv(expected_api_key, "").strip():
        return {
            "provider": normalized_provider,
            "state": "unavailable",
            "message": f"{label} unavailable. Set {expected_api_key} to load upcoming events.",
        }
    if events:
        return {
            "provider": normalized_provider,
            "state": "ready",
            "message": None,
        }
    return {
        "provider": normalized_provider,
        "state": "empty",
        "message": empty_message,
    }


def get_market_overview(
    home_market: str,
    trade_date: Optional[str],
    settings: Dict[str, Any],
    include_calendars: bool = True,
) -> Dict[str, Any]:
    requested_market = (home_market or "").upper()
    settings_market = str(settings.get("home_market", "US") or "US").upper()
    resolved_market = requested_market if requested_market in MARKET_DEFINITIONS else settings_market
    if resolved_market not in MARKET_DEFINITIONS:
        resolved_market = "US"
    as_of_date = trade_date or date.today().isoformat()
    start = (datetime.fromisoformat(as_of_date) - timedelta(days=400)).date().isoformat()
    end = (datetime.fromisoformat(as_of_date) + timedelta(days=1)).date().isoformat()

    region_payloads: Dict[str, Dict[str, Any]] = {}
    for region, definition in MARKET_DEFINITIONS.items():
        if region != resolved_market:
            region_payloads[region] = {
                "indices": [],
                "regime": _neutral_regime(),
                "breadth": _empty_breadth(),
                "sectors": [],
            }
            continue

        tile_symbols = [tile["symbol"] for tile in definition["tiles"]]
        sector_symbols = [symbol for symbol, _ in definition["sector_proxies"]]
        credit_symbols = definition.get("credit_symbols")
        request_symbols = tile_symbols + definition["universe"] + sector_symbols
        if credit_symbols:
            request_symbols.extend(list(credit_symbols))

        histories = _download_daily_history(request_symbols, start, end)
        benchmark_history = histories.get(definition["tiles"][0]["symbol"], pd.DataFrame())
        volatility_history = histories.get(definition["vol_symbol"], pd.DataFrame()) if definition.get("vol_symbol") else None
        breadth = _compute_breadth({symbol: histories.get(symbol, pd.DataFrame()) for symbol in definition["universe"]})

        credit_change_pct = None
        if credit_symbols:
            hyg = histories.get(credit_symbols[0], pd.DataFrame())
            ief = histories.get(credit_symbols[1], pd.DataFrame())
            if not hyg.empty and not ief.empty and len(hyg) > 20 and len(ief) > 20:
                ratio = _history_series(hyg, "Close").reset_index(drop=True) / _history_series(ief, "Close").reset_index(drop=True)
                if len(ratio) > 20 and float(ratio.iloc[-21]) != 0.0:
                    credit_change_pct = round(((float(ratio.iloc[-1]) / float(ratio.iloc[-21])) - 1.0) * 100.0, 4)

        regime = _classify_regime(
            benchmark_history=benchmark_history,
            volatility_history=volatility_history,
            breadth=breadth,
            credit_change_pct=credit_change_pct,
        )
        indices: List[Dict[str, Any]] = []
        for tile in definition["tiles"]:
            hist = histories.get(tile["symbol"], pd.DataFrame())
            closes = _history_series(hist, "Close")
            if closes.empty:
                indices.append({"symbol": tile["symbol"], "label": tile["label"], "price": 0.0, "change_pct": 0.0})
                continue
            latest = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else latest
            change_pct = 0.0 if prev == 0.0 else round(((latest / prev) - 1.0) * 100.0, 4)
            indices.append({"symbol": tile["symbol"], "label": tile["label"], "price": round(latest, 4), "change_pct": change_pct})

        sectors: List[Dict[str, Any]] = []
        for symbol, label in definition["sector_proxies"]:
            hist = histories.get(symbol, pd.DataFrame())
            closes = _history_series(hist, "Close")
            if closes.empty:
                sectors.append({"symbol": symbol, "label": label, "change_pct": 0.0})
                continue
            latest = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else latest
            change_pct = 0.0 if prev == 0.0 else round(((latest / prev) - 1.0) * 100.0, 4)
            sectors.append({"symbol": symbol, "label": label, "change_pct": change_pct})

        region_payloads[region] = {
            "indices": indices,
            "regime": regime,
            "breadth": breadth,
            "sectors": sectors,
        }

    calendar_provider = settings.get("calendar_provider", "fmp")
    finance_calendar_provider = settings.get("finance_calendar_provider", "finnhub")
    month_start, month_end = _month_window(as_of_date)
    calendar_unavailable_message = None
    finance_calendar_unavailable_message = None
    economic_cache_key = ("economic", str(calendar_provider), resolved_market, month_start, month_end)
    financial_cache_key = ("financial", str(finance_calendar_provider), resolved_market, month_start, month_end)
    try:
        if include_calendars:
            events = _get_cached_calendar_payload(
                economic_cache_key,
                lambda: _normalize_calendar_events(
                    _fetch_calendar_events(
                        calendar_provider,
                        [resolved_market],
                        month_start,
                        month_end,
                    )
                )
            )
        else:
            events = _peek_cached_calendar_payload(economic_cache_key) or []
    except Exception as exc:
        cached_events = _peek_cached_calendar_payload(economic_cache_key)
        if cached_events:
            _LOGGER.warning("Economic calendar provider failed; serving stale cached events instead: %s", exc)
            events = cached_events
        else:
            _LOGGER.warning("Economic calendar unavailable with no cached fallback: %s", exc)
            events = []
            calendar_unavailable_message = f"Economic calendar unavailable. {exc}"

    try:
        if include_calendars:
            finance_events = _get_cached_calendar_payload(
                financial_cache_key,
                lambda: _normalize_finance_calendar_events(
                    _fetch_finance_calendar_events(
                        finance_calendar_provider,
                        MARKET_DEFINITIONS[resolved_market]["universe"],
                        month_start,
                        month_end,
                    )
                )
            )
        else:
            finance_events = _peek_cached_calendar_payload(financial_cache_key) or []
    except Exception as exc:
        cached_finance_events = _peek_cached_calendar_payload(financial_cache_key)
        if cached_finance_events:
            _LOGGER.warning("Financial calendar provider failed; serving stale cached events instead: %s", exc)
            finance_events = cached_finance_events
        else:
            _LOGGER.warning("Financial calendar unavailable with no cached fallback: %s", exc)
            finance_events = []
            finance_calendar_unavailable_message = f"Financial calendar unavailable. {exc}"

    calendar_status = _calendar_status(
        str(calendar_provider),
        events,
        label="Economic calendar",
        empty_message="No medium or high impact events scheduled this month.",
        unavailable_message=calendar_unavailable_message,
    )
    finance_calendar_status = _calendar_status(
        str(finance_calendar_provider),
        finance_events,
        label="Financial calendar",
        empty_message="No upcoming earnings found for the representative market basket this month.",
        unavailable_message=finance_calendar_unavailable_message,
    )
    home_payload = region_payloads[resolved_market]
    home_payload["regime"]["event_risk_flag"] = any(
        event.get("impact") == "high" and event.get("date") == as_of_date for event in events
    )

    regions = {
        region: {
            "regime": payload["regime"],
            "benchmark": payload["indices"][0] if payload["indices"] else None,
        }
        for region, payload in region_payloads.items()
    }
    return {
        "home_market": resolved_market,
        "trade_date": as_of_date,
        "status": "ready",
        "indices": home_payload["indices"],
        "regime": home_payload["regime"],
        "breadth": home_payload["breadth"],
        "sectors": home_payload["sectors"],
        "events": events,
        "calendar_status": calendar_status,
        "finance_events": finance_events,
        "finance_calendar_status": finance_calendar_status,
        "regions": regions,
        "stream": {
            "status": settings.get("live_quote_mode", "delayed_fallback"),
            "transport": "websocket",
            "provider": settings.get("data_vendors", {}).get("market", "yfinance"),
        },
    }


def get_market_chart(
    symbol: str,
    interval: Optional[str] = None,
    limit: Optional[int] = None,
    before: Optional[int] = None,
    trade_date: Optional[str] = None,
    session: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_symbol = (symbol or "").strip().upper()
    normalized_interval = _normalize_chart_interval(interval)
    resolved_limit = _coerce_chart_limit(normalized_interval, limit)

    if not normalized_symbol:
        return {
            "symbol": "",
            "interval": normalized_interval,
            "limit": resolved_limit,
            "has_more": False,
            "oldest_time": None,
            "newest_time": None,
            "points": [],
            "bars": [],
        }

    config = CHART_INTERVAL_CONFIG[normalized_interval]
    anchor_dt = _chart_anchor_dt(trade_date, before)
    start = (anchor_dt.date() - timedelta(days=int(config["lookback_days"]))).isoformat()
    end = (anchor_dt.date() + timedelta(days=1)).isoformat()

    if config["kind"] == "intraday":
        chart_frame = get_intraday_bars(
            normalized_symbol,
            config["fetch_interval"],
            start,
            end,
            session=session or config.get("session", "regular"),
        ).rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
            }
        )
        chart_frame = chart_frame[["open", "high", "low", "close"]] if not chart_frame.empty else chart_frame
        chart_frame = _normalize_time_index(chart_frame)
    else:
        history = _download_daily_history([normalized_symbol], start, end).get(normalized_symbol, pd.DataFrame())
        chart_frame = _history_to_ohlc_frame(history)
        resample_rule = config.get("resample_rule")
        if resample_rule:
            chart_frame = _resample_ohlc_frame(chart_frame, str(resample_rule))

    if before is not None and not chart_frame.empty:
        chart_frame = chart_frame[chart_frame.index < anchor_dt]

    has_more = len(chart_frame) > resolved_limit
    payload = _serialize_chart_payload(normalized_symbol, normalized_interval, resolved_limit, chart_frame.tail(resolved_limit))
    payload["has_more"] = has_more
    return payload


def _build_screening_quant_config(entry_mode: str, request: Dict[str, Any]) -> Dict[str, Any]:
    filters = request.get("filters") or {}
    condition_params = request.get("condition_params") or {}
    config: Dict[str, Any] = {"entry_mode": entry_mode}
    filter_map = {
        "momentum": "validation_momentum",
        "squeeze": "validation_squeeze",
        "sr_proximity": "validation_sr_proximity",
    }
    for request_key, config_key in filter_map.items():
        if request_key in filters:
            config[config_key] = bool(filters[request_key])
    if "sr_proximity_pct" in condition_params:
        try:
            sr_proximity_pct = float(condition_params["sr_proximity_pct"])
        except (TypeError, ValueError):
            sr_proximity_pct = None
        if sr_proximity_pct is not None and sr_proximity_pct > 0:
            config["sr_proximity_pct"] = sr_proximity_pct
    return config


def run_screening(request: Dict[str, Any], store, settings: Dict[str, Any]) -> Dict[str, Any]:
    home_market = _resolve_screening_market(request.get("universe", ""), settings.get("home_market", "US"))
    screening_run = store.create_screening_run(
        request,
        home_market=home_market,
        workflow_session_id=request.get("workflow_session_id"),
    )
    universe_name, symbols = _resolve_screening_universe(
        request.get("universe", ""),
        request.get("custom_symbols", []),
        screening_run["home_market"],
    )
    trade_date = request.get("trade_date") or date.today().isoformat()
    settings_defaults = settings.get("workflow_defaults", {})
    threshold = float(request.get("min_score", settings_defaults.get("min_score", 0.3)))
    top_n = int(request.get("top_n", settings_defaults.get("top_n", 20)))
    overview = get_market_overview(screening_run["home_market"], trade_date, settings)

    results: List[Dict[str, Any]] = []
    error_count = 0
    below_threshold_count = 0
    start = (datetime.fromisoformat(trade_date) - timedelta(days=45)).date().isoformat()
    for symbol in symbols:
        market = _market_for_symbol(symbol, screening_run["home_market"])
        region_regime = overview["regions"].get(market, {}).get("regime", {})
        strategy = request.get("strategy", "auto")
        entry_mode = region_regime.get("suggested_entry_mode", "auto") if strategy == "auto" else strategy
        errored = False
        try:
            bars_15m = get_intraday_bars(symbol, "15m", start, trade_date)
            bars_4h = get_intraday_bars(symbol, "4h", start, trade_date)
            from tradingagents.quant.engine import run_quant_engine

            contract = run_quant_engine(
                symbol,
                trade_date,
                bars_15m,
                bars_4h,
                _build_screening_quant_config(entry_mode, request),
            )
            last_price = float(bars_15m["Close"].iloc[-1]) if not bars_15m.empty else 0.0
            score = float(contract.score) if contract.score != float("-inf") else -999.0
            result = {
                "symbol": symbol,
                "market": market,
                "score": round(score, 4),
                "confidence": contract.confidence,
                "signal": contract.signal.value,
                "summary": contract.summary,
                "last_price": round(last_price, 4),
                "suggested_entry_mode": entry_mode,
                "regime": region_regime,
            }
        except Exception as exc:
            errored = True
            result = {
                "symbol": symbol,
                "market": market,
                "score": -999.0,
                "confidence": None,
                "signal": "error",
                "summary": str(exc),
                "last_price": 0.0,
                "suggested_entry_mode": entry_mode,
                "regime": region_regime,
                "error": str(exc),
            }
        if errored:
            error_count += 1
            continue
        # Use absolute score so strong SELL signals (negative) pass the same threshold as BUYs.
        if abs(result["score"]) >= threshold:
            results.append(result)
        else:
            below_threshold_count += 1

    results.sort(
        key=lambda item: (abs(item.get("score", 0.0)), item.get("confidence") or -1.0),
        reverse=True,
    )
    results = results[:top_n]
    completed_at = _utc_now()
    payload = {
        "run_id": screening_run["run_id"],
        "workflow_session_id": screening_run["workflow_session_id"],
        "home_market": screening_run["home_market"],
        "universe": universe_name,
        "trade_date": trade_date,
        "regime": overview["regime"],
        "results": results,
        "summary": (
            f"{len(results)} candidates scored "
            f"(evaluated {len(symbols)}, "
            f"{below_threshold_count} below threshold {threshold:g}, "
            f"{error_count} errored)"
        ),
        "diagnostics": {
            "evaluated": len(symbols),
            "passed": len(results),
            "below_threshold": below_threshold_count,
            "errors": error_count,
            "threshold": threshold,
        },
        "completed_at": completed_at,
    }
    store.update_screening_run(screening_run["run_id"], status="completed", result=payload)
    return store.get_screening_run(screening_run["run_id"]) or payload


def resolve_basket_items(request: Dict[str, Any], store) -> Dict[str, Any]:
    payload = dict(request)
    if payload.get("items"):
        return payload
    if payload.get("source_screening_run_id"):
        screening = store.get_screening_run(payload["source_screening_run_id"])
        if screening:
            by_symbol = {item["symbol"]: item for item in screening.get("results", [])}
            payload["items"] = [by_symbol[symbol] for symbol in payload.get("symbols", []) if symbol in by_symbol]
    return payload


def _batch_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "skipped": 0}
    for item in items:
        status = item.get("status", "queued")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _batch_terminal_status(counts: Dict[str, int]) -> str:
    if counts.get("failed", 0) and counts.get("completed", 0):
        return "partial_failure"
    if counts.get("failed", 0):
        return "error"
    return "completed"


def finalize_stopped_batch(batch_id: str, store) -> Optional[Dict[str, Any]]:
    with _get_batch_state_lock(batch_id):
        batch = store.get_analysis_batch(batch_id)
        if batch is None:
            return None

        items = list(batch.get("items", []))
        events = list(batch.get("events", []))
        timestamp = _utc_now()

        for item in items:
            status = str(item.get("status", "queued")).lower()
            if status == "running":
                item.update(
                    {
                        "status": "failed",
                        "completed_at": timestamp,
                        "error": item.get("error") or "Batch stopped before this ticker completed.",
                        "summary": item.get("summary") or "Batch stopped before this ticker completed.",
                    }
                )
            elif status == "queued":
                item.update(
                    {
                        "status": "skipped",
                        "completed_at": timestamp,
                        "summary": item.get("summary") or "Skipped because the batch was stopped.",
                    }
                )

        counts = _batch_counts(items)
        summary = {
            "counts": counts,
            "title": f"{len(items)} ticker batch",
            "headline": f"{counts.get('completed', 0)} completed, {counts.get('failed', 0)} failed, {counts.get('skipped', 0)} skipped",
            "completed_at": timestamp,
        }
        if not events or events[-1].get("status") != "stopped" or events[-1].get("type") != "batch_status":
            events.append(
                {
                    "type": "batch_status",
                    "batch_id": batch_id,
                    "status": "stopped",
                    "timestamp": timestamp,
                    "counts": counts,
                }
            )
        return store.update_analysis_batch(batch_id, status="stopped", items=items, summary=summary, events=events)


def stopped_batch_needs_reconciliation(batch: Optional[Dict[str, Any]]) -> bool:
    if not batch or str(batch.get("status", "")).lower() != "stopped":
        return False

    items = list(batch.get("items", []))
    if any(str(item.get("status", "queued")).lower() in {"queued", "running"} for item in items):
        return True

    expected_counts = _batch_counts(items)
    actual_counts = ((batch.get("summary") or {}).get("counts") or {}) if isinstance(batch.get("summary"), dict) else {}
    for key, value in expected_counts.items():
        if int(actual_counts.get(key, 0) or 0) != value:
            return True
    return False


def run_batch_analysis(request: Dict[str, Any], store, settings: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(request)
    if payload.get("basket_id") and not payload.get("symbols"):
        basket = store.get_basket(payload["basket_id"])
        if basket:
            payload["symbols"] = basket.get("symbols", [])
    batch = store.create_analysis_batch(
        payload,
        home_market=settings.get("home_market", "US"),
        workflow_session_id=payload.get("workflow_session_id"),
    )
    # Seed items as queued so the SSE stream sees them before work begins.
    items: List[Dict[str, Any]] = [
        {"symbol": s, "run_id": None, "status": "queued"}
        for s in payload.get("symbols", [])
    ]
    events: List[Dict[str, Any]] = [
        {"type": "batch_status", "batch_id": batch["batch_id"], "status": "queued", "timestamp": _utc_now()}
    ]
    store.update_analysis_batch(batch["batch_id"], status="running", items=items, summary={"counts": _batch_counts(items)}, events=events)

    t = _thread_cls(
        target=_run_batch_thread,
        args=(batch["batch_id"], payload, settings),
        daemon=True,
    )
    t.start()

    return store.get_analysis_batch(batch["batch_id"]) or batch


def _run_batch_thread(batch_id: str, payload: Dict[str, Any], settings: Dict[str, Any]) -> None:
    from tradingagents.web.storage import get_workflow_store
    store = get_workflow_store()

    batch = store.get_analysis_batch(batch_id)
    if batch is None:
        return

    with _get_batch_state_lock(batch_id):
        batch = store.get_analysis_batch(batch_id)
        if batch is None:
            return
        events = list(batch.get("events", []))
        events.append({"type": "batch_status", "batch_id": batch_id, "status": "running", "timestamp": _utc_now()})
        store.update_analysis_batch(batch_id, status="running", events=events)

    llm_provider = payload.get("llm_provider") or settings.get("llm_provider", "")
    deep_think_llm = payload.get("deep_think_llm") or settings.get("deep_think_llm", "")
    quick_think_llm = payload.get("quick_think_llm") or settings.get("quick_think_llm", "")
    symbols = list(payload.get("symbols", []))
    worker_limit = _batch_worker_limit(payload, settings, len(symbols))
    active_threads: List[Any] = []

    for symbol in symbols:
        if _is_cancelled(batch_id):
            break
        while len(active_threads) >= worker_limit:
            active_threads = _reap_finished_threads(active_threads)
            if len(active_threads) >= worker_limit:
                _join_thread(active_threads[0], timeout=0.05)
                active_threads = _reap_finished_threads(active_threads)
        worker = _thread_cls(
            target=_run_single_item,
            args=(batch_id, symbol, payload, llm_provider, deep_think_llm, quick_think_llm, store),
            daemon=True,
        )
        worker.start()
        active_threads.append(worker)

    while active_threads:
        active_threads = _reap_finished_threads(active_threads)
        if active_threads:
            _join_thread(active_threads[0], timeout=0.05)

    batch = store.get_analysis_batch(batch_id)
    if batch is None:
        return
    items = list(batch.get("items", []))
    events = list(batch.get("events", []))
    if _is_cancelled(batch_id):
        finalize_stopped_batch(batch_id, store)
        return
    counts = _batch_counts(items)
    final_status = "stopped" if _is_cancelled(batch_id) else _batch_terminal_status(counts)
    summary = {
        "counts": counts,
        "title": f"{len(items)} ticker batch",
        "headline": f"{counts.get('completed', 0)} completed, {counts.get('failed', 0)} failed",
        "completed_at": _utc_now(),
    }
    events.append({"type": "batch_status", "batch_id": batch_id, "status": final_status, "timestamp": _utc_now(), "counts": counts})
    store.update_analysis_batch(batch_id, status=final_status, items=items, summary=summary, events=events)


def _run_single_item(
    batch_id: str,
    symbol: str,
    payload: Dict[str, Any],
    llm_provider: str,
    deep_think_llm: str,
    quick_think_llm: str,
    store,
) -> None:
    with _get_batch_state_lock(batch_id):
        batch = store.get_analysis_batch(batch_id)
        if batch is None:
            return
        items = list(batch.get("items", []))
        events = list(batch.get("events", []))

        item = next((it for it in items if it.get("symbol") == symbol), None)
        if item is None:
            return

        run = runner.create_run(
            ticker=symbol,
            analysis_date=payload.get("analysis_date") or date.today().isoformat(),
            selected_analysts=payload.get("selected_analysts", []),
            execution_mode=payload.get("execution_mode", "llm_assisted"),
            llm_provider=llm_provider,
            deep_think_llm=deep_think_llm,
            quick_think_llm=quick_think_llm,
            trading_style=payload.get("trading_style", "swing"),
            intraday_interval=payload.get("intraday_interval"),
            trade_datetime=payload.get("trade_datetime"),
            include_extended_hours=payload.get("include_extended_hours"),
        )
        item.update({"run_id": run.run_id, "status": "running", "started_at": _utc_now()})
        events.append({
            "type": "batch_item", "batch_id": batch_id,
            "symbol": symbol, "run_id": run.run_id,
            "status": "running", "phase": "starting",
            "timestamp": _utc_now(),
        })
        store.update_analysis_batch(batch_id, items=items, events=events)

    try:
        completed = runner.run_sync(
            run.run_id,
            config={
                "trading_style": payload.get("trading_style", "swing"),
                "intraday_interval": payload.get("intraday_interval"),
                "trade_datetime": payload.get("trade_datetime"),
                "include_extended_hours": payload.get("include_extended_hours"),
            },
        )
        if completed is None:
            raise RuntimeError("analysis run did not return a result")
        final_order = completed.final_order_intent or {}
        item_update = {
            "status": "completed" if completed.status == "completed" else "failed",
            "completed_at": _utc_now(),
            "rating": final_order.get("rating", "HOLD"),
            "summary": completed.report_sections.get("final_trade_decision") or final_order.get("reason") or "",
            "report_paths": completed.report_paths,
            "order_intent": final_order,
            "error": "; ".join(completed.errors) if completed.errors else None,
        }
    except Exception as exc:
        item_update = {"status": "failed", "completed_at": _utc_now(), "error": str(exc), "rating": "HOLD", "summary": str(exc)}

    with _get_batch_state_lock(batch_id):
        batch = store.get_analysis_batch(batch_id)
        if batch is None:
            return
        if _is_cancelled(batch_id) or str(batch.get("status", "")).lower() == "stopped":
            return

        items = list(batch.get("items", []))
        events = list(batch.get("events", []))
        item = next((it for it in items if it.get("symbol") == symbol), None)
        if item is None:
            return

        item.update(item_update)
        events.append({
            "type": "batch_item", "batch_id": batch_id,
            "symbol": symbol, "run_id": item.get("run_id"),
            "status": item["status"],
            "rating": item.get("rating"),
            "error": item.get("error"),
            "timestamp": _utc_now(),
        })
        counts = _batch_counts(items)
        if counts.get("running", 0) or counts.get("queued", 0):
            next_status = "running"
        else:
            next_status = _batch_terminal_status(counts)
            events.append({
                "type": "batch_status",
                "batch_id": batch_id,
                "status": next_status,
                "timestamp": _utc_now(),
                "counts": counts,
            })
        store.update_analysis_batch(batch_id, status=next_status, items=items, summary={"counts": counts}, events=events)


def rerun_batch_item_analysis(batch_id: str, symbol: str, store, settings: Dict[str, Any]) -> None:
    with _get_batch_state_lock(batch_id):
        batch = store.get_analysis_batch(batch_id)
        if batch is None:
            return
        resume_batch(batch_id)

        items = list(batch.get("items", []))
        events = list(batch.get("events", []))
        item = next((it for it in items if str(it.get("symbol", "")).upper() == symbol.upper()), None)
        if item is None:
            return
        item.update({
            "status": "queued",
            "error": None,
            "summary": None,
            "rating": None,
            "completed_at": None,
        })
        counts = _batch_counts(items)
        events.append({
            "type": "batch_status",
            "batch_id": batch_id,
            "status": "running",
            "timestamp": _utc_now(),
            "counts": counts,
        })
        store.update_analysis_batch(batch_id, status="running", items=items, summary={"counts": counts}, events=events)

    llm_provider = settings.get("llm_provider", "")
    deep_think_llm = settings.get("deep_think_llm", "")
    quick_think_llm = settings.get("quick_think_llm", "")
    payload = {
        "analysis_date": batch.get("analysis_date") or date.today().isoformat(),
        "selected_analysts": batch.get("selected_analysts", []),
        "execution_mode": batch.get("execution_mode", "llm_assisted"),
    }
    t = _thread_cls(
        target=_run_single_item,
        args=(batch_id, symbol, payload, llm_provider, deep_think_llm, quick_think_llm, store),
        daemon=True,
    )
    t.start()


def retry_batch_item_analysis(batch_id: str, symbol: str, store, settings: Dict[str, Any]) -> None:
    rerun_batch_item_analysis(batch_id, symbol, store, settings)


def resume_batch_item_from_step_analysis(batch_id: str, symbol: str, store, settings: Dict[str, Any]) -> str:
    batch = store.get_analysis_batch(batch_id)
    if batch is None:
        raise ValueError("batch not found")

    item = next((it for it in list(batch.get("items", [])) if str(it.get("symbol", "")).upper() == symbol.upper()), None)
    if item is None:
        raise ValueError("batch item not found")

    previous_run_id = item.get("run_id")
    checkpoint_sections = runner.load_report_sections_from_events(previous_run_id) if previous_run_id else {}
    resume_phase = runner.infer_resume_phase(checkpoint_sections)
    if not resume_phase:
        raise ValueError(
            "Retry from interrupted step is not supported yet for this ticker because no resumable checkpoint was found. Use rerun full analysis instead."
        )

    with _get_batch_state_lock(batch_id):
        batch = store.get_analysis_batch(batch_id)
        if batch is None:
            raise ValueError("batch not found")
        resume_batch(batch_id)

        items = list(batch.get("items", []))
        events = list(batch.get("events", []))
        item = next((it for it in items if str(it.get("symbol", "")).upper() == symbol.upper()), None)
        if item is None:
            raise ValueError("batch item not found")

        run = runner.create_run(
            ticker=str(item.get("symbol") or symbol.upper()),
            analysis_date=batch.get("analysis_date") or date.today().isoformat(),
            selected_analysts=batch.get("selected_analysts", []),
            execution_mode=batch.get("execution_mode", "llm_assisted"),
            llm_provider=batch.get("llm_provider") or settings.get("llm_provider", ""),
            deep_think_llm=batch.get("deep_think_llm") or settings.get("deep_think_llm", ""),
            quick_think_llm=batch.get("quick_think_llm") or settings.get("quick_think_llm", ""),
            trading_style=batch.get("request", {}).get("trading_style", batch.get("trading_style", "swing")),
            intraday_interval=batch.get("request", {}).get("intraday_interval", batch.get("intraday_interval")),
            trade_datetime=batch.get("request", {}).get("trade_datetime", batch.get("trade_datetime")),
            include_extended_hours=batch.get("request", {}).get("include_extended_hours"),
        )
        item.update(
            {
                "run_id": run.run_id,
                "status": "running",
                "error": None,
                "summary": None,
                "rating": None,
                "completed_at": None,
                "started_at": _utc_now(),
            }
        )
        counts = _batch_counts(items)
        events.append(
            {
                "type": "batch_item",
                "batch_id": batch_id,
                "symbol": symbol.upper(),
                "run_id": run.run_id,
                "status": "running",
                "phase": resume_phase.title(),
                "timestamp": _utc_now(),
            }
        )
        events.append(
            {
                "type": "batch_status",
                "batch_id": batch_id,
                "status": "running",
                "timestamp": _utc_now(),
                "counts": counts,
            }
        )
        store.update_analysis_batch(batch_id, status="running", items=items, summary={"counts": counts}, events=events)

    def _resume_worker() -> None:
        completed = runner.run_resumed_sync(
            run.run_id,
            resume_from=resume_phase,
            checkpoint_sections=checkpoint_sections,
            config={
                "trading_style": run.trading_style,
                "intraday_interval": run.intraday_interval,
                "trade_datetime": run.trade_datetime,
                "include_extended_hours": run.include_extended_hours,
            },
        )
        item_update: Dict[str, Any]
        if completed is None:
            item_update = {"status": "failed", "completed_at": _utc_now(), "error": "analysis run did not return a result", "rating": "HOLD", "summary": "analysis run did not return a result"}
        else:
            final_order = completed.final_order_intent or {}
            item_update = {
                "status": "completed" if completed.status == "completed" else "failed",
                "completed_at": _utc_now(),
                "rating": final_order.get("rating", "HOLD"),
                "summary": completed.report_sections.get("final_trade_decision") or final_order.get("reason") or "",
                "report_paths": completed.report_paths,
                "order_intent": final_order,
                "error": "; ".join(completed.errors) if completed.errors else None,
            }

        with _get_batch_state_lock(batch_id):
            next_batch = store.get_analysis_batch(batch_id)
            if next_batch is None:
                return
            if _is_cancelled(batch_id) or str(next_batch.get("status", "")).lower() == "stopped":
                return

            items = list(next_batch.get("items", []))
            events = list(next_batch.get("events", []))
            next_item = next((it for it in items if str(it.get("symbol", "")).upper() == symbol.upper()), None)
            if next_item is None:
                return

            next_item.update(item_update)
            events.append(
                {
                    "type": "batch_item",
                    "batch_id": batch_id,
                    "symbol": symbol.upper(),
                    "run_id": next_item.get("run_id"),
                    "status": next_item["status"],
                    "rating": next_item.get("rating"),
                    "error": next_item.get("error"),
                    "timestamp": _utc_now(),
                }
            )
            counts = _batch_counts(items)
            next_status = "running" if counts.get("running", 0) or counts.get("queued", 0) else _batch_terminal_status(counts)
            if next_status != "running":
                events.append(
                    {
                        "type": "batch_status",
                        "batch_id": batch_id,
                        "status": next_status,
                        "timestamp": _utc_now(),
                        "counts": counts,
                    }
                )
            store.update_analysis_batch(batch_id, status=next_status, items=items, summary={"counts": counts}, events=events)

    t = _thread_cls(target=_resume_worker, daemon=True)
    t.start()
    return resume_phase


def _compute_atr_from_intraday(bars_15m: pd.DataFrame, period: int = 14) -> float:
    if bars_15m.empty or len(bars_15m) < period + 1:
        return 1.0
    tr = _true_range(
        bars_15m["High"].astype(float),
        bars_15m["Low"].astype(float),
        bars_15m["Close"].astype(float),
    )
    atr = tr.rolling(period).mean().iloc[-1]
    return max(round(float(atr), 8), 0.01)


def build_strategy_from_batch(request: Dict[str, Any], store, settings: Dict[str, Any]) -> Dict[str, Any]:
    strategy = store.create_strategy_plan(
        request,
        home_market=settings.get("home_market", "US"),
        workflow_session_id=request.get("workflow_session_id"),
    )
    batch = store.get_analysis_batch(request["batch_id"])
    if batch is None:
        raise ValueError(f"Unknown batch_id {request['batch_id']}")

    mode = request.get("mode", "auto")
    portfolio_size = float(request.get("portfolio_size", settings.get("workflow_defaults", {}).get("portfolio_size", 100_000.0)))
    risk_per_trade = float(request.get("risk_per_trade", settings.get("workflow_defaults", {}).get("risk_per_trade", 0.01)))
    allow_shorts = bool(request.get("allow_shorts", settings.get("workflow_defaults", {}).get("allow_shorts", True)))
    trades: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    start = (datetime.fromisoformat(batch["analysis_date"]) - timedelta(days=30)).date().isoformat() if batch.get("analysis_date") else (date.today() - timedelta(days=30)).isoformat()
    trade_date = batch.get("analysis_date") or date.today().isoformat()

    for item in batch.get("items", []):
        rating = str(item.get("rating", "HOLD")).upper()
        if rating in {"BUY", "OVERWEIGHT"}:
            direction = "long"
            side = "buy"
        elif rating in {"SELL", "UNDERWEIGHT"}:
            direction = "short"
            side = "sell"
        else:
            skipped.append({"symbol": item.get("symbol"), "reason": f"Skipped {rating} rating"})
            continue
        if direction == "short" and not allow_shorts:
            skipped.append({"symbol": item.get("symbol"), "reason": "Shorts are disabled"})
            continue

        symbol = item["symbol"]
        market = _market_for_symbol(symbol, strategy["home_market"])
        overview = get_market_overview(market, trade_date, settings)
        entry_mode = overview["regime"]["suggested_entry_mode"] if mode == "auto" else mode
        bars_15m = get_intraday_bars(symbol, "15m", start, trade_date)
        if bars_15m.empty:
            skipped.append({"symbol": symbol, "reason": "No intraday bars available"})
            continue
        entry_price = round(float(bars_15m["Close"].iloc[-1]), 4)
        atr = _compute_atr_from_intraday(bars_15m)
        engine = EntryEngine.MEAN_REVERSION if entry_mode == "mean_reversion" else EntryEngine.BREAKOUT
        entry_signal = EntrySignal(engine=engine, direction=direction, strength=1.0, reason=item.get("summary") or f"{rating} rating")
        size_cfg = {"risk_per_trade_pct": risk_per_trade}
        size_contract = size_position(entry_signal, entry_price, atr, portfolio_size, size_cfg)
        stops = compute_stops(direction, entry_price, atr, size_cfg)
        reward_distance = abs(entry_price - stops.initial_stop) * 2.0
        target_price = round(entry_price + reward_distance if direction == "long" else entry_price - reward_distance, 4)
        rr_ratio = round(reward_distance / max(abs(entry_price - stops.initial_stop), 0.01), 4)
        trades.append(
            {
                "symbol": symbol,
                "market": market,
                "side": side,
                "direction": direction,
                "quantity": round(size_contract.quantity, 6),
                "entry_price": entry_price,
                "stop_price": round(stops.initial_stop, 4),
                "target_price": target_price,
                "risk_amount": round(size_contract.risk_amount, 4),
                "notional": round(size_contract.notional, 4),
                "rr_ratio": rr_ratio,
                "rating": rating,
                "entry_mode": entry_mode,
                "horizon": request.get("horizon", "intraday"),
                "analysis_run_id": item.get("run_id"),
                "summary": item.get("summary") or entry_signal.reason,
            }
        )

    gross_exposure = round(sum(abs(trade["notional"]) for trade in trades), 4)
    net_exposure = round(sum(trade["notional"] if trade["direction"] == "long" else -trade["notional"] for trade in trades), 4)
    max_loss = round(sum(trade["risk_amount"] for trade in trades), 4)
    concentration = {
        "largest_position_pct": round((max((abs(trade["notional"]) for trade in trades), default=0.0) / portfolio_size) * 100.0, 4),
        "positions": len(trades),
    }
    exposure = {
        "gross_exposure": gross_exposure,
        "net_exposure": net_exposure,
        "gross_exposure_pct": round((gross_exposure / portfolio_size) * 100.0, 4) if portfolio_size else 0.0,
        "net_exposure_pct": round((net_exposure / portfolio_size) * 100.0, 4) if portfolio_size else 0.0,
    }
    risk = {
        "max_loss": max_loss,
        "worst_case_gap_estimate": round(max_loss * 1.25, 4),
        "risk_per_trade": risk_per_trade,
    }
    result = {
        "status": "ready",
        "headline": f"{len(trades)} trade rows built from {len(batch.get('items', []))} analyses",
        "completed_at": _utc_now(),
        "trades": trades,
        "skipped": skipped,
        "exposure": exposure,
        "concentration": concentration,
        "risk": risk,
    }
    store.update_strategy_plan(strategy["strategy_id"], result=result)
    return store.get_strategy_plan(strategy["strategy_id"]) or strategy


def _aggregate_equity_curves(results: List[Dict[str, Any]], per_symbol_equity: float) -> List[float]:
    if not results:
        return []
    max_len = max(len(item.get("equity_curve", [])) for item in results)
    aggregate: List[float] = []
    for idx in range(max_len):
        total = 0.0
        for item in results:
            curve = item.get("equity_curve", [])
            if not curve:
                total += per_symbol_equity
            elif idx < len(curve):
                total += float(curve[idx])
            else:
                total += float(curve[-1])
        aggregate.append(round(total, 4))
    return aggregate


def _strategy_trade_allocations(
    strategy: Dict[str, Any],
    portfolio_size: float,
) -> Tuple[List[Dict[str, Any]], float]:
    trades = list(strategy.get("trades", []))
    if not trades:
        return [], portfolio_size

    weighted_notional = 0.0
    for trade in trades:
        notional = _json_safe_float(trade.get("notional"))
        if notional <= 0.0:
            quantity = _json_safe_float(trade.get("quantity"))
            entry_price = _json_safe_float(trade.get("entry_price"))
            notional = round(abs(quantity * entry_price), 4)
        trade["allocated_equity"] = round(notional, 4)
        weighted_notional += notional

    if weighted_notional <= 0.0:
        per_trade_equity = round(portfolio_size / max(len(trades), 1), 4)
        for trade in trades:
            trade["allocated_equity"] = per_trade_equity
        return trades, 0.0

    scale = 1.0 if weighted_notional <= portfolio_size or portfolio_size <= 0.0 else portfolio_size / weighted_notional
    allocated_total = 0.0
    for trade in trades:
        trade["allocated_equity"] = round(float(trade["allocated_equity"]) * scale, 4)
        allocated_total += float(trade["allocated_equity"])
    idle_cash = round(portfolio_size - allocated_total, 4)
    return trades, idle_cash


def run_backtest_for_strategy(request: Dict[str, Any], store, settings: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(request)
    payload["execution_mode"] = "quant_strict"
    payload["llm_constructed"] = False
    backtest = store.create_backtest_run(
        payload,
        home_market=settings.get("home_market", "US"),
        workflow_session_id=payload.get("workflow_session_id"),
    )
    events: List[Dict[str, Any]] = [{"type": "backtest_status", "backtest_id": backtest["backtest_id"], "status": "queued", "execution_mode": "quant_strict", "timestamp": _utc_now()}]
    store.update_backtest_run(backtest["backtest_id"], status="running", events=events)

    strategy = store.get_strategy_plan(payload["strategy_id"]) if payload.get("strategy_id") else None
    if strategy and strategy.get("trades"):
        strategy_trades, idle_cash = _strategy_trade_allocations(strategy, portfolio_size=0.0)
        symbols = [trade["symbol"] for trade in strategy_trades]
    else:
        strategy_trades = []
        idle_cash = 0.0
        symbols = payload.get("symbols", [])
    if not symbols:
        raise ValueError("Backtest requires at least one symbol or a saved strategy with trades")

    config = dict(payload.get("config", {}))
    walkforward_n_folds = int(config.get("walkforward_n_folds", 0) or 0)
    walkforward_in_sample_ratio = float(config.get("walkforward_in_sample_ratio", 0.7))
    portfolio_size = payload.get("portfolio_size")
    if portfolio_size is None and strategy:
        portfolio_size = strategy.get("portfolio_size")
    portfolio_size = float(portfolio_size or 100_000.0)
    if strategy_trades:
        strategy_trades, idle_cash = _strategy_trade_allocations(strategy, portfolio_size)
        per_symbol_equity = 0.0
    else:
        per_symbol_equity = portfolio_size / max(len(symbols), 1)
    per_symbol_results: List[Dict[str, Any]] = []

    for index, symbol in enumerate(symbols):
        events.append({"type": "backtest_symbol", "backtest_id": backtest["backtest_id"], "symbol": symbol, "status": "running", "timestamp": _utc_now()})
        store.update_backtest_run(backtest["backtest_id"], status="running", events=events)
        bars_15m = get_intraday_bars(symbol, "15m", payload["start_date"], payload["end_date"])
        bars_4h = get_intraday_bars(symbol, "4h", payload["start_date"], payload["end_date"])
        symbol_cfg = dict(config)
        if strategy_trades:
            trade_plan = strategy_trades[index]
            symbol_cfg.setdefault("risk_per_trade_pct", strategy.get("risk_per_trade", 0.01) if strategy else 0.01)
            symbol_cfg.setdefault("entry_mode", trade_plan.get("entry_mode") or (strategy.get("mode", "auto") if strategy else "auto"))
            initial_equity = float(trade_plan.get("allocated_equity", 0.0))
            backtest_result = run_trade_plan_backtest(symbol, bars_15m, trade_plan, initial_equity, symbol_cfg)
        else:
            if strategy:
                symbol_cfg.setdefault("risk_per_trade_pct", strategy.get("risk_per_trade", 0.01))
                symbol_cfg.setdefault("entry_mode", strategy.get("mode", "auto"))
            backtest_result = run_backtest(symbol, bars_15m, bars_4h, per_symbol_equity, symbol_cfg)
        symbol_payload = backtest_result.to_dict()
        symbol_payload["equity_curve"] = list(backtest_result.equity_curve)
        if walkforward_n_folds >= 2 and not strategy_trades:
            walk = run_walk_forward(
                symbol,
                bars_15m,
                bars_4h,
                n_folds=walkforward_n_folds,
                in_sample_ratio=walkforward_in_sample_ratio,
                initial_equity=per_symbol_equity,
                config=symbol_cfg,
            )
            symbol_payload["walkforward"] = walk.to_dict()
        if strategy_trades:
            symbol_payload["trade_plan"] = {
                "side": trade_plan.get("side"),
                "direction": trade_plan.get("direction"),
                "quantity": trade_plan.get("quantity"),
                "entry_price": trade_plan.get("entry_price"),
                "stop_price": trade_plan.get("stop_price"),
                "target_price": trade_plan.get("target_price"),
                "notional": trade_plan.get("notional"),
            }
        per_symbol_results.append(symbol_payload)
        events.append({"type": "backtest_symbol", "backtest_id": backtest["backtest_id"], "symbol": symbol, "status": "completed", "timestamp": _utc_now(), "trade_count": backtest_result.trade_count})
        store.update_backtest_run(backtest["backtest_id"], status="running", events=events)

    total_initial = round(portfolio_size, 4)
    total_final = round(idle_cash + sum(item["final_equity"] for item in per_symbol_results), 4)
    total_trades = sum(int(item["trade_count"]) for item in per_symbol_results)
    total_winners = sum(int(item["winning_trades"]) for item in per_symbol_results)
    win_rate = round(total_winners / total_trades, 4) if total_trades else 0.0
    aggregate_equity_curve = _aggregate_equity_curves(per_symbol_results, per_symbol_equity)
    if strategy_trades and aggregate_equity_curve:
        aggregate_equity_curve = [round(idle_cash + equity, 4) for equity in aggregate_equity_curve]
    result = {
        "headline": f"{len(symbols)} symbols backtested in quant_strict mode",
        "summary": {
            "initial_equity": total_initial,
            "final_equity": total_final,
            "total_return_pct": round(((total_final / total_initial) - 1.0) * 100.0, 4) if total_initial else 0.0,
            "trade_count": total_trades,
            "winning_trades": total_winners,
            "win_rate": win_rate,
            "symbols": symbols,
            "source": "saved_strategy" if strategy_trades else "symbol_list",
            "idle_cash": idle_cash,
        },
        "equity_curve": aggregate_equity_curve,
        "per_symbol": per_symbol_results,
        "execution_mode": "quant_strict",
    }
    events.append({"type": "backtest_status", "backtest_id": backtest["backtest_id"], "status": "completed", "execution_mode": "quant_strict", "timestamp": _utc_now()})
    store.update_backtest_run(backtest["backtest_id"], status="completed", result=result, events=events)
    return store.get_backtest_run(backtest["backtest_id"]) or backtest


def stage_futu_strategy(request: Dict[str, Any], store, settings: Dict[str, Any]) -> Dict[str, Any]:
    strategy = store.get_strategy_plan(request["strategy_id"]) if request.get("strategy_id") else None
    payload = dict(request)
    if not payload.get("orders") and strategy:
        payload["orders"] = [
            {
                "symbol": trade["symbol"],
                "side": trade["side"],
                "quantity": trade["quantity"],
                "entry_price": trade["entry_price"],
            }
            for trade in strategy.get("trades", [])
        ]
    payload["stage_only"] = True
    payload["submits_orders"] = False
    stage = store.create_broker_stage_request(
        payload,
        home_market=settings.get("home_market", "US"),
        workflow_session_id=payload.get("workflow_session_id"),
    )

    orders = list(payload.get("orders", []))
    if strategy and not strategy.get("allow_shorts", True):
        orders = [order for order in orders if str(order.get("side", "")).lower() != "sell"]

    if request.get("strategy_id") and strategy is None:
        response = {
            "status": "failed",
            "headline": "Strategy not found",
            "error": f"Unknown strategy_id {request['strategy_id']}",
            "stage_only": True,
            "submits_orders": False,
            "orders": [],
        }
        store.update_broker_stage_request(stage["stage_id"], status="failed", response=response, error=response["error"])
        return store.get_broker_stage_request(stage["stage_id"]) or stage

    if not orders:
        response = {
            "status": "failed",
            "headline": "No orders available to stage",
            "error": "Saved strategy did not produce any stageable orders.",
            "stage_only": True,
            "submits_orders": False,
            "orders": [],
        }
        store.update_broker_stage_request(stage["stage_id"], status="failed", response=response, error=response["error"])
        return store.get_broker_stage_request(stage["stage_id"]) or stage

    broker_cfg = settings.get("broker", {}).get("futu", {})
    from tradingagents.integrations.futu.opend import FutuStageOnlyAdapter

    adapter = FutuStageOnlyAdapter(
        host=broker_cfg.get("host", "127.0.0.1"),
        port=int(broker_cfg.get("port", 11111)),
        enabled=bool(broker_cfg.get("enabled", False)),
    )
    response = adapter.stage_orders(stage["stage_id"], orders)
    status = response.get("status", "failed")
    error = response.get("error")
    store.update_broker_stage_request(stage["stage_id"], status=status, response=response, error=error)
    return store.get_broker_stage_request(stage["stage_id"]) or stage
