# TradingAgents/graph/setup.py

from typing import Any, Dict
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_parallel_analysts_node

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        bull_memory,
        bear_memory,
        trader_memory,
        invest_judge_memory,
        portfolio_manager_memory,
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.trader_memory = trader_memory
        self.invest_judge_memory = invest_judge_memory
        self.portfolio_manager_memory = portfolio_manager_memory
        self.conditional_logic = conditional_logic

    def setup_graph(
        self, selected_analysts=["market", "social", "news", "fundamentals"]
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst (swing-mode default)
                - "intraday_market": Intraday market analyst (daytrade mode)
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Both market and intraday_market write to the `market_report` state
        # field. With analysts running in parallel inside one node, the merge
        # would silently drop one of the two reports. Reject the combination
        # explicitly: callers must pick swing OR daytrade, not both.
        if "market" in selected_analysts and "intraday_market" in selected_analysts:
            raise ValueError(
                "Trading Agents Graph Setup Error: cannot select both 'market' and "
                "'intraday_market' analysts; they share the market_report state field."
            )

        # Create analyst nodes. Each analyst now runs a self-contained ReAct
        # loop (see agent_utils.run_analyst_loop), so the LangGraph tool nodes
        # and per-analyst Msg Clear nodes are no longer required.
        analyst_nodes: Dict[str, Any] = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(self.quick_thinking_llm)

        if "intraday_market" in selected_analysts:
            analyst_nodes["intraday_market"] = create_intraday_market_analyst(
                self.quick_thinking_llm
            )

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(self.quick_thinking_llm)

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(self.quick_thinking_llm)

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.quick_thinking_llm
            )

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(
            self.quick_thinking_llm, self.bull_memory
        )
        bear_researcher_node = create_bear_researcher(
            self.quick_thinking_llm, self.bear_memory
        )
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )
        trader_node = create_trader(self.quick_thinking_llm, self.trader_memory)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(
            self.deep_thinking_llm, self.portfolio_manager_memory
        )

        # Create workflow
        workflow = StateGraph(AgentState)

        # Single parallel-analyst node: each selected analyst runs concurrently
        # in its own thread, writing only to its dedicated *_report state
        # field. With one analyst selected this becomes a no-op pass-through.
        parallel_analysts = create_parallel_analysts_node(analyst_nodes)
        workflow.add_node("Analysts", parallel_analysts)

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        workflow.add_edge(START, "Analysts")
        workflow.add_edge("Analysts", "Bull Researcher")

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", END)

        # Compile and return
        return workflow.compile()
