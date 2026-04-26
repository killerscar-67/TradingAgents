"""LangChain @tool wrappers for intraday-mode data and indicators.

These tools route through `route_to_vendor` so vendor fallback works the
same way the daily tools do. Currently only yfinance implements the intraday
backend; Alpha Vantage intraday is not wired in v1.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_intraday_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    end_date: Annotated[str, "Session date (YYYY-MM-DD) — last day of bars to return"],
    interval: Annotated[str, "Bar interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h"] = "5m",
    lookback_days: Annotated[int, "Calendar days of bars to fetch back from end_date"] = 5,
    prepost: Annotated[bool, "Include premarket/aftermarket bars"] = False,
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
        prepost,
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
    prepost: Annotated[bool, "include premarket/aftermarket bars"] = False,
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
                symbol, ind, end_date, interval, lookback_days, prepost,
            ))
        except ValueError as e:
            results.append(str(e))
    return "\n\n".join(results)
