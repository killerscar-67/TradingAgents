"""Intraday data layer + tool routing (mocks yfinance to stay offline)."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingagents.dataflows import stockstats_utils
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.interface import (
    TOOLS_CATEGORIES,
    VENDOR_METHODS,
    get_category_for_method,
)
from tradingagents.dataflows.stockstats_utils import load_ohlcv_intraday


def _fake_intraday_df() -> pd.DataFrame:
    """Synthetic 5m bars with a Datetime index (yfinance shape for intraday)."""
    idx = pd.date_range("2025-04-24 09:30", periods=10, freq="5min")
    return pd.DataFrame({
        "Open": [100 + i * 0.1 for i in range(10)],
        "High": [100.2 + i * 0.1 for i in range(10)],
        "Low": [99.9 + i * 0.1 for i in range(10)],
        "Close": [100.1 + i * 0.1 for i in range(10)],
        "Volume": [1000 + i * 10 for i in range(10)],
    }, index=pd.DatetimeIndex(idx, name="Datetime"))


class LookbackCapsTests(unittest.TestCase):
    def test_rejects_unknown_interval(self):
        with self.assertRaises(ValueError):
            load_ohlcv_intraday("AAPL", "2025-04-24", interval="3m", lookback_days=5)

    def test_rejects_lookback_above_yfinance_cap(self):
        with self.assertRaises(ValueError):
            load_ohlcv_intraday("AAPL", "2025-04-24", interval="1m", lookback_days=30)


class CacheKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        set_config({"data_cache_dir": self.tmp})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("tradingagents.dataflows.stockstats_utils.yf.Ticker")
    def test_cache_key_includes_interval_and_prepost(self, mock_ticker):
        mock_obj = MagicMock()
        mock_obj.history.return_value = _fake_intraday_df()
        mock_ticker.return_value = mock_obj

        load_ohlcv_intraday("AAPL", "2025-04-24", interval="5m", lookback_days=5, prepost=False)
        load_ohlcv_intraday("AAPL", "2025-04-24", interval="5m", lookback_days=5, prepost=True)
        load_ohlcv_intraday("AAPL", "2025-04-24", interval="15m", lookback_days=5, prepost=False)

        files = os.listdir(self.tmp)
        # Three distinct cache files because (interval, prepost) differ.
        self.assertEqual(len(files), 3)
        # Sanity: filenames contain interval and prepost tags.
        self.assertTrue(any("5m-rth" in f for f in files))
        self.assertTrue(any("5m-ext" in f for f in files))
        self.assertTrue(any("15m-rth" in f for f in files))

    @patch("tradingagents.dataflows.stockstats_utils.yf.Ticker")
    def test_second_call_uses_cache(self, mock_ticker):
        mock_obj = MagicMock()
        mock_obj.history.return_value = _fake_intraday_df()
        mock_ticker.return_value = mock_obj

        load_ohlcv_intraday("AAPL", "2025-04-24", interval="5m", lookback_days=5)
        load_ohlcv_intraday("AAPL", "2025-04-24", interval="5m", lookback_days=5)
        # Only one network call.
        self.assertEqual(mock_obj.history.call_count, 1)


class VendorRegistrationTests(unittest.TestCase):
    def test_intraday_tools_registered_in_categories(self):
        self.assertIn("get_intraday_stock_data", TOOLS_CATEGORIES["core_stock_apis"]["tools"])
        self.assertIn("get_intraday_indicators", TOOLS_CATEGORIES["technical_indicators"]["tools"])

    def test_intraday_methods_routable(self):
        self.assertEqual(get_category_for_method("get_intraday_stock_data"), "core_stock_apis")
        self.assertEqual(get_category_for_method("get_intraday_indicators"), "technical_indicators")
        self.assertIn("yfinance", VENDOR_METHODS["get_intraday_stock_data"])
        self.assertIn("yfinance", VENDOR_METHODS["get_intraday_indicators"])


class IntradayToolDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.original_config = get_config()

    def tearDown(self):
        set_config(self.original_config)

    @patch("tradingagents.agents.utils.intraday_tools.route_to_vendor")
    def test_stock_data_tool_defaults_to_extended_hours(self, mock_route):
        from tradingagents.agents.utils.intraday_tools import get_intraday_stock_data

        get_intraday_stock_data.func("AAPL", "2026-04-23")

        mock_route.assert_called_once_with(
            "get_intraday_stock_data",
            "AAPL",
            "2026-04-23",
            "5m",
            5,
            True,
        )

    @patch("tradingagents.agents.utils.intraday_tools.route_to_vendor")
    def test_stock_data_tool_respects_extended_hours_config(self, mock_route):
        from tradingagents.agents.utils.intraday_tools import get_intraday_stock_data

        set_config({"include_extended_hours": False})
        get_intraday_stock_data.func("AAPL", "2026-04-23")

        mock_route.assert_called_once_with(
            "get_intraday_stock_data",
            "AAPL",
            "2026-04-23",
            "5m",
            5,
            False,
        )

    @patch("tradingagents.agents.utils.intraday_tools.route_to_vendor")
    def test_indicator_tool_defaults_to_extended_hours(self, mock_route):
        from tradingagents.agents.utils.intraday_tools import get_intraday_indicators

        mock_route.return_value = "indicator"
        get_intraday_indicators.func("AAPL", "vwap", "2026-04-23")

        mock_route.assert_called_once_with(
            "get_intraday_indicators",
            "AAPL",
            "vwap",
            "2026-04-23",
            "5m",
            30,
            True,
        )


if __name__ == "__main__":
    unittest.main()
