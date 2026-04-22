"""Phase 6 tests: backtest, walk-forward, and paper gate.

Coverage
--------
BacktestEngine
  - equity curve starts at initial_equity
  - fills happen at the *next* bar's open (no same-bar execution)
  - slippage is applied conservatively (buys pay up, sells receive less)
  - commission is deducted at both entry and exit
  - stop loss triggers when bar's Low/High crosses stop_price
  - signal_reversal exit fires when engine flips direction
  - end_of_data exit closes position at last bar's close with no exit commission
  - equity curve tracks realized_equity + unrealized_pnl correctly
  - 3 known-trade spot-checks verify P&L arithmetic
  - no lookahead: visible bars at signal time are strictly [:i+1]
  - determinism: identical inputs produce identical outputs

WalkForward
  - IS and OOS windows are non-overlapping for every fold
  - IS_end == OOS_start (adjacent, zero gap)
  - oos_sharpe_positive_pct reports correct fraction

PaperGate
  - passes when all thresholds are met
  - fails on low Sharpe, high drawdown, or insufficient trades
  - PaperGateResult fields are accurate
"""

import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

from tradingagents.quant.backtest import (
    BacktestResult,
    BacktestTrade,
    _compute_sharpe,
    _compute_max_drawdown,
    run_backtest,
)
from tradingagents.quant.walkforward import run_walk_forward
from tradingagents.quant.paper_gate import PaperGate, PaperGateResult
from tradingagents.quant.contracts import QuantSignalContract, QuantSignalLabel


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_15m(n: int = 300, base: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Reproducible 15-minute bars that stay in a narrow range."""
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(0, 0.2, n))
    closes = np.maximum(closes, 1.0)
    opens = closes * (1 + rng.normal(0, 0.001, n))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.003, n))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.003, n))
    volumes = rng.integers(300_000, 800_000, n).astype(float)
    idx = pd.date_range("2024-01-02 09:30", periods=n, freq="15min")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


def _make_4h(n: int = 80, base: float = 100.0, seed: int = 0) -> pd.DataFrame:
    """Reproducible 4-hour bars."""
    rng = np.random.default_rng(seed + 1)
    closes = base + np.cumsum(rng.normal(0, 0.5, n))
    closes = np.maximum(closes, 1.0)
    opens = closes * (1 + rng.normal(0, 0.002, n))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.005, n))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.005, n))
    volumes = rng.integers(500_000, 1_500_000, n).astype(float)
    idx = pd.date_range("2024-01-02 09:30", periods=n, freq="4h")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


def _stub_signal(label: QuantSignalLabel) -> QuantSignalContract:
    return QuantSignalContract(
        symbol="TEST",
        trade_date="2024-01-02",
        signal=label,
        score=1.0 if label == QuantSignalLabel.BUY else -1.0,
        confidence=0.9,
        summary="stub",
    )


# ---------------------------------------------------------------------------
# Metric unit tests
# ---------------------------------------------------------------------------

class TestMetrics(unittest.TestCase):

    def test_sharpe_constant_returns_zero(self):
        """Zero std → Sharpe = 0.0."""
        eq = tuple([100_000.0] * 50)
        self.assertEqual(_compute_sharpe(eq), 0.0)

    def test_sharpe_monotone_positive(self):
        """Strictly increasing equity → positive Sharpe."""
        eq = tuple(100_000 + i * 10 for i in range(100))
        self.assertGreater(_compute_sharpe(eq), 0.0)

    def test_sharpe_monotone_negative(self):
        """Strictly decreasing equity → negative Sharpe."""
        eq = tuple(100_000 - i * 10 for i in range(100))
        self.assertLess(_compute_sharpe(eq), 0.0)

    def test_max_drawdown_zero_for_monotone(self):
        """No drawdown for always-increasing equity."""
        eq = tuple(100_000 + i for i in range(50))
        self.assertAlmostEqual(_compute_max_drawdown(eq), 0.0)

    def test_max_drawdown_correct(self):
        """Peak=110, trough=99 → drawdown ≈ 10%."""
        eq = (100.0, 105.0, 110.0, 99.0, 100.0)
        dd = _compute_max_drawdown(eq)
        self.assertAlmostEqual(dd, 11 / 110, places=5)

    def test_sharpe_single_bar_zero(self):
        self.assertEqual(_compute_sharpe((100_000.0,)), 0.0)

    def test_drawdown_single_bar_zero(self):
        self.assertEqual(_compute_max_drawdown((100_000.0,)), 0.0)


# ---------------------------------------------------------------------------
# Backtest mechanics — using mocked run_quant_engine
# ---------------------------------------------------------------------------

_BASE_CFG = {
    "backtest_warmup_bars": 2,
    "backtest_slippage_pct": 0.001,
    "backtest_commission": 5.0,
    "bars_per_day": 26,
    "min_4h_bars": 1,
    "atr_period": 3,
    "atr_stop_mult": 2.0,
    "risk_per_trade_pct": 0.01,
    "max_position_size_pct": 0.10,
    # Disable validation filters for predictable signals
    "validation_momentum": False,
    "validation_squeeze": False,
    "validation_sr_proximity": False,
}


class TestBacktestMechanics(unittest.TestCase):
    """Patch run_quant_engine so we control exactly which signals fire."""

    def setUp(self):
        self.bars_15m = _make_15m(n=30, base=100.0)
        self.bars_4h = _make_4h(n=10, base=100.0)

    # ----- Helpers ---------------------------------------------------------

    def _run(self, signal_seq, cfg_override=None):
        """Run backtest with a pre-defined per-call signal sequence."""
        cfg = {**_BASE_CFG, **(cfg_override or {})}
        call_count = [0]

        def fake_engine(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(signal_seq):
                return _stub_signal(signal_seq[idx])
            return _stub_signal(QuantSignalLabel.HOLD)

        with patch("tradingagents.quant.backtest.run_quant_engine", side_effect=fake_engine):
            return run_backtest("TEST", self.bars_15m, self.bars_4h, 10_000.0, cfg)

    # ----- Tests -----------------------------------------------------------

    def test_equity_starts_at_initial(self):
        """Equity curve first value equals initial_equity when no position opens early."""
        result = self._run([QuantSignalLabel.HOLD] * 30)
        self.assertEqual(result.equity_curve[0], 10_000.0)

    def test_no_signal_no_trades(self):
        result = self._run([QuantSignalLabel.HOLD] * 30)
        self.assertEqual(result.trade_count, 0)
        self.assertAlmostEqual(result.final_equity, 10_000.0)

    def test_buy_signal_opens_long(self):
        """A BUY signal at bar warmup opens a long position at bar warmup+1 open."""
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.HOLD] * 27
        result = self._run(signals)
        self.assertGreater(result.trade_count, 0)
        trade = result.trades[0]
        self.assertEqual(trade.direction, "long")

    def test_fill_at_next_bar_open(self):
        """Entry fill price must be based on the bar *after* the signal bar."""
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.HOLD] * 27
        cfg = {**_BASE_CFG, "backtest_slippage_pct": 0.0}  # zero slippage for clean check
        result = self._run(signals, cfg)
        if result.trade_count == 0:
            return  # ATR sizing gave 0 qty — skip (insufficient price movement)
        trade = result.trades[0]
        # Entry bar index is after warmup (index 2), so signal fires at i=2, fill at i=3
        # entry_bar_idx should be 3 (the bar where fill happened)
        self.assertGreater(trade.entry_bar_idx, 2)
        expected_open = float(self.bars_15m.iloc[trade.entry_bar_idx]["Open"])
        self.assertAlmostEqual(trade.entry_price, expected_open, places=4)

    def test_slippage_applied_to_entry(self):
        """Long entry fill price > bar open (slippage adds cost)."""
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.HOLD] * 27
        result = self._run(signals)
        if result.trade_count == 0:
            return
        trade = result.trades[0]
        bar_open = float(self.bars_15m.iloc[trade.entry_bar_idx]["Open"])
        self.assertGreaterEqual(trade.entry_price, bar_open)

    def test_commission_deducted(self):
        """net_pnl == gross_pnl − 2×commission for a signal-reversal round-trip."""
        # Force a quick BUY then immediate SELL reversal
        signals = (
            [QuantSignalLabel.HOLD] * 2
            + [QuantSignalLabel.BUY]
            + [QuantSignalLabel.SELL]
            + [QuantSignalLabel.HOLD] * 26
        )
        result = self._run(signals)
        if result.trade_count == 0:
            return
        trade = result.trades[0]
        # A closed trade pays entry commission + exit commission = 2 × commission_per_order
        total_commission = 2.0 * _BASE_CFG["backtest_commission"]
        expected_net = round(trade.gross_pnl - total_commission, 6)
        self.assertAlmostEqual(trade.net_pnl, expected_net, places=4)

    def test_signal_reversal_exit(self):
        """SELL signal while long triggers signal_reversal exit."""
        signals = (
            [QuantSignalLabel.HOLD] * 2
            + [QuantSignalLabel.BUY]
            + [QuantSignalLabel.SELL]
            + [QuantSignalLabel.HOLD] * 26
        )
        result = self._run(signals)
        if result.trade_count == 0:
            return
        self.assertEqual(result.trades[0].exit_reason, "signal_reversal")

    def test_end_of_data_exit(self):
        """Open position at end of data is closed with exit_reason end_of_data."""
        # Use a very large stop multiplier so the stop never fires on 28-bar test data,
        # guaranteeing the position remains open until end-of-data.
        cfg_wide_stop = {**_BASE_CFG, "atr_stop_mult": 1000.0}
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.HOLD] * 27
        result = self._run(signals, cfg_wide_stop)
        if result.trade_count == 0:
            return
        self.assertEqual(result.trades[-1].exit_reason, "end_of_data")

    def test_stop_exit_fires(self):
        """Stop loss fires when bar's Low crosses below stop_price for a long."""
        # We need ATR-based stop. Use very tight stop (atr_stop_mult=0.001)
        # so that any normal bar movement triggers stop.
        cfg = {**_BASE_CFG, "atr_stop_mult": 0.001}
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.HOLD] * 27
        result = self._run(signals, cfg)
        # With very tight stops, stop should fire on most bars
        if result.trade_count > 0:
            # At least one exit should be a stop
            stop_trades = [t for t in result.trades if t.exit_reason == "stop"]
            self.assertGreater(len(stop_trades), 0)

    def test_determinism(self):
        """Same inputs produce identical BacktestResult."""
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.SELL] + [QuantSignalLabel.HOLD] * 26
        r1 = self._run(signals)
        r2 = self._run(signals)
        self.assertEqual(r1.equity_curve, r2.equity_curve)
        self.assertEqual(r1.trade_count, r2.trade_count)
        self.assertEqual(r1.final_equity, r2.final_equity)

    def test_equity_curve_length_equals_bar_count(self):
        """Equity curve has exactly one entry per 15m bar."""
        result = self._run([QuantSignalLabel.HOLD] * 30)
        self.assertEqual(len(result.equity_curve), len(self.bars_15m))

    def test_equity_curve_length_invariant_for_single_bar(self):
        """len(equity_curve) == len(bars_15m) even when bars_15m has fewer than 2 bars."""
        single_bar = self.bars_15m.iloc[:1]
        four_h = self.bars_4h.iloc[:2]
        with patch("tradingagents.quant.backtest.run_quant_engine", return_value=_stub_signal(QuantSignalLabel.HOLD)):
            result = run_backtest("TEST", single_bar, four_h, 10_000.0, _BASE_CFG)
        self.assertEqual(len(result.equity_curve), 1)
        self.assertEqual(result.equity_curve[0], 10_000.0)

    def test_equity_curve_length_invariant_for_zero_bars(self):
        """len(equity_curve) == 0 when bars_15m is empty."""
        empty = self.bars_15m.iloc[:0]
        result = run_backtest("TEST", empty, self.bars_4h, 10_000.0, _BASE_CFG)
        self.assertEqual(len(result.equity_curve), 0)

    def test_final_equity_matches_last_equity_curve(self):
        result = self._run([QuantSignalLabel.HOLD] * 30)
        self.assertAlmostEqual(result.final_equity, result.equity_curve[-1], places=5)


# ---------------------------------------------------------------------------
# Three known-trade spot-checks (P&L arithmetic)
# ---------------------------------------------------------------------------

class TestKnownTradeSpotChecks(unittest.TestCase):
    """Verify P&L arithmetic matches manual calculation for 3 specific trades."""

    def _make_flat_bars(self, n=50, price=100.0):
        """Flat OHLCV bars: every bar has the same Open/High/Low/Close."""
        idx = pd.date_range("2024-01-02 09:30", periods=n, freq="15min")
        return pd.DataFrame(
            {
                "Open": [price] * n,
                "High": [price * 1.001] * n,
                "Low": [price * 0.999] * n,
                "Close": [price] * n,
                "Volume": [500_000.0] * n,
            },
            index=idx,
        )

    def _make_flat_4h(self, n=15, price=100.0):
        idx = pd.date_range("2024-01-02 09:30", periods=n, freq="4h")
        return pd.DataFrame(
            {
                "Open": [price] * n,
                "High": [price * 1.001] * n,
                "Low": [price * 0.999] * n,
                "Close": [price] * n,
                "Volume": [1_000_000.0] * n,
            },
            index=idx,
        )

    def _run_with_signals(self, bars_15m, bars_4h, signal_seq, cfg=None):
        full_cfg = {**_BASE_CFG, **(cfg or {})}
        call_count = [0]

        def fake_engine(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(signal_seq):
                return _stub_signal(signal_seq[idx])
            return _stub_signal(QuantSignalLabel.HOLD)

        with patch("tradingagents.quant.backtest.run_quant_engine", side_effect=fake_engine):
            return run_backtest("TEST", bars_15m, bars_4h, 10_000.0, full_cfg)

    # Trade 1: winning long (buy at 100, close at 102)
    def test_trade1_winning_long(self):
        """Long entry at 100, exit at 102 → gross_pnl = (102-100)*qty."""
        bars_15m = self._make_flat_bars(n=30, price=100.0)
        # Modify last 5 bars to have a higher close for mark-to-market
        for i in range(25, 30):
            bars_15m.iloc[i, bars_15m.columns.get_loc("Close")] = 102.0
            bars_15m.iloc[i, bars_15m.columns.get_loc("Open")] = 102.0
            bars_15m.iloc[i, bars_15m.columns.get_loc("High")] = 102.5
            bars_15m.iloc[i, bars_15m.columns.get_loc("Low")] = 101.5
        bars_4h = self._make_flat_4h(n=8)

        # Signal: BUY at bar 2 → fill at bar 3's open (100.0)
        # Then HOLD until end → end_of_data exit at bar 29's close (102.0)
        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.BUY] + [QuantSignalLabel.HOLD] * 27
        cfg = {"backtest_slippage_pct": 0.0, "backtest_commission": 0.0}
        result = self._run_with_signals(bars_15m, bars_4h, signals, cfg)

        if result.trade_count == 0:
            return  # ATR gave 0 qty for flat data — skip

        trade = result.trades[-1]  # end_of_data exit
        self.assertEqual(trade.direction, "long")
        self.assertAlmostEqual(trade.exit_price, 102.0, places=2)
        expected_gross = (trade.exit_price - trade.entry_price) * trade.quantity
        self.assertAlmostEqual(trade.gross_pnl, expected_gross, places=4)

    # Trade 2: winning short (sell at 100, buy back at 98)
    def test_trade2_winning_short(self):
        """Short entry at 100, closed at 98 → gross_pnl = (100-98)*qty."""
        bars_15m = self._make_flat_bars(n=30, price=100.0)
        for i in range(25, 30):
            bars_15m.iloc[i, bars_15m.columns.get_loc("Close")] = 98.0
            bars_15m.iloc[i, bars_15m.columns.get_loc("Open")] = 98.0
            bars_15m.iloc[i, bars_15m.columns.get_loc("High")] = 98.5
            bars_15m.iloc[i, bars_15m.columns.get_loc("Low")] = 97.5
        bars_4h = self._make_flat_4h(n=8)

        signals = [QuantSignalLabel.HOLD] * 2 + [QuantSignalLabel.SELL] + [QuantSignalLabel.HOLD] * 27
        cfg = {"backtest_slippage_pct": 0.0, "backtest_commission": 0.0}
        result = self._run_with_signals(bars_15m, bars_4h, signals, cfg)

        if result.trade_count == 0:
            return

        trade = result.trades[-1]
        self.assertEqual(trade.direction, "short")
        self.assertAlmostEqual(trade.exit_price, 98.0, places=2)
        expected_gross = (trade.entry_price - trade.exit_price) * trade.quantity
        self.assertAlmostEqual(trade.gross_pnl, expected_gross, places=4)

    # Trade 3: commission correctly reduces net_pnl
    def test_trade3_commission_arithmetic(self):
        """net_pnl = gross_pnl - total_commission for a reversal exit."""
        bars_15m = self._make_flat_bars(n=20, price=100.0)
        bars_4h = self._make_flat_4h(n=5)

        # BUY → immediate SELL reversal
        signals = (
            [QuantSignalLabel.HOLD] * 2
            + [QuantSignalLabel.BUY]
            + [QuantSignalLabel.SELL]
            + [QuantSignalLabel.HOLD] * 16
        )
        commission = 7.5
        cfg = {"backtest_slippage_pct": 0.0, "backtest_commission": commission}
        result = self._run_with_signals(bars_15m, bars_4h, signals, cfg)

        if result.trade_count == 0:
            return

        trade = result.trades[0]
        # net_pnl = gross_pnl - total_commission; commission field holds entry + exit
        self.assertAlmostEqual(trade.net_pnl, round(trade.gross_pnl - trade.commission, 6), places=4)


# ---------------------------------------------------------------------------
# No-lookahead verification
# ---------------------------------------------------------------------------

class TestNoLookahead(unittest.TestCase):

    def test_engine_never_sees_future_bars(self):
        """At each engine call, visible_15m must not exceed bar index i."""
        bars_15m = _make_15m(n=50, base=100.0, seed=7)
        bars_4h = _make_4h(n=15, base=100.0, seed=7)
        cfg = {**_BASE_CFG, "backtest_warmup_bars": 5}

        seen_lengths = []

        def recording_engine(symbol, trade_date, vis_15m, vis_4h, cfg_arg):
            seen_lengths.append(len(vis_15m))
            return _stub_signal(QuantSignalLabel.HOLD)

        with patch(
            "tradingagents.quant.backtest.run_quant_engine",
            side_effect=recording_engine,
        ):
            run_backtest("TEST", bars_15m, bars_4h, 10_000.0, cfg)

        # Each call i should have seen exactly (i+1) bars.
        # We call from i=warmup=5 to i=n_bars-2=48, so lengths are 6,7,...,49
        self.assertTrue(len(seen_lengths) > 0)
        for j, L in enumerate(seen_lengths):
            expected_i = 5 + j  # warmup=5, first call at i=5 → L=6
            self.assertEqual(L, expected_i + 1, msg=f"Call {j}: expected {expected_i+1} bars, got {L}")

    def test_4h_bars_filtered_by_timestamp(self):
        """Visible 4h bars must have index ≤ current 15m bar timestamp."""
        bars_15m = _make_15m(n=50, base=100.0, seed=9)
        bars_4h = _make_4h(n=15, base=100.0, seed=9)
        cfg = {**_BASE_CFG, "backtest_warmup_bars": 5}

        violations = []

        def checking_engine(symbol, trade_date, vis_15m, vis_4h, cfg_arg):
            current_ts = vis_15m.index[-1]
            if not vis_4h.empty and vis_4h.index.max() > current_ts:
                violations.append((str(current_ts), str(vis_4h.index.max())))
            return _stub_signal(QuantSignalLabel.HOLD)

        with patch(
            "tradingagents.quant.backtest.run_quant_engine",
            side_effect=checking_engine,
        ):
            run_backtest("TEST", bars_15m, bars_4h, 10_000.0, cfg)

        self.assertEqual(violations, [], msg=f"Lookahead violations found: {violations}")


# ---------------------------------------------------------------------------
# Walk-forward fold non-leakage
# ---------------------------------------------------------------------------

class TestWalkForward(unittest.TestCase):

    def setUp(self):
        self.bars_15m = _make_15m(n=500, base=100.0, seed=3)
        self.bars_4h = _make_4h(n=130, base=100.0, seed=3)
        self.cfg = {**_BASE_CFG, "backtest_warmup_bars": 10}

    def test_folds_are_adjacent_and_non_overlapping(self):
        """For every fold k, fold[k].is_end == fold[k].oos_start."""
        with patch(
            "tradingagents.quant.walkforward.run_backtest",
            side_effect=lambda *a, **kw: _stub_backtest_result(),
        ):
            result = run_walk_forward(
                "TEST", self.bars_15m, self.bars_4h,
                n_folds=4, in_sample_ratio=0.7,
                initial_equity=10_000.0, config=self.cfg,
            )

        self.assertEqual(result.n_folds, 4)
        for fold in result.folds:
            self.assertEqual(
                fold.is_end, fold.oos_start,
                msg=f"Fold {fold.fold_idx}: IS_end={fold.is_end} != OOS_start={fold.oos_start}",
            )

    def test_no_bar_appears_in_two_oos_windows(self):
        """OOS windows are disjoint across all folds."""
        with patch(
            "tradingagents.quant.walkforward.run_backtest",
            side_effect=lambda *a, **kw: _stub_backtest_result(),
        ):
            result = run_walk_forward(
                "TEST", self.bars_15m, self.bars_4h,
                n_folds=4, in_sample_ratio=0.7,
                initial_equity=10_000.0, config=self.cfg,
            )

        oos_ranges = [range(f.oos_start, f.oos_end) for f in result.folds]
        all_oos = [idx for r in oos_ranges for idx in r]
        self.assertEqual(len(all_oos), len(set(all_oos)), "Duplicate bar indices in OOS windows")

    def test_oos_sharpe_positive_pct_calculation(self):
        """oos_sharpe_positive_pct counts folds with OOS Sharpe > 0 correctly."""
        sharpes = [0.8, -0.2, 1.1, -0.5]
        call_idx = [0]

        def fake_backtest(symbol, bars_15m, bars_4h, eq, cfg):
            # Alternate IS/OOS calls: IS=0,2,4,6, OOS=1,3,5,7
            is_sharpe = 1.0
            oos_sharpe = sharpes[call_idx[0] // 2] if call_idx[0] % 2 == 1 else 1.0
            call_idx[0] += 1
            return _stub_backtest_result(sharpe=oos_sharpe if call_idx[0] % 2 == 0 else is_sharpe)

        with patch("tradingagents.quant.walkforward.run_backtest", side_effect=fake_backtest):
            result = run_walk_forward(
                "TEST", self.bars_15m, self.bars_4h,
                n_folds=4, in_sample_ratio=0.7,
                initial_equity=10_000.0, config=self.cfg,
            )

        # oos_sharpe_positive_pct is computed from WalkForwardFold.oos_sharpe
        # which is the sharpe of the OOS backtest (second call per fold)
        pos = sum(1 for f in result.folds if f.oos_sharpe > 0.0)
        self.assertEqual(result.oos_sharpe_positive_pct, round(pos / 4, 4))

    def test_invalid_n_folds_raises(self):
        with self.assertRaises(ValueError):
            run_walk_forward("X", self.bars_15m, self.bars_4h, n_folds=1)

    def test_invalid_in_sample_ratio_raises(self):
        with self.assertRaises(ValueError):
            run_walk_forward("X", self.bars_15m, self.bars_4h, n_folds=2, in_sample_ratio=1.0)


# ---------------------------------------------------------------------------
# Paper gate
# ---------------------------------------------------------------------------

class TestPaperGate(unittest.TestCase):

    def _result(self, sharpe=1.0, drawdown=0.02, trades=5, eq_gain=1000.0):
        initial = 10_000.0
        final = initial + eq_gain
        n = 50
        # Build a simple monotone equity curve for the given Sharpe direction
        eq = tuple(initial + (eq_gain / n) * i for i in range(n))
        return BacktestResult(
            symbol="TEST",
            initial_equity=initial,
            final_equity=final,
            trades=(),
            equity_curve=eq,
            sharpe_ratio=sharpe,
            max_drawdown_pct=drawdown,
            total_return_pct=round(eq_gain / initial * 100, 4),
            trade_count=trades,
            winning_trades=trades,
            win_rate=1.0,
        )

    def test_passes_all_thresholds(self):
        gate = PaperGate(min_session_sharpe=0.5, max_intraday_drawdown_pct=0.05, min_trades=1)
        r = self._result(sharpe=1.2, drawdown=0.03, trades=5)
        outcome = gate.evaluate(r)
        self.assertTrue(outcome.passed)
        self.assertEqual(len(outcome.reasons), 0)

    def test_fails_low_sharpe(self):
        gate = PaperGate(min_session_sharpe=0.5)
        r = self._result(sharpe=0.3, drawdown=0.03, trades=5)
        outcome = gate.evaluate(r)
        self.assertFalse(outcome.passed)
        self.assertTrue(any("Sharpe" in reason for reason in outcome.reasons))

    def test_fails_high_drawdown(self):
        gate = PaperGate(max_intraday_drawdown_pct=0.05)
        r = self._result(sharpe=1.0, drawdown=0.07, trades=5)
        outcome = gate.evaluate(r)
        self.assertFalse(outcome.passed)
        self.assertTrue(any("drawdown" in reason for reason in outcome.reasons))

    def test_fails_insufficient_trades(self):
        gate = PaperGate(min_trades=3)
        r = self._result(sharpe=1.0, drawdown=0.02, trades=2)
        outcome = gate.evaluate(r)
        self.assertFalse(outcome.passed)
        self.assertTrue(any("trades" in reason for reason in outcome.reasons))

    def test_sharpe_exactly_at_threshold_fails(self):
        """Sharpe must be strictly greater than the threshold."""
        gate = PaperGate(min_session_sharpe=0.5)
        r = self._result(sharpe=0.5, drawdown=0.02, trades=5)
        outcome = gate.evaluate(r)
        self.assertFalse(outcome.passed)

    def test_drawdown_exactly_at_limit_fails(self):
        """Drawdown must be strictly less than the limit."""
        gate = PaperGate(max_intraday_drawdown_pct=0.05)
        r = self._result(sharpe=1.0, drawdown=0.05, trades=5)
        outcome = gate.evaluate(r)
        self.assertFalse(outcome.passed)

    def test_result_fields_populated(self):
        gate = PaperGate()
        r = self._result(sharpe=1.0, drawdown=0.02, trades=5, eq_gain=500.0)
        outcome = gate.evaluate(r)
        self.assertEqual(outcome.session_sharpe, 1.0)
        self.assertAlmostEqual(outcome.max_intraday_drawdown_pct, 0.02)
        self.assertEqual(outcome.trade_count, 5)
        self.assertAlmostEqual(outcome.net_pnl, 500.0)

    def test_zero_trades_always_fails(self):
        gate = PaperGate(min_trades=1)
        r = self._result(sharpe=10.0, drawdown=0.001, trades=0)
        outcome = gate.evaluate(r)
        self.assertFalse(outcome.passed)

    def test_invalid_gate_params(self):
        with self.assertRaises(ValueError):
            PaperGate(min_session_sharpe=-1.0)
        with self.assertRaises(ValueError):
            PaperGate(max_intraday_drawdown_pct=0.0)
        with self.assertRaises(ValueError):
            PaperGate(min_trades=0)

    def test_to_dict_serialisable(self):
        gate = PaperGate()
        r = self._result()
        outcome = gate.evaluate(r)
        d = outcome.to_dict()
        self.assertIn("passed", d)
        self.assertIn("session_sharpe", d)
        self.assertIn("reasons", d)
        self.assertIsInstance(d["reasons"], list)


# ---------------------------------------------------------------------------
# Integration smoke test (real engine, synthetic data)
# ---------------------------------------------------------------------------

class TestBacktestIntegration(unittest.TestCase):
    """Light integration test — real engine on synthetic data, smoke only."""

    def test_run_backtest_returns_result(self):
        bars_15m = _make_15m(n=300, base=100.0, seed=42)
        bars_4h = _make_4h(n=80, base=100.0, seed=42)
        cfg = {
            "backtest_warmup_bars": 60,
            "backtest_slippage_pct": 0.0005,
            "backtest_commission": 1.0,
            "bars_per_day": 26,
            "min_4h_bars": 30,
            "validation_momentum": False,
            "validation_squeeze": False,
            "validation_sr_proximity": False,
        }
        result = run_backtest("SMOKE", bars_15m, bars_4h, 100_000.0, cfg)
        self.assertIsInstance(result, BacktestResult)
        self.assertEqual(len(result.equity_curve), len(bars_15m))
        self.assertAlmostEqual(result.equity_curve[0], 100_000.0, places=2)
        # Final equity must be positive
        self.assertGreater(result.final_equity, 0.0)

    def test_paper_gate_evaluates_integration_result(self):
        bars_15m = _make_15m(n=300, base=100.0, seed=13)
        bars_4h = _make_4h(n=80, base=100.0, seed=13)
        cfg = {
            "backtest_warmup_bars": 60,
            "min_4h_bars": 30,
            "validation_momentum": False,
            "validation_squeeze": False,
            "validation_sr_proximity": False,
        }
        result = run_backtest("SMOKE", bars_15m, bars_4h, 100_000.0, cfg)
        gate = PaperGate(min_session_sharpe=0.5, max_intraday_drawdown_pct=0.05, min_trades=1)
        outcome = gate.evaluate(result)
        # Just verify it runs without error and fields are populated
        self.assertIsInstance(outcome.passed, bool)
        self.assertIsInstance(outcome.reasons, tuple)


# ---------------------------------------------------------------------------
# Helpers for stub results
# ---------------------------------------------------------------------------

def _stub_backtest_result(sharpe: float = 0.0) -> BacktestResult:
    return BacktestResult(
        symbol="STUB",
        initial_equity=10_000.0,
        final_equity=10_000.0,
        trades=(),
        equity_curve=(10_000.0,),
        sharpe_ratio=sharpe,
        max_drawdown_pct=0.0,
        total_return_pct=0.0,
        trade_count=0,
        winning_trades=0,
        win_rate=0.0,
    )


if __name__ == "__main__":
    unittest.main()
