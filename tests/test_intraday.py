"""Tests for Phase 1: Intraday data foundation.

Acceptance criteria (from plan):
- 15m and 4h bars fetch correctly for NYSE/crypto sessions.
- Cache returns identical DataFrame on repeat call with same key.
- No data beyond current bar is accessible (no-lookahead guarantee).
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingagents.dataflows.intraday import (
    _cache_key,
    _enforce_no_lookahead,
    _align_session,
    _resample_1h_to_4h,
    fetch_intraday_bars,
    get_intraday_bars,
)


def _make_utc_index(*naive_strings: str) -> pd.DatetimeIndex:
    """Build a UTC-aware DatetimeIndex from naive ISO strings."""
    return pd.DatetimeIndex(
        pd.to_datetime(naive_strings, utc=True)
    )


def _sample_df(timestamps) -> pd.DataFrame:
    idx = _make_utc_index(*timestamps)
    return pd.DataFrame(
        {
            "Open": [100.0] * len(idx),
            "High": [101.0] * len(idx),
            "Low": [99.0] * len(idx),
            "Close": [100.5] * len(idx),
            "Volume": [1000] * len(idx),
        },
        index=idx,
    )


class IntradayCacheKeyTests(unittest.TestCase):
    def test_same_inputs_produce_same_key(self):
        k1 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular")
        k2 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular")
        self.assertEqual(k1, k2)

    def test_different_symbol_produces_different_key(self):
        k1 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular")
        k2 = _cache_key("TSLA", "15m", "2026-04-01", "2026-04-10", "regular")
        self.assertNotEqual(k1, k2)

    def test_different_interval_produces_different_key(self):
        k1 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular")
        k2 = _cache_key("AAPL", "4h", "2026-04-01", "2026-04-10", "regular")
        self.assertNotEqual(k1, k2)

    def test_different_session_produces_different_key(self):
        k1 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular")
        k2 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "crypto")
        self.assertNotEqual(k1, k2)

    def test_symbol_is_case_insensitive_in_key(self):
        k1 = _cache_key("aapl", "15m", "2026-04-01", "2026-04-10", "regular")
        k2 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular")
        self.assertEqual(k1, k2)

    def test_different_vendor_produces_different_key(self):
        k1 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular", vendor="yfinance")
        k2 = _cache_key("AAPL", "15m", "2026-04-01", "2026-04-10", "regular", vendor="alpha_vantage")
        self.assertNotEqual(k1, k2)


class NoLookaheadTests(unittest.TestCase):
    def test_bars_at_or_after_as_of_are_stripped(self):
        df = _sample_df([
            "2026-04-01 09:30",
            "2026-04-01 09:45",
            "2026-04-01 10:00",
            "2026-04-01 10:15",
        ])
        as_of = datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc)
        result = _enforce_no_lookahead(df, as_of)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(result.index < pd.Timestamp(as_of)))

    def test_none_as_of_returns_full_dataframe(self):
        df = _sample_df(["2026-04-01 09:30", "2026-04-01 09:45"])
        result = _enforce_no_lookahead(df, None)
        self.assertEqual(len(result), len(df))

    def test_empty_dataframe_is_safe(self):
        df = pd.DataFrame()
        result = _enforce_no_lookahead(df, datetime(2026, 4, 1, tzinfo=timezone.utc))
        self.assertTrue(result.empty)


class SessionAlignmentTests(unittest.TestCase):
    def test_regular_session_filters_outside_hours(self):
        # Mix of pre-market, regular, and after-hours bars (ET times)
        # 08:00 ET = pre-market, 10:00 ET = regular, 17:00 ET = after-hours
        df = _sample_df([
            "2026-04-01 12:00",   # 08:00 ET — pre-market
            "2026-04-01 13:30",   # 09:30 ET — regular open
            "2026-04-01 14:00",   # 10:00 ET — regular
            "2026-04-01 21:00",   # 17:00 ET — after-hours
        ])
        result = _align_session(df, "regular")
        # Only 09:30 ET and 10:00 ET bars should survive
        self.assertEqual(len(result), 2)

    def test_crypto_session_returns_all_bars(self):
        df = _sample_df([
            "2026-04-05 00:00",  # Sunday midnight UTC
            "2026-04-05 06:00",
            "2026-04-05 12:00",
        ])
        result = _align_session(df, "crypto")
        self.assertEqual(len(result), 3)

    def test_empty_dataframe_is_safe(self):
        df = pd.DataFrame()
        result = _align_session(df, "regular")
        self.assertTrue(result.empty)

    def test_regular_session_around_dst_springforward(self):
        # 2026-03-09 is the first Monday after spring-forward to EDT.
        # 09:30 ET maps to 13:30 UTC.
        df = _sample_df([
            "2026-03-09 12:30",  # 08:30 ET — pre-market
            "2026-03-09 13:30",  # 09:30 ET — regular open
            "2026-03-09 15:00",  # 11:00 ET — regular
            "2026-03-09 20:00",  # 16:00 ET — close boundary (excluded)
        ])
        result = _align_session(df, "regular")
        self.assertEqual(len(result), 2)
        self.assertIn(pd.Timestamp("2026-03-09 13:30:00+00:00"), result.index)
        self.assertIn(pd.Timestamp("2026-03-09 15:00:00+00:00"), result.index)

    def test_regular_session_around_dst_fallback(self):
        # 2026-11-02 is the first Monday after fall-back to EST.
        # 09:30 ET maps to 14:30 UTC.
        df = _sample_df([
            "2026-11-02 13:30",  # 08:30 ET — pre-market
            "2026-11-02 14:30",  # 09:30 ET — regular open
            "2026-11-02 16:00",  # 11:00 ET — regular
            "2026-11-02 21:00",  # 16:00 ET — close boundary (excluded)
        ])
        result = _align_session(df, "regular")
        self.assertEqual(len(result), 2)
        self.assertIn(pd.Timestamp("2026-11-02 14:30:00+00:00"), result.index)
        self.assertIn(pd.Timestamp("2026-11-02 16:00:00+00:00"), result.index)

    def test_extended_session_enforces_boundaries_and_weekdays(self):
        # 04:00 ET open is inclusive, 20:00 ET close is exclusive.
        # Saturday bars must be excluded.
        df = _sample_df([
            "2026-04-06 07:59",  # Mon 03:59 ET — too early
            "2026-04-06 08:00",  # Mon 04:00 ET — include
            "2026-04-06 12:00",  # Mon 08:00 ET — include
            "2026-04-07 00:00",  # Mon 20:00 ET — exclude
            "2026-04-11 13:00",  # Sat 09:00 ET — exclude
        ])
        result = _align_session(df, "extended")
        self.assertEqual(len(result), 2)
        self.assertIn(pd.Timestamp("2026-04-06 08:00:00+00:00"), result.index)
        self.assertIn(pd.Timestamp("2026-04-06 12:00:00+00:00"), result.index)


class ResamplingTests(unittest.TestCase):
    def test_resample_1h_to_4h_drops_single_bar_partial_windows(self):
        # EST example (UTC-5): 10:00-15:00 ET -> 15:00-20:00 UTC.
        # UTC-aligned 4h buckets contain counts 1, 4, 1. Single-bar
        # boundary candles should be dropped.
        df = _sample_df([
            "2026-01-15 15:00",
            "2026-01-15 16:00",
            "2026-01-15 17:00",
            "2026-01-15 18:00",
            "2026-01-15 19:00",
            "2026-01-15 20:00",
        ])
        resampled = _resample_1h_to_4h(df)
        self.assertEqual(len(resampled), 1)
        self.assertIn(pd.Timestamp("2026-01-15 16:00:00+00:00"), resampled.index)
        self.assertEqual(resampled.iloc[0]["Volume"], 4000)

    @patch("yfinance.Ticker")
    def test_fetch_4h_respects_as_of_before_resampling(self, mock_ticker_cls):
        idx = _make_utc_index(
            "2026-04-01 12:00",
            "2026-04-01 13:00",
            "2026-04-01 14:00",
            "2026-04-01 15:00",
        )
        source = pd.DataFrame(
            {
                "Open": [1.0, 2.0, 3.0, 4.0],
                "High": [1.5, 2.5, 3.5, 4.5],
                "Low": [0.5, 1.5, 2.5, 3.5],
                "Close": [1.1, 2.1, 3.1, 4.1],
                "Volume": [100, 100, 100, 100],
            },
            index=idx,
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = source
        mock_ticker_cls.return_value = mock_ticker

        as_of = datetime(2026, 4, 1, 14, 30, tzinfo=timezone.utc)
        result = fetch_intraday_bars(
            "AAPL",
            "4h",
            "2026-04-01",
            "2026-04-02",
            as_of=as_of,
            session="crypto",
            vendor="yfinance",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["Volume"], 300)
        self.assertEqual(result.iloc[0]["Close"], 3.1)


class IntradayValidationTests(unittest.TestCase):
    def test_invalid_interval_raises_value_error(self):
        with self.assertRaises(ValueError):
            fetch_intraday_bars("AAPL", "30m", "2026-04-01", "2026-04-10")  # type: ignore[arg-type]

    def test_invalid_session_raises_value_error(self):
        with self.assertRaises(ValueError):
            fetch_intraday_bars("AAPL", "15m", "2026-04-01", "2026-04-10", session="overnight")  # type: ignore[arg-type]

    def test_unsupported_vendor_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            fetch_intraday_bars("AAPL", "15m", "2026-04-01", "2026-04-10", vendor="alpha_vantage")


class IntradayCacheDeterminismTests(unittest.TestCase):
    """Cache returns identical DataFrame for identical inputs."""

    def _make_mock_fetch(self):
        """Return a mock that returns a fixed sample DataFrame on first call, then fails."""
        sample = _sample_df([
            "2026-04-01 13:30",
            "2026-04-01 13:45",
            "2026-04-01 14:00",
        ])
        call_count = [0]

        def _fetch(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return sample
            raise AssertionError("fetch_intraday_bars called more than once — cache miss on repeat call")

        return _fetch, call_count

    def test_repeat_call_with_same_key_uses_cache(self):
        mock_fetch, call_count = self._make_mock_fetch()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dataflows.intraday.fetch_intraday_bars", side_effect=mock_fetch):
                df1 = get_intraday_bars(
                    "AAPL", "15m", "2026-04-01", "2026-04-02",
                    cache_dir=tmpdir
                )
                df2 = get_intraday_bars(
                    "AAPL", "15m", "2026-04-01", "2026-04-02",
                    cache_dir=tmpdir
                )
        self.assertEqual(call_count[0], 1)
        pd.testing.assert_frame_equal(df1, df2)

    def test_refresh_cache_refetches(self):
        sample = _sample_df(["2026-04-01 13:30"])
        fetch_count = [0]

        def _fetch(**kwargs):
            fetch_count[0] += 1
            return sample

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dataflows.intraday.fetch_intraday_bars", side_effect=_fetch):
                get_intraday_bars("AAPL", "15m", "2026-04-01", "2026-04-02", cache_dir=tmpdir)
                get_intraday_bars("AAPL", "15m", "2026-04-01", "2026-04-02", cache_dir=tmpdir, refresh_cache=True)
        self.assertEqual(fetch_count[0], 2)

    def test_cache_result_is_utc_aware(self):
        sample = _sample_df(["2026-04-01 13:30", "2026-04-01 13:45"])
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dataflows.intraday.fetch_intraday_bars", return_value=sample):
                df = get_intraday_bars("AAPL", "15m", "2026-04-01", "2026-04-02", cache_dir=tmpdir)
        self.assertIsNotNone(df.index.tz)
        self.assertEqual(str(df.index.tz), "UTC")

    def test_as_of_cutoff_applies_after_cache_load(self):
        """as_of is applied post-cache-load so the stored payload remains intact."""
        sample = _sample_df([
            "2026-04-01 13:30",
            "2026-04-01 13:45",
            "2026-04-01 14:00",
        ])
        as_of = datetime(2026, 4, 1, 13, 45, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dataflows.intraday.fetch_intraday_bars", return_value=sample):
                df = get_intraday_bars(
                    "AAPL", "15m", "2026-04-01", "2026-04-02",
                    as_of=as_of,
                    cache_dir=tmpdir,
                )
        self.assertEqual(len(df), 1)
        self.assertTrue(all(df.index < pd.Timestamp(as_of)))

    def test_live_end_date_fetch_is_not_persisted_to_cache(self):
        live_sample = _sample_df(["2026-04-01 13:30"])
        historical_sample = _sample_df(["2026-04-01 13:30", "2026-04-01 13:45"])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "tradingagents.dataflows.intraday._is_live_end_date",
                side_effect=[True, False],
            ) as mock_is_live:
                with patch(
                    "tradingagents.dataflows.intraday.fetch_intraday_bars",
                    side_effect=[live_sample, historical_sample],
                ) as mock_fetch:
                    first = get_intraday_bars(
                        "AAPL", "15m", "2026-04-01", "2026-04-22", cache_dir=tmpdir
                    )
                    second = get_intraday_bars(
                        "AAPL", "15m", "2026-04-01", "2026-04-22", cache_dir=tmpdir
                    )

        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(mock_is_live.call_count, 2)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2)

    def test_cached_yfinance_data_is_not_reused_for_other_vendor(self):
        sample = _sample_df(["2026-04-01 13:30"])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tradingagents.dataflows.intraday.fetch_intraday_bars", return_value=sample):
                get_intraday_bars(
                    "AAPL", "15m", "2026-04-01", "2026-04-02", cache_dir=tmpdir, vendor="yfinance"
                )

            with self.assertRaises(NotImplementedError):
                get_intraday_bars(
                    "AAPL", "15m", "2026-04-01", "2026-04-02", cache_dir=tmpdir, vendor="alpha_vantage"
                )


if __name__ == "__main__":
    unittest.main()
