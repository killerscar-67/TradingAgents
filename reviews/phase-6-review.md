# Phase 6 Review — Validation Gates

**Reviewer:** GitHub Copilot  
**Date:** 2026-04-22  
**Artifacts reviewed:** `tradingagents/quant/backtest.py`, `tradingagents/quant/walkforward.py`, `tradingagents/quant/paper_gate.py`, `tests/test_backtest.py`, `docs/handoffs/phase-6.md`, `reviews/phase-6-diff.patch`

---

## Round 1 Findings (addressed)

### MEDIUM — resolved

**M-1 — `BacktestTrade.net_pnl` was overstated by `commission` for EOD exits**

Fixed: EOD exit now records `net_pnl = round(gross - commission, 6)` (entry commission already deducted from equity; record now consistent). `BacktestTrade.commission` field also correctly reflects the entry-only commission paid.

**M-2 — OOS walk-forward folds started cold with empty 4h context**

Fixed: `oos_4h` now includes all 4h bars up to `bars_15m.index[oos_end - 1]` (full history tail), not just bars within the OOS window. The backtest's own no-lookahead slice (`bars_4h.index <= current_15m_ts`) prevents future 4h data from leaking in. OOS folds now have HTF regime context from bar 1.

### LOW — resolved

**L-1 — `_empty_result` broke `len(equity_curve) == len(bars_15m)` for `n_bars < 2`**

Fixed: `_empty_result` now accepts `n_bars` parameter and returns `equity_curve = tuple([initial_equity] * n_bars)`. For `n_bars == 1`, one entry is returned; for `n_bars == 0`, the tuple is empty. Contract holds in all cases.

---

## Re-review (post-fix)

**L-1 — `_empty_result` broke `len(equity_curve) == len(bars_15m)` for `n_bars < 2`**

Fixed: see above.

---

## Re-review (post-fix)

### Findings

No new findings. All three fixable items are addressed correctly and covered by tests.

### Scope Checklist

| Check | Result |
|---|---|
| No future bar data reachable: `visible_15m = bars_15m.iloc[:i+1]` | ✅ Confirmed structurally at Step 4 |
| 4h slice: `bars_4h.loc[bars_4h.index <= bars_15m.index[i]]` | ✅ Strictly ≤ current bar timestamp |
| Fills at next bar's open (not current bar's close) | ✅ Signal queued as `pending` at bar `i`; applied at bar `i+1`'s open |
| Slippage on both sides: buys pay up, sells receive less | ✅ `sign = +1` for long entry, `-1` for long exit |
| Commission deducted at entry and exit for normal trades | ✅ `realized_equity -= commission` at entry; `net = gross - commission` at exit |
| EOD exit equity accounting correct | ✅ Equity correct; `BacktestTrade.net_pnl = gross − commission` now consistent (M-1 fixed) |
| OOS folds have 4h context from bar 1 | ✅ `oos_4h` includes full history tail; no-lookahead enforced inside `run_backtest` (M-2 fixed) |
| `_empty_result` equity_curve length matches `n_bars` | ✅ `tuple([initial_equity] * n_bars)` (L-1 fixed) |
| `WalkForwardFold.is_end == WalkForwardFold.oos_start` for every fold | ✅ `oos_start = is_end` by construction; confirmed by test |
| OOS windows are disjoint (no bar in two OOS windows) | ✅ Non-overlapping by fixed-width layout; confirmed by test |
| `PaperGateResult.passed=False` when Sharpe exactly equals threshold | ✅ `result.sharpe_ratio <= self.min_session_sharpe` (strict `<=`) |
| `PaperGateResult.passed=False` when drawdown exactly equals limit | ✅ `result.max_drawdown_pct >= self.max_intraday_drawdown_pct` (strict `>=`) |
| All tests pass | ✅ 58/58 (43 Phase 6 + 15 regression) |

---

## Merge Decision: APPROVE

All three fixable findings resolved. No-lookahead guarantee structurally enforced; OOS folds now have full 4h context; EOD trade records are internally consistent; equity-curve length contract holds for all `n_bars`. 58/58 tests pass.
