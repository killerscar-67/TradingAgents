import time
import logging

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from stockstats import wrap
from typing import Annotated
import os
from .config import get_config

logger = logging.getLogger(__name__)


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


# yfinance lookback caps per interval (see https://yfinance-python.org).
# Hard limits enforced by Yahoo: requests beyond these silently truncate.
_INTRADAY_MAX_LOOKBACK_DAYS = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1h": 730,
}


def load_ohlcv_intraday(
    symbol: str,
    end_date: str,
    interval: str = "5m",
    lookback_days: int = 5,
    prepost: bool = False,
) -> pd.DataFrame:
    """Fetch intraday OHLCV bars with per-day caching.

    Cache key is (symbol, interval, end_date, prepost) so daily and intraday
    caches never collide and different sessions stay separate. Honors
    yfinance's interval-specific lookback caps and raises ValueError if the
    caller asks for more history than Yahoo will serve.
    """
    if interval not in _INTRADAY_MAX_LOOKBACK_DAYS:
        raise ValueError(
            f"Interval '{interval}' not supported for intraday loads. "
            f"Allowed: {sorted(_INTRADAY_MAX_LOOKBACK_DAYS.keys())}"
        )
    max_lookback = _INTRADAY_MAX_LOOKBACK_DAYS[interval]
    if lookback_days > max_lookback:
        raise ValueError(
            f"yfinance only serves {max_lookback}d of {interval} bars; "
            f"requested {lookback_days}d. Use a coarser interval or shorter window."
        )

    config = get_config()
    end_dt = pd.to_datetime(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    # End is exclusive in yfinance — bump by one day so we include `end_date`.
    fetch_end = end_dt + pd.Timedelta(days=1)

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    prepost_tag = "ext" if prepost else "rth"
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{symbol}-YFin-intraday-{interval}-{prepost_tag}-"
        f"{start_dt.date().isoformat()}-{end_dt.date().isoformat()}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip")
    else:
        ticker = yf.Ticker(symbol.upper())
        data = yf_retry(lambda: ticker.history(
            start=start_dt.strftime("%Y-%m-%d"),
            end=fetch_end.strftime("%Y-%m-%d"),
            interval=interval,
            prepost=prepost,
            auto_adjust=True,
        ))
        if data.empty:
            return data
        # Strip tz so downstream stockstats wrappers don't trip on tz-aware index.
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        data = data.reset_index()
        # Yahoo uses "Datetime" for intraday; rename to "Date" so _clean_dataframe works.
        if "Datetime" in data.columns:
            data = data.rename(columns={"Datetime": "Date"})
        data.to_csv(data_file, index=False)

    if data.empty:
        return data

    data = _clean_dataframe(data)
    # Filter to end_date inclusive to prevent look-ahead (intraday backtests).
    data = data[data["Date"] <= end_dt + pd.Timedelta(days=1)]
    return data


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 15 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    # Cache uses a fixed window (15y to today) so one file per symbol
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip")
    else:
        data = yf_retry(lambda: yf.download(
            symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        data = data.reset_index()
        data.to_csv(data_file, index=False)

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
