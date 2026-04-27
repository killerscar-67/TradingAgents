import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup


def _dummy_node(state):
    return {}


class GraphSetupParallelAnalystsTests(unittest.TestCase):
    def _setup(self):
        tool_nodes = {
            "market": _dummy_node,
            "social": _dummy_node,
            "news": _dummy_node,
            "fundamentals": _dummy_node,
        }
        return GraphSetup(
            quick_thinking_llm=None,
            deep_thinking_llm=None,
            tool_nodes=tool_nodes,
            bull_memory=None,
            bear_memory=None,
            trader_memory=None,
            invest_judge_memory=None,
            portfolio_manager_memory=None,
            conditional_logic=ConditionalLogic(),
        )

    def test_selected_analysts_fan_out_from_start_and_join_before_research(self):
        patches = [
            patch("tradingagents.graph.setup.create_market_analyst", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_social_media_analyst", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_news_analyst", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_fundamentals_analyst", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_bull_researcher", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_bear_researcher", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_research_manager", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_trader", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_aggressive_debator", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_neutral_debator", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_conservative_debator", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_portfolio_manager", return_value=_dummy_node),
        ]

        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        graph = self._setup().setup_graph(["market", "social", "news", "fundamentals"])
        nodes = set(graph.get_graph().nodes.keys())
        edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

        # All analysts run inside one parallel "Analysts" node (a
        # ThreadPoolExecutor wrapper). The graph has a single fan-out point.
        self.assertIn("Analysts", nodes)
        self.assertIn(("__start__", "Analysts"), edges)
        self.assertIn(("Analysts", "Bull Researcher"), edges)

        # Per-analyst LangGraph nodes and their tool/clear scaffolding are gone.
        for legacy in (
            "Market Analyst", "Social Analyst", "News Analyst", "Fundamentals Analyst",
            "tools_market", "tools_social", "tools_news", "tools_fundamentals",
            "Msg Clear Market", "Msg Clear Social", "Msg Clear News", "Msg Clear Fundamentals",
        ):
            self.assertNotIn(legacy, nodes)

    def test_parallel_analysts_keep_message_state_isolated(self):
        def market_node(state):
            return {
                "messages": [AIMessage(content="market", id="market-message")],
                "market_report": "market report",
            }

        def news_node(state):
            return {
                "messages": [AIMessage(content="news", id="news-message")],
                "news_report": "news report",
            }

        def bull_node(state):
            self.assertEqual(state["market_report"], "market report")
            self.assertEqual(state["news_report"], "news report")
            return {
                "investment_debate_state": {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "Bull done",
                    "judge_decision": "",
                    "count": 0,
                }
            }

        patches = [
            patch("tradingagents.graph.setup.create_market_analyst", return_value=market_node),
            patch("tradingagents.graph.setup.create_news_analyst", return_value=news_node),
            patch("tradingagents.graph.setup.create_bull_researcher", return_value=bull_node),
            patch("tradingagents.graph.setup.create_bear_researcher", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_research_manager", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_trader", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_aggressive_debator", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_neutral_debator", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_conservative_debator", return_value=_dummy_node),
            patch("tradingagents.graph.setup.create_portfolio_manager", return_value=_dummy_node),
        ]

        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        setup = GraphSetup(
            quick_thinking_llm=None,
            deep_thinking_llm=None,
            tool_nodes={"market": _dummy_node, "news": _dummy_node},
            bull_memory=None,
            bear_memory=None,
            trader_memory=None,
            invest_judge_memory=None,
            portfolio_manager_memory=None,
            conditional_logic=ConditionalLogic(max_debate_rounds=0, max_risk_discuss_rounds=0),
        )
        graph = setup.setup_graph(["market", "news"])

        result = graph.invoke({
            "messages": [],
            "company_of_interest": "AAPL",
            "trade_date": "2026-04-27",
            "market_report": "",
            "news_report": "",
            "sentiment_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {
                "bull_history": "",
                "bear_history": "",
                "history": "",
                "current_response": "",
                "judge_decision": "",
                "count": 0,
            },
            "risk_debate_state": {
                "aggressive_history": "",
                "conservative_history": "",
                "neutral_history": "",
                "history": "",
                "latest_speaker": "",
                "current_aggressive_response": "",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 0,
            },
        })

        self.assertEqual(result["market_report"], "market report")
        self.assertEqual(result["news_report"], "news report")


if __name__ == "__main__":
    unittest.main()
