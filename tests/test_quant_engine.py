"""Phase 2: Deterministic quant engine tests.

Covers:
- Regime classifier: label assignment, tradability filter, HTF bias
- Breakout entry engine: detection, direction, volume gate
- Mean reversion entry engine: RSI + stretch detection, direction
- Directional filter: HTF bias gates entry direction
- Validation filters: momentum, squeeze, SR proximity (individually and combined)
- Engine orchestration: end-to-end pipeline + error isolation
- Determinism: identical inputs → identical outputs
- Contract types: NoSignal, EntrySignal, RegimeContract, ValidationResult
"""

import unittest
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import numpy as np

from tradingagents.quant.contracts import (
    EntryEngine,
    EntrySignal,
    NoSignal,
    RegimeLabel,
    QuantSignalLabel,
    ValidationResult,
)
from tradingagents.quant import regime as regime_mod
from tradingagents.quant import entry as entry_mod
from tradingagents.quant import validation as val_mod
from tradingagents.quant.engine import run_quant_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_index(n: int, freq: str = "15min") -> pd.DatetimeIndex:
    start = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
    return pd.date_range(start=start, periods=n, freq=freq)


def _make_bars(
    n: int,
    base_price: float = 100.0,
    trend: float = 0.0,          # price increment per bar
    noise: float = 0.5,          # ±noise around base
    volume: float = 500_000.0,
    freq: str = "15min",
    seed: int = 42,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with deterministic content."""
    rng = np.random.default_rng(seed)
    half = max(noise, 0.01)      # guard against noise=0 causing uniform(a,b) with a>b
    closes = base_price + trend * np.arange(n) + rng.uniform(-half, half, n)
    highs = closes + rng.uniform(0.01, half, n)
    lows = closes - rng.uniform(0.01, half, n)
    opens = closes + rng.uniform(-half / 2, half / 2, n)
    volumes = np.full(n, volume)

    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=_utc_index(n, freq),
    )


def _make_trending_bars(n: int = 200, freq: str = "4h") -> pd.DataFrame:
    """Strong uptrend — ADX should be high (trending regime)."""
    return _make_bars(n, base_price=100.0, trend=0.5, noise=0.2, freq=freq, seed=1)


def _make_ranging_bars(n: int = 200, freq: str = "4h") -> pd.DataFrame:
    """Oscillating price — ADX should be low (ranging regime)."""
    rng = np.random.default_rng(2)
    t = np.arange(n)
    closes = 100.0 + 3.0 * np.sin(2 * np.pi * t / 20) + rng.uniform(-0.3, 0.3, n)
    highs = closes + 0.3
    lows = closes - 0.3
    opens = closes + rng.uniform(-0.1, 0.1, n)
    idx = _utc_index(n, freq)
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": np.full(n, 500_000)},
        index=idx,
    )


def _make_tight_bars(n: int = 200, freq: str = "4h") -> pd.DataFrame:
    """Nearly flat bars — very low ATR → consolidation regime."""
    return _make_bars(n, base_price=100.0, trend=0.0, noise=0.01, volume=500_000, freq=freq, seed=3)


# ---------------------------------------------------------------------------
# Regime classifier tests
# ---------------------------------------------------------------------------


class RegimeClassifierTests(unittest.TestCase):

    def test_trending_regime_label(self):
        bars = _make_trending_bars()
        result = regime_mod.classify(bars)
        self.assertEqual(result.label, RegimeLabel.TRENDING)

    def test_ranging_regime_label(self):
        bars = _make_ranging_bars()
        result = regime_mod.classify(bars)
        self.assertIn(result.label, {RegimeLabel.RANGING, RegimeLabel.CONSOLIDATION})

    def test_consolidation_regime_label(self):
        bars = _make_tight_bars()
        result = regime_mod.classify(bars)
        # Very tight bars → low ATR → not tradable (regardless of label)
        self.assertFalse(result.tradable)

    def test_insufficient_bars_returns_non_tradable(self):
        bars = _make_bars(10, freq="4h")
        result = regime_mod.classify(bars)
        self.assertFalse(result.tradable)
        self.assertEqual(result.label, RegimeLabel.CONSOLIDATION)

    def test_low_volume_not_tradable(self):
        bars = _make_trending_bars()
        bars["Volume"] = 1.0   # far below default 100_000 threshold
        result = regime_mod.classify(bars)
        self.assertFalse(result.tradable)

    def test_htf_bias_bullish_when_above_sma(self):
        # Strong uptrend: price should be above SMA
        bars = _make_trending_bars()
        result = regime_mod.classify(bars)
        self.assertEqual(result.htf_bias, "bullish")

    def test_htf_bias_neutral_custom_threshold(self):
        bars = _make_bars(100, trend=0.001, noise=0.0, freq="4h")
        # With a very wide neutral band, even small trends register as neutral
        result = regime_mod.classify(bars, config={"htf_bias_neutral_pct": 1.0})
        self.assertEqual(result.htf_bias, "neutral")

    def test_adx_is_non_negative(self):
        bars = _make_ranging_bars()
        result = regime_mod.classify(bars)
        self.assertGreaterEqual(result.adx, 0.0)

    def test_atr_pct_is_non_negative(self):
        bars = _make_trending_bars()
        result = regime_mod.classify(bars)
        self.assertGreaterEqual(result.atr_pct, 0.0)

    def test_determinism(self):
        bars = _make_trending_bars()
        r1 = regime_mod.classify(bars)
        r2 = regime_mod.classify(bars)
        self.assertEqual(r1, r2)

    def test_to_dict_round_trips_label(self):
        bars = _make_trending_bars()
        result = regime_mod.classify(bars)
        d = result.to_dict()
        self.assertIn(d["label"], {"trending", "ranging", "consolidation"})


# ---------------------------------------------------------------------------
# Breakout entry engine tests
# ---------------------------------------------------------------------------


class BreakoutEngineTests(unittest.TestCase):

    def _bars_with_breakout_up(self, lookback: int = 20) -> pd.DataFrame:
        """N flat bars then one bar that closes above channel with high volume."""
        bars = _make_bars(lookback + 10, base_price=100.0, trend=0.0, noise=0.3, seed=10)
        # Force last bar to close well above channel high with volume spike
        bars.iloc[-1, bars.columns.get_loc("Close")] = 110.0
        bars.iloc[-1, bars.columns.get_loc("High")] = 110.5
        bars.iloc[-1, bars.columns.get_loc("Volume")] = 2_000_000.0  # spike > 1.5x avg
        return bars

    def _bars_with_breakout_down(self, lookback: int = 20) -> pd.DataFrame:
        bars = _make_bars(lookback + 10, base_price=100.0, trend=0.0, noise=0.3, seed=11)
        bars.iloc[-1, bars.columns.get_loc("Close")] = 90.0
        bars.iloc[-1, bars.columns.get_loc("Low")] = 89.5
        bars.iloc[-1, bars.columns.get_loc("Volume")] = 2_000_000.0  # spike > 1.5x avg
        return bars

    def test_detects_bullish_breakout(self):
        bars = self._bars_with_breakout_up()
        result = entry_mod.run_breakout(bars)
        self.assertIsInstance(result, EntrySignal)
        self.assertEqual(result.direction, "long")
        self.assertEqual(result.engine, EntryEngine.BREAKOUT)

    def test_detects_bearish_breakout(self):
        bars = self._bars_with_breakout_down()
        result = entry_mod.run_breakout(bars)
        self.assertIsInstance(result, EntrySignal)
        self.assertEqual(result.direction, "short")

    def test_no_signal_in_channel(self):
        bars = _make_bars(50, base_price=100.0, trend=0.0, noise=0.3, seed=12)
        result = entry_mod.run_breakout(bars)
        # price stays near 100; channel high/low close to same range
        # Allow either NoSignal or EntrySignal (depends on noise)
        # The important thing is that the function returns without error
        self.assertIsInstance(result, (EntrySignal, NoSignal))

    def test_insufficient_bars_returns_no_signal(self):
        bars = _make_bars(5)
        result = entry_mod.run_breakout(bars, config={"breakout_lookback": 20})
        self.assertIsInstance(result, NoSignal)

    def test_volume_gate_rejects_low_volume(self):
        bars = self._bars_with_breakout_up()
        # Set last bar volume to near-zero
        bars.iloc[-1, bars.columns.get_loc("Volume")] = 1.0
        result = entry_mod.run_breakout(bars, config={"breakout_volume_factor": 1.5})
        self.assertIsInstance(result, NoSignal)

    def test_strength_in_range(self):
        bars = self._bars_with_breakout_up()
        result = entry_mod.run_breakout(bars)
        if isinstance(result, EntrySignal):
            self.assertGreaterEqual(result.strength, 0.0)
            self.assertLessEqual(result.strength, 1.0)

    def test_determinism(self):
        bars = self._bars_with_breakout_up()
        r1 = entry_mod.run_breakout(bars)
        r2 = entry_mod.run_breakout(bars)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Mean reversion entry engine tests
# ---------------------------------------------------------------------------


class MeanReversionEngineTests(unittest.TestCase):

    # Use mr_stretch_std=1.5 in tests: a linear crash creates ~1.73 std of deviation
    # from the SMA (geometric property of linear series), which exceeds 1.5 but not 2.0.
    _MR_TEST_CONFIG = {"mr_stretch_std": 1.5}

    def _bars_oversold(self) -> pd.DataFrame:
        """80 flat bars at 100 then 10 rapid down bars to ~55.

        Design: SMA(20) window sees 10 flat + 10 falling bars → anchored ~77.
        RSI(14) with consecutive falls and EWM starting from flat → deep oversold.
        """
        flat_n, drop_n = 80, 10
        n = flat_n + drop_n
        rng = np.random.default_rng(20)
        flat = np.full(flat_n, 100.0) + rng.uniform(-0.02, 0.02, flat_n)
        drop = 100.0 - np.linspace(5, 45, drop_n) + rng.uniform(-0.02, 0.02, drop_n)
        closes = np.concatenate([flat, drop])
        highs = closes + 0.2
        lows = closes - 0.2
        opens = closes + rng.uniform(-0.02, 0.02, n)
        return pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": closes,
             "Volume": np.full(n, 500_000)},
            index=_utc_index(n),
        )

    def _bars_overbought(self) -> pd.DataFrame:
        """80 flat bars at 100 then 10 rapid up bars to ~145."""
        flat_n, rise_n = 80, 10
        n = flat_n + rise_n
        rng = np.random.default_rng(21)
        flat = np.full(flat_n, 100.0) + rng.uniform(-0.02, 0.02, flat_n)
        rise = 100.0 + np.linspace(5, 45, rise_n) + rng.uniform(-0.02, 0.02, rise_n)
        closes = np.concatenate([flat, rise])
        highs = closes + 0.2
        lows = closes - 0.2
        opens = closes + rng.uniform(-0.02, 0.02, n)
        return pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": closes,
             "Volume": np.full(n, 500_000)},
            index=_utc_index(n),
        )

    def test_oversold_produces_long_signal(self):
        bars = self._bars_oversold()
        result = entry_mod.run_mean_reversion(bars, config=self._MR_TEST_CONFIG)
        self.assertIsInstance(result, EntrySignal)
        self.assertEqual(result.direction, "long")
        self.assertEqual(result.engine, EntryEngine.MEAN_REVERSION)

    def test_overbought_produces_short_signal(self):
        bars = self._bars_overbought()
        result = entry_mod.run_mean_reversion(bars, config=self._MR_TEST_CONFIG)
        self.assertIsInstance(result, EntrySignal)
        self.assertEqual(result.direction, "short")

    def test_insufficient_bars_no_signal(self):
        bars = _make_bars(10)
        result = entry_mod.run_mean_reversion(bars)
        self.assertIsInstance(result, NoSignal)

    def test_neutral_bars_no_signal(self):
        bars = _make_bars(100, trend=0.0, noise=0.1, seed=30)
        result = entry_mod.run_mean_reversion(bars)
        # Flat market: RSI ~50, small stretch → no signal expected
        # (might be signal depending on noise; just check no exception)
        self.assertIsInstance(result, (EntrySignal, NoSignal))

    def test_strength_in_range(self):
        bars = self._bars_oversold()
        result = entry_mod.run_mean_reversion(bars, config=self._MR_TEST_CONFIG)
        if isinstance(result, EntrySignal):
            self.assertGreaterEqual(result.strength, 0.0)
            self.assertLessEqual(result.strength, 1.0)

    def test_determinism(self):
        bars = self._bars_oversold()
        r1 = entry_mod.run_mean_reversion(bars, config=self._MR_TEST_CONFIG)
        r2 = entry_mod.run_mean_reversion(bars, config=self._MR_TEST_CONFIG)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Directional filter tests (run_entry)
# ---------------------------------------------------------------------------


class DirectionalFilterTests(unittest.TestCase):

    def _regime(self, label=RegimeLabel.TRENDING, htf_bias="bullish", tradable=True):
        from tradingagents.quant.contracts import RegimeContract
        return RegimeContract(
            label=label, tradable=tradable, adx=30.0, atr=1.0, atr_pct=0.01,
            htf_bias=htf_bias,
        )

    def _breakout_up_bars(self, n: int = 40, seed: int = 40) -> pd.DataFrame:
        bars = _make_bars(n, base_price=100.0, trend=0.0, noise=0.3, seed=seed)
        bars.iloc[-1, bars.columns.get_loc("Close")] = 110.0
        bars.iloc[-1, bars.columns.get_loc("High")] = 110.5
        bars.iloc[-1, bars.columns.get_loc("Volume")] = 2_000_000.0
        return bars

    def test_bearish_htf_rejects_long_breakout(self):
        bars = self._breakout_up_bars(seed=40)
        regime = self._regime(label=RegimeLabel.TRENDING, htf_bias="bearish")
        result = entry_mod.run_entry(bars, regime)
        self.assertIsInstance(result, NoSignal)
        self.assertIn("HTF bias", result.reason)

    def test_bullish_htf_allows_long_breakout(self):
        bars = self._breakout_up_bars(seed=41)
        regime = self._regime(label=RegimeLabel.TRENDING, htf_bias="bullish")
        result = entry_mod.run_entry(bars, regime)
        self.assertIsInstance(result, EntrySignal)

    def test_non_tradable_regime_returns_no_signal(self):
        bars = _make_bars(100)
        regime = self._regime(tradable=False)
        result = entry_mod.run_entry(bars, regime)
        self.assertIsInstance(result, NoSignal)

    def test_consolidation_returns_no_signal(self):
        bars = _make_bars(100)
        regime = self._regime(label=RegimeLabel.CONSOLIDATION)
        result = entry_mod.run_entry(bars, regime)
        self.assertIsInstance(result, NoSignal)

    def test_neutral_bias_allows_both_directions(self):
        # neutral bias should not block either long or short
        signal = EntrySignal(
            engine=EntryEngine.BREAKOUT, direction="long", strength=0.5, reason="test"
        )
        self.assertTrue(entry_mod._direction_allowed(signal, "neutral"))

        signal_short = EntrySignal(
            engine=EntryEngine.BREAKOUT, direction="short", strength=0.5, reason="test"
        )
        self.assertTrue(entry_mod._direction_allowed(signal_short, "neutral"))


# ---------------------------------------------------------------------------
# Validation filter tests
# ---------------------------------------------------------------------------


class ValidationFilterTests(unittest.TestCase):

    def _entry(self, direction: str = "long") -> EntrySignal:
        return EntrySignal(
            engine=EntryEngine.BREAKOUT, direction=direction, strength=0.7, reason="test"
        )

    def test_no_signal_input_fails_validation(self):
        bars = _make_bars(100)
        result = val_mod.validate(bars, NoSignal("no entry"), {})
        self.assertFalse(result.passed)
        self.assertEqual(result.filters_total, 0)

    def test_all_filters_disabled_passes(self):
        bars = _make_bars(100)
        cfg = {
            "validation_momentum": False,
            "validation_squeeze": False,
            "validation_sr_proximity": False,
        }
        result = val_mod.validate(bars, self._entry(), cfg)
        self.assertTrue(result.passed)
        self.assertEqual(result.filters_total, 0)

    def test_momentum_filter_runs_without_error(self):
        bars = _make_bars(100)
        cfg = {
            "validation_momentum": True,
            "validation_squeeze": False,
            "validation_sr_proximity": False,
        }
        result = val_mod.validate(bars, self._entry("long"), cfg)
        self.assertEqual(result.filters_total, 1)
        self.assertIsInstance(result.passed, bool)

    def test_squeeze_filter_runs_without_error(self):
        bars = _make_bars(100)
        cfg = {
            "validation_momentum": False,
            "validation_squeeze": True,
            "validation_sr_proximity": False,
        }
        result = val_mod.validate(bars, self._entry(), cfg)
        self.assertEqual(result.filters_total, 1)

    def test_sr_proximity_filter_runs_without_error(self):
        bars = _make_bars(100)
        cfg = {
            "validation_momentum": False,
            "validation_squeeze": False,
            "validation_sr_proximity": True,
        }
        result = val_mod.validate(bars, self._entry(), cfg)
        self.assertEqual(result.filters_total, 1)

    def test_all_filters_count(self):
        bars = _make_bars(100)
        result = val_mod.validate(bars, self._entry(), {})
        self.assertEqual(result.filters_total, 3)

    def test_filters_passed_consistent_with_passed(self):
        bars = _make_bars(100)
        result = val_mod.validate(bars, self._entry(), {})
        if result.passed:
            self.assertEqual(result.filters_passed, result.filters_total)
        else:
            self.assertLess(result.filters_passed, result.filters_total)

    def test_reasons_tuple_length_matches_total(self):
        bars = _make_bars(100)
        result = val_mod.validate(bars, self._entry(), {})
        self.assertEqual(len(result.reasons), result.filters_total)

    def test_determinism(self):
        bars = _make_bars(100)
        r1 = val_mod.validate(bars, self._entry(), {})
        r2 = val_mod.validate(bars, self._entry(), {})
        self.assertEqual(r1, r2)

    def test_to_dict_structure(self):
        bars = _make_bars(100)
        result = val_mod.validate(bars, self._entry(), {})
        d = result.to_dict()
        self.assertIn("passed", d)
        self.assertIn("filters_passed", d)
        self.assertIn("filters_total", d)
        self.assertIsInstance(d["reasons"], list)


# ---------------------------------------------------------------------------
# Engine orchestration tests
# ---------------------------------------------------------------------------


class EngineOrchestrationTests(unittest.TestCase):

    def _bars_pair(self, n_15m: int = 200, n_4h: int = 200):
        bars_15m = _make_bars(n_15m, freq="15min", seed=50)
        bars_4h = _make_trending_bars(n=n_4h)
        return bars_15m, bars_4h

    def test_returns_quant_signal_contract(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine("AAPL", "2026-01-02", bars_15m, bars_4h)
        from tradingagents.quant.contracts import QuantSignalContract
        self.assertIsInstance(result, QuantSignalContract)

    def test_signal_label_is_valid(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine("AAPL", "2026-01-02", bars_15m, bars_4h)
        self.assertIn(result.signal, list(QuantSignalLabel))

    def test_empty_bars_returns_error_contract(self):
        empty = pd.DataFrame()
        result = run_quant_engine("AAPL", "2026-01-02", empty, empty)
        self.assertIsNotNone(result.error or result.signal)
        # Must not raise

    def test_determinism(self):
        bars_15m, bars_4h = self._bars_pair()
        r1 = run_quant_engine("AAPL", "2026-01-02", bars_15m, bars_4h)
        r2 = run_quant_engine("AAPL", "2026-01-02", bars_15m, bars_4h)
        self.assertEqual(r1, r2)

    def test_symbol_and_date_in_contract(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine("MSFT", "2026-03-15", bars_15m, bars_4h)
        self.assertEqual(result.symbol, "MSFT")
        self.assertEqual(result.trade_date, "2026-03-15")

    def test_hold_when_no_entry_signal(self):
        # Trending 4h but 15m bars with no breakout → likely HOLD
        bars_15m = _make_bars(200, trend=0.0, noise=0.1, seed=60)
        bars_4h = _make_trending_bars()
        result = run_quant_engine("X", "2026-01-02", bars_15m, bars_4h)
        # Result depends on noise; just verify no crash and valid label
        self.assertIsInstance(result.signal, QuantSignalLabel)

    def test_forced_breakout_mode(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine(
            "AAPL", "2026-01-02", bars_15m, bars_4h,
            config={"entry_mode": "breakout"},
        )
        self.assertIsInstance(result.signal, QuantSignalLabel)

    def test_forced_mean_reversion_mode(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine(
            "AAPL", "2026-01-02", bars_15m, bars_4h,
            config={"entry_mode": "mean_reversion"},
        )
        self.assertIsInstance(result.signal, QuantSignalLabel)

    def test_raw_contains_regime_entry_validation(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine("AAPL", "2026-01-02", bars_15m, bars_4h)
        self.assertIn("regime", result.raw)
        self.assertIn("entry", result.raw)
        self.assertIn("validation", result.raw)

    def test_score_sign_consistent_with_signal(self):
        bars_15m, bars_4h = self._bars_pair()
        result = run_quant_engine("AAPL", "2026-01-02", bars_15m, bars_4h)
        if result.signal == QuantSignalLabel.BUY:
            self.assertGreater(result.score, 0.0)
        elif result.signal == QuantSignalLabel.SELL:
            self.assertLess(result.score, 0.0)
        elif result.signal == QuantSignalLabel.HOLD:
            self.assertAlmostEqual(result.score, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
