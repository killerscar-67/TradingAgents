"""Paper-trading gate (Phase 6).

Evaluates a BacktestResult (or live paper-session result) against promotion
thresholds before allowing progression to live trading.

Acceptance thresholds (from the plan):
    - Session Sharpe > min_session_sharpe  (default 0.5)
    - Max intraday drawdown < max_intraday_drawdown_pct  (default 5%)

Both conditions must be met AND the session must contain at least
``min_trades`` completed trades for a PASS verdict.

Public API
----------
PaperGate(min_session_sharpe, max_intraday_drawdown_pct, min_trades)
PaperGate.evaluate(result: BacktestResult) -> PaperGateResult
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .backtest import BacktestResult


@dataclass(frozen=True)
class PaperGateResult:
    """Outcome of the paper-trading gate evaluation."""

    passed: bool
    session_sharpe: float
    max_intraday_drawdown_pct: float
    trade_count: int
    net_pnl: float
    reasons: Tuple[str, ...]        # non-empty when passed=False, may be advisory when True

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "session_sharpe": self.session_sharpe,
            "max_intraday_drawdown_pct": self.max_intraday_drawdown_pct,
            "trade_count": self.trade_count,
            "net_pnl": self.net_pnl,
            "reasons": list(self.reasons),
        }


class PaperGate:
    """Evaluate paper-session quality against hardcoded promotion thresholds.

    Args:
        min_session_sharpe: Minimum required annualised Sharpe (default 0.5).
        max_intraday_drawdown_pct: Max allowable peak-to-trough drawdown as a
            fraction; 0.05 = 5% (default).
        min_trades: Minimum completed round-trips required for a PASS verdict
            (default 1). A session with zero trades always fails.
    """

    def __init__(
        self,
        min_session_sharpe: float = 0.5,
        max_intraday_drawdown_pct: float = 0.05,
        min_trades: int = 1,
    ) -> None:
        if min_session_sharpe < 0:
            raise ValueError("min_session_sharpe must be ≥ 0")
        if not (0.0 < max_intraday_drawdown_pct <= 1.0):
            raise ValueError("max_intraday_drawdown_pct must be in (0, 1]")
        if min_trades < 1:
            raise ValueError("min_trades must be ≥ 1")

        self.min_session_sharpe = float(min_session_sharpe)
        self.max_intraday_drawdown_pct = float(max_intraday_drawdown_pct)
        self.min_trades = int(min_trades)

    def evaluate(self, result: BacktestResult) -> PaperGateResult:
        """Evaluate a BacktestResult against the gate thresholds.

        Args:
            result: Output of run_backtest() or an equivalent paper-session
                accumulator that exposes the same fields.

        Returns:
            PaperGateResult — passed=True only when all conditions are met.
        """
        failures: List[str] = []

        # Condition 1: minimum trade count
        if result.trade_count < self.min_trades:
            failures.append(
                f"insufficient trades: {result.trade_count} < {self.min_trades} required"
            )

        # Condition 2: Sharpe threshold
        if result.sharpe_ratio <= self.min_session_sharpe:
            failures.append(
                f"Sharpe {result.sharpe_ratio:.4f} ≤ threshold {self.min_session_sharpe:.4f}"
            )

        # Condition 3: drawdown threshold
        if result.max_drawdown_pct >= self.max_intraday_drawdown_pct:
            failures.append(
                f"max drawdown {result.max_drawdown_pct*100:.2f}% ≥ "
                f"limit {self.max_intraday_drawdown_pct*100:.2f}%"
            )

        net_pnl = result.final_equity - result.initial_equity

        return PaperGateResult(
            passed=len(failures) == 0,
            session_sharpe=result.sharpe_ratio,
            max_intraday_drawdown_pct=result.max_drawdown_pct,
            trade_count=result.trade_count,
            net_pnl=round(net_pnl, 6),
            reasons=tuple(failures),
        )
