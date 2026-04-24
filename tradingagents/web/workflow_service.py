"""Deterministic Phase 11 workflow services."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import yfinance as yf

from tradingagents.dataflows.interface import get_intraday_bars
from tradingagents.quant.backtest import run_backtest, run_trade_plan_backtest
from tradingagents.quant.contracts import EntryEngine, EntrySignal
from tradingagents.quant.risk import compute_stops, size_position
from tradingagents.quant.walkforward import run_walk_forward
from tradingagents.web import runner


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
CHART_PERIOD_LOOKBACK_DAYS = {
    "1D": 7,
    "1W": 14,
    "1M": 45,
    "3M": 120,
    "1Y": 400,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _resolve_screening_universe(universe: str, custom_symbols: List[str], home_market: str) -> Tuple[str, List[str]]:
    if custom_symbols:
        return "CUSTOM", [symbol.strip().upper() for symbol in custom_symbols if symbol.strip()]
    key = (universe or "").strip().lower()
    if key in UNIVERSE_ALIASES:
        _, symbols = UNIVERSE_ALIASES[key]
        return universe, list(symbols)
    market = home_market.upper() if home_market.upper() in MARKET_DEFINITIONS else "US"
    return universe or market, list(MARKET_DEFINITIONS[market]["universe"])


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

    downloaded = yf.download(
        active_symbols[0] if len(active_symbols) == 1 else active_symbols,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
        timeout=10,
    )
    if not isinstance(downloaded, pd.DataFrame):
        for symbol in active_symbols:
            result[symbol] = pd.DataFrame()
        return result

    if len(active_symbols) == 1:
        result[active_symbols[0]] = downloaded
        return result

    for symbol in active_symbols:
        frame = pd.DataFrame()
        if isinstance(downloaded.columns, pd.MultiIndex):
            if symbol in downloaded.columns.get_level_values(0):
                frame = downloaded.xs(symbol, axis=1, level=0, drop_level=True)
            elif symbol in downloaded.columns.get_level_values(downloaded.columns.nlevels - 1):
                frame = downloaded.xs(symbol, axis=1, level=downloaded.columns.nlevels - 1, drop_level=True)
        result[symbol] = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
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
        return {
            "pct_above_50d": 0.0,
            "pct_above_200d": 0.0,
            "new_highs_minus_lows": 0,
            "advance_decline_ratio": 0.0,
            "mcclellan_oscillator": 0.0,
            "headline": "Breadth unavailable",
        }

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
        records.append(
            {
                "timestamp": row.get("date"),
                "title": row.get("event") or row.get("name"),
                "impact": impact,
                "region": region or None,
            }
        )
    return records


def get_market_overview(home_market: str, trade_date: Optional[str], settings: Dict[str, Any]) -> Dict[str, Any]:
    resolved_market = home_market.upper() if home_market.upper() in MARKET_DEFINITIONS else settings.get("home_market", "US")
    as_of_date = trade_date or date.today().isoformat()
    start = (datetime.fromisoformat(as_of_date) - timedelta(days=400)).date().isoformat()
    end = (datetime.fromisoformat(as_of_date) + timedelta(days=1)).date().isoformat()

    region_payloads: Dict[str, Dict[str, Any]] = {}
    for region, definition in MARKET_DEFINITIONS.items():
        tile_symbols = [tile["symbol"] for tile in definition["tiles"]]
        histories = _download_daily_history(tile_symbols + definition["universe"], start, end)
        benchmark_history = histories.get(definition["tiles"][0]["symbol"], pd.DataFrame())
        volatility_history = histories.get(definition["vol_symbol"], pd.DataFrame()) if definition.get("vol_symbol") else None
        breadth = _compute_breadth({symbol: histories.get(symbol, pd.DataFrame()) for symbol in definition["universe"]})

        credit_change_pct = None
        credit_symbols = definition.get("credit_symbols")
        if credit_symbols:
            credit_histories = _download_daily_history(list(credit_symbols), start, end)
            hyg = credit_histories.get(credit_symbols[0], pd.DataFrame())
            ief = credit_histories.get(credit_symbols[1], pd.DataFrame())
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
        sector_histories = _download_daily_history([symbol for symbol, _ in definition["sector_proxies"]], start, end)
        for symbol, label in definition["sector_proxies"]:
            hist = sector_histories.get(symbol, pd.DataFrame())
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

    events = _fetch_calendar_events(
        settings.get("calendar_provider", "fmp"),
        [resolved_market],
        as_of_date,
        (datetime.fromisoformat(as_of_date) + timedelta(days=1)).date().isoformat(),
    )
    home_payload = region_payloads[resolved_market]
    home_payload["regime"]["event_risk_flag"] = any(event.get("impact") == "high" for event in events)

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
        "regions": regions,
        "stream": {
            "status": settings.get("live_quote_mode", "delayed_fallback"),
            "transport": "websocket",
            "provider": settings.get("data_vendors", {}).get("market", "yfinance"),
        },
    }


def get_market_chart(symbol: str, period: str = "1M", trade_date: Optional[str] = None) -> Dict[str, Any]:
    normalized_symbol = (symbol or "").strip().upper()
    normalized_period = (period or "1M").strip().upper()

    if not normalized_symbol:
        return {"symbol": "", "period": normalized_period, "points": [], "bars": []}

    as_of_date = trade_date or date.today().isoformat()
    lookback_days = CHART_PERIOD_LOOKBACK_DAYS.get(normalized_period, CHART_PERIOD_LOOKBACK_DAYS["1M"])
    start = (datetime.fromisoformat(as_of_date) - timedelta(days=lookback_days)).date().isoformat()
    end = (datetime.fromisoformat(as_of_date) + timedelta(days=1)).date().isoformat()
    history = _download_daily_history([normalized_symbol], start, end).get(normalized_symbol, pd.DataFrame())

    close_series = _history_series(history, "Close")
    points: List[Dict[str, Any]] = []
    for timestamp, value in close_series.items():
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        points.append({"time": int(ts.timestamp()), "value": round(float(value), 4)})

    ohlc = pd.concat(
        [
            _history_series(history, "Open").rename("open"),
            _history_series(history, "High").rename("high"),
            _history_series(history, "Low").rename("low"),
            _history_series(history, "Close").rename("close"),
        ],
        axis=1,
    ).dropna(subset=["open", "high", "low", "close"])

    bars: List[Dict[str, Any]] = []
    for timestamp, row in ohlc.iterrows():
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        bars.append(
            {
                "time": int(ts.timestamp()),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
            }
        )

    return {
        "symbol": normalized_symbol,
        "period": normalized_period,
        "points": points,
        "bars": bars,
    }


def run_screening(request: Dict[str, Any], store, settings: Dict[str, Any]) -> Dict[str, Any]:
    home_market = settings.get("home_market", "US")
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
    threshold = float(request.get("min_score", settings_defaults.get("min_score", 0.65)))
    top_n = int(request.get("top_n", settings_defaults.get("top_n", 20)))
    overview = get_market_overview(screening_run["home_market"], trade_date, settings)

    results: List[Dict[str, Any]] = []
    start = (datetime.fromisoformat(trade_date) - timedelta(days=45)).date().isoformat()
    for symbol in symbols:
        market = _market_for_symbol(symbol, screening_run["home_market"])
        region_regime = overview["regions"].get(market, {}).get("regime", {})
        strategy = request.get("strategy", "auto")
        entry_mode = region_regime.get("suggested_entry_mode", "auto") if strategy == "auto" else strategy
        try:
            bars_15m = get_intraday_bars(symbol, "15m", start, trade_date)
            bars_4h = get_intraday_bars(symbol, "4h", start, trade_date)
            from tradingagents.quant.engine import run_quant_engine

            contract = run_quant_engine(symbol, trade_date, bars_15m, bars_4h, {"entry_mode": entry_mode})
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
        if result["score"] >= threshold:
            results.append(result)

    results.sort(key=lambda item: (item.get("score", -999.0), item.get("confidence") or -1.0), reverse=True)
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
        "summary": f"{len(results)} candidates scored",
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
    events: List[Dict[str, Any]] = [{"type": "batch_status", "batch_id": batch["batch_id"], "status": "queued", "timestamp": _utc_now()}]
    items: List[Dict[str, Any]] = []
    store.update_analysis_batch(batch["batch_id"], status="running", items=items, summary={"counts": _batch_counts(items)}, events=events)

    for symbol in payload.get("symbols", []):
        run = runner.create_run(
            ticker=symbol,
            analysis_date=payload.get("analysis_date"),
            selected_analysts=payload.get("selected_analysts", []),
            execution_mode=payload.get("execution_mode", "llm_assisted"),
            llm_provider=payload.get("llm_provider", "openai"),
            deep_think_llm=payload.get("deep_think_llm", settings.get("deep_think_llm", "gpt-5.4")),
            quick_think_llm=payload.get("quick_think_llm", settings.get("quick_think_llm", "gpt-5.4-mini")),
        )
        item = {"symbol": symbol, "run_id": run.run_id, "status": "running", "started_at": _utc_now()}
        items.append(item)
        events.append({"type": "batch_item", "batch_id": batch["batch_id"], "symbol": symbol, "run_id": run.run_id, "status": "running", "timestamp": _utc_now()})
        store.update_analysis_batch(batch["batch_id"], status="running", items=items, summary={"counts": _batch_counts(items)}, events=events)

        try:
            completed = runner.run_sync(run.run_id)
            if completed is None:
                raise RuntimeError("analysis run did not return a result")
            final_order = completed.final_order_intent or {}
            item.update(
                {
                    "status": "completed" if completed.status == "completed" else "failed",
                    "completed_at": _utc_now(),
                    "rating": final_order.get("rating", "HOLD"),
                    "summary": completed.report_sections.get("final_trade_decision") or final_order.get("reason") or "",
                    "report_paths": completed.report_paths,
                    "order_intent": final_order,
                    "error": "; ".join(completed.errors) if completed.errors else None,
                }
            )
        except Exception as exc:
            item.update({"status": "failed", "completed_at": _utc_now(), "error": str(exc), "rating": "HOLD", "summary": str(exc)})

        events.append({"type": "batch_item", "batch_id": batch["batch_id"], "symbol": symbol, "run_id": run.run_id, "status": item["status"], "timestamp": _utc_now()})
        store.update_analysis_batch(batch["batch_id"], status="running", items=items, summary={"counts": _batch_counts(items)}, events=events)

    counts = _batch_counts(items)
    final_status = _batch_terminal_status(counts)
    summary = {
        "counts": counts,
        "title": f"{len(items)} ticker batch",
        "headline": f"{counts['completed']} completed, {counts['failed']} failed",
        "completed_at": _utc_now(),
    }
    events.append({"type": "batch_status", "batch_id": batch["batch_id"], "status": final_status, "timestamp": _utc_now(), "counts": counts})
    store.update_analysis_batch(batch["batch_id"], status=final_status, items=items, summary=summary, events=events)
    return store.get_analysis_batch(batch["batch_id"]) or batch


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
