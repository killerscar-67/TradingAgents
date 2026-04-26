"""Top-level deterministic quant engine (Phase 2).

Orchestration pipeline:
    1. regime.classify(bars_4h)         — regime label + tradability + HTF bias
    2. entry.run_entry(bars_15m, regime) — breakout or mean-reversion signal
    3. validation.validate(bars_15m, entry_signal) — momentum / squeeze / SR filters
    4. _score()                         — map to QuantSignalContract

All steps are deterministic. No LLM calls.

Public API:
    run_quant_engine(symbol, trade_date, bars_15m, bars_4h, config)
        -> QuantSignalContract
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from .contracts import (
    EntrySignal,
    NoSignal,
    QuantSignalContract,
    QuantSignalLabel,
    RegimeContract,
    ValidationResult,
)
from . import regime as _regime
from . import entry as _entry
from . import validation as _validation

# ---------------------------------------------------------------------------
# Score mapping
# ---------------------------------------------------------------------------


def _to_signal_label(
    entry: EntrySignal,
    validation_result: ValidationResult,
) -> QuantSignalLabel:
    if not validation_result.passed:
        return QuantSignalLabel.HOLD
    if entry.direction == "long":
        return QuantSignalLabel.BUY
    return QuantSignalLabel.SELL


def _to_score(
    entry: EntrySignal,
    validation_result: ValidationResult,
) -> float:
    """Score in [-1.0, 1.0]. Positive = buy, negative = sell.

    Magnitude = entry strength * validation pass rate.
    """
    if not validation_result.passed:
        return 0.0
    rate = (
        validation_result.filters_passed / validation_result.filters_total
        if validation_result.filters_total > 0
        else 1.0
    )
    signed = entry.strength * rate
    return round(signed if entry.direction == "long" else -signed, 6)


def _to_confidence(validation_result: ValidationResult) -> Optional[float]:
    if validation_result.filters_total == 0:
        return None
    return round(
        validation_result.filters_passed / validation_result.filters_total, 4
    )


def _build_summary(
    symbol: str,
    trade_date: str,
    regime_contract: RegimeContract,
    entry_result,
    val_result: ValidationResult,
    signal: QuantSignalLabel,
) -> str:
    parts = [
        f"{symbol} {trade_date}",
        f"regime={regime_contract.label.value}",
        f"ADX={regime_contract.adx:.1f}",
        f"bias={regime_contract.htf_bias}",
    ]
    if isinstance(entry_result, EntrySignal):
        parts.append(f"entry={entry_result.engine.value}/{entry_result.direction}")
        parts.append(f"strength={entry_result.strength:.2f}")
    else:
        parts.append(f"no_entry: {entry_result.reason}")
    parts.append(f"validation={val_result.filters_passed}/{val_result.filters_total}")
    parts.append(f"signal={signal.value}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_quant_engine(
    symbol: str,
    trade_date: str,
    bars_15m: pd.DataFrame,
    bars_4h: pd.DataFrame,
    config: Optional[Dict] = None,
) -> QuantSignalContract:
    """Run the deterministic quant engine for a single symbol/date.

    Pipeline:
        regime(bars_4h) → entry(bars_15m, regime) → validate(bars_15m, entry)
        → QuantSignalContract

    Args:
        symbol: Ticker symbol (used for labelling only).
        trade_date: ISO date string ``"YYYY-MM-DD"`` (labelling only).
        bars_15m: 15-minute OHLCV bars (UTC-indexed), used for entry + validation.
        bars_4h: 4-hour OHLCV bars (UTC-indexed), used for regime classification.
        config: Combined config dict forwarded to all sub-modules. Accepted keys
            include all keys from regime, entry, and validation modules, plus:
            entry_mode (str): ``"auto"`` (default) uses regime-based dispatch;
                ``"breakout"`` forces breakout; ``"mean_reversion"`` forces MR.

    Returns:
        QuantSignalContract — deterministic for identical inputs.
    """
    cfg = config or {}

    # --- Step 1: Regime ---
    try:
        regime_contract: RegimeContract = _regime.classify(bars_4h, cfg)
    except Exception as exc:
        return QuantSignalContract(
            symbol=symbol,
            trade_date=trade_date,
            signal=QuantSignalLabel.UNKNOWN,
            score=float("-inf"),
            confidence=None,
            summary=f"regime classification failed: {exc}",
            error=str(exc),
        )

    # --- Step 2: Entry ---
    entry_mode = str(cfg.get("entry_mode", "auto")).lower()
    try:
        if entry_mode == "breakout":
            entry_result = _entry.run_breakout(bars_15m, cfg)
            if isinstance(entry_result, EntrySignal):
                # Still apply directional filter from regime
                if not _entry._direction_allowed(entry_result, regime_contract.htf_bias):
                    entry_result = NoSignal(
                        reason=f"{entry_result.direction} entry rejected by HTF bias ({regime_contract.htf_bias})"
                    )
        elif entry_mode == "mean_reversion":
            entry_result = _entry.run_mean_reversion(bars_15m, cfg)
            if isinstance(entry_result, EntrySignal):
                if not _entry._direction_allowed(entry_result, regime_contract.htf_bias):
                    entry_result = NoSignal(
                        reason=f"{entry_result.direction} entry rejected by HTF bias ({regime_contract.htf_bias})"
                    )
        else:
            # "auto": regime-based dispatch (default)
            entry_result = _entry.run_entry(bars_15m, regime_contract, cfg)
    except Exception as exc:
        return QuantSignalContract(
            symbol=symbol,
            trade_date=trade_date,
            signal=QuantSignalLabel.UNKNOWN,
            score=float("-inf"),
            confidence=None,
            summary=f"entry engine failed: {exc}",
            error=str(exc),
        )

    # --- Step 3: Validation ---
    try:
        val_result: ValidationResult = _validation.validate(bars_15m, entry_result, cfg)
    except Exception as exc:
        return QuantSignalContract(
            symbol=symbol,
            trade_date=trade_date,
            signal=QuantSignalLabel.UNKNOWN,
            score=float("-inf"),
            confidence=None,
            summary=f"validation failed: {exc}",
            error=str(exc),
        )

    # --- Step 4: Score and emit ---
    if isinstance(entry_result, NoSignal):
        signal_label = QuantSignalLabel.HOLD
        score = 0.0
        confidence = None
    else:
        signal_label = _to_signal_label(entry_result, val_result)
        score = _to_score(entry_result, val_result)
        confidence = _to_confidence(val_result)

    summary = _build_summary(
        symbol, trade_date, regime_contract, entry_result, val_result, signal_label
    )

    return QuantSignalContract(
        symbol=symbol,
        trade_date=trade_date,
        signal=signal_label,
        score=score,
        confidence=confidence,
        summary=summary,
        raw={
            "regime": regime_contract.to_dict(),
            "entry": entry_result.to_dict() if isinstance(entry_result, EntrySignal) else entry_result.to_dict(),
            "validation": val_result.to_dict(),
        },
    )
