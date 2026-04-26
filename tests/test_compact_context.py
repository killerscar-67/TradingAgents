"""Phase 8: tests for compact context helpers and agent prompt switching."""

import unittest
from unittest.mock import MagicMock, patch

from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    cap_debate_history,
    extract_brief,
    get_context_mode,
)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestExtractBrief(unittest.TestCase):
    def test_short_string_unchanged(self):
        s = "Hello world"
        self.assertEqual(extract_brief(s, max_chars=400), s)

    def test_long_string_truncated(self):
        s = "A" * 500
        result = extract_brief(s, max_chars=400)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), 402)

    def test_exact_length_unchanged(self):
        s = "B" * 400
        self.assertEqual(extract_brief(s, max_chars=400), s)

    def test_empty_string(self):
        self.assertEqual(extract_brief("", max_chars=400), "")

    def test_none_like_empty(self):
        self.assertEqual(extract_brief("", max_chars=50), "")


class TestBuildAnalysisBrief(unittest.TestCase):
    def test_keys_present(self):
        brief = build_analysis_brief("m", "s", "n", "f")
        self.assertSetEqual(set(brief.keys()), {"market", "sentiment", "news", "fundamentals"})

    def test_truncation_applied(self):
        long = "X" * 500
        brief = build_analysis_brief(long, long, long, long, max_chars=100)
        for key in ("market", "sentiment", "news", "fundamentals"):
            self.assertLessEqual(len(brief[key]), 102)

    def test_short_reports_pass_through(self):
        brief = build_analysis_brief("m", "s", "n", "f", max_chars=100)
        self.assertEqual(brief["market"], "m")
        self.assertEqual(brief["news"], "n")


class TestCapDebateHistory(unittest.TestCase):
    def test_short_history_unchanged(self):
        h = "Round 1\nRound 2"
        self.assertEqual(cap_debate_history(h, max_chars=2000, preserve_latest_chars=600), h)

    def test_long_history_truncated(self):
        h = "A" * 3000
        result = cap_debate_history(h, max_chars=2000, preserve_latest_chars=600)
        self.assertLessEqual(len(result), 2000 + 50)
        self.assertIn("truncated", result)

    def test_tail_is_preserved(self):
        tail = "TAIL" * 100  # 400 chars
        head = "HEAD" * 1000
        h = head + tail
        result = cap_debate_history(h, max_chars=2000, preserve_latest_chars=600)
        self.assertTrue(result.endswith(tail))

    def test_empty_history(self):
        self.assertEqual(cap_debate_history(""), "")


class TestGetContextMode(unittest.TestCase):
    def test_default_compact(self):
        with patch("tradingagents.dataflows.config.get_config", return_value={}):
            self.assertEqual(get_context_mode(), "compact")

    def test_explicit_full(self):
        with patch(
            "tradingagents.dataflows.config.get_config",
            return_value={"context_mode": "full"},
        ):
            self.assertEqual(get_context_mode(), "full")

    def test_compact_mode(self):
        with patch(
            "tradingagents.dataflows.config.get_config",
            return_value={"context_mode": "compact"},
        ):
            self.assertEqual(get_context_mode(), "compact")


# ---------------------------------------------------------------------------
# Fake LLM for agent tests
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Prompt-capturing LLM stand-in: records the last invoke argument."""

    def __init__(self, reply: str = "fake response"):
        self._reply = reply
        self.last_prompt: str = ""

    def invoke(self, prompt):
        self.last_prompt = prompt if isinstance(prompt, str) else str(prompt)
        msg = MagicMock()
        msg.content = self._reply
        return msg


class _FakeMemory:
    def get_memories(self, *args, **kwargs):
        return []


# ---------------------------------------------------------------------------
# Shared state helpers
# ---------------------------------------------------------------------------


def _ctx(mode: str, brief_max_chars: int = 400) -> dict:
    return {
        "mode": mode,
        "brief_max_chars": brief_max_chars,
        "debate_max_chars": 2000,
        "debate_preserve_chars": 600,
    }


def _make_invest_debate_state():
    return {
        "history": "",
        "bull_history": "",
        "bear_history": "",
        "current_response": "",
        "judge_decision": "",
        "count": 0,
    }


def _make_base_state(invest_debate=None):
    return {
        "messages": [],
        "company_of_interest": "AAPL",
        "trade_date": "2026-01-01",
        "sender": "",
        "market_report": "Market report text " * 20,
        "sentiment_report": "Sentiment report " * 20,
        "news_report": "News report " * 20,
        "fundamentals_report": "Fundamentals report " * 20,
        "analysis_brief": {},
        "investment_debate_state": invest_debate or _make_invest_debate_state(),
        "investment_plan": "Buy AAPL",
        "trader_investment_plan": "BUY",
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
        "final_trade_decision": "",
    }


# ---------------------------------------------------------------------------
# Bull researcher agent
# ---------------------------------------------------------------------------


class TestBullResearcherCompact(unittest.TestCase):
    _MODULE = "tradingagents.agents.researchers.bull_researcher.get_context_cfg"

    def _run(self, mode: str, pre_brief: dict = None, brief_max_chars: int = 400):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = _FakeLLM("bull reply")
        node = create_bull_researcher(llm, _FakeMemory())
        state = _make_base_state()
        if pre_brief is not None:
            state["analysis_brief"] = pre_brief
        with patch(self._MODULE, return_value=_ctx(mode, brief_max_chars)):
            node(state)
        return state, llm  # state mutated, llm.last_prompt captured

    def _run_result(self, mode: str, pre_brief: dict = None, brief_max_chars: int = 400):
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = _FakeLLM("bull reply")
        node = create_bull_researcher(llm, _FakeMemory())
        state = _make_base_state()
        if pre_brief is not None:
            state["analysis_brief"] = pre_brief
        with patch(self._MODULE, return_value=_ctx(mode, brief_max_chars)):
            result = node(state)
        return result, llm

    def test_full_mode_no_brief_written(self):
        result, _ = self._run_result("full")
        self.assertNotIn("analysis_brief", result)

    def test_compact_mode_brief_written(self):
        result, _ = self._run_result("compact")
        self.assertIn("analysis_brief", result)
        for key in ("market", "sentiment", "news", "fundamentals"):
            self.assertIn(key, result["analysis_brief"])

    def test_compact_prompt_excludes_full_report(self):
        long_report = "DetailedMarketReport_XYZ " * 50
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = _FakeLLM("bull reply")
        node = create_bull_researcher(llm, _FakeMemory())
        state = _make_base_state()
        state["market_report"] = long_report
        with patch(self._MODULE, return_value=_ctx("compact")):
            node(state)
        self.assertIn("Market:", llm.last_prompt)
        self.assertNotIn(long_report, llm.last_prompt)

    def test_full_prompt_contains_full_report(self):
        report = "UniqueFullMarketReport"
        from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
        llm = _FakeLLM("bull reply")
        node = create_bull_researcher(llm, _FakeMemory())
        state = _make_base_state()
        state["market_report"] = report
        with patch(self._MODULE, return_value=_ctx("full")):
            node(state)
        self.assertIn(report, llm.last_prompt)

    def test_brief_max_chars_respected(self):
        result, _ = self._run_result("compact", brief_max_chars=10)
        for key in ("market", "sentiment", "news", "fundamentals"):
            self.assertLessEqual(len(result["analysis_brief"][key]), 12)

    def test_compact_mode_reuses_existing_brief(self):
        existing = {"market": "m", "sentiment": "s", "news": "n", "fundamentals": "f"}
        result, _ = self._run_result("compact", pre_brief=existing)
        self.assertEqual(result["analysis_brief"], existing)

    def test_debate_state_count_incremented(self):
        result, _ = self._run_result("full")
        self.assertEqual(result["investment_debate_state"]["count"], 1)


class TestBearResearcherCompact(unittest.TestCase):
    _MODULE = "tradingagents.agents.researchers.bear_researcher.get_context_cfg"

    def _run(self, mode: str):
        from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
        node = create_bear_researcher(_FakeLLM("bear reply"), _FakeMemory())
        state = _make_base_state()
        with patch(self._MODULE, return_value=_ctx(mode)):
            return node(state)

    def test_full_mode_no_brief(self):
        self.assertNotIn("analysis_brief", self._run("full"))

    def test_compact_mode_brief_present(self):
        self.assertIn("analysis_brief", self._run("compact"))

    def test_count_incremented(self):
        result = self._run("full")
        self.assertEqual(result["investment_debate_state"]["count"], 1)


class TestTraderCompact(unittest.TestCase):
    _MODULE = "tradingagents.agents.trader.trader.get_context_cfg"

    def _run(self, mode: str):
        from tradingagents.agents.trader.trader import create_trader
        node = create_trader(_FakeLLM("FINAL TRANSACTION PROPOSAL: **BUY**"), _FakeMemory())
        state = _make_base_state()
        with patch(self._MODULE, return_value=_ctx(mode)):
            return node(state)

    def _run_with_llm(self, mode: str):
        from tradingagents.agents.trader.trader import create_trader
        llm = _FakeLLM("FINAL TRANSACTION PROPOSAL: **BUY**")
        node = create_trader(llm, _FakeMemory())
        state = _make_base_state()
        with patch(self._MODULE, return_value=_ctx(mode)):
            result = node(state)
        return result, llm

    def test_full_mode_no_brief(self):
        result = self._run("full")
        self.assertEqual(result["sender"], "Trader")
        self.assertNotIn("analysis_brief", result)

    def test_compact_mode_brief(self):
        self.assertIn("analysis_brief", self._run("compact"))

    def test_full_mode_no_analysis_summary_in_prompt(self):
        _, llm = self._run_with_llm("full")
        self.assertNotIn("Analysis Summary:", llm.last_prompt)

    def test_compact_mode_analysis_summary_in_prompt(self):
        _, llm = self._run_with_llm("compact")
        self.assertIn("Analysis Summary:", llm.last_prompt)

    def test_compact_prompt_excludes_full_report(self):
        long_report = "DetailedMarketReport_XYZ " * 50
        from tradingagents.agents.trader.trader import create_trader
        llm = _FakeLLM("FINAL TRANSACTION PROPOSAL: **BUY**")
        node = create_trader(llm, _FakeMemory())
        state = _make_base_state()
        state["market_report"] = long_report
        with patch(self._MODULE, return_value=_ctx("compact")):
            node(state)
        self.assertIn("Market:", llm.last_prompt)
        self.assertNotIn(long_report, llm.last_prompt)

    def test_full_prompt_contains_investment_plan(self):
        _, llm = self._run_with_llm("full")
        self.assertIn("Buy AAPL", llm.last_prompt)


class TestRiskDebatorsCompact(unittest.TestCase):
    def _run_aggressive(self, mode: str):
        from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
        node = create_aggressive_debator(_FakeLLM("aggressive"))
        state = _make_base_state()
        with patch(
            "tradingagents.agents.risk_mgmt.aggressive_debator.get_context_cfg",
            return_value=_ctx(mode),
        ):
            return node(state)

    def _run_conservative(self, mode: str):
        from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
        node = create_conservative_debator(_FakeLLM("conservative"))
        state = _make_base_state()
        with patch(
            "tradingagents.agents.risk_mgmt.conservative_debator.get_context_cfg",
            return_value=_ctx(mode),
        ):
            return node(state)

    def _run_neutral(self, mode: str):
        from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
        node = create_neutral_debator(_FakeLLM("neutral"))
        state = _make_base_state()
        with patch(
            "tradingagents.agents.risk_mgmt.neutral_debator.get_context_cfg",
            return_value=_ctx(mode),
        ):
            return node(state)

    def test_aggressive_compact_brief(self):
        self.assertIn("analysis_brief", self._run_aggressive("compact"))

    def test_aggressive_full_no_brief(self):
        self.assertNotIn("analysis_brief", self._run_aggressive("full"))

    def test_conservative_compact_brief(self):
        self.assertIn("analysis_brief", self._run_conservative("compact"))

    def test_neutral_compact_brief(self):
        self.assertIn("analysis_brief", self._run_neutral("compact"))

    def test_aggressive_count_incremented(self):
        result = self._run_aggressive("full")
        self.assertEqual(result["risk_debate_state"]["count"], 1)


class TestPortfolioManagerCompact(unittest.TestCase):
    _MODULE = "tradingagents.agents.managers.portfolio_manager.get_context_cfg"

    def _run(self, mode: str):
        from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
        llm = _FakeLLM("Rating: Buy")
        node = create_portfolio_manager(llm, _FakeMemory())
        state = _make_base_state()
        with patch(self._MODULE, return_value=_ctx(mode)):
            result = node(state)
        return result, llm

    def test_full_mode_decision_set(self):
        result, _ = self._run("full")
        self.assertEqual(result["final_trade_decision"], "Rating: Buy")

    def test_full_mode_no_brief_and_no_analysis_summary(self):
        result, llm = self._run("full")
        self.assertNotIn("analysis_brief", result)
        # Full mode must NOT inject an Analysis Summary block (regression guard)
        self.assertNotIn("Analysis Summary:", llm.last_prompt)

    def test_compact_mode_brief_present(self):
        result, _ = self._run("compact")
        self.assertIn("analysis_brief", result)

    def test_compact_mode_analysis_summary_in_prompt(self):
        _, llm = self._run("compact")
        self.assertIn("Analysis Summary:", llm.last_prompt)


if __name__ == "__main__":
    unittest.main()
