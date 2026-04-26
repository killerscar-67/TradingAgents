"""Walk-forward validation (Phase 6).

Splits historical bar data into sequential non-overlapping folds. For each
fold the in-sample (IS) window is used to verify the strategy performs
adequately on data it was "trained" on; the out-of-sample (OOS) window
immediately following measures generalisation with zero leakage from IS.

No leakage guarantee
--------------------
Each fold's IS and OOS 15m windows are strictly adjacent and non-overlapping.
The OOS 15m window of fold k starts at the first bar *after* fold k's IS
15m window ends. No 15m bar appears in more than one fold's OOS window.

4h context
----------
IS 4h bars are sliced to the IS window. OOS 4h bars include all history up to
the end of the OOS window (not just the OOS period) so the regime classifier
has sufficient warmup from the first OOS bar. The backtest's internal
no-lookahead slice (visible_4h = bars_4h.index ≤ current_bar_ts) prevents any
future 4h bar from being seen during OOS evaluation.

Fold layout (rolling, fixed-width windows)
------------------------------------------
total_bars = len(bars_15m)
fold_size  = total_bars // n_folds
is_size    = int(fold_size * in_sample_ratio)   # ≥ 1
oos_size   = fold_size - is_size                # ≥ 1

Fold k:  IS  = [k*fold_size,           k*fold_size + is_size)
         OOS = [k*fold_size + is_size, (k+1)*fold_size)

Public API
----------
run_walk_forward(symbol, bars_15m, bars_4h, n_folds, in_sample_ratio,
                 initial_equity, config)
    -> WalkForwardResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .backtest import BacktestResult, run_backtest


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardFold:
    """Metrics for a single IS/OOS fold."""

    fold_idx: int
    is_start: int       # inclusive bar index in bars_15m
    is_end: int         # exclusive bar index
    oos_start: int      # inclusive bar index
    oos_end: int        # exclusive bar index
    is_sharpe: float
    oos_sharpe: float
    oos_result: BacktestResult

    def to_dict(self) -> Dict:
        return {
            "fold_idx": self.fold_idx,
            "is_start": self.is_start,
            "is_end": self.is_end,
            "oos_start": self.oos_start,
            "oos_end": self.oos_end,
            "is_sharpe": self.is_sharpe,
            "oos_sharpe": self.oos_sharpe,
            "oos_trade_count": self.oos_result.trade_count,
            "oos_total_return_pct": self.oos_result.total_return_pct,
        }


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward validation output."""

    folds: Tuple[WalkForwardFold, ...]
    n_folds: int
    oos_sharpe_positive_pct: float   # fraction of folds where OOS Sharpe > 0
    mean_oos_sharpe: float

    def to_dict(self) -> Dict:
        return {
            "n_folds": self.n_folds,
            "oos_sharpe_positive_pct": self.oos_sharpe_positive_pct,
            "mean_oos_sharpe": self.mean_oos_sharpe,
            "folds": [f.to_dict() for f in self.folds],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_walk_forward(
    symbol: str,
    bars_15m,
    bars_4h,
    n_folds: int = 5,
    in_sample_ratio: float = 0.7,
    initial_equity: float = 100_000.0,
    config: Optional[Dict] = None,
) -> WalkForwardResult:
    """Walk-forward validation with rolling fixed-width IS/OOS folds.

    Args:
        symbol: Ticker label.
        bars_15m: Full 15-minute OHLCV history (UTC-indexed DataFrame).
        bars_4h: Full 4-hour OHLCV history (UTC-indexed DataFrame).
        n_folds: Number of IS/OOS folds. Must be ≥ 2.
        in_sample_ratio: Fraction of each fold used as IS. Must be in (0, 1).
        initial_equity: Starting equity for each fold's backtest.
        config: Config dict forwarded to run_backtest.

    Returns:
        WalkForwardResult — deterministic for identical inputs.

    Raises:
        ValueError: If n_folds < 2, in_sample_ratio out of range, or not
                    enough bars to form folds with at least 1 IS and 1 OOS bar.
    """
    if n_folds < 2:
        raise ValueError(f"n_folds must be ≥ 2, got {n_folds}")
    if not (0.0 < in_sample_ratio < 1.0):
        raise ValueError(f"in_sample_ratio must be in (0, 1), got {in_sample_ratio}")

    total = len(bars_15m)
    fold_size = total // n_folds
    is_size = max(1, int(fold_size * in_sample_ratio))
    oos_size = fold_size - is_size

    if is_size < 1 or oos_size < 1:
        raise ValueError(
            f"Not enough bars to form {n_folds} folds with at least 1 IS and 1 OOS bar "
            f"(total={total}, fold_size={fold_size}, is_size={is_size}, oos_size={oos_size})"
        )

    cfg = dict(config or {})
    folds: List[WalkForwardFold] = []

    for k in range(n_folds):
        is_start = k * fold_size
        is_end = is_start + is_size
        oos_start = is_end
        oos_end = (k + 1) * fold_size

        # IS backtest (used to track is_sharpe, not for optimisation here)
        is_15m = bars_15m.iloc[is_start:is_end]
        is_4h = bars_4h.loc[
            (bars_4h.index >= bars_15m.index[is_start])
            & (bars_4h.index <= bars_15m.index[is_end - 1])
        ]
        is_result = run_backtest(symbol, is_15m, is_4h, initial_equity, cfg)

        # OOS backtest — 15m bars are strictly OOS-only (no leakage).
        # 4h bars include all history up to the OOS window end so the regime
        # classifier has enough context from the first OOS bar. The backtest's
        # own no-lookahead slice (bars_4h.index <= current_15m_ts) ensures the
        # engine never sees 4h bars beyond the current signal bar's timestamp.
        oos_15m = bars_15m.iloc[oos_start:oos_end]
        oos_4h = bars_4h.loc[bars_4h.index <= bars_15m.index[oos_end - 1]]
        oos_result = run_backtest(symbol, oos_15m, oos_4h, initial_equity, cfg)

        folds.append(
            WalkForwardFold(
                fold_idx=k,
                is_start=is_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
                is_sharpe=is_result.sharpe_ratio,
                oos_sharpe=oos_result.sharpe_ratio,
                oos_result=oos_result,
            )
        )

    folds_tuple = tuple(folds)
    pos_count = sum(1 for f in folds_tuple if f.oos_sharpe > 0.0)
    pos_pct = round(pos_count / n_folds, 4)
    sharpe_values = [f.oos_sharpe for f in folds_tuple]
    mean_sharpe = round(sum(sharpe_values) / len(sharpe_values), 4)

    return WalkForwardResult(
        folds=folds_tuple,
        n_folds=n_folds,
        oos_sharpe_positive_pct=pos_pct,
        mean_oos_sharpe=mean_sharpe,
    )
