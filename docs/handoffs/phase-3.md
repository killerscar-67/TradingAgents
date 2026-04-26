# Phase 3 Handoff — Hard Risk and Sizing

Agent: Claude Code
Date: 2026-04-21

## What was built

- `tradingagents/quant/risk.py`: Pure deterministic risk and sizing module. Four public functions:
    - `size_position(entry_signal, entry_price, atr_15m, account_equity, config) -> PositionSizeContract`
      Fixed-fractional sizing: `quantity = min(equity*risk_pct/stop_dist, equity*max_pos_pct/price)`. Raises `ValueError` for non-positive inputs.
    - `compute_stops(direction, entry_price, atr_15m, config) -> StopContract`
      ATR-based: initial stop (`±atr_stop_mult*atr`), break-even trigger (`±be_mult*atr`), trailing distance (`trail_mult*atr`). Raises `ValueError` for non-positive inputs.
    - `check_risk_gates(size_contract, daily_loss_state, current_exposure, account_equity, config) -> RiskGateResult`
      Three priority-ordered gates: kill switch → daily loss cap → exposure cap.
    - `update_daily_loss(state, trade_pnl, account_equity, config) -> DailyLossState`
      Accumulates daily P&L; latches `kill_switch=True` when `net_pnl <= -(equity*ks_pct)`.
    - No LLM calls, no I/O, no mutable module-level state.

- `tradingagents/quant/contracts.py`: Added four Phase 3 frozen dataclasses:
    - `PositionSizeContract`: `symbol, direction, quantity, entry_price, notional, stop_price, risk_amount, method` — `.to_dict()`
    - `StopContract`: `initial_stop, breakeven_trigger, trailing_distance` — `.to_dict()`
    - `RiskGateResult`: `allowed, reason, kill_switch` — `.to_dict()`
    - `DailyLossState`: `date, net_pnl, kill_switch, trade_count` — `.to_dict()`, `.new_day(date)` constructor

- `tradingagents/quant/__init__.py`: Exports all Phase 3 symbols alongside Phase 0-2 symbols.

- `tradingagents/default_config.py`: Added 8 new risk/sizing config keys (see Config keys section).

- `tests/test_risk.py`: 40 unit tests covering: basic sizing (long/short), cap binding, custom config, ValueError paths, stop calculations (both directions), all three risk gates, kill-switch latch, daily loss accumulation, immutability of state, and determinism.

## Contracts exposed to next phase

- `size_position(entry_signal, entry_price, atr_15m, account_equity, config) -> PositionSizeContract`:
  lives in `tradingagents.quant.risk`. Phase 4 broker adapter calls this to compute share quantity before placing an order.
- `compute_stops(direction, entry_price, atr_15m, config) -> StopContract`:
  lives in `tradingagents.quant.risk`. Phase 4 order manager uses `initial_stop` for OCO/bracket orders; `breakeven_trigger` and `trailing_distance` for post-entry management.
- `check_risk_gates(size_contract, daily_loss_state, current_exposure, account_equity, config) -> RiskGateResult`:
  lives in `tradingagents.quant.risk`. Phase 4 must call this before every order submission; if `allowed=False`, the order must be dropped with the `reason` logged.
- `update_daily_loss(state, trade_pnl, account_equity, config) -> DailyLossState`:
  lives in `tradingagents.quant.risk`. Phase 4 portfolio state reconciliation calls this on every fill to maintain the daily loss accumulator.
- `DailyLossState` (`tradingagents.quant.contracts`): immutable value object. Phase 4 stores one per trading day; reconstruct via `.new_day(date)` at session start.
- `PositionSizeContract`, `StopContract`, `RiskGateResult` (`tradingagents.quant.contracts`): all frozen; fully serialisable via `.to_dict()`.

## Config keys added

All keys live in `DEFAULT_CONFIG` in `tradingagents/default_config.py`. No env overrides (programmatic-only).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `risk_per_trade_pct` | float | 0.01 | Fraction of equity risked per trade |
| `atr_stop_mult` | float | 2.0 | ATR multiples for initial stop distance |
| `breakeven_atr_mult` | float | 1.0 | ATR multiples of profit to trigger break-even |
| `trailing_atr_mult` | float | 1.5 | ATR multiples for trailing stop distance |
| `max_position_size_pct` | float | 0.10 | Max single-position notional as fraction of equity |
| `max_exposure_pct` | float | 0.20 | Max aggregate notional exposure as fraction of equity |
| `max_daily_loss_pct` | float | 0.02 | Daily loss cap (block new orders when breached) |
| `kill_switch_daily_loss_pct` | float | 0.03 | Permanent halt threshold (latches for remainder of day) |

## Test command

```
tradingagent_venv/bin/python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation tests.test_risk -v
```
Expected: 55 tests, all OK.

## Known limitations / deferred decisions

- **Symbol field on PositionSizeContract**: set to `entry_signal.engine.value` (e.g. `"breakout"`) rather than the ticker symbol. Phase 4 callers must override or the order manager must enrich with the actual symbol before submission.
- **No bars_15m passed to size_position**: ATR for sizing is passed as a float (`atr_15m`). The caller must compute it from Phase 2's `regime.compute_atr(bars_15m, config["atr_period"])` before calling `size_position`. This keeps the risk module pure and avoids a pandas dependency.
- **No partial-fill or slippage adjustment**: `PositionSizeContract.quantity` is a raw float. Phase 4 broker adapter is responsible for rounding to lot size and adjusting for slippage.
- **Kelly sizing stub**: `method="fixed_fractional"` only. Capped Kelly requires win-rate and payoff-ratio inputs that are not available until Phase 6 backtesting. The `method` field is the extension point.
- **`check_risk_gates` exposure gate uses notional**: `current_exposure` is total open notional in base currency. Phase 4 must maintain a running sum of open position notionals and pass it on every gate check.
- **Kill switch resets across days**: `DailyLossState.new_day()` starts fresh. Session management (ensuring one state per calendar day) is deferred to Phase 4 portfolio state.
- **No per-instrument exposure cap**: only a total aggregate cap is enforced. Per-ticker concentration limits are deferred.

## What the reviewer must focus on

- **Sizing formula correctness**: verify `min(raw_qty, cap_qty)` correctly binds to the tighter constraint in all cases, including when `raw_qty < cap_qty` (risk limit binds before position cap).
- **Kill switch reachability**: verify that a single call to `check_risk_gates` with `kill_switch=True` in the state always returns `allowed=False`, regardless of other gate values.
- **No float precision traps in stop calculations**: verify that stop prices are rounded consistently (8 decimal places) and that the rounding does not push `initial_stop` to or above `entry_price` for a long trade with very small ATR.
- **Exposure cap boundary**: confirm that `current_exposure + notional == max_exposure` is allowed (not `>`), matching the test `test_exposure_exactly_at_cap_is_allowed`.
- **Kill switch latch**: verify that once `kill_switch=True` in `DailyLossState`, subsequent calls to `update_daily_loss` with profitable trades never clear it.
- **Integration with Phase 0 contracts**: verify `PositionSizeContract` and `RiskGateResult` are typed, frozen, and serialisable — and that Phase 0's `OrderIntentContract` can be enriched with sizing info in Phase 4 without structural changes to existing contracts.

## Fix notes

(none yet)
