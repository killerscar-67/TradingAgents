import shutil
import tempfile
import unittest
from unittest.mock import patch

from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.interface import VENDOR_METHODS, route_to_vendor


class InterfaceCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.original_config = get_config()
        set_config({
            "data_cache_dir": self.tmp,
            "data_cache_enabled": True,
            "data_cache_refresh": False,
            "data_vendors": {"news_data": "stub"},
            "tool_vendors": {},
        })

    def tearDown(self):
        set_config(self.original_config)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repeated_vendor_call_uses_cache(self):
        calls = []

        def fake_news(ticker, start_date, end_date):
            calls.append((ticker, start_date, end_date))
            return f"news:{ticker}:{start_date}:{end_date}"

        with patch.dict(VENDOR_METHODS["get_news"], {"stub": fake_news}):
            first = route_to_vendor("get_news", "AAPL", "2026-04-20", "2026-04-27")
            second = route_to_vendor("get_news", "AAPL", "2026-04-20", "2026-04-27")

        self.assertEqual(first, "news:AAPL:2026-04-20:2026-04-27")
        self.assertEqual(second, first)
        self.assertEqual(calls, [("AAPL", "2026-04-20", "2026-04-27")])

    def test_cache_key_includes_vendor(self):
        calls = []

        def fake_yfinance(ticker, start_date, end_date):
            calls.append(("yfinance", ticker, start_date, end_date))
            return "yf-news"

        def fake_alpha(ticker, start_date, end_date):
            calls.append(("alpha_vantage", ticker, start_date, end_date))
            return "av-news"

        with patch.dict(
            VENDOR_METHODS["get_news"],
            {"yfinance": fake_yfinance, "alpha_vantage": fake_alpha},
            clear=True,
        ):
            set_config({"data_vendors": {"news_data": "yfinance"}, "tool_vendors": {}})
            self.assertEqual(
                route_to_vendor("get_news", "AAPL", "2026-04-20", "2026-04-27"),
                "yf-news",
            )

            set_config({"data_vendors": {"news_data": "alpha_vantage"}, "tool_vendors": {}})
            self.assertEqual(
                route_to_vendor("get_news", "AAPL", "2026-04-20", "2026-04-27"),
                "av-news",
            )

        self.assertEqual(
            calls,
            [
                ("yfinance", "AAPL", "2026-04-20", "2026-04-27"),
                ("alpha_vantage", "AAPL", "2026-04-20", "2026-04-27"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
