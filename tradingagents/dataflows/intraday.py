"""
Intraday bar module for 15m and 4h timeframes.

Design rules:
- All returned DataFrames have a timezone-aware UTC DatetimeIndex.
- Session-boundary enforcement: bars whose open timestamp is at or after
  ``as_of`` are stripped before returning (no-lookahead guarantee).
- Deterministic disk cache keyed by SHA-256 of (symbol, interval, start, end,
  session, vendor, cache_version).  Identical inputs always return identical
  data.
- Vendor routing: yfinance (default) or alpha_vantage (stub).

Public API:
    get_intraday_bars(symbol, interval, start, end, as_of=None, session="regular", ...)
    fetch_intraday_bars(symbol, interval, start, end, ...)        # no-cache variant
    IntradayInterval                                               # typed interval enum
    IntradaySession                                                # typed session enum
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Union

import pandas as pd

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

IntradayInterval = Literal["15m", "4h"]
IntradaySession = Literal["regular", "extended", "crypto"]

_VALID_INTERVALS: set[str] = {"15m", "4h"}
_VALID_SESSIONS: set[str] = {"regular", "extended", "crypto"}
_CACHE_VERSION = "v1"
_MIN_BARS_PER_4H_CANDLE = 2

# yfinance interval tokens
_YF_INTERVAL_MAP: dict[str, str] = {
    "15m": "15m",
    "4h": "1h",   # yfinance has no 4h; we resample from 1h
}

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    session: str,
    vendor: str = "yfinance",
) -> str:
    payload = json.dumps(
        {
            "v": _CACHE_VERSION,
            "symbol": symbol.upper(),
            "interval": interval,
            "start": start,
            "end": end,
            "session": session,
            "vendor": vendor,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def _cache_path(cache_dir: str, key: str) -> Path:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{key}.parquet"


def _load_cache(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            return None
        if df.index.tz is None:
            return None
        return df
    except Exception:
        return None


def _save_cache(path: Path, df: pd.DataFrame) -> None:
    try:
        df.to_parquet(path)
    except Exception:
        pass  # cache write failure is non-fatal


# ---------------------------------------------------------------------------
# Session / timezone alignment helpers
# ---------------------------------------------------------------------------


def _to_utc(ts: Union[datetime, pd.Timestamp]) -> pd.Timestamp:
    """Coerce timestamp to UTC-aware pd.Timestamp."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _is_live_end_date(end: str) -> bool:
    """Return True when end date is today or in the future (UTC)."""
    try:
        end_date = pd.Timestamp(end).date()
    except Exception:
        return False
    return end_date >= datetime.now(timezone.utc).date()


def _align_session(df: pd.DataFrame, session: str) -> pd.DataFrame:
    """Filter DataFrame to rows within the requested session boundaries.

    regular  — NYSE trading hours 09:30–16:00 ET (Mon–Fri)
    extended — pre/post market 04:00–20:00 ET (Mon–Fri)
    crypto   — 24 h, 7 days (no filter applied)
    """
    if df.empty or session == "crypto":
        return df

    import pytz

    et = pytz.timezone("America/New_York")
    idx_et = df.index.tz_convert(et)

    weekday_mask = idx_et.dayofweek < 5  # Mon=0 … Fri=4

    if session == "regular":
        hour_mask = (idx_et.hour > 9) | ((idx_et.hour == 9) & (idx_et.minute >= 30))
        hour_mask &= idx_et.hour < 16
        return df[weekday_mask & hour_mask]
    elif session == "extended":
        hour_mask = idx_et.hour >= 4
        hour_mask &= idx_et.hour < 20
        return df[weekday_mask & hour_mask]

    return df  # unknown session: return unfiltered


def _enforce_no_lookahead(df: pd.DataFrame, as_of: Optional[datetime]) -> pd.DataFrame:
    """Drop bars whose open timestamp is at or after ``as_of``.

    This guarantees that no future bar data is accessible to the strategy.
    """
    if as_of is None or df.empty:
        return df
    cutoff = _to_utc(as_of)
    return df[df.index < cutoff]


# ---------------------------------------------------------------------------
# Vendor: yfinance
# ---------------------------------------------------------------------------


def _resample_1h_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1h bars to 4h bars.  Sessions are already filtered before
    resampling so no cross-session aggregation occurs.

    We drop partial 4h windows that contain fewer than
    ``_MIN_BARS_PER_4H_CANDLE`` source bars to avoid generating unstable
    open/close candles around session boundaries and DST shifts.
    """
    if df.empty:
        return df

    ohlcv: dict = {}
    if "Open" in df.columns:
        ohlcv["Open"] = ("Open", "first")
    if "High" in df.columns:
        ohlcv["High"] = ("High", "max")
    if "Low" in df.columns:
        ohlcv["Low"] = ("Low", "min")
    if "Close" in df.columns:
        ohlcv["Close"] = ("Close", "last")
    if "Volume" in df.columns:
        ohlcv["Volume"] = ("Volume", "sum")

    resampled = df.resample("4h", closed="left", label="left").agg(**ohlcv)
    count_col = "Close" if "Close" in df.columns else df.columns[0]
    counts = df[count_col].resample("4h", closed="left", label="left").count()
    resampled = resampled[counts >= _MIN_BARS_PER_4H_CANDLE]
    return resampled.dropna(how="all")


def _fetch_yfinance(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    session: str,
    as_of: Optional[datetime] = None,
) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance is required for intraday data; install it with: pip install yfinance") from exc

    yf_interval = _YF_INTERVAL_MAP[interval]
    need_resample = interval == "4h"
    fetch_interval = yf_interval if not need_resample else "1h"

    premarket = session == "extended"
    ticker = yf.Ticker(symbol.upper())

    df: pd.DataFrame = ticker.history(
        start=start,
        end=end,
        interval=fetch_interval,
        prepost=premarket,
        auto_adjust=True,
    )

    if df.empty:
        return df

    # Normalise index to UTC-aware
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    # Keep only standard OHLCV columns
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].copy()

    # Session filter before resampling (avoids cross-session candles)
    df = _align_session(df, session)

    if need_resample:
        # Enforce no-lookahead on source bars before aggregation so a 4h
        # candle cannot include 1h bars that open at/after as_of.
        if as_of is not None:
            df = _enforce_no_lookahead(df, as_of)
        df = _resample_1h_to_4h(df)

    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_intraday_bars(
    symbol: str,
    interval: IntradayInterval,
    start: str,
    end: str,
    as_of: Optional[datetime] = None,
    session: IntradaySession = "regular",
    vendor: str = "yfinance",
) -> pd.DataFrame:
    """Fetch intraday bars without caching.

    Args:
        symbol: Ticker symbol (case-insensitive).
        interval: ``"15m"`` or ``"4h"``.
        start: Inclusive start date, ``"YYYY-MM-DD"``.
        end: Exclusive end date, ``"YYYY-MM-DD"``.
        as_of: If provided, bars at or after this timestamp are stripped
            (no-lookahead guarantee).  Pass the current strategy clock time.
        session: ``"regular"`` (NYSE hours), ``"extended"`` (pre/post), or
            ``"crypto"`` (24/7, no filter).
        vendor: Data vendor; currently only ``"yfinance"`` is implemented.

    Returns:
        UTC-indexed DataFrame with columns [Open, High, Low, Close, Volume].
        Empty DataFrame if no data is available.

    Raises:
        ValueError: On invalid ``interval`` or ``session`` values.
    """
    if interval not in _VALID_INTERVALS:
        raise ValueError(f"interval must be one of {sorted(_VALID_INTERVALS)!r}, got {interval!r}")
    if session not in _VALID_SESSIONS:
        raise ValueError(f"session must be one of {sorted(_VALID_SESSIONS)!r}, got {session!r}")

    if vendor == "yfinance":
        df = _fetch_yfinance(symbol, interval, start, end, session, as_of=as_of)
    else:
        raise NotImplementedError(f"Vendor {vendor!r} is not yet implemented for intraday data")

    return _enforce_no_lookahead(df, as_of)


def get_intraday_bars(
    symbol: str,
    interval: IntradayInterval,
    start: str,
    end: str,
    as_of: Optional[datetime] = None,
    session: IntradaySession = "regular",
    vendor: str = "yfinance",
    cache_dir: Optional[str] = None,
    refresh_cache: bool = False,
) -> pd.DataFrame:
    """Fetch intraday bars with deterministic disk cache.

    Cache key is a SHA-256 hash of (symbol, interval, start, end, session,
    vendor,
    cache_version).  ``as_of`` is intentionally excluded from the cache key
    because the full date range is fetched and stored; ``as_of`` trimming is
    applied after cache load to ensure the stored payload is reusable.

    Args:
        symbol: Ticker symbol.
        interval: ``"15m"`` or ``"4h"``.
        start: Inclusive start date, ``"YYYY-MM-DD"``.
        end: Exclusive end date, ``"YYYY-MM-DD"`` interpreted as a UTC
            calendar date. Local dates in UTC-ahead timezones may classify
            live vs historical ranges unexpectedly.
        as_of: No-lookahead cutoff (applied after cache load, not part of key).
        session: Session filter.
        vendor: Data vendor.
        cache_dir: Directory for parquet cache files.  Defaults to
            ``~/.tradingagents/cache/intraday``.
        refresh_cache: If ``True``, bypass the cache and re-fetch.

    Returns:
        UTC-indexed DataFrame with columns [Open, High, Low, Close, Volume].
    """
    if interval not in _VALID_INTERVALS:
        raise ValueError(f"interval must be one of {sorted(_VALID_INTERVALS)!r}, got {interval!r}")
    if session not in _VALID_SESSIONS:
        raise ValueError(f"session must be one of {sorted(_VALID_SESSIONS)!r}, got {session!r}")

    resolved_cache_dir = cache_dir or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "cache", "intraday"
    )
    key = _cache_key(symbol, interval, start, end, session, vendor=vendor)
    path = _cache_path(resolved_cache_dir, key)

    is_live = _is_live_end_date(end)   # capture once to avoid TOCTOU across UTC midnight
    df: Optional[pd.DataFrame] = None
    use_cache = (not refresh_cache) and (not is_live)
    if use_cache:
        df = _load_cache(path)

    if df is None:
        df = fetch_intraday_bars(
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            as_of=None,   # store full range; as_of trimming applied below
            session=session,
            vendor=vendor,
        )
        if not is_live:
            _save_cache(path, df)

    return _enforce_no_lookahead(df, as_of)
