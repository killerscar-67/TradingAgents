"""Unit tests for the web runner service."""

import json
import queue
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tradingagents.web import runner as runner_module
from tradingagents.web.models import AnalysisRun
from tradingagents.web.runner import (
    _DONE,
    create_run,
    get_event_queue,
    get_run,
    load_events_from_disk,
    run_sync,
)


def _make_run(**kwargs) -> AnalysisRun:
    defaults = dict(
        ticker="AAPL",
        analysis_date="2026-04-23",
        selected_analysts=["market"],
        execution_mode="llm_assisted",
        llm_provider="openai",
        deep_think_llm="gpt-4o",
        quick_think_llm="gpt-4o-mini",
    )
    defaults.update(kwargs)
    return create_run(**defaults)


def _make_graph_factory(chunks, final_decision="HOLD"):
    """Return a callable that acts as a TradingAgentsGraph constructor."""
    def factory(selected_analysts, config):
        mock_graph = MagicMock()
        mock_graph.graph.stream.return_value = iter(chunks)
        mock_graph.propagator.create_initial_state.return_value = {}
        mock_graph.propagator.get_graph_args.return_value = {}
        mock_graph.build_order_intent.return_value = {
            "rating": final_decision,
            "blocked": False,
            "source": "llm_assisted",
            "execution_mode": "llm_assisted",
            "reason": "",
            "annotations": {},
            "symbol": "AAPL",
            "trade_date": "2026-04-23",
        }
        return mock_graph
    return factory


def _make_stats_factory():
    def factory():
        m = MagicMock()
        m.get_stats.return_value = {}
        return m
    return factory


class CreateRunTests(unittest.TestCase):
    def test_returns_analysis_run(self):
        run = _make_run()
        self.assertIsInstance(run, AnalysisRun)
        self.assertEqual(run.status, "pending")
        self.assertEqual(run.ticker, "AAPL")

    def test_run_id_unique(self):
        r1 = _make_run()
        r2 = _make_run()
        self.assertNotEqual(r1.run_id, r2.run_id)

    def test_event_queue_created(self):
        run = _make_run()
        q = get_event_queue(run.run_id)
        self.assertIsNotNone(q)
        self.assertIsInstance(q, queue.Queue)

    def test_get_run_returns_none_for_unknown(self):
        self.assertIsNone(get_run("does-not-exist"))

    def test_preserves_exchange_suffix(self):
        for ticker in ("RY.TO", "HSBA.L", "0700.HK", "7203.T"):
            run = create_run(
                ticker=ticker,
                analysis_date="2026-04-23",
                selected_analysts=["market"],
                execution_mode="llm_assisted",
                llm_provider="openai",
                deep_think_llm="gpt-4o",
                quick_think_llm="gpt-4o-mini",
            )
            self.assertEqual(run.ticker, ticker)


class RunSyncTests(unittest.TestCase):
    def _run(self, run, chunks, final_decision="HOLD", on_chunk=None):
        return run_sync(
            run.run_id,
            on_chunk=on_chunk,
            _graph_factory=_make_graph_factory(chunks, final_decision),
            _stats_factory=_make_stats_factory(),
            _save_report=MagicMock(),
        )

    def test_status_transitions_to_completed(self):
        run = _make_run()
        result = self._run(run, [
            {"messages": [], "market_report": "Market is bullish.", "final_trade_decision": "BUY"},
        ], "BUY")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.errors, [])

    def test_report_sections_populated(self):
        run = _make_run()
        result = self._run(run, [
            {"messages": [], "market_report": "Bullish outlook.", "final_trade_decision": "BUY"},
        ])
        self.assertIn("market_report", result.report_sections)
        self.assertEqual(result.report_sections["market_report"], "Bullish outlook.")

    def test_done_sentinel_placed_in_queue(self):
        run = _make_run()
        self._run(run, [{"messages": [], "final_trade_decision": "HOLD"}])
        q = get_event_queue(run.run_id)
        last = None
        while not q.empty():
            last = q.get_nowait()
        self.assertIs(last, _DONE)

    def test_graph_exception_sets_error_status(self):
        run = _make_run()
        def bad_factory(selected_analysts, config):
            m = MagicMock()
            m.propagator.create_initial_state.return_value = {}
            m.propagator.get_graph_args.return_value = {}
            m.graph.stream.side_effect = RuntimeError("LLM provider unreachable")
            return m

        result = run_sync(
            run.run_id,
            _graph_factory=bad_factory,
            _stats_factory=_make_stats_factory(),
            _save_report=MagicMock(),
        )

        self.assertEqual(result.status, "error")
        self.assertTrue(len(result.errors) > 0)
        self.assertIn("RuntimeError", result.errors[0])

    def test_on_chunk_callback_called(self):
        run = _make_run()
        received = []
        self._run(
            run,
            [{"messages": [], "market_report": "data", "final_trade_decision": "BUY"}],
            on_chunk=received.append,
        )
        self.assertEqual(len(received), 1)

    def test_investment_debate_sections_populated(self):
        run = _make_run()
        result = self._run(run, [{
            "messages": [],
            "final_trade_decision": "BUY",
            "investment_debate_state": {
                "bull_history": "Bull case: strong growth.",
                "bear_history": "Bear case: macro risk.",
                "judge_decision": "Lean bull.",
            },
        }])
        self.assertIn("investment_debate_bull_history", result.report_sections)
        self.assertIn("investment_debate_bear_history", result.report_sections)
        self.assertIn("investment_debate_judge_decision", result.report_sections)

    def test_order_intent_stored(self):
        run = _make_run()
        result = self._run(run, [
            {"messages": [], "market_report": "ok", "final_trade_decision": "BUY"},
        ], "BUY")
        self.assertIsNotNone(result.final_order_intent)
        self.assertEqual(result.final_order_intent["rating"], "BUY")


class LoadEventsFromDiskTests(unittest.TestCase):
    def test_returns_empty_for_missing_file(self):
        run = _make_run()
        events = load_events_from_disk(run.run_id)
        self.assertEqual(events, [])

    def test_returns_empty_for_unknown_run(self):
        events = load_events_from_disk("nonexistent-id")
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
