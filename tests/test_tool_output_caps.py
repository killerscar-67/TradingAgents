import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.y_finance import (
    get_YFin_data_online,
    get_balance_sheet,
    get_fundamentals,
    get_stock_stats_indicators_window,
)
from tradingagents.dataflows.yfinance_news import get_global_news_yfinance, get_news_yfinance


class ToolOutputCapsTests(unittest.TestCase):
    def setUp(self):
        self._config_patch = patch(
            "tradingagents.dataflows.config.default_config.DEFAULT_CONFIG",
            {
                "tool_output_ohlcv_max_rows": 3,
                "tool_output_indicator_max_points": 2,
                "tool_output_fundamentals_max_fields": 2,
                "tool_output_financial_max_rows": 2,
                "tool_output_financial_max_cols": 2,
                "tool_output_news_max_articles": 2,
                "tool_output_news_summary_max_chars": 12,
            },
        )
        self._config_patch.start()
        set_config({
            "tool_output_ohlcv_max_rows": 3,
            "tool_output_indicator_max_points": 2,
            "tool_output_fundamentals_max_fields": 2,
            "tool_output_financial_max_rows": 2,
            "tool_output_financial_max_cols": 2,
            "tool_output_news_max_articles": 2,
            "tool_output_news_summary_max_chars": 12,
        })

    def tearDown(self):
        self._config_patch.stop()

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_ohlcv_output_is_capped(self, mock_ticker_cls, mock_retry):
        idx = pd.date_range("2026-01-01", periods=5, freq="D")
        frame = pd.DataFrame(
            {
                "Open": [1, 2, 3, 4, 5],
                "High": [1, 2, 3, 4, 5],
                "Low": [1, 2, 3, 4, 5],
                "Close": [1, 2, 3, 4, 5],
                "Adj Close": [1, 2, 3, 4, 5],
            },
            index=idx,
        )
        mock_retry.return_value = frame
        mock_ticker_cls.return_value = MagicMock(history=MagicMock(return_value=frame))

        result = get_YFin_data_online("AAPL", "2026-01-01", "2026-01-05")

        self.assertIn("Output capped to 3 rows", result)
        self.assertEqual(sum(1 for line in result.splitlines() if line.startswith("2026-")), 3)
        self.assertIn("\n2026-01-03,3,3,3,3,3", result)
        self.assertIn("\n2026-01-05,5,5,5,5,5", result)
        self.assertNotIn("\n2026-01-01,1,1,1,1,1", result)

    @patch("tradingagents.dataflows.y_finance._get_stock_stats_bulk")
    def test_indicator_output_is_capped(self, mock_bulk):
        mock_bulk.return_value = {
            "2026-01-05": "5",
            "2026-01-04": "4",
            "2026-01-03": "3",
            "2026-01-02": "2",
            "2026-01-01": "1",
        }

        result = get_stock_stats_indicators_window("AAPL", "rsi", "2026-01-05", 4)

        self.assertIn("Output capped to the most recent 2 points", result)
        self.assertIn("2026-01-05: 5", result)
        self.assertIn("2026-01-04: 4", result)
        self.assertNotIn("2026-01-03: 3", result)

    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_fundamentals_output_is_capped(self, mock_ticker_cls, mock_retry):
        info = {"longName": "Apple", "sector": "Tech", "industry": "Hardware", "marketCap": 10}
        mock_retry.return_value = info
        mock_ticker_cls.return_value = MagicMock(info=info)

        result = get_fundamentals("AAPL")

        self.assertIn("Output capped to 2 fields", result)
        self.assertIn("Name: Apple", result)
        self.assertIn("Sector: Tech", result)
        self.assertNotIn("Industry: Hardware", result)

    @patch("tradingagents.dataflows.y_finance.filter_financials_by_date")
    @patch("tradingagents.dataflows.y_finance.yf_retry")
    @patch("tradingagents.dataflows.y_finance.yf.Ticker")
    def test_financial_statement_output_is_capped(self, mock_ticker_cls, mock_retry, mock_filter):
        frame = pd.DataFrame(
            {
                "2025-12-31": [1, 2, 3],
                "2025-09-30": [4, 5, 6],
                "2025-06-30": [7, 8, 9],
            },
            index=["A", "B", "C"],
        )
        ticker = MagicMock(quarterly_balance_sheet=frame)
        mock_ticker_cls.return_value = ticker
        mock_retry.return_value = frame
        mock_filter.return_value = frame

        result = get_balance_sheet("AAPL")

        self.assertIn("Output capped to 2 rows", result)
        self.assertIn("Output capped to 2 columns", result)
        self.assertIn("A,1,4", result)
        self.assertIn("B,2,5", result)
        self.assertNotIn("C,3,6", result)
        self.assertNotIn("2025-06-30", result)

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker")
    def test_news_output_is_capped(self, mock_ticker_cls, mock_retry):
        articles = [
            {
                "content": {
                    "title": f"Title {i}",
                    "summary": "This summary is far too long",
                    "provider": {"displayName": "Provider"},
                    "canonicalUrl": {"url": f"https://example.com/{i}"},
                    "pubDate": "2026-01-01T12:00:00Z",
                }
            }
            for i in range(3)
        ]
        mock_retry.return_value = articles
        mock_ticker_cls.return_value = MagicMock(get_news=MagicMock(return_value=articles))

        result = get_news_yfinance("AAPL", "2026-01-01", "2026-01-02")

        self.assertIn("Output capped to 2 articles", result)
        self.assertIn("This summar…", result)
        self.assertNotIn("Title 2", result)

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker")
    def test_news_cap_note_shown_at_boundary(self, mock_ticker_cls, mock_retry):
        """Cap note must appear when the source returns exactly max_articles items."""
        articles = [
            {
                "content": {
                    "title": f"Title {i}",
                    "summary": "summary",
                    "provider": {"displayName": "Provider"},
                    "canonicalUrl": {"url": f"https://example.com/{i}"},
                    "pubDate": "2026-01-01T12:00:00Z",
                }
            }
            for i in range(2)  # exactly max_articles=2
        ]
        mock_retry.return_value = articles
        mock_ticker_cls.return_value = MagicMock(get_news=MagicMock(return_value=articles))

        result = get_news_yfinance("AAPL", "2026-01-01", "2026-01-02")

        self.assertIn("Output capped to 2 articles", result)

    @patch("tradingagents.dataflows.yfinance_news.yf.Search")
    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_global_news_cap_note_shown_at_boundary(self, mock_retry, mock_search):
        articles = [
            {
                "content": {
                    "title": f"Macro {i}",
                    "summary": "summary",
                    "provider": {"displayName": "Provider"},
                    "canonicalUrl": {"url": f"https://example.com/global/{i}"},
                    "pubDate": "2026-01-01T12:00:00Z",
                }
            }
            for i in range(2)
        ]
        mock_retry.side_effect = lambda func: func()
        mock_search.return_value = MagicMock(news=articles)

        result = get_global_news_yfinance("2026-01-02", limit=2)

        self.assertIn("Output capped to 2 articles", result)
        self.assertIn("Macro 0", result)


if __name__ == "__main__":
    unittest.main()