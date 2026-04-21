import json
import unittest
from unittest.mock import patch

import pandas as pd

from tradingagents.agents.utils.quant_tools import get_quant_signals


class QuantToolTests(unittest.TestCase):
    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    def test_get_quant_signals_returns_structured_json(self, mock_download):
        index = pd.date_range("2026-01-01", periods=90, freq="D")
        prices = pd.Series(range(100, 190), index=index, dtype=float)
        mock_download.return_value = pd.DataFrame({"Close": prices})

        payload = json.loads(
            get_quant_signals.func("AAPL", "2026-03-30")
        )

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["signal"], "buy")
        self.assertIn("summary", payload)
        self.assertIn("metadata", payload)

    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    def test_get_quant_signals_handles_empty_history(self, mock_download):
        mock_download.return_value = pd.DataFrame()

        payload = json.loads(
            get_quant_signals.func("AAPL", "2026-03-30")
        )

        self.assertIn("error", payload)
        self.assertEqual(payload["error"], "No price history returned")

    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    def test_get_quant_signals_uses_exclusive_end_date(self, mock_download):
        mock_download.return_value = pd.DataFrame()

        get_quant_signals.func("AAPL", "2026-03-30")

        self.assertTrue(mock_download.called)
        kwargs = mock_download.call_args.kwargs
        self.assertEqual(kwargs.get("end"), "2026-03-30")

    @patch("tradingagents.agents.utils.quant_tools.vbt", None)
    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    def test_get_quant_signals_works_without_vectorbt(self, mock_download):
        index = pd.date_range("2026-01-01", periods=90, freq="D")
        prices = pd.Series(range(100, 190), index=index, dtype=float)
        mock_download.return_value = pd.DataFrame({"Close": prices})

        payload = json.loads(get_quant_signals.func("AAPL", "2026-03-30"))

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertIn(payload["signal"], {"buy", "hold", "sell"})
        self.assertIn("score", payload)

    @patch("tradingagents.agents.utils.quant_tools.vbt", None)
    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    def test_get_quant_signals_without_vectorbt_preserves_rsi_extremes(self, mock_download):
        index = pd.date_range("2026-01-01", periods=90, freq="D")
        prices = pd.Series(range(100, 190), index=index, dtype=float)
        mock_download.return_value = pd.DataFrame({"Close": prices})

        payload = json.loads(get_quant_signals.func("AAPL", "2026-03-30"))

        self.assertGreater(payload["metadata"]["rsi"], 90.0)