"""Hard risk and position sizing module (Phase 3).

All functions are pure and deterministic: same inputs always produce same outputs.
No LLM calls, no I/O, no mutable module-level state.

Public API
----------
size_position(entry_signal, entry_price, atr_15m, account_equity, config)
    -> PositionSizeContract

compute_stops(direction, entry_price, atr_15m, config)
    -> StopContract

check_risk_gates(size_contract, daily_loss_state, current_exposure, account_equity, config)
    -> RiskGateResult

update_daily_loss(state, trade_pnl, account_equity, config)
    -> DailyLossState
"""

from __future__ import annotations

from typing import Dict, Literal, Optional

from .contracts import (
    DailyLossState,
    EntrySignal,
    PositionSizeContract,
    RiskGateResult,
    StopContract,
)

# ---------------------------------------------------------------------------
# Defaults (also in DEFAULT_CONFIG; kept here to avoid import cycle)
# ---------------------------------------------------------------------------

_DEFAULT_RISK_PER_TRADE_PCT = 0.01
_DEFAULT_ATR_STOP_MULT = 2.0
_DEFAULT_BREAKEVEN_ATR_MULT = 1.0
_DEFAULT_TRAILING_ATR_MULT = 1.5
_DEFAULT_MAX_POSITION_SIZE_PCT = 0.10
_DEFAULT_MAX_EXPOSURE_PCT = 0.20
_DEFAULT_MAX_DAILY_LOSS_PCT = 0.02
_DEFAULT_KILL_SWITCH_DAILY_LOSS_PCT = 0.03
_ROUNDING_EPSILON = 1e-8


def _cfg(config, key, default):
    return config.get(key, default) if config else default


def _rounded_directional_levels(direction: str, entry_price: float, stop_price: float, breakeven_trigger: float):
    rounded_stop = round(stop_price, 8)
    rounded_trigger = round(breakeven_trigger, 8)

    if direction == "long":
        if rounded_stop >= entry_price:
            rounded_stop = round(entry_price - _ROUNDING_EPSILON, 8)
        if rounded_trigger <= entry_price:
            rounded_trigger = round(entry_price + _ROUNDING_EPSILON, 8)
    else:
        if rounded_stop <= entry_price:
            rounded_stop = round(entry_price + _ROUNDING_EPSILON, 8)
        if rounded_trigger >= entry_price:
            rounded_trigger = round(entry_price - _ROUNDING_EPSILON, 8)

    return rounded_stop, rounded_trigger


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------


def size_position(
    entry_signal: EntrySignal,
    entry_price: float,
    atr_15m: float,
    account_equity: float,
    config=None,
) -> PositionSizeContract:
    """Fixed-fractional position sizing from ATR stop distance.

    Formula:
        stop_distance = atr_stop_mult x atr_15m
        max_risk_dollars = account_equity x risk_per_trade_pct
        raw_quantity = max_risk_dollars / stop_distance
        cap_quantity = (account_equity x max_position_size_pct) / entry_price
        quantity = min(raw_quantity, cap_quantity)

    Raises:
        ValueError: If entry_price, atr_15m, or account_equity is not positive.
    """
    if entry_price <= 0:
        raise ValueError(f"entry_price must be positive, got {entry_price}")
    if atr_15m <= 0:
        raise ValueError(f"atr_15m must be positive, got {atr_15m}")
    if account_equity <= 0:
        raise ValueError(f"account_equity must be positive, got {account_equity}")

    risk_pct = float(_cfg(config, "risk_per_trade_pct", _DEFAULT_RISK_PER_TRADE_PCT))
    atr_stop_mult = float(_cfg(config, "atr_stop_mult", _DEFAULT_ATR_STOP_MULT))
    max_pos_pct = float(_cfg(config, "max_position_size_pct", _DEFAULT_MAX_POSITION_SIZE_PCT))

    stop_distance = atr_stop_mult * atr_15m
    max_risk_dollars = account_equity * risk_pct

    raw_quantity = max_risk_dollars / stop_distance
    cap_quantity = (account_equity * max_pos_pct) / entry_price
    quantity = min(raw_quantity, cap_quantity)

    direction = entry_signal.direction
    if direction == "long":
        stop_price = entry_price - stop_distance
    else:
        stop_price = entry_price + stop_distance

    rounded_stop_price, _ = _rounded_directional_levels(
        direction,
        entry_price,
        stop_price,
        entry_price,
    )

    notional = quantity * entry_price
    risk_amount = quantity * stop_distance

    return PositionSizeContract(
        symbol=entry_signal.engine.value,
        direction=direction,
        quantity=round(quantity, 8),
        entry_price=entry_price,
        notional=round(notional, 8),
        stop_price=rounded_stop_price,
        risk_amount=round(risk_amount, 8),
        method="fixed_fractional",
    )


# ---------------------------------------------------------------------------
# Stop calculation
# ---------------------------------------------------------------------------


def compute_stops(
    direction: str,
    entry_price: float,
    atr_15m: float,
    config=None,
) -> StopContract:
    """Compute ATR-based initial stop, break-even trigger, and trailing distance.

    Args:
        direction: "long" or "short".
        entry_price: Price at entry (must be > 0).
        atr_15m: ATR on 15m bars (must be > 0).
        config: Config dict. Keys: atr_stop_mult, breakeven_atr_mult, trailing_atr_mult.
    """
    if entry_price <= 0:
        raise ValueError(f"entry_price must be positive, got {entry_price}")
    if atr_15m <= 0:
        raise ValueError(f"atr_15m must be positive, got {atr_15m}")

    atr_stop_mult = float(_cfg(config, "atr_stop_mult", _DEFAULT_ATR_STOP_MULT))
    be_mult = float(_cfg(config, "breakeven_atr_mult", _DEFAULT_BREAKEVEN_ATR_MULT))
    trail_mult = float(_cfg(config, "trailing_atr_mult", _DEFAULT_TRAILING_ATR_MULT))

    stop_distance = atr_stop_mult * atr_15m
    be_distance = be_mult * atr_15m
    trailing_distance = trail_mult * atr_15m

    if direction == "long":
        initial_stop = entry_price - stop_distance
        breakeven_trigger = entry_price + be_distance
    else:
        initial_stop = entry_price + stop_distance
        breakeven_trigger = entry_price - be_distance

    rounded_initial_stop, rounded_breakeven_trigger = _rounded_directional_levels(
        direction,
        entry_price,
        initial_stop,
        breakeven_trigger,
    )

    return StopContract(
        initial_stop=rounded_initial_stop,
        breakeven_trigger=rounded_breakeven_trigger,
        trailing_distance=max(round(trailing_distance, 8), _ROUNDING_EPSILON),
    )


# ---------------------------------------------------------------------------
# Risk gate checks
# ---------------------------------------------------------------------------


def check_risk_gates(
    size_contract: PositionSizeContract,
    daily_loss_state: DailyLossState,
    current_exposure: float,
    account_equity: float,
    config=None,
) -> RiskGateResult:
    """Run pre-trade risk gates in priority order.

    Gates (checked in order):
        1. Kill switch: permanently halt all orders after threshold breach.
        2. Max daily loss: block when net_pnl <= -(equity x max_daily_loss_pct).
        3. Exposure cap: block when adding new notional would exceed cap.
    """
    if account_equity <= 0:
        return RiskGateResult(
            allowed=False,
            reason="account_equity must be positive",
            kill_switch=False,
        )

    # Gate 1: kill switch
    if daily_loss_state.kill_switch:
        return RiskGateResult(
            allowed=False,
            reason="kill switch active: daily loss limit breached",
            kill_switch=True,
        )

    # Gate 2: daily loss cap
    max_daily_loss_pct = float(_cfg(config, "max_daily_loss_pct", _DEFAULT_MAX_DAILY_LOSS_PCT))
    loss_threshold = -(account_equity * max_daily_loss_pct)
    if daily_loss_state.net_pnl <= loss_threshold:
        return RiskGateResult(
            allowed=False,
            reason=(
                f"daily loss cap reached: net_pnl={daily_loss_state.net_pnl:.2f} "
                f"<= threshold={loss_threshold:.2f}"
            ),
            kill_switch=False,
        )

    # Gate 3: exposure cap
    max_exposure_pct = float(_cfg(config, "max_exposure_pct", _DEFAULT_MAX_EXPOSURE_PCT))
    max_exposure = account_equity * max_exposure_pct
    if current_exposure + size_contract.notional > max_exposure:
        return RiskGateResult(
            allowed=False,
            reason=(
                f"exposure cap exceeded: current={current_exposure:.2f} "
                f"+ new={size_contract.notional:.2f} > cap={max_exposure:.2f}"
            ),
            kill_switch=False,
        )

    return RiskGateResult(allowed=True, reason="", kill_switch=False)


# ---------------------------------------------------------------------------
# Daily loss state update
# ---------------------------------------------------------------------------


def update_daily_loss(
    state: DailyLossState,
    trade_pnl: float,
    account_equity: float,
    config=None,
) -> DailyLossState:
    """Return an updated DailyLossState after a completed trade.

    The kill switch fires (and latches) when:
        net_pnl <= -(account_equity x kill_switch_daily_loss_pct)

    Once set, kill_switch is never cleared within the same day.
    """
    new_pnl = state.net_pnl + trade_pnl
    new_trade_count = state.trade_count + 1

    ks_pct = float(_cfg(config, "kill_switch_daily_loss_pct", _DEFAULT_KILL_SWITCH_DAILY_LOSS_PCT))
    ks_threshold = -(account_equity * ks_pct)

    kill_switch = state.kill_switch or (new_pnl <= ks_threshold)

    return DailyLossState(
        date=state.date,
        net_pnl=new_pnl,
        kill_switch=kill_switch,
        trade_count=new_trade_count,
    )
