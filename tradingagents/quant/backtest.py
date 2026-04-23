"""Bar-replay backtest engine (Phase 6).

No-lookahead guarantee
----------------------
At signal bar i the engine receives only ``bars_15m.iloc[:i+1]`` and the
subset of ``bars_4h`` whose index timestamp is ≤ ``bars_15m.index[i]``.
Fills execute at bar ``i+1``'s open with configured slippage and commission.

Friction model
--------------
- Slippage: fill_price = next_bar_open × (1 + slippage_pct) for buys,
  next_bar_open × (1 − slippage_pct) for sells.
- Commission: flat dollar amount per order; paid once at entry, once at exit.

Position management
-------------------
One position at a time (no pyramiding).
Entry  — when the engine emits BUY or SELL and no position is open.
Stop   — when the current bar's Low (long) or High (short) touches the
         ATR-derived stop; fills at the *next* bar's open.
Reversal — when the engine emits the opposite direction while a position is
           open; fills at the next bar's open.
EOD    — open position is closed at the last bar's close (no commission).

Public API
----------
run_backtest(symbol, bars_15m, bars_4h, initial_equity, config)
    -> BacktestResult
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .contracts import EntryEngine, EntrySignal, QuantSignalLabel
from .engine import run_quant_engine
from .regime import compute_atr
from .risk import compute_stops, size_position

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestTrade:
    """A completed round-trip trade (entry fill + exit fill)."""

    symbol: str
    direction: str          # "long" or "short"
    entry_bar_idx: int
    exit_bar_idx: int
    entry_price: float      # fill price at entry (includes slippage)
    exit_price: float       # fill price at exit (includes slippage)
    quantity: float
    gross_pnl: float        # (exit - entry) × qty for long; reversed for short
    commission: float       # total commission paid (entry + exit combined)
    net_pnl: float          # gross_pnl − commission
    entry_timestamp: str
    exit_timestamp: str
    exit_reason: str        # "stop" | "signal_reversal" | "end_of_data"

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_bar_idx": self.entry_bar_idx,
            "exit_bar_idx": self.exit_bar_idx,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "gross_pnl": self.gross_pnl,
            "commission": self.commission,
            "net_pnl": self.net_pnl,
            "entry_timestamp": self.entry_timestamp,
            "exit_timestamp": self.exit_timestamp,
            "exit_reason": self.exit_reason,
        }


@dataclass
class BacktestResult:
    """Full backtest run output."""

    symbol: str
    initial_equity: float
    final_equity: float
    trades: Tuple[BacktestTrade, ...]
    equity_curve: Tuple[float, ...]     # one value per bar in bars_15m
    sharpe_ratio: float
    max_drawdown_pct: float
    total_return_pct: float
    trade_count: int
    winning_trades: int
    win_rate: float
    config: Dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "initial_equity": self.initial_equity,
            "final_equity": self.final_equity,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "total_return_pct": self.total_return_pct,
            "trade_count": self.trade_count,
            "winning_trades": self.winning_trades,
            "win_rate": self.win_rate,
            "trades": [t.to_dict() for t in self.trades],
        }


# ---------------------------------------------------------------------------
# Metric helpers (pure functions)
# ---------------------------------------------------------------------------


def _compute_sharpe(equity_curve: Tuple[float, ...], bars_per_day: int = 26) -> float:
    """Annualized Sharpe from bar-level equity curve. Returns 0.0 for ≤1 bar."""
    if len(equity_curve) < 2:
        return 0.0
    eq = np.array(equity_curve, dtype=float)
    prev = eq[:-1]
    safe = np.where(prev != 0.0, prev, np.nan)
    returns = (eq[1:] - prev) / safe
    returns = returns[np.isfinite(returns)]
    if len(returns) < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std == 0.0:
        return 0.0
    ann = math.sqrt(252 * bars_per_day)
    return round(float(np.mean(returns)) / std * ann, 4)


def _compute_max_drawdown(equity_curve: Tuple[float, ...]) -> float:
    """Peak-to-trough max drawdown as a positive fraction (0.0–1.0)."""
    if len(equity_curve) < 2:
        return 0.0
    eq = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(eq)
    safe_peak = np.where(peak != 0.0, peak, np.nan)
    dd = (eq - peak) / safe_peak
    finite = dd[np.isfinite(dd)]
    return float(abs(np.min(finite))) if len(finite) > 0 else 0.0


def _coerce_entry_signal(direction: str, signal_payload: Optional[Dict]) -> EntrySignal:
    entry_payload = signal_payload.get("entry") if isinstance(signal_payload, dict) else None
    engine_value = str(entry_payload.get("engine", EntryEngine.BREAKOUT.value)).strip().lower() if isinstance(entry_payload, dict) else EntryEngine.BREAKOUT.value
    strength = entry_payload.get("strength", 1.0) if isinstance(entry_payload, dict) else 1.0
    reason = str(entry_payload.get("reason", "backtest entry")) if isinstance(entry_payload, dict) else "backtest entry"

    try:
        engine = EntryEngine(engine_value)
    except ValueError:
        engine = EntryEngine.BREAKOUT

    try:
        strength = float(strength)
    except (TypeError, ValueError):
        strength = 1.0

    return EntrySignal(
        engine=engine,
        direction=direction,
        strength=strength,
        reason=reason,
    )


def _trade_plan_direction(trade_plan: Dict) -> Optional[str]:
    direction = str(trade_plan.get("direction", "")).strip().lower()
    if direction in {"long", "short"}:
        return direction
    side = str(trade_plan.get("side", "")).strip().lower()
    if side == "buy":
        return "long"
    if side == "sell":
        return "short"
    return None


def _to_positive_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0.0 else 0.0


def run_trade_plan_backtest(
    symbol: str,
    bars_15m: pd.DataFrame,
    trade_plan: Dict,
    initial_equity: float = 100_000.0,
    config: Optional[Dict] = None,
) -> BacktestResult:
    """Replay a frozen saved trade plan without re-running the quant engine.

    The trade enters at the saved entry price on the first available bar and then
    uses the saved quantity, stop, and target for deterministic management.
    """
    cfg = dict(config or {})
    bars_per_day = int(cfg.get("bars_per_day", 26))
    commission = float(cfg.get("backtest_commission", 1.0))
    slippage_pct = float(cfg.get("backtest_slippage_pct", 0.0005))
    n_bars = len(bars_15m)

    if n_bars == 0:
        return _empty_result(symbol, initial_equity, cfg, n_bars)

    direction = _trade_plan_direction(trade_plan)
    entry_price = _to_positive_float(trade_plan.get("entry_price"))
    quantity = _to_positive_float(trade_plan.get("quantity"))
    stop_price = _to_positive_float(trade_plan.get("stop_price"))
    target_price = _to_positive_float(trade_plan.get("target_price"))
    if direction is None or entry_price <= 0.0 or quantity <= 0.0:
        return _empty_result(symbol, initial_equity, cfg, n_bars)

    realized_equity = initial_equity - commission
    equity_curve: List[float] = []
    trades: List[BacktestTrade] = []
    entry_timestamp = str(bars_15m.index[0])

    for i in range(n_bars):
        bar = bars_15m.iloc[i]
        bar_close = float(bar["Close"])
        bar_low = float(bar["Low"])
        bar_high = float(bar["High"])
        unreal = (
            (bar_close - entry_price) * quantity
            if direction == "long"
            else (entry_price - bar_close) * quantity
        )
        equity_curve.append(realized_equity + unreal)

        if i >= n_bars - 1:
            continue

        stop_hit = False
        target_hit = False
        if direction == "long":
            stop_hit = stop_price > 0.0 and bar_low <= stop_price
            target_hit = target_price > 0.0 and bar_high >= target_price
        else:
            stop_hit = stop_price > 0.0 and bar_high >= stop_price
            target_hit = target_price > 0.0 and bar_low <= target_price

        if not stop_hit and not target_hit:
            continue

        next_open = float(bars_15m.iloc[i + 1]["Open"])
        sign = -1.0 if direction == "long" else 1.0
        fill = max(next_open * (1.0 + sign * slippage_pct), 1e-10)
        gross = (
            (fill - entry_price) * quantity
            if direction == "long"
            else (entry_price - fill) * quantity
        )
        realized_equity += gross - commission
        exit_reason = "stop" if stop_hit else "target"
        trades.append(
            BacktestTrade(
                symbol=symbol,
                direction=direction,
                entry_bar_idx=0,
                exit_bar_idx=i + 1,
                entry_price=round(entry_price, 8),
                exit_price=round(fill, 8),
                quantity=round(quantity, 8),
                gross_pnl=round(gross, 6),
                commission=round(2.0 * commission, 6),
                net_pnl=round(gross - (2.0 * commission), 6),
                entry_timestamp=entry_timestamp,
                exit_timestamp=str(bars_15m.index[i + 1]),
                exit_reason=exit_reason,
            )
        )
        equity_curve[-1] = realized_equity
        break
    else:
        last_close = float(bars_15m["Close"].iloc[-1])
        gross = (
            (last_close - entry_price) * quantity
            if direction == "long"
            else (entry_price - last_close) * quantity
        )
        realized_equity += gross
        trades.append(
            BacktestTrade(
                symbol=symbol,
                direction=direction,
                entry_bar_idx=0,
                exit_bar_idx=n_bars - 1,
                entry_price=round(entry_price, 8),
                exit_price=round(last_close, 8),
                quantity=round(quantity, 8),
                gross_pnl=round(gross, 6),
                commission=round(commission, 6),
                net_pnl=round(gross - commission, 6),
                entry_timestamp=entry_timestamp,
                exit_timestamp=str(bars_15m.index[-1]),
                exit_reason="end_of_data",
            )
        )
        equity_curve[-1] = realized_equity

    eq_tuple = tuple(equity_curve)
    trades_tuple = tuple(trades)
    wins = sum(1 for trade in trades_tuple if trade.net_pnl > 0.0)
    final_eq = round(realized_equity, 6)
    ret_pct = round((final_eq - initial_equity) / initial_equity * 100.0, 4) if initial_equity else 0.0
    return BacktestResult(
        symbol=symbol,
        initial_equity=initial_equity,
        final_equity=final_eq,
        trades=trades_tuple,
        equity_curve=eq_tuple,
        sharpe_ratio=_compute_sharpe(eq_tuple, bars_per_day),
        max_drawdown_pct=_compute_max_drawdown(eq_tuple),
        total_return_pct=ret_pct,
        trade_count=len(trades_tuple),
        winning_trades=wins,
        win_rate=round(wins / len(trades_tuple), 4) if trades_tuple else 0.0,
        config=cfg,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_backtest(
    symbol: str,
    bars_15m: pd.DataFrame,
    bars_4h: pd.DataFrame,
    initial_equity: float = 100_000.0,
    config: Optional[Dict] = None,
) -> BacktestResult:
    """Bar-replay backtest with strict no-lookahead bar slicing.

    Args:
        symbol: Ticker label (used in trade records only).
        bars_15m: UTC-indexed OHLCV DataFrame of 15-minute bars. Must have
            columns Open, High, Low, Close (Volume optional).
        bars_4h: UTC-indexed OHLCV DataFrame of 4-hour bars used for HTF
            regime context. Must share the same timezone convention as bars_15m.
        initial_equity: Starting account equity in dollars.
        config: Combined config dict. Additional Phase 6 keys:
            backtest_warmup_bars  (int, default 60)  — minimum IS bars before
                                   the engine is queried.
            backtest_slippage_pct (float, default 0.0005) — one-way slippage.
            backtest_commission   (float, default 1.0)   — dollar commission
                                   per order (paid at entry and again at exit).
            bars_per_day          (int, default 26) — 15m bars per trading day,
                                   used for Sharpe annualization.
            min_4h_bars           (int, default 30) — skip signal if visible
                                   4h history is shorter than this.

    Returns:
        BacktestResult — deterministic for identical inputs.
    """
    cfg = dict(config or {})

    warmup = int(cfg.get("backtest_warmup_bars", 60))
    slippage_pct = float(cfg.get("backtest_slippage_pct", 0.0005))
    commission = float(cfg.get("backtest_commission", 1.0))
    bars_per_day = int(cfg.get("bars_per_day", 26))
    min_4h_bars = int(cfg.get("min_4h_bars", 30))
    atr_period = int(cfg.get("atr_period", 14))

    n_bars = len(bars_15m)
    if n_bars < 2:
        return _empty_result(symbol, initial_equity, cfg, n_bars)

    realized_equity: float = initial_equity
    equity_curve: List[float] = []
    trades: List[BacktestTrade] = []

    # Open position state (None when flat)
    pos_dir: Optional[str] = None
    pos_entry_bar: int = 0
    pos_entry_price: float = 0.0
    pos_quantity: float = 0.0
    pos_stop_price: float = 0.0
    pos_entry_ts: str = ""

    # One pending order at a time (filled at the NEXT bar's open)
    pending: Optional[Dict] = None

    for i in range(n_bars):
        bar = bars_15m.iloc[i]
        bar_open = float(bar["Open"])
        bar_close = float(bar["Close"])
        bar_low = float(bar["Low"])
        bar_high = float(bar["High"])
        bar_ts = str(bars_15m.index[i])

        # ── Step 1: Process the pending order at this bar's open ──────────
        if pending is not None:
            ptype = pending["type"]

            if ptype == "entry" and pos_dir is None:
                direction = pending["direction"]
                last_atr = pending["atr"]
                entry_signal = pending["entry_signal"]
                # Conservative fill: pay up for buys, receive less for sells
                sign = 1.0 if direction == "long" else -1.0
                fill = max(bar_open * (1.0 + sign * slippage_pct), 1e-10)
                try:
                    size_contract = size_position(
                        entry_signal,
                        fill,
                        last_atr,
                        realized_equity,
                        cfg,
                    )
                    stop_contract = compute_stops(direction, fill, last_atr, cfg)
                except ValueError:
                    size_contract = None
                    stop_contract = None
                if size_contract is not None and stop_contract is not None and size_contract.quantity > 0.0:
                    pos_stop_price = stop_contract.initial_stop
                    pos_dir = direction
                    pos_entry_bar = i
                    pos_entry_price = fill
                    pos_quantity = size_contract.quantity
                    pos_entry_ts = bar_ts
                    realized_equity -= commission  # entry commission

            elif ptype == "exit" and pos_dir is not None:
                reason = pending["reason"]
                # Conservative fill: sell lower for longs, buy higher for shorts
                sign = -1.0 if pos_dir == "long" else 1.0
                fill = max(bar_open * (1.0 + sign * slippage_pct), 1e-10)
                gross = (
                    (fill - pos_entry_price) * pos_quantity
                    if pos_dir == "long"
                    else (pos_entry_price - fill) * pos_quantity
                )
                total_commission = 2.0 * commission  # entry + exit
                net = gross - commission  # exit commission; entry commission already deducted
                realized_equity += net

                trades.append(
                    BacktestTrade(
                        symbol=symbol,
                        direction=pos_dir,
                        entry_bar_idx=pos_entry_bar,
                        exit_bar_idx=i,
                        entry_price=round(pos_entry_price, 8),
                        exit_price=round(fill, 8),
                        quantity=round(pos_quantity, 8),
                        gross_pnl=round(gross, 6),
                        commission=round(total_commission, 6),
                        net_pnl=round(gross - total_commission, 6),
                        entry_timestamp=pos_entry_ts,
                        exit_timestamp=bar_ts,
                        exit_reason=reason,
                    )
                )
                pos_dir = None
                pos_entry_price = 0.0
                pos_quantity = 0.0

            pending = None

        # ── Step 2: Mark-to-market equity ────────────────────────────────
        if pos_dir is not None:
            unreal = (
                (bar_close - pos_entry_price) * pos_quantity
                if pos_dir == "long"
                else (pos_entry_price - bar_close) * pos_quantity
            )
            equity_curve.append(realized_equity + unreal)
        else:
            equity_curve.append(realized_equity)

        # ── Step 3: Stop check (need next bar to fill) ────────────────────
        if pos_dir is not None and i < n_bars - 1 and pending is None:
            stop_hit = (pos_dir == "long" and bar_low <= pos_stop_price) or (
                pos_dir == "short" and bar_high >= pos_stop_price
            )
            if stop_hit:
                pending = {"type": "exit", "reason": "stop"}
                continue  # skip signal for this bar

        # ── Step 4: Generate signal ───────────────────────────────────────
        if i >= warmup and i < n_bars - 1 and pending is None:
            visible_15m = bars_15m.iloc[: i + 1]
            visible_4h = bars_4h.loc[bars_4h.index <= bars_15m.index[i]]

            if len(visible_4h) < min_4h_bars:
                continue

            trade_date = str(bars_15m.index[i].date())
            signal = run_quant_engine(
                symbol, trade_date, visible_15m, visible_4h, cfg
            )
            sig = signal.signal

            if pos_dir is None:
                if sig in (QuantSignalLabel.BUY, QuantSignalLabel.SELL):
                    atr_s = compute_atr(visible_15m, atr_period)
                    last_atr = float(atr_s.iloc[-1]) if not atr_s.empty else 0.0
                    if last_atr > 0.0:
                        direction = "long" if sig == QuantSignalLabel.BUY else "short"
                        entry_signal = _coerce_entry_signal(direction, signal.raw)
                        pending = {
                            "type": "entry",
                            "direction": direction,
                            "atr": last_atr,
                            "entry_signal": entry_signal,
                        }
            else:
                if (pos_dir == "long" and sig == QuantSignalLabel.SELL) or (
                    pos_dir == "short" and sig == QuantSignalLabel.BUY
                ):
                    pending = {"type": "exit", "reason": "signal_reversal"}

    # ── End-of-data: close any open position at last bar's close ─────────
    if pos_dir is not None:
        last_close = float(bars_15m["Close"].iloc[-1])
        gross = (
            (last_close - pos_entry_price) * pos_quantity
            if pos_dir == "long"
            else (pos_entry_price - last_close) * pos_quantity
        )
        net = gross  # no commission on EOD close
        realized_equity += net

        trades.append(
            BacktestTrade(
                symbol=symbol,
                direction=pos_dir,
                entry_bar_idx=pos_entry_bar,
                exit_bar_idx=n_bars - 1,
                entry_price=round(pos_entry_price, 8),
                exit_price=round(last_close, 8),
                quantity=round(pos_quantity, 8),
                gross_pnl=round(gross, 6),
                commission=round(commission, 6),        # only entry commission was paid; no exit order at EOD
                net_pnl=round(gross - commission, 6),   # gross minus entry commission (maintains net_pnl = gross - commission)
                entry_timestamp=pos_entry_ts,
                exit_timestamp=str(bars_15m.index[-1]),
                exit_reason="end_of_data",
            )
        )
        if equity_curve:
            equity_curve[-1] = realized_equity

    eq_tuple = tuple(equity_curve)
    trades_tuple = tuple(trades)
    final_eq = realized_equity
    ret_pct = round((final_eq - initial_equity) / initial_equity * 100.0, 4)
    wins = sum(1 for t in trades_tuple if t.net_pnl > 0.0)
    win_rate = round(wins / len(trades_tuple), 4) if trades_tuple else 0.0

    return BacktestResult(
        symbol=symbol,
        initial_equity=initial_equity,
        final_equity=round(final_eq, 6),
        trades=trades_tuple,
        equity_curve=eq_tuple,
        sharpe_ratio=_compute_sharpe(eq_tuple, bars_per_day),
        max_drawdown_pct=_compute_max_drawdown(eq_tuple),
        total_return_pct=ret_pct,
        trade_count=len(trades_tuple),
        winning_trades=wins,
        win_rate=win_rate,
        config=cfg,
    )


def _empty_result(symbol: str, initial_equity: float, cfg: Dict, n_bars: int = 0) -> BacktestResult:
    return BacktestResult(
        symbol=symbol,
        initial_equity=initial_equity,
        final_equity=initial_equity,
        trades=(),
        equity_curve=tuple([initial_equity] * n_bars),
        sharpe_ratio=0.0,
        max_drawdown_pct=0.0,
        total_return_pct=0.0,
        trade_count=0,
        winning_trades=0,
        win_rate=0.0,
        config=cfg,
    )
