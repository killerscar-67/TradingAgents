"""Unit tests for Phase 3: hard risk and position sizing."""

import unittest
from tradingagents.quant.contracts import (
    DailyLossState, EntryEngine, EntrySignal, PositionSizeContract,
    RiskGateResult, StopContract,
)
from tradingagents.quant.risk import (
    check_risk_gates, compute_stops, size_position, update_daily_loss,
)


def _long_signal() -> EntrySignal:
    return EntrySignal(engine=EntryEngine.BREAKOUT, direction="long", strength=0.8, reason="t")


def _short_signal() -> EntrySignal:
    return EntrySignal(engine=EntryEngine.MEAN_REVERSION, direction="short", strength=0.6, reason="t")


def _fresh_state(date="2026-04-21") -> DailyLossState:
    return DailyLossState.new_day(date)


def _make_size(notional=5000.0, direction="long", entry_price=100.0) -> PositionSizeContract:
    return PositionSizeContract(
        symbol="breakout", direction=direction,
        quantity=notional / entry_price, entry_price=entry_price,
        notional=notional, stop_price=entry_price - 2.0,
        risk_amount=notional / entry_price * 2.0, method="fixed_fractional",
    )


class TestSizePosition(unittest.TestCase):
    def test_basic_long_sizing(self):
        # equity=100_000, risk=1%, atr=1.0, stop_mult=2.0 -> qty=100
        result = size_position(_long_signal(), entry_price=100.0, atr_15m=1.0, account_equity=100_000)
        self.assertEqual(result.direction, "long")
        self.assertAlmostEqual(result.quantity, 100.0)
        self.assertAlmostEqual(result.notional, 10_000.0)
        self.assertAlmostEqual(result.stop_price, 98.0)
        self.assertAlmostEqual(result.risk_amount, 200.0)
        self.assertEqual(result.method, "fixed_fractional")

    def test_basic_short_stop_above_entry(self):
        result = size_position(_short_signal(), entry_price=50.0, atr_15m=0.5, account_equity=100_000)
        self.assertEqual(result.direction, "short")
        self.assertAlmostEqual(result.stop_price, 51.0)

    def test_risk_budget_binds(self):
        # equity=10_000, atr=1.0, stop=2.0, raw=50; cap=20 -> qty=20
        result = size_position(_long_signal(), entry_price=50.0, atr_15m=1.0, account_equity=10_000)
        self.assertAlmostEqual(result.quantity, 20.0)

    def test_custom_config(self):
        cfg = {"risk_per_trade_pct": 0.02, "atr_stop_mult": 1.0, "max_position_size_pct": 0.50}
        # stop=1, max_risk=200, raw=200; cap=50 -> qty=50
        result = size_position(_long_signal(), entry_price=100.0, atr_15m=1.0, account_equity=10_000, config=cfg)
        self.assertAlmostEqual(result.quantity, 50.0)

    def test_raises_non_positive_entry_price(self):
        with self.assertRaises(ValueError):
            size_position(_long_signal(), entry_price=0.0, atr_15m=1.0, account_equity=10_000)

    def test_raises_non_positive_atr(self):
        with self.assertRaises(ValueError):
            size_position(_long_signal(), entry_price=100.0, atr_15m=0.0, account_equity=10_000)

    def test_raises_non_positive_equity(self):
        with self.assertRaises(ValueError):
            size_position(_long_signal(), entry_price=100.0, atr_15m=1.0, account_equity=0.0)

    def test_to_dict_has_required_fields(self):
        d = size_position(_long_signal(), entry_price=100.0, atr_15m=1.0, account_equity=10_000).to_dict()
        for key in ("quantity", "notional", "stop_price", "risk_amount", "method"):
            self.assertIn(key, d)


class TestComputeStops(unittest.TestCase):
    def test_long_stops(self):
        result = compute_stops("long", entry_price=100.0, atr_15m=1.0)
        self.assertAlmostEqual(result.initial_stop, 98.0)
        self.assertAlmostEqual(result.breakeven_trigger, 101.0)
        self.assertAlmostEqual(result.trailing_distance, 1.5)

    def test_short_stops(self):
        result = compute_stops("short", entry_price=100.0, atr_15m=1.0)
        self.assertAlmostEqual(result.initial_stop, 102.0)
        self.assertAlmostEqual(result.breakeven_trigger, 99.0)

    def test_trailing_distance_always_positive(self):
        for direction in ("long", "short"):
            result = compute_stops(direction, entry_price=50.0, atr_15m=0.5)
            self.assertGreater(result.trailing_distance, 0)

    def test_custom_multiples(self):
        cfg = {"atr_stop_mult": 3.0, "breakeven_atr_mult": 2.0, "trailing_atr_mult": 2.5}
        result = compute_stops("long", entry_price=100.0, atr_15m=1.0, config=cfg)
        self.assertAlmostEqual(result.initial_stop, 97.0)
        self.assertAlmostEqual(result.breakeven_trigger, 102.0)
        self.assertAlmostEqual(result.trailing_distance, 2.5)

    def test_raises_non_positive_entry(self):
        with self.assertRaises(ValueError):
            compute_stops("long", entry_price=-1.0, atr_15m=1.0)

    def test_raises_non_positive_atr(self):
        with self.assertRaises(ValueError):
            compute_stops("long", entry_price=100.0, atr_15m=0.0)

    def test_to_dict_fields(self):
        d = compute_stops("long", entry_price=100.0, atr_15m=1.0).to_dict()
        for key in ("initial_stop", "breakeven_trigger", "trailing_distance"):
            self.assertIn(key, d)

    def test_long_stop_rounding_preserves_directional_levels(self):
        result = compute_stops("long", entry_price=100.0, atr_15m=1e-9)
        self.assertLess(result.initial_stop, 100.0)
        self.assertGreater(result.breakeven_trigger, 100.0)
        self.assertGreater(result.trailing_distance, 0.0)

class TestCheckRiskGates(unittest.TestCase):
    def test_all_clear(self):
        result = check_risk_gates(_make_size(), _fresh_state(), 0.0, 100_000)
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "")
        self.assertFalse(result.kill_switch)

    def test_kill_switch_blocks(self):
        state = DailyLossState(date="2026-04-21", net_pnl=-3_500.0, kill_switch=True, trade_count=5)
        result = check_risk_gates(_make_size(), state, 0.0, 100_000)
        self.assertFalse(result.allowed)
        self.assertTrue(result.kill_switch)

    def test_daily_loss_cap_blocks(self):
        state = DailyLossState(date="2026-04-21", net_pnl=-2_001.0, kill_switch=False, trade_count=3)
        result = check_risk_gates(_make_size(), state, 0.0, 100_000)
        self.assertFalse(result.allowed)
        self.assertIn("daily loss cap", result.reason)

    def test_daily_loss_exact_threshold_blocks(self):
        state = DailyLossState(date="2026-04-21", net_pnl=-2_000.0, kill_switch=False, trade_count=2)
        result = check_risk_gates(_make_size(), state, 0.0, 100_000)
        self.assertFalse(result.allowed)

    def test_exposure_cap_blocks(self):
        result = check_risk_gates(_make_size(), _fresh_state(), 16_000.0, 100_000)
        self.assertFalse(result.allowed)
        self.assertIn("exposure cap", result.reason)

    def test_exposure_exactly_at_cap_is_allowed(self):
        # current=15_000 + notional=5_000 = 20_000 == cap -> NOT strictly greater
        result = check_risk_gates(_make_size(), _fresh_state(), 15_000.0, 100_000)
        self.assertTrue(result.allowed)

    def test_kill_switch_priority_over_daily_loss(self):
        state = DailyLossState(date="2026-04-21", net_pnl=-5_000.0, kill_switch=True, trade_count=10)
        result = check_risk_gates(_make_size(), state, 0.0, 100_000)
        self.assertTrue(result.kill_switch)

    def test_non_positive_equity_blocks(self):
        result = check_risk_gates(_make_size(), _fresh_state(), 0.0, 0.0)
        self.assertFalse(result.allowed)

    def test_custom_daily_loss_pct_relaxed(self):
        cfg = {"max_daily_loss_pct": 0.05}
        state = DailyLossState(date="2026-04-21", net_pnl=-3_000.0, kill_switch=False, trade_count=2)
        result = check_risk_gates(_make_size(), state, 0.0, 100_000, config=cfg)
        self.assertTrue(result.allowed)

    def test_to_dict_fields(self):
        d = check_risk_gates(_make_size(), _fresh_state(), 0.0, 100_000).to_dict()
        for key in ("allowed", "reason", "kill_switch"):
            self.assertIn(key, d)

class TestUpdateDailyLoss(unittest.TestCase):
    def test_profitable_trade(self):
        new = update_daily_loss(_fresh_state(), 500.0, 100_000)
        self.assertAlmostEqual(new.net_pnl, 500.0)
        self.assertEqual(new.trade_count, 1)
        self.assertFalse(new.kill_switch)

    def test_losing_trade(self):
        new = update_daily_loss(_fresh_state(), -1_000.0, 100_000)
        self.assertAlmostEqual(new.net_pnl, -1_000.0)

    def test_kill_switch_at_threshold(self):
        new = update_daily_loss(_fresh_state(), -3_000.0, 100_000)
        self.assertTrue(new.kill_switch)

    def test_kill_switch_not_triggered_below_threshold(self):
        new = update_daily_loss(_fresh_state(), -2_999.0, 100_000)
        self.assertFalse(new.kill_switch)

    def test_kill_switch_latches(self):
        state = DailyLossState(date="2026-04-21", net_pnl=-3_500.0, kill_switch=True, trade_count=4)
        new = update_daily_loss(state, 1_000.0, 100_000)
        self.assertTrue(new.kill_switch)

    def test_trade_count_increments(self):
        state = DailyLossState(date="2026-04-21", net_pnl=0.0, kill_switch=False, trade_count=7)
        new = update_daily_loss(state, 100.0, 100_000)
        self.assertEqual(new.trade_count, 8)

    def test_date_preserved(self):
        new = update_daily_loss(_fresh_state("2026-01-15"), -100.0, 100_000)
        self.assertEqual(new.date, "2026-01-15")

    def test_custom_ks_pct(self):
        cfg = {"kill_switch_daily_loss_pct": 0.05}
        new = update_daily_loss(_fresh_state(), -3_000.0, 100_000, config=cfg)
        self.assertFalse(new.kill_switch)
        new2 = update_daily_loss(_fresh_state(), -5_000.0, 100_000, config=cfg)
        self.assertTrue(new2.kill_switch)

    def test_original_state_immutable(self):
        state = _fresh_state()
        _ = update_daily_loss(state, -500.0, 100_000)
        self.assertAlmostEqual(state.net_pnl, 0.0)
        self.assertEqual(state.trade_count, 0)


class TestNewDay(unittest.TestCase):
    def test_zeroed(self):
        state = DailyLossState.new_day("2026-04-21")
        self.assertEqual(state.date, "2026-04-21")
        self.assertAlmostEqual(state.net_pnl, 0.0)
        self.assertFalse(state.kill_switch)
        self.assertEqual(state.trade_count, 0)

    def test_to_dict(self):
        d = DailyLossState.new_day("2026-04-21").to_dict()
        for key in ("date", "net_pnl", "kill_switch", "trade_count"):
            self.assertIn(key, d)


class TestDeterminism(unittest.TestCase):
    def test_size_position(self):
        s = _long_signal()
        self.assertEqual(size_position(s, 100.0, 1.5, 50_000), size_position(s, 100.0, 1.5, 50_000))

    def test_compute_stops(self):
        self.assertEqual(compute_stops("long", 100.0, 1.5), compute_stops("long", 100.0, 1.5))

    def test_check_risk_gates(self):
        sz = _make_size()
        st = _fresh_state()
        self.assertEqual(check_risk_gates(sz, st, 0.0, 100_000), check_risk_gates(sz, st, 0.0, 100_000))

    def test_update_daily_loss(self):
        st = _fresh_state()
        self.assertEqual(update_daily_loss(st, -1_000.0, 50_000), update_daily_loss(st, -1_000.0, 50_000))


if __name__ == "__main__":
    unittest.main()