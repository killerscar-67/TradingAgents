"""Local-compute intraday indicator math (no network)."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.dataflows.intraday_indicators import (
    fast_macd,
    fast_rsi,
    fast_stochastic,
    keltner_channels,
    opening_range,
    relative_volume,
    session_atr,
    session_vwap,
)


ET = ZoneInfo("America/New_York")


def _bars(session_date: str, n: int = 30, base: float = 100.0, vol: int = 1000) -> pd.DataFrame:
    """Build n consecutive 5m RTH bars on session_date."""
    start = datetime.fromisoformat(f"{session_date}T09:30:00").replace(tzinfo=ET)
    rows = []
    for i in range(n):
        ts = start + timedelta(minutes=5 * i)
        close = base + i * 0.10
        rows.append({
            "Date": ts,
            "Open": close - 0.05,
            "High": close + 0.10,
            "Low": close - 0.10,
            "Close": close,
            "Volume": vol + i,
        })
    return pd.DataFrame(rows)


class VWAPTests(unittest.TestCase):
    def test_vwap_matches_manual_formula(self):
        df = _bars("2025-04-24", n=10)
        v = session_vwap(df, "2025-04-24")
        self.assertIsNotNone(v)
        # Manual reproduction of the same math.
        local = df.copy()
        typical = (local["High"] + local["Low"] + local["Close"]) / 3
        expected = float((typical * local["Volume"]).sum() / local["Volume"].sum())
        self.assertAlmostEqual(v, expected, places=4)

    def test_vwap_returns_none_for_no_session_bars(self):
        df = _bars("2025-04-24", n=5)
        self.assertIsNone(session_vwap(df, "2025-04-25"))


class OpeningRangeTests(unittest.TestCase):
    def test_orb_first_15_minutes(self):
        df = _bars("2025-04-24", n=20)  # 5m bars × 20 = 100 minutes coverage
        rng = opening_range(df, "2025-04-24", minutes=15)
        self.assertIsNotNone(rng)
        high, low = rng
        # First 15 min = 3 bars (09:30, 09:35, 09:40). Confirm bounds.
        first3 = df.head(3)
        self.assertAlmostEqual(high, float(first3["High"].max()), places=4)
        self.assertAlmostEqual(low, float(first3["Low"].min()), places=4)


class RelVolumeTests(unittest.TestCase):
    def test_returns_none_when_no_prior_history(self):
        df = _bars("2025-04-24", n=10)
        self.assertIsNone(relative_volume(df, "2025-04-24"))

    def test_relvol_with_prior_sessions(self):
        # 7 prior weekday sessions + today, all identical → rel_volume ≈ 1.0
        # (relative_volume requires at least 5 prior sessions of bars).
        frames = []
        base = datetime(2025, 4, 7)  # Monday — gives 10 weekdays through 4/18
        days = 0
        i = 0
        while days < 8:
            d = base + timedelta(days=i)
            i += 1
            if d.weekday() >= 5:
                continue
            frames.append(_bars(d.strftime("%Y-%m-%d"), n=5))
            days += 1
        df = pd.concat(frames, ignore_index=True)
        today = frames[-1]["Date"].iloc[0].strftime("%Y-%m-%d")
        rv = relative_volume(df, today)
        self.assertIsNotNone(rv)
        self.assertAlmostEqual(rv, 1.0, places=2)


class FastOscillatorTests(unittest.TestCase):
    def test_rsi_with_increasing_closes_is_extreme(self):
        df = _bars("2025-04-24", n=30)
        rsi = fast_rsi(df, period=7)
        self.assertIsNotNone(rsi)
        # Monotonically increasing closes ⇒ RSI saturates near 100.
        self.assertGreater(rsi, 90)

    def test_macd_returns_three_values(self):
        df = _bars("2025-04-24", n=30)
        out = fast_macd(df)
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 3)

    def test_stochastic_returns_two_values(self):
        df = _bars("2025-04-24", n=30)
        out = fast_stochastic(df)
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 2)

    def test_keltner_returns_band_pair(self):
        df = _bars("2025-04-24", n=40)
        out = keltner_channels(df)
        self.assertIsNotNone(out)
        upper, lower = out
        self.assertGreater(upper, lower)


class SessionATRTests(unittest.TestCase):
    def test_atr_positive_for_synthetic_bars(self):
        df = _bars("2025-04-24", n=40)
        atr = session_atr(df, "2025-04-24")
        self.assertIsNotNone(atr)
        self.assertGreater(atr, 0)


if __name__ == "__main__":
    unittest.main()
