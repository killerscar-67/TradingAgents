"""LangChain @tool wrappers for intraday-mode data and indicators.

These tools route through `route_to_vendor` so vendor fallback works the
same way the daily tools do. Currently only yfinance implements the intraday
backend; Alpha Vantage intraday is not wired in v1.
"""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.session import resolve_session_context


def _resolve_prepost(prepost: Optional[bool]) -> bool:
    if prepost is None:
        return bool(get_config().get("include_extended_hours", True))
    return bool(prepost)


@tool
def get_session_context(
    when: Annotated[str, "ISO 8601 datetime (e.g. 2025-04-24T10:30:00-04:00) or YYYY-MM-DD"],
) -> str:
    """
    Resolve the trading-session context for a given moment.

    Returns the session phase (premarket/morning/midday/power_hour/close/postmarket/closed),
    minutes remaining until 16:00 ET, and the date whose bars should be used
    (same day during premarket/postmarket; walks back when fully closed).
    """
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(when)
    except ValueError:
        dt = datetime.strptime(when, "%Y-%m-%d")
    ctx = resolve_session_context(dt)
    return (
        f"Requested moment: {ctx.requested_dt.isoformat()}\n"
        f"Session phase: {ctx.session_phase}\n"
        f"Minutes to close: {ctx.minutes_to_close}\n"
        f"Data session date: {ctx.data_session_date}\n"
        f"Walked back to prior session: {ctx.walked_back}"
    )


@tool
def get_intraday_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    end_date: Annotated[str, "Session date (YYYY-MM-DD) — last day of bars to return"],
    interval: Annotated[str, "Bar interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h"] = "5m",
    lookback_days: Annotated[int, "Calendar days of bars to fetch back from end_date"] = 5,
    prepost: Annotated[Optional[bool], "Include premarket/aftermarket bars"] = None,
) -> str:
    """
    Retrieve intraday OHLCV bars for a ticker.

    Lookback is capped per yfinance: 1m=7d, 5m/15m/30m=60d, 60m/1h=730d.
    Returns CSV-formatted bars with timezone-naive timestamps in the
    exchange-local timezone.
    """
    return route_to_vendor(
        "get_intraday_stock_data",
        symbol,
        end_date,
        interval,
        lookback_days,
        _resolve_prepost(prepost),
    )


@tool
def get_intraday_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[
        str,
        "intraday indicator name (e.g. vwap, orb_high_15, rel_volume, fast_rsi_7, "
        "fast_macd_hist, keltner_upper, session_atr)",
    ],
    end_date: Annotated[str, "session date (YYYY-MM-DD)"],
    interval: Annotated[str, "bar interval"] = "5m",
    lookback_days: Annotated[int, "calendar days of bars to load"] = 30,
    prepost: Annotated[Optional[bool], "include premarket/aftermarket bars"] = None,
) -> str:
    """
    Compute one intraday technical indicator. Pass one indicator name per call.
    Comma-separated names are split and computed sequentially.
    """
    indicators = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            results.append(route_to_vendor(
                "get_intraday_indicators",
                symbol, ind, end_date, interval, lookback_days, _resolve_prepost(prepost),
            ))
        except ValueError as e:
            results.append(str(e))
    return "\n\n".join(results)
