"""Intraday-tuned technical indicators.

Operates on bar DataFrames produced by load_ohlcv_intraday. All indicators
are computed locally — no vendor routing — because the inputs (session
boundaries, opening-range windows, time-of-day buckets) are domain-specific
and not exposed by Alpha Vantage's flat indicator API.
"""
from __future__ import annotations

from typing import Annotated, Optional

import pandas as pd

from .session import RTH_OPEN, _session_tz, to_session_tz
from .stockstats_utils import load_ohlcv_intraday


SUPPORTED_INTRADAY_INDICATORS = {
    "vwap": (
        "Session VWAP anchored to today's RTH open. Mean-reversion target on "
        "trend days; rejection/reclaim levels on range days."
    ),
    "orb_high_5": "Opening range high over the first 5 minutes of RTH (09:30-09:35).",
    "orb_low_5": "Opening range low over the first 5 minutes of RTH.",
    "orb_high_15": "Opening range high over the first 15 minutes of RTH (09:30-09:45).",
    "orb_low_15": "Opening range low over the first 15 minutes of RTH.",
    "orb_high_30": "Opening range high over the first 30 minutes of RTH (09:30-10:00).",
    "orb_low_30": "Opening range low over the first 30 minutes of RTH.",
    "rel_volume": (
        "Cumulative session volume divided by 20-session average cumulative "
        "volume at the same minute-of-day. >1.5 = unusually heavy."
    ),
    "fast_rsi_7": "RSI(7) on intraday closes. 80/20 thresholds for intraday extremes.",
    "fast_stoch_k": "Stochastic %K(5,3,3) on intraday bars.",
    "fast_stoch_d": "Stochastic %D(5,3,3) on intraday bars.",
    "fast_macd": "MACD(5,13,4) line on intraday bars.",
    "fast_macd_signal": "MACD(5,13,4) signal line on intraday bars.",
    "fast_macd_hist": "MACD(5,13,4) histogram on intraday bars.",
    "keltner_upper": "Keltner channel upper (EMA20 + 2*ATR14).",
    "keltner_lower": "Keltner channel lower (EMA20 - 2*ATR14).",
    "session_atr": "ATR(14) computed on the current session's bars only.",
    "gap_percent": (
        "Today's RTH open vs prior session's close, in percent. "
        ">+1% gap up or <-1% gap down typically warrants different playbooks "
        "(gap-and-go vs gap-fill). Returns null if today's open or prior close is missing."
    ),
}


def _ensure_session_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Add a tz-aware 'SessionDate' column for grouping by trading day."""
    if df.empty:
        return df
    df = df.copy()
    # Bars from yfinance arrive in exchange-local naive form post-cleaning.
    # Re-attach the session tz so we can isolate today's RTH bars.
    df["Date"] = pd.to_datetime(df["Date"])
    if df["Date"].dt.tz is None:
        df["Date"] = df["Date"].dt.tz_localize(_session_tz(), nonexistent="shift_forward", ambiguous="NaT")
    else:
        df["Date"] = df["Date"].dt.tz_convert(_session_tz())
    df = df.dropna(subset=["Date"])
    df["SessionDate"] = df["Date"].dt.date
    return df


def _filter_to_session(df: pd.DataFrame, session_date: str, rth_only: bool = True) -> pd.DataFrame:
    target = pd.to_datetime(session_date).date()
    out = df[df["SessionDate"] == target]
    if rth_only and not out.empty:
        out = out[(out["Date"].dt.time >= RTH_OPEN) & (out["Date"].dt.time < pd.Timestamp("16:00").time())]
    return out


def session_vwap(df: pd.DataFrame, session_date: str) -> Optional[float]:
    """Volume-weighted average price for the session, anchored to RTH open."""
    df = _ensure_session_tz(df)
    s = _filter_to_session(df, session_date, rth_only=True)
    if s.empty:
        return None
    typical = (s["High"] + s["Low"] + s["Close"]) / 3.0
    vol = s["Volume"]
    cum_vol = vol.cumsum()
    if cum_vol.iloc[-1] == 0:
        return None
    return float((typical * vol).cumsum().iloc[-1] / cum_vol.iloc[-1])


def opening_range(df: pd.DataFrame, session_date: str, minutes: int = 15) -> Optional[tuple[float, float]]:
    """High/low over the first N minutes of RTH for a given session date."""
    df = _ensure_session_tz(df)
    s = _filter_to_session(df, session_date, rth_only=True)
    if s.empty:
        return None
    cutoff = (pd.Timestamp(session_date).tz_localize(_session_tz()) +
              pd.Timedelta(hours=RTH_OPEN.hour, minutes=RTH_OPEN.minute + minutes))
    window = s[s["Date"] < cutoff]
    if window.empty:
        return None
    return float(window["High"].max()), float(window["Low"].min())


def relative_volume(df: pd.DataFrame, session_date: str) -> Optional[float]:
    """Today's cumulative RTH volume divided by 20-session average to same time-of-day.

    Requires at least 5 prior sessions of bars in df. Returns None otherwise.
    """
    df = _ensure_session_tz(df)
    today = _filter_to_session(df, session_date, rth_only=True)
    if today.empty:
        return None

    # Minutes-since-open for the most recent bar today.
    last_bar = today["Date"].iloc[-1]
    open_dt = (pd.Timestamp(session_date).tz_localize(_session_tz()) +
               pd.Timedelta(hours=RTH_OPEN.hour, minutes=RTH_OPEN.minute))
    minutes_in = int((last_bar - open_dt).total_seconds() // 60)
    if minutes_in <= 0:
        return None

    cutoff_today = open_dt + pd.Timedelta(minutes=minutes_in)
    today_cum = float(today[today["Date"] <= cutoff_today]["Volume"].sum())

    prior_sessions = sorted(d for d in df["SessionDate"].unique()
                            if d < pd.to_datetime(session_date).date())
    if len(prior_sessions) < 5:
        return None

    cum_vols = []
    for d in prior_sessions[-20:]:
        prior = _filter_to_session(df, d.isoformat(), rth_only=True)
        if prior.empty:
            continue
        prior_open = (pd.Timestamp(d).tz_localize(_session_tz()) +
                      pd.Timedelta(hours=RTH_OPEN.hour, minutes=RTH_OPEN.minute))
        cutoff = prior_open + pd.Timedelta(minutes=minutes_in)
        window = prior[prior["Date"] <= cutoff]
        if not window.empty:
            cum_vols.append(float(window["Volume"].sum()))

    if not cum_vols:
        return None
    avg = sum(cum_vols) / len(cum_vols)
    if avg == 0:
        return None
    return today_cum / avg


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_pc = (df["High"] - df["Close"].shift()).abs()
    low_pc = (df["Low"] - df["Close"].shift()).abs()
    return pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)


def fast_rsi(df: pd.DataFrame, period: int = 7) -> Optional[float]:
    if len(df) < period + 1:
        return None
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    # When loss == 0 and gain > 0, RSI is 100; tiny epsilon prevents NaN.
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return None if pd.isna(val) else float(val)


def fast_stochastic(df: pd.DataFrame, k: int = 5, d: int = 3, smooth: int = 3) -> Optional[tuple[float, float]]:
    if len(df) < k + d + smooth:
        return None
    low_k = df["Low"].rolling(k).min()
    high_k = df["High"].rolling(k).max()
    raw_k = 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, pd.NA)
    k_smooth = raw_k.rolling(smooth).mean()
    d_line = k_smooth.rolling(d).mean()
    if pd.isna(k_smooth.iloc[-1]) or pd.isna(d_line.iloc[-1]):
        return None
    return float(k_smooth.iloc[-1]), float(d_line.iloc[-1])


def fast_macd(df: pd.DataFrame, fast: int = 5, slow: int = 13, signal: int = 4) -> Optional[tuple[float, float, float]]:
    if len(df) < slow + signal:
        return None
    macd_line = _ema(df["Close"], fast) - _ema(df["Close"], slow)
    sig_line = _ema(macd_line, signal)
    hist = macd_line - sig_line
    return float(macd_line.iloc[-1]), float(sig_line.iloc[-1]), float(hist.iloc[-1])


def keltner_channels(df: pd.DataFrame, ema_period: int = 20, atr_period: int = 14, mult: float = 2.0) -> Optional[tuple[float, float]]:
    if len(df) < max(ema_period, atr_period) + 1:
        return None
    ema = _ema(df["Close"], ema_period)
    atr = _true_range(df).rolling(atr_period).mean()
    if pd.isna(ema.iloc[-1]) or pd.isna(atr.iloc[-1]):
        return None
    return float(ema.iloc[-1] + mult * atr.iloc[-1]), float(ema.iloc[-1] - mult * atr.iloc[-1])


def gap_percent(df: pd.DataFrame, session_date: str) -> Optional[float]:
    """Today's RTH open vs prior session's RTH close, expressed as percent.

    Requires at least one prior session of bars. Returns None when today's
    opening bar or the prior session's closing bar is missing.
    """
    df = _ensure_session_tz(df)
    today = _filter_to_session(df, session_date, rth_only=True)
    if today.empty:
        return None
    today_open = float(today["Open"].iloc[0])

    prior_sessions = sorted(d for d in df["SessionDate"].unique()
                            if d < pd.to_datetime(session_date).date())
    if not prior_sessions:
        return None
    prior = _filter_to_session(df, prior_sessions[-1].isoformat(), rth_only=True)
    if prior.empty:
        return None
    prior_close = float(prior["Close"].iloc[-1])
    if prior_close == 0:
        return None
    return (today_open - prior_close) / prior_close * 100.0


def session_atr(df: pd.DataFrame, session_date: str, period: int = 14) -> Optional[float]:
    df = _ensure_session_tz(df)
    s = _filter_to_session(df, session_date, rth_only=True)
    if len(s) < period + 1:
        return None
    atr = _true_range(s).rolling(period).mean().iloc[-1]
    return None if pd.isna(atr) else float(atr)


def get_intraday_indicators_window(
    symbol: Annotated[str, "ticker symbol"],
    indicator: Annotated[str, "intraday indicator name (see SUPPORTED_INTRADAY_INDICATORS)"],
    end_date: Annotated[str, "session date (YYYY-MM-DD)"],
    interval: Annotated[str, "bar interval"] = "5m",
    lookback_days: Annotated[int, "calendar days of bars to load"] = 30,
    prepost: Annotated[bool, "include premarket/aftermarket bars"] = False,
) -> str:
    """Compute one intraday indicator and return as a formatted string.

    Loads bars via load_ohlcv_intraday (cached), then dispatches to the
    appropriate compute function. Returns a markdown-friendly string with
    the value and the indicator's playbook description.
    """
    if indicator not in SUPPORTED_INTRADAY_INDICATORS:
        raise ValueError(
            f"Indicator '{indicator}' not supported intraday. "
            f"Choose from: {sorted(SUPPORTED_INTRADAY_INDICATORS.keys())}"
        )

    df = load_ohlcv_intraday(
        symbol.upper(),
        end_date=end_date,
        interval=interval,
        lookback_days=lookback_days,
        prepost=prepost,
    )
    if df.empty:
        return f"No intraday bars available for {symbol} on {end_date}"

    # For session-relative indicators we need today's bars; otherwise use whole window.
    session_today = _filter_to_session(_ensure_session_tz(df), end_date, rth_only=True)

    description = SUPPORTED_INTRADAY_INDICATORS[indicator]
    val: object = None

    if indicator == "vwap":
        val = session_vwap(df, end_date)
    elif indicator.startswith("orb_"):
        # orb_high_5 / orb_low_15 etc.
        parts = indicator.split("_")
        side, mins = parts[1], int(parts[2])
        rng = opening_range(df, end_date, minutes=mins)
        if rng is not None:
            val = rng[0] if side == "high" else rng[1]
    elif indicator == "rel_volume":
        val = relative_volume(df, end_date)
    elif indicator == "fast_rsi_7":
        val = fast_rsi(session_today if not session_today.empty else df, period=7)
    elif indicator == "fast_stoch_k":
        out = fast_stochastic(session_today if not session_today.empty else df)
        val = None if out is None else out[0]
    elif indicator == "fast_stoch_d":
        out = fast_stochastic(session_today if not session_today.empty else df)
        val = None if out is None else out[1]
    elif indicator == "fast_macd":
        out = fast_macd(session_today if not session_today.empty else df)
        val = None if out is None else out[0]
    elif indicator == "fast_macd_signal":
        out = fast_macd(session_today if not session_today.empty else df)
        val = None if out is None else out[1]
    elif indicator == "fast_macd_hist":
        out = fast_macd(session_today if not session_today.empty else df)
        val = None if out is None else out[2]
    elif indicator == "keltner_upper":
        out = keltner_channels(session_today if not session_today.empty else df)
        val = None if out is None else out[0]
    elif indicator == "keltner_lower":
        out = keltner_channels(session_today if not session_today.empty else df)
        val = None if out is None else out[1]
    elif indicator == "session_atr":
        val = session_atr(df, end_date)
    elif indicator == "gap_percent":
        val = gap_percent(df, end_date)

    if val is None:
        rendered = "N/A: insufficient data"
    elif isinstance(val, float):
        rendered = f"{val:.4f}"
    else:
        rendered = str(val)

    return (
        f"## {indicator} for {symbol.upper()} on {end_date} ({interval} bars):\n\n"
        f"{rendered}\n\n"
        f"{description}"
    )
