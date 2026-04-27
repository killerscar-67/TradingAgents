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
    load_report_sections_from_events,
    run_resumed_sync,
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


def _make_capturing_graph_factory(chunks, capture, final_decision="HOLD"):
    """Return a graph factory that records constructor and initial-state inputs."""
    def factory(selected_analysts, config):
        capture["selected_analysts"] = selected_analysts
        capture["config"] = dict(config)
        mock_graph = MagicMock()
        mock_graph.graph.stream.return_value = iter(chunks)

        def create_initial_state(company_name, trade_date, **kwargs):
            capture["initial_state"] = {
                "company_name": company_name,
                "trade_date": trade_date,
                **kwargs,
            }
            return {}

        mock_graph.propagator.create_initial_state.side_effect = create_initial_state
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

    def test_daytrade_metadata_is_stored_on_run(self):
        run = _make_run(
            selected_analysts=["intraday_market", "news"],
            trading_style="daytrade",
            intraday_interval="15m",
            trade_datetime="2026-04-23T10:15:00-04:00",
        )

        self.assertEqual(run.trading_style, "daytrade")
        self.assertEqual(run.intraday_interval, "15m")
        self.assertEqual(run.trade_datetime, "2026-04-23T10:15:00-04:00")


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

    def test_daytrade_config_passed_to_graph_and_initial_state(self):
        run = _make_run(
            selected_analysts=["intraday_market", "news"],
            trading_style="daytrade",
            intraday_interval="15m",
            trade_datetime="2026-04-23T10:15:00-04:00",
        )
        capture = {}

        result = run_sync(
            run.run_id,
            config={"journal_enabled": True},
            _graph_factory=_make_capturing_graph_factory(
                [{"messages": [], "final_trade_decision": "HOLD"}],
                capture,
            ),
            _stats_factory=_make_stats_factory(),
            _save_report=MagicMock(),
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(capture["selected_analysts"], ["intraday_market", "news"])
        self.assertEqual(capture["config"]["trading_style"], "daytrade")
        self.assertEqual(capture["config"]["intraday_interval"], "15m")
        self.assertEqual(capture["initial_state"]["trading_style"], "daytrade")
        self.assertEqual(capture["initial_state"]["trade_date"], "2026-04-23T10:15:00-04:00")

    def test_intraday_decisions_are_persisted_from_final_state(self):
        run = _make_run(trading_style="daytrade", intraday_interval="5m")
        decision = {
            "variant": "default",
            "setup_name": "VWAP reclaim",
            "bias": "long",
            "entry": 101.5,
            "stop": 100.7,
            "target1": 103.0,
            "confidence": "medium",
            "rationale": "Price reclaimed VWAP.",
        }

        result = self._run(run, [{
            "messages": [],
            "final_trade_decision": "BUY",
            "intraday_decisions": [decision],
            "session_phase": "regular",
            "data_session_date": "2026-04-23",
        }])

        self.assertEqual(result.intraday_decisions, [decision])
        self.assertEqual(result.session_phase, "regular")
        self.assertEqual(result.data_session_date, "2026-04-23")

    def test_resumed_sync_runs_remaining_downstream_phases(self):
        run = _make_run(selected_analysts=["market"])

        class FakeConditionalLogic:
            def __init__(self):
                self.risk_calls = 0

            def should_continue_debate(self, state):
                return "Research Manager"

            def should_continue_risk_analysis(self, state):
                self.risk_calls += 1
                return "Aggressive Analyst" if self.risk_calls == 1 else "Portfolio Manager"

        def fake_graph_factory(selected_analysts, config):
            graph = MagicMock()
            graph.quick_thinking_llm = object()
            graph.deep_thinking_llm = object()
            graph.bull_memory = MagicMock()
            graph.bear_memory = MagicMock()
            graph.trader_memory = MagicMock()
            graph.invest_judge_memory = MagicMock()
            graph.portfolio_manager_memory = MagicMock()
            graph.conditional_logic = FakeConditionalLogic()
            graph.propagator.create_initial_state.return_value = {
                "messages": [],
                "company_of_interest": "AAPL",
                "trade_date": "2026-04-23",
                "trade_datetime": "",
                "session_phase": "",
                "minutes_to_close": 0,
                "data_session_date": "",
                "intraday_decisions": [],
                "investment_debate_state": {"bull_history": "", "bear_history": "", "history": "", "current_response": "", "judge_decision": "", "count": 0},
                "risk_debate_state": {"aggressive_history": "", "conservative_history": "", "neutral_history": "", "history": "", "latest_speaker": "", "current_aggressive_response": "", "current_conservative_response": "", "current_neutral_response": "", "judge_decision": "", "count": 0},
                "market_report": "Recovered market report",
                "sentiment_report": "",
                "news_report": "",
                "fundamentals_report": "",
                "analysis_brief": {},
            }
            graph.build_order_intent.return_value = {
                "rating": "BUY",
                "blocked": False,
                "source": "llm_assisted",
                "execution_mode": "llm_assisted",
                "reason": "Resumed path",
                "annotations": {},
                "symbol": "AAPL",
                "trade_date": "2026-04-23",
            }
            return graph

        with patch("tradingagents.agents.create_research_manager", return_value=lambda state: {
            "investment_debate_state": {"bull_history": "", "bear_history": "", "history": "", "current_response": "", "judge_decision": "Recovered research plan", "count": 0},
            "investment_plan": "Recovered research plan",
        }), patch("tradingagents.agents.create_trader", return_value=lambda state: {
            "trader_investment_plan": "Trader resumed plan",
            "messages": [],
            "sender": "Trader",
        }), patch("tradingagents.agents.create_aggressive_debator", return_value=lambda state: {
            "risk_debate_state": {"history": "Aggressive Analyst: go", "aggressive_history": "Aggressive Analyst: go", "conservative_history": "", "neutral_history": "", "latest_speaker": "Aggressive", "current_aggressive_response": "Aggressive Analyst: go", "current_conservative_response": "", "current_neutral_response": "", "judge_decision": "", "count": 1},
        }), patch("tradingagents.agents.create_portfolio_manager", return_value=lambda state: {
            "risk_debate_state": {"history": "Aggressive Analyst: go", "aggressive_history": "Aggressive Analyst: go", "conservative_history": "", "neutral_history": "", "latest_speaker": "Judge", "current_aggressive_response": "Aggressive Analyst: go", "current_conservative_response": "", "current_neutral_response": "", "judge_decision": "Risk approved", "count": 1},
            "final_trade_decision": "BUY",
        }), patch("tradingagents.agents.create_bull_researcher"), patch("tradingagents.agents.create_bear_researcher"), patch("tradingagents.agents.create_conservative_debator"), patch("tradingagents.agents.create_neutral_debator"):
            result = run_resumed_sync(
                run.run_id,
                resume_from="trader",
                checkpoint_sections={
                    "market_report": "Recovered market report",
                    "investment_debate_judge_decision": "Recovered research plan",
                },
                _graph_factory=fake_graph_factory,
                _save_report=MagicMock(),
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report_sections["trader_investment_plan"], "Trader resumed plan")
        self.assertEqual(result.report_sections["final_trade_decision"], "BUY")


class LoadEventsFromDiskTests(unittest.TestCase):
    def test_returns_empty_for_missing_file(self):
        run = _make_run()
        events = load_events_from_disk(run.run_id)
        self.assertEqual(events, [])

    def test_returns_empty_for_unknown_run(self):
        events = load_events_from_disk("nonexistent-id")
        self.assertEqual(events, [])

    def test_load_report_sections_from_events_extracts_latest_sections(self):
        run = _make_run()
        with patch.object(runner_module, "load_events_from_disk", return_value=[
            {"type": "report_section", "payload": {"key": "market_report", "content": "Market one"}},
            {"type": "report_section", "payload": {"key": "market_report", "content": "Market two"}},
            {"type": "agent_status", "payload": {"agent": "Trader", "status": "completed"}},
        ]):
            sections = load_report_sections_from_events(run.run_id)

        self.assertEqual(sections["market_report"], "Market two")


if __name__ == "__main__":
    unittest.main()
