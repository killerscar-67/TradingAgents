"""Dual entry engines: breakout and mean reversion.

Both engines are fully deterministic: same bars input → identical output.
No LLM calls, no mutable module-level state.

Public API:
    run_breakout(bars, config)        -> EntrySignal | NoSignal
    run_mean_reversion(bars, config)  -> EntrySignal | NoSignal
    run_entry(bars, regime, config)   -> EntrySignal | NoSignal
"""

from __future__ import annotations

from typing import Dict, Literal, Optional, Union

import pandas as pd

from .contracts import EntryEngine, EntrySignal, NoSignal, RegimeContract, RegimeLabel

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_BREAKOUT_LOOKBACK = 20       # N-bar channel
_DEFAULT_BREAKOUT_VOLUME_FACTOR = 1.5  # current vol must be > avg * factor
_DEFAULT_RSI_PERIOD = 14
_DEFAULT_RSI_OVERSOLD = 30.0
_DEFAULT_RSI_OVERBOUGHT = 70.0
_DEFAULT_MR_SMA_PERIOD = 20
_DEFAULT_MR_STRETCH_STD = 2.0         # price must be > N std from SMA
_DEFAULT_MR_MIN_STRETCH_PCT = 0.01    # or at least 1% from SMA (whichever is larger)


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder RSI: identical to TradingView's default RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    safe_loss = avg_loss.replace(0.0, float("nan"))
    rs = avg_gain / safe_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _volume_ok(bars: pd.DataFrame, factor: float, lookback: int) -> bool:
    if "Volume" not in bars.columns or len(bars) < 2:
        return True   # no volume data → don't gate
    avg_vol = bars["Volume"].iloc[-lookback - 1 : -1].mean()
    cur_vol = float(bars["Volume"].iloc[-1])
    if pd.isna(avg_vol) or avg_vol == 0.0:
        return True
    return cur_vol >= avg_vol * factor


# ---------------------------------------------------------------------------
# Breakout engine
# ---------------------------------------------------------------------------


def run_breakout(
    bars: pd.DataFrame,
    config: Optional[Dict] = None,
) -> Union[EntrySignal, NoSignal]:
    """Detect N-bar channel breakout on the most recent bar.

    Args:
        bars: UTC-indexed OHLCV DataFrame (15m bars).
        config: Parameter overrides. Keys:
            breakout_lookback (int, default 20)
            breakout_volume_factor (float, default 1.5)

    Returns:
        EntrySignal if a breakout is detected, NoSignal otherwise.
    """
    cfg = config or {}
    lookback = int(cfg.get("breakout_lookback", _DEFAULT_BREAKOUT_LOOKBACK))
    vol_factor = float(cfg.get("breakout_volume_factor", _DEFAULT_BREAKOUT_VOLUME_FACTOR))

    if bars.empty or len(bars) < lookback + 1:
        return NoSignal(reason=f"insufficient bars: need {lookback + 1}, got {len(bars)}")

    # Channel is the N bars *before* the current bar (exclusive of current)
    channel = bars.iloc[-(lookback + 1) : -1]
    current = bars.iloc[-1]

    channel_high = float(channel["High"].max())
    channel_low = float(channel["Low"].min())
    cur_close = float(current["Close"])

    if cur_close > channel_high:
        if not _volume_ok(bars, vol_factor, lookback):
            return NoSignal(reason="breakout rejected: volume below threshold")
        strength = min(1.0, (cur_close - channel_high) / channel_high) if channel_high > 0 else 0.5
        return EntrySignal(
            engine=EntryEngine.BREAKOUT,
            direction="long",
            strength=round(min(1.0, strength * 20), 4),  # scale: 5% move → strength=1.0
            reason=f"close {cur_close:.4f} broke above {lookback}-bar high {channel_high:.4f}",
        )

    if cur_close < channel_low:
        if not _volume_ok(bars, vol_factor, lookback):
            return NoSignal(reason="breakout rejected: volume below threshold")
        strength = min(1.0, (channel_low - cur_close) / channel_low) if channel_low > 0 else 0.5
        return EntrySignal(
            engine=EntryEngine.BREAKOUT,
            direction="short",
            strength=round(min(1.0, strength * 20), 4),
            reason=f"close {cur_close:.4f} broke below {lookback}-bar low {channel_low:.4f}",
        )

    return NoSignal(
        reason=f"price {cur_close:.4f} within channel [{channel_low:.4f}, {channel_high:.4f}]"
    )


# ---------------------------------------------------------------------------
# Mean reversion engine
# ---------------------------------------------------------------------------


def run_mean_reversion(
    bars: pd.DataFrame,
    config: Optional[Dict] = None,
) -> Union[EntrySignal, NoSignal]:
    """Detect mean-reversion opportunity: RSI extreme + stretched price.

    Both conditions must be true simultaneously:
      1. RSI is oversold (< threshold) or overbought (> threshold).
      2. Price is stretched from its SMA by at least N std devs OR min pct.

    Args:
        bars: UTC-indexed OHLCV DataFrame (15m bars).
        config: Parameter overrides. Keys:
            rsi_period (int, default 14)
            rsi_oversold (float, default 30.0)
            rsi_overbought (float, default 70.0)
            mr_sma_period (int, default 20)
            mr_stretch_std (float, default 2.0)
            mr_min_stretch_pct (float, default 0.01)

    Returns:
        EntrySignal if both RSI extreme and stretch are confirmed, NoSignal otherwise.
    """
    cfg = config or {}
    rsi_period = int(cfg.get("rsi_period", _DEFAULT_RSI_PERIOD))
    oversold = float(cfg.get("rsi_oversold", _DEFAULT_RSI_OVERSOLD))
    overbought = float(cfg.get("rsi_overbought", _DEFAULT_RSI_OVERBOUGHT))
    sma_period = int(cfg.get("mr_sma_period", _DEFAULT_MR_SMA_PERIOD))
    stretch_std = float(cfg.get("mr_stretch_std", _DEFAULT_MR_STRETCH_STD))
    min_stretch_pct = float(cfg.get("mr_min_stretch_pct", _DEFAULT_MR_MIN_STRETCH_PCT))

    min_bars = max(rsi_period * 2, sma_period) + 1
    if bars.empty or len(bars) < min_bars:
        return NoSignal(reason=f"insufficient bars: need {min_bars}, got {len(bars)}")

    close = bars["Close"]
    rsi = _compute_rsi(close, rsi_period)
    last_rsi = float(rsi.iloc[-1])
    last_close = float(close.iloc[-1])

    sma = close.rolling(sma_period).mean()
    std = close.rolling(sma_period).std()
    last_sma = float(sma.iloc[-1])
    last_std = float(std.iloc[-1])

    if pd.isna(last_rsi) or pd.isna(last_sma):
        return NoSignal(reason="NaN in RSI or SMA — insufficient history")

    # Stretch threshold: larger of (N * std) or (min_pct * sma)
    stretch_threshold = max(stretch_std * last_std, min_stretch_pct * last_sma)
    deviation = last_close - last_sma
    stretched = abs(deviation) >= stretch_threshold

    if last_rsi <= oversold and deviation < 0 and stretched:
        strength = round(min(1.0, (oversold - last_rsi) / oversold), 4)
        return EntrySignal(
            engine=EntryEngine.MEAN_REVERSION,
            direction="long",
            strength=strength,
            reason=f"RSI={last_rsi:.1f} oversold, price {abs(deviation):.4f} below SMA",
        )

    if last_rsi >= overbought and deviation > 0 and stretched:
        strength = round(min(1.0, (last_rsi - overbought) / (100.0 - overbought)), 4)
        return EntrySignal(
            engine=EntryEngine.MEAN_REVERSION,
            direction="short",
            strength=strength,
            reason=f"RSI={last_rsi:.1f} overbought, price {deviation:.4f} above SMA",
        )

    return NoSignal(
        reason=f"RSI={last_rsi:.1f}, deviation={deviation:.4f} (threshold={stretch_threshold:.4f}) — no MR setup"
    )


# ---------------------------------------------------------------------------
# Directional filter + engine dispatcher
# ---------------------------------------------------------------------------


def _direction_allowed(
    signal: EntrySignal,
    htf_bias: Literal["bullish", "bearish", "neutral"],
) -> bool:
    """Return False when HTF bias directly contradicts signal direction."""
    if htf_bias == "neutral":
        return True
    if htf_bias == "bullish" and signal.direction == "short":
        return False
    if htf_bias == "bearish" and signal.direction == "long":
        return False
    return True


def run_entry(
    bars: pd.DataFrame,
    regime: RegimeContract,
    config: Optional[Dict] = None,
) -> Union[EntrySignal, NoSignal]:
    """Dispatch to the appropriate entry engine based on regime label.

    Regime → engine mapping:
        TRENDING     → breakout engine
        RANGING      → mean reversion engine
        CONSOLIDATION → NoSignal (wait for regime to resolve)

    The HTF bias from the regime contract gates directional entries:
    a bullish bias rejects short entries and vice versa.

    Args:
        bars: 15m OHLCV bars.
        regime: Output of regime.classify() for HTF context.
        config: Combined config dict forwarded to each engine.

    Returns:
        EntrySignal or NoSignal.
    """
    if not regime.tradable:
        return NoSignal(reason=f"regime not tradable: {regime.label.value}")

    if regime.label == RegimeLabel.CONSOLIDATION:
        return NoSignal(reason="consolidation: waiting for regime to resolve")

    if regime.label == RegimeLabel.TRENDING:
        result = run_breakout(bars, config)
    else:
        result = run_mean_reversion(bars, config)

    if isinstance(result, EntrySignal):
        if not _direction_allowed(result, regime.htf_bias):
            return NoSignal(
                reason=f"{result.direction} entry rejected by HTF bias ({regime.htf_bias})"
            )

    return result
