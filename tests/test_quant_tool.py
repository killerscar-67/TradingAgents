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