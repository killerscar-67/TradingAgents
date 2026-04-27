"""Regime classifier: trending / ranging / consolidation + tradability gate.

All computations are deterministic: same DataFrame input → identical output.
No LLM calls, no mutable module-level state.

Public API:
    classify(bars, config) -> RegimeContract
"""

from __future__ import annotations

from typing import Dict, Literal, Optional

import pandas as pd

from .contracts import RegimeContract, RegimeLabel

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_ADX_PERIOD = 14
_DEFAULT_ATR_PERIOD = 14
_DEFAULT_BB_PERIOD = 20
_DEFAULT_ADX_TRENDING_THRESHOLD = 25.0
_DEFAULT_ADX_RANGING_THRESHOLD = 20.0
_DEFAULT_MIN_ATR_PCT = 0.001          # 0.1 % minimum move — below this = dead market
_DEFAULT_MIN_VOLUME = 100_000
_DEFAULT_HTF_SMA_PERIOD = 20
_DEFAULT_HTF_BIAS_NEUTRAL_PCT = 0.005  # ±0.5 % of SMA → "neutral"


# ---------------------------------------------------------------------------
# Indicator helpers (pure functions, no side effects)
# ---------------------------------------------------------------------------


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RMA (exponential smoothing with alpha = 1/period)."""
    alpha = 1.0 / period
    return series.ewm(alpha=alpha, adjust=False).mean()


def _true_range(bars: pd.DataFrame) -> pd.Series:
    high = bars["High"]
    low = bars["Low"]
    prev_close = bars["Close"].shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def compute_atr(bars: pd.DataFrame, period: int = _DEFAULT_ATR_PERIOD) -> pd.Series:
    """Average True Range via Wilder smoothing."""
    return _wilder_smooth(_true_range(bars), period)


def compute_adx(
    bars: pd.DataFrame, period: int = _DEFAULT_ADX_PERIOD
) -> pd.DataFrame:
    """Return DataFrame with columns [adx, plus_di, minus_di]."""
    high = bars["High"]
    low = bars["Low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = _true_range(bars)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr = _wilder_smooth(tr, period)
    safe_atr = atr.replace(0.0, float("nan"))
    plus_di = 100.0 * _wilder_smooth(plus_dm, period) / safe_atr
    minus_di = 100.0 * _wilder_smooth(minus_dm, period) / safe_atr

    di_sum = (plus_di + minus_di).replace(0.0, float("nan"))
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum

    adx = _wilder_smooth(dx.fillna(0.0), period)
    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di})


def _htf_bias(
    bars: pd.DataFrame,
    sma_period: int,
    neutral_pct: float,
) -> Literal["bullish", "bearish", "neutral"]:
    if len(bars) < sma_period:
        return "neutral"
    sma = bars["Close"].rolling(sma_period).mean()
    last_close = float(bars["Close"].iloc[-1])
    last_sma = float(sma.iloc[-1])
    if pd.isna(last_sma) or last_sma == 0.0:
        return "neutral"
    deviation = (last_close - last_sma) / last_sma
    if deviation > neutral_pct:
        return "bullish"
    if deviation < -neutral_pct:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(
    bars: pd.DataFrame,
    config: Optional[Dict] = None,
) -> RegimeContract:
    """Classify market regime from OHLCV bars.

    Args:
        bars: UTC-indexed OHLCV DataFrame (4h bars recommended for HTF context).
              Must have columns: Open, High, Low, Close, Volume (Volume optional).
        config: Parameter overrides. Accepted keys:
            adx_period (int, default 14)
            atr_period (int, default 14)
            bb_period (int, default 20)
            adx_trending_threshold (float, default 25.0)
            adx_ranging_threshold (float, default 20.0)
            min_atr_pct (float, default 0.001)
            min_volume (float, default 100_000)
            htf_sma_period (int, default 20)
            htf_bias_neutral_pct (float, default 0.005)

    Returns:
        RegimeContract — deterministic for identical inputs.
    """
    cfg: Dict = config or {}
    adx_period = int(cfg.get("adx_period", _DEFAULT_ADX_PERIOD))
    atr_period = int(cfg.get("atr_period", _DEFAULT_ATR_PERIOD))
    bb_period = int(cfg.get("bb_period", _DEFAULT_BB_PERIOD))
    trending_thr = float(cfg.get("adx_trending_threshold", _DEFAULT_ADX_TRENDING_THRESHOLD))
    ranging_thr = float(cfg.get("adx_ranging_threshold", _DEFAULT_ADX_RANGING_THRESHOLD))
    min_atr_pct = float(cfg.get("min_atr_pct", _DEFAULT_MIN_ATR_PCT))
    min_volume = float(cfg.get("min_volume", _DEFAULT_MIN_VOLUME))
    htf_sma_period = int(cfg.get("htf_sma_period", _DEFAULT_HTF_SMA_PERIOD))
    neutral_pct = float(cfg.get("htf_bias_neutral_pct", _DEFAULT_HTF_BIAS_NEUTRAL_PCT))

    min_bars_needed = max(adx_period * 2, atr_period * 2, htf_sma_period, bb_period) + 1

    if bars.empty or len(bars) < min_bars_needed:
        return RegimeContract(
            label=RegimeLabel.CONSOLIDATION,
            tradable=False,
            adx=0.0,
            atr=0.0,
            atr_pct=0.0,
            htf_bias="neutral",
        )

    last_close = float(bars["Close"].iloc[-1])

    atr_series = compute_atr(bars, atr_period)
    last_atr = float(atr_series.iloc[-1])
    atr_pct = (last_atr / last_close) if last_close > 0.0 else 0.0

    adx_df = compute_adx(bars, adx_period)
    last_adx = float(adx_df["adx"].iloc[-1])

    # --- Regime label ---
    if last_adx >= trending_thr:
        label = RegimeLabel.TRENDING
    elif last_adx <= ranging_thr:
        # Distinguish consolidation (very tight BB) from ranging (oscillating)
        if len(bars) >= bb_period:
            close_std = float(bars["Close"].rolling(bb_period).std().iloc[-1])
            bb_width_pct = (2.0 * close_std / last_close) if last_close > 0.0 else 0.0
            label = (
                RegimeLabel.CONSOLIDATION
                if bb_width_pct < min_atr_pct * 2.0
                else RegimeLabel.RANGING
            )
        else:
            label = RegimeLabel.RANGING
    else:
        # ADX between thresholds → transitional, treat as ranging
        label = RegimeLabel.RANGING

    # --- Tradability filter ---
    vol_ok = True
    if "Volume" in bars.columns:
        avg_vol = bars["Volume"].rolling(min(20, len(bars))).mean().iloc[-1]
        if not pd.isna(avg_vol):
            vol_ok = float(avg_vol) >= min_volume

    tradable = (atr_pct >= min_atr_pct) and vol_ok

    bias = _htf_bias(bars, htf_sma_period, neutral_pct)

    return RegimeContract(
        label=label,
        tradable=tradable,
        adx=round(last_adx, 4),
        atr=round(last_atr, 6),
        atr_pct=round(atr_pct, 6),
        htf_bias=bias,
    )
