"""Validation filters applied after entry signal confirmation.

Each filter is independently togglable via config flags. All filters are
deterministic: same input → identical output. No LLM calls.

Filters:
    momentum_acceleration — MACD histogram must be increasing (trend
        confirmation). Rejects signals when momentum is decelerating.
    squeeze_gate — rejects signals when Bollinger Bands are inside
        Keltner Channels (TTM Squeeze is ON); volatility compression
        makes breakout/MR timing unreliable.
    sr_proximity — rejects signals if price is within X% of a recent
        swing high or swing low (risk of bounce at key level).

Public API:
    validate(bars, entry_signal, config) -> ValidationResult
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from .contracts import EntrySignal, NoSignal, ValidationResult

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MACD_FAST = 12
_DEFAULT_MACD_SLOW = 26
_DEFAULT_MACD_SIGNAL = 9
_DEFAULT_BB_PERIOD = 20
_DEFAULT_BB_STD = 2.0
_DEFAULT_KC_PERIOD = 20
_DEFAULT_KC_ATR_FACTOR = 1.5
_DEFAULT_KC_ATR_PERIOD = 14
_DEFAULT_SR_LOOKBACK = 50        # bars to scan for swing highs/lows
_DEFAULT_SR_SWING_WIDTH = 5      # local-extrema neighbourhood half-width
_DEFAULT_SR_PROXIMITY_PCT = 0.005  # 0.5% proximity threshold


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _wilder_atr(bars: pd.DataFrame, period: int) -> pd.Series:
    high = bars["High"]
    low = bars["Low"]
    prev_close = bars["Close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Filter: momentum acceleration (MACD histogram increasing)
# ---------------------------------------------------------------------------


def _filter_momentum(
    bars: pd.DataFrame,
    direction: str,
    cfg: Dict,
) -> Tuple[bool, str]:
    fast = int(cfg.get("macd_fast", _DEFAULT_MACD_FAST))
    slow = int(cfg.get("macd_slow", _DEFAULT_MACD_SLOW))
    signal_p = int(cfg.get("macd_signal_period", _DEFAULT_MACD_SIGNAL))

    min_bars = slow + signal_p + 2
    if len(bars) < min_bars:
        return True, "momentum: skipped (insufficient bars)"

    close = bars["Close"]
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal_p)
    histogram = macd_line - signal_line

    if len(histogram) < 2:
        return True, "momentum: skipped (insufficient histogram)"

    prev_hist = float(histogram.iloc[-2])
    last_hist = float(histogram.iloc[-1])

    # For long entries: histogram should be increasing (negative or positive, trending up)
    # For short entries: histogram should be decreasing (trending down)
    if direction == "long":
        ok = last_hist > prev_hist
        reason = (
            f"momentum: histogram increasing ({prev_hist:.4f}→{last_hist:.4f})"
            if ok
            else f"momentum: histogram decelerating ({prev_hist:.4f}→{last_hist:.4f})"
        )
    else:
        ok = last_hist < prev_hist
        reason = (
            f"momentum: histogram decreasing ({prev_hist:.4f}→{last_hist:.4f})"
            if ok
            else f"momentum: histogram accelerating up ({prev_hist:.4f}→{last_hist:.4f})"
        )

    return ok, reason


# ---------------------------------------------------------------------------
# Filter: squeeze gate (BB inside Keltner Channels)
# ---------------------------------------------------------------------------


def _filter_squeeze(
    bars: pd.DataFrame,
    cfg: Dict,
) -> Tuple[bool, str]:
    bb_period = int(cfg.get("bb_period", _DEFAULT_BB_PERIOD))
    bb_std = float(cfg.get("bb_std", _DEFAULT_BB_STD))
    kc_period = int(cfg.get("kc_period", _DEFAULT_KC_PERIOD))
    kc_factor = float(cfg.get("kc_atr_factor", _DEFAULT_KC_ATR_FACTOR))
    kc_atr_period = int(cfg.get("kc_atr_period", _DEFAULT_KC_ATR_PERIOD))

    min_bars = max(bb_period, kc_period, kc_atr_period) + 1
    if len(bars) < min_bars:
        return True, "squeeze: skipped (insufficient bars)"

    close = bars["Close"]

    # Bollinger Bands
    bb_mid = close.rolling(bb_period).mean()
    bb_std_val = close.rolling(bb_period).std()
    bb_upper = bb_mid + bb_std * bb_std_val
    bb_lower = bb_mid - bb_std * bb_std_val

    # Keltner Channels
    kc_mid = _ema(close, kc_period)
    atr = _wilder_atr(bars, kc_atr_period)
    kc_upper = kc_mid + kc_factor * atr
    kc_lower = kc_mid - kc_factor * atr

    last_bb_upper = float(bb_upper.iloc[-1])
    last_bb_lower = float(bb_lower.iloc[-1])
    last_kc_upper = float(kc_upper.iloc[-1])
    last_kc_lower = float(kc_lower.iloc[-1])

    # Squeeze is ON when BB is completely inside KC
    squeeze_on = (last_bb_upper < last_kc_upper) and (last_bb_lower > last_kc_lower)

    if squeeze_on:
        return False, f"squeeze: ON (BB [{last_bb_lower:.4f},{last_bb_upper:.4f}] inside KC [{last_kc_lower:.4f},{last_kc_upper:.4f}])"
    return True, f"squeeze: OFF (BB outside KC)"


# ---------------------------------------------------------------------------
# Filter: SR proximity
# ---------------------------------------------------------------------------


def _swing_levels(bars: pd.DataFrame, lookback: int, width: int) -> List[float]:
    """Identify recent swing high and swing low price levels."""
    if len(bars) < width * 2 + 1:
        return []

    subset = bars.iloc[-lookback:] if len(bars) >= lookback else bars
    highs = subset["High"]
    lows = subset["Low"]
    levels: List[float] = []

    for i in range(width, len(subset) - width):
        h = float(highs.iloc[i])
        if all(h >= float(highs.iloc[j]) for j in range(i - width, i + width + 1) if j != i):
            levels.append(h)
        low_val = float(lows.iloc[i])
        if all(low_val <= float(lows.iloc[j]) for j in range(i - width, i + width + 1) if j != i):
            levels.append(low_val)

    return levels


def _filter_sr_proximity(
    bars: pd.DataFrame,
    direction: str,
    cfg: Dict,
) -> Tuple[bool, str]:
    lookback = int(cfg.get("sr_lookback", _DEFAULT_SR_LOOKBACK))
    width = int(cfg.get("sr_swing_width", _DEFAULT_SR_SWING_WIDTH))
    proximity_pct = float(cfg.get("sr_proximity_pct", _DEFAULT_SR_PROXIMITY_PCT))

    if bars.empty:
        return True, "sr_proximity: skipped (no bars)"

    cur_price = float(bars["Close"].iloc[-1])
    levels = _swing_levels(bars, lookback, width)

    if not levels:
        return True, "sr_proximity: no swing levels found, passing"

    closest_dist = min(abs(cur_price - lvl) / lvl for lvl in levels if lvl > 0)

    if closest_dist <= proximity_pct:
        return False, (
            f"sr_proximity: price {cur_price:.4f} within {closest_dist*100:.2f}% of"
            f" an SR level (threshold {proximity_pct*100:.2f}%)"
        )
    return True, f"sr_proximity: clear ({closest_dist*100:.2f}% from nearest SR level)"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate(
    bars: pd.DataFrame,
    entry_signal: Union[EntrySignal, NoSignal],
    config: Optional[Dict] = None,
) -> ValidationResult:
    """Run all enabled validation filters against an entry signal.

    If ``entry_signal`` is a NoSignal the function returns a failed
    ValidationResult immediately without running any filters.

    Args:
        bars: 15m OHLCV DataFrame (same bars used for entry detection).
        entry_signal: Output of run_entry().
        config: Parameter and toggle overrides. Toggle keys (all default True):
            validation_momentum (bool)
            validation_squeeze (bool)
            validation_sr_proximity (bool)

    Returns:
        ValidationResult — deterministic for identical inputs.
    """
    cfg = config or {}

    if isinstance(entry_signal, NoSignal):
        return ValidationResult(
            passed=False,
            filters_passed=0,
            filters_total=0,
            reasons=(f"no entry signal: {entry_signal.reason}",),
        )

    direction = entry_signal.direction
    results: List[Tuple[bool, str]] = []

    if cfg.get("validation_momentum", True):
        results.append(_filter_momentum(bars, direction, cfg))

    if cfg.get("validation_squeeze", True):
        results.append(_filter_squeeze(bars, cfg))

    if cfg.get("validation_sr_proximity", True):
        results.append(_filter_sr_proximity(bars, direction, cfg))

    if not results:
        # All filters disabled → pass through
        return ValidationResult(
            passed=True,
            filters_passed=0,
            filters_total=0,
            reasons=("all validation filters disabled",),
        )

    passed_count = sum(1 for ok, _ in results if ok)
    all_passed = all(ok for ok, _ in results)
    reasons: Tuple[str, ...] = tuple(reason for _, reason in results)

    return ValidationResult(
        passed=all_passed,
        filters_passed=passed_count,
        filters_total=len(results),
        reasons=reasons,
    )
