import unittest
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tradingagents.graph.prefilter import score_tickers_with_quant


class QuantPrefilterTests(unittest.TestCase):
    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    def test_prefilter_selects_top_n_by_score(self, mock_quant):
        payloads = {
            "AAPL": '{"signal":"buy","score":0.8,"confidence":0.7}',
            "MSFT": '{"signal":"hold","score":0.2,"confidence":0.5}',
            "TSLA": '{"signal":"sell","score":-0.6,"confidence":0.8}',
        }
        mock_quant.side_effect = lambda symbol, trade_date, **kwargs: payloads[symbol]

        result = score_tickers_with_quant(["AAPL", "MSFT", "TSLA"], "2026-04-21", top_n=2)

        self.assertEqual([x["symbol"] for x in result["selected"]], ["AAPL", "MSFT"])
        self.assertEqual(result["ranked"][0]["symbol"], "AAPL")

    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    def test_prefilter_pushes_errors_to_bottom(self, mock_quant):
        payloads = {
            "AAPL": '{"signal":"buy","score":0.8,"confidence":0.7}',
            "BAD": '{"error":"No data"}',
        }
        mock_quant.side_effect = lambda symbol, trade_date, **kwargs: payloads[symbol]

        result = score_tickers_with_quant(["BAD", "AAPL"], "2026-04-21", top_n=2)

        self.assertEqual(result["ranked"][0]["symbol"], "AAPL")
        self.assertEqual(result["ranked"][1]["symbol"], "BAD")
        self.assertEqual([x["symbol"] for x in result["selected"]], ["AAPL"])

    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    def test_prefilter_uses_disk_cache_on_repeated_run(self, mock_quant):
        payloads = {
            "AAPL": '{"signal":"buy","score":0.8,"confidence":0.7}',
            "MSFT": '{"signal":"hold","score":0.2,"confidence":0.5}',
        }
        mock_quant.side_effect = lambda symbol, trade_date, **kwargs: payloads[symbol]

        with TemporaryDirectory() as cache_dir:
            first = score_tickers_with_quant(
                ["AAPL", "MSFT"],
                "2026-04-01",
                top_n=2,
                cache_dir=cache_dir,
            )
            second = score_tickers_with_quant(
                ["AAPL", "MSFT"],
                "2026-04-01",
                top_n=2,
                cache_dir=cache_dir,
            )

        self.assertEqual(mock_quant.call_count, 2)
        self.assertEqual(sum(1 for item in first["ranked"] if item["cache_hit"]), 0)
        self.assertEqual(sum(1 for item in second["ranked"] if item["cache_hit"]), 2)

    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    def test_prefilter_expires_cache_by_ttl(self, mock_quant):
        payloads = {
            "AAPL": '{"signal":"buy","score":0.8,"confidence":0.7}',
        }
        mock_quant.side_effect = lambda symbol, trade_date, **kwargs: payloads[symbol]

        with TemporaryDirectory() as cache_dir:
            score_tickers_with_quant(
                ["AAPL"],
                "2026-04-01",
                top_n=1,
                cache_dir=cache_dir,
                cache_ttl_days=1,
            )

            cache_files = list(Path(cache_dir).glob("*.json"))
            self.assertEqual(len(cache_files), 1)
            payload = json.loads(cache_files[0].read_text(encoding="utf-8"))
            payload["saved_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            cache_files[0].write_text(json.dumps(payload), encoding="utf-8")

            second = score_tickers_with_quant(
                ["AAPL"],
                "2026-04-01",
                top_n=1,
                cache_dir=cache_dir,
                cache_ttl_days=1,
            )

        self.assertEqual(mock_quant.call_count, 2)
        self.assertFalse(second["ranked"][0]["cache_hit"])

    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    def test_prefilter_refresh_flag_bypasses_cache(self, mock_quant):
        payloads = {
            "AAPL": '{"signal":"buy","score":0.8,"confidence":0.7}',
        }
        mock_quant.side_effect = lambda symbol, trade_date, **kwargs: payloads[symbol]

        with TemporaryDirectory() as cache_dir:
            score_tickers_with_quant(
                ["AAPL"],
                "2026-04-01",
                top_n=1,
                cache_dir=cache_dir,
            )
            second = score_tickers_with_quant(
                ["AAPL"],
                "2026-04-01",
                top_n=1,
                cache_dir=cache_dir,
                refresh_cache=True,
            )

        self.assertEqual(mock_quant.call_count, 2)
        self.assertFalse(second["ranked"][0]["cache_hit"])

    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    def test_prefilter_does_not_cache_error_payloads(self, mock_quant):
        mock_quant.side_effect = [
            '{"error":"No price history returned"}',
            '{"signal":"buy","score":0.8,"confidence":0.7}',
        ]

        with TemporaryDirectory() as cache_dir:
            first = score_tickers_with_quant(
                ["AAPL"],
                "2026-04-01",
                top_n=1,
                cache_dir=cache_dir,
            )
            second = score_tickers_with_quant(
                ["AAPL"],
                "2026-04-01",
                top_n=1,
                cache_dir=cache_dir,
            )

        self.assertEqual(mock_quant.call_count, 2)
        self.assertFalse(first["ranked"][0]["cache_hit"])
        self.assertFalse(second["ranked"][0]["cache_hit"])
        self.assertEqual(first["ranked"][0]["error"], "No price history returned")
        self.assertEqual(second["ranked"][0]["symbol"], "AAPL")
        self.assertEqual(second["ranked"][0]["signal"], "buy")

    @patch("tradingagents.graph.prefilter.get_quant_signals.func")
    @patch("tradingagents.graph.prefilter._is_live_trade_date", return_value=True)
    def test_prefilter_live_trade_date_bypasses_cache(self, _mock_live, mock_quant):
        mock_quant.side_effect = [
            '{"signal":"buy","score":0.8,"confidence":0.7}',
            '{"signal":"hold","score":0.1,"confidence":0.5}',
        ]

        with TemporaryDirectory() as cache_dir:
            first = score_tickers_with_quant(
                ["AAPL"],
                "2026-04-21",
                top_n=1,
                cache_dir=cache_dir,
            )
            second = score_tickers_with_quant(
                ["AAPL"],
                "2026-04-21",
                top_n=1,
                cache_dir=cache_dir,
            )

            cache_files = list(Path(cache_dir).glob("*.json"))

        self.assertEqual(mock_quant.call_count, 2)
        self.assertFalse(first["ranked"][0]["cache_hit"])
        self.assertFalse(second["ranked"][0]["cache_hit"])
        self.assertEqual(len(cache_files), 0)
