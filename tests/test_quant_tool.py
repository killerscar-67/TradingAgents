import json
import unittest
from unittest.mock import patch

import pandas as pd

from tradingagents.agents.utils.quant_tools import get_quant_signals
from tradingagents.quant.contracts import QuantSignalContract


class QuantToolTests(unittest.TestCase):
    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    @patch("tradingagents.agents.utils.quant_tools.run_quant_engine")
    @patch("tradingagents.agents.utils.quant_tools.get_intraday_bars")
    def test_get_quant_signals_uses_intraday_quant_engine_when_available(
        self,
        mock_intraday,
        mock_run_engine,
        mock_download,
    ):
        index_15m = pd.date_range("2026-03-30 13:30", periods=80, freq="15min", tz="UTC")
        index_4h = pd.date_range("2026-03-01", periods=40, freq="4h", tz="UTC")
        bars_15m = pd.DataFrame(
            {
                "Open": [100.0] * len(index_15m),
                "High": [101.0] * len(index_15m),
                "Low": [99.0] * len(index_15m),
                "Close": [100.5] * len(index_15m),
                "Volume": [200_000] * len(index_15m),
            },
            index=index_15m,
        )
        bars_4h = pd.DataFrame(
            {
                "Open": [100.0] * len(index_4h),
                "High": [101.0] * len(index_4h),
                "Low": [99.0] * len(index_4h),
                "Close": [100.5] * len(index_4h),
                "Volume": [200_000] * len(index_4h),
            },
            index=index_4h,
        )
        mock_intraday.side_effect = [bars_15m, bars_4h]
        mock_run_engine.return_value = QuantSignalContract.from_raw(
            "AAPL",
            "2026-03-30",
            {"signal": "buy", "score": 0.8, "confidence": 1.0, "summary": "engine"},
        )

        payload = json.loads(get_quant_signals.func("AAPL", "2026-03-30"))

        self.assertEqual(payload["signal"], "buy")
        self.assertEqual(payload["summary"], "engine")
        contract = QuantSignalContract.from_raw("AAPL", "2026-03-30", payload)
        self.assertEqual(contract.signal.value, "buy")
        self.assertEqual(contract.score, 0.8)
        self.assertEqual(contract.confidence, 1.0)
        self.assertEqual(mock_intraday.call_count, 2)
        self.assertEqual(mock_intraday.call_args_list[0].kwargs["session"], "extended")
        self.assertEqual(mock_intraday.call_args_list[1].kwargs["session"], "extended")
        mock_run_engine.assert_called_once()
        mock_download.assert_not_called()

    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    @patch("tradingagents.agents.utils.quant_tools.get_intraday_bars", side_effect=RuntimeError("fallback"))
    def test_get_quant_signals_returns_structured_json(self, _mock_intraday, mock_download):
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
    @patch("tradingagents.agents.utils.quant_tools.get_intraday_bars", side_effect=RuntimeError("fallback"))
    def test_get_quant_signals_handles_empty_history(self, _mock_intraday, mock_download):
        mock_download.return_value = pd.DataFrame()

        payload = json.loads(
            get_quant_signals.func("AAPL", "2026-03-30")
        )

        self.assertIn("error", payload)
        self.assertEqual(payload["error"], "No price history returned")

    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    @patch("tradingagents.agents.utils.quant_tools.get_intraday_bars", side_effect=RuntimeError("fallback"))
    def test_get_quant_signals_uses_exclusive_end_date(self, _mock_intraday, mock_download):
        mock_download.return_value = pd.DataFrame()

        get_quant_signals.func("AAPL", "2026-03-30")

        self.assertTrue(mock_download.called)
        kwargs = mock_download.call_args.kwargs
        self.assertEqual(kwargs.get("end"), "2026-03-30")

    @patch("tradingagents.agents.utils.quant_tools.vbt", None)
    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    @patch("tradingagents.agents.utils.quant_tools.get_intraday_bars", side_effect=RuntimeError("fallback"))
    def test_get_quant_signals_works_without_vectorbt(self, _mock_intraday, mock_download):
        index = pd.date_range("2026-01-01", periods=90, freq="D")
        prices = pd.Series(range(100, 190), index=index, dtype=float)
        mock_download.return_value = pd.DataFrame({"Close": prices})

        payload = json.loads(get_quant_signals.func("AAPL", "2026-03-30"))

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertIn(payload["signal"], {"buy", "hold", "sell"})
        self.assertIn("score", payload)

    @patch("tradingagents.agents.utils.quant_tools.vbt", None)
    @patch("tradingagents.agents.utils.quant_tools.yf.download")
    @patch("tradingagents.agents.utils.quant_tools.get_intraday_bars", side_effect=RuntimeError("fallback"))
    def test_get_quant_signals_without_vectorbt_preserves_rsi_extremes(self, _mock_intraday, mock_download):
        index = pd.date_range("2026-01-01", periods=90, freq="D")
        prices = pd.Series(range(100, 190), index=index, dtype=float)
        mock_download.return_value = pd.DataFrame({"Close": prices})

        payload = json.loads(get_quant_signals.func("AAPL", "2026-03-30"))

        self.assertGreater(payload["metadata"]["rsi"], 90.0)
