# TradingAgents/graph/setup.py

from typing import Any, Dict
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    ANALYST_OUTPUT_KEYS = {
        "market": ("market_report",),
        "intraday_market": ("market_report", "intraday_decisions"),
        "social": ("sentiment_report",),
        "news": ("news_report",),
        "fundamentals": ("fundamentals_report",),
    }

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

    def _create_isolated_analyst_runner(self, analyst_type: str, analyst_node, tool_node):
        """Run one analyst's tool loop in a private message state.

        The outer graph fans analysts out in parallel. The legacy analyst/tool
        loop uses the shared ``messages`` channel, so each branch must execute
        in isolation and merge back only its report fields.
        """
        analyst_name = f"{analyst_type.capitalize()} Analyst"
        tools_name = f"tools_{analyst_type}"
        clear_name = f"Msg Clear {analyst_type.capitalize()}"

        subworkflow = StateGraph(AgentState)
        subworkflow.add_node(analyst_name, analyst_node)
        subworkflow.add_node(tools_name, tool_node)
        subworkflow.add_node(clear_name, create_msg_delete())
        subworkflow.add_edge(START, analyst_name)
        subworkflow.add_conditional_edges(
            analyst_name,
            getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
            [tools_name, clear_name],
        )
        subworkflow.add_edge(tools_name, analyst_name)
        subworkflow.add_edge(clear_name, END)
        analyst_graph = subworkflow.compile()
        output_keys = self.ANALYST_OUTPUT_KEYS.get(analyst_type, ())

        def run_isolated_analyst(state, config=None):
            sub_state = dict(state)
            sub_state["messages"] = list(state.get("messages", []))
            final_state = analyst_graph.invoke(sub_state, config=config)
            return {
                key: final_state[key]
                for key in output_keys
                if key in final_state
            }

        return run_isolated_analyst

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

        # Create analyst nodes
        analyst_nodes = {}
        tool_nodes = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self.quick_thinking_llm
            )
            tool_nodes["market"] = self.tool_nodes["market"]

        if "intraday_market" in selected_analysts:
            analyst_nodes["intraday_market"] = create_intraday_market_analyst(
                self.quick_thinking_llm
            )
            tool_nodes["intraday_market"] = self.tool_nodes["intraday_market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(
                self.quick_thinking_llm
            )
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.quick_thinking_llm
            )
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.quick_thinking_llm
            )
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

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

        # Add analyst runners to the graph. Each runner contains that
        # analyst's private tool loop and returns only report fields.
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(
                f"{analyst_type.capitalize()} Analyst",
                self._create_isolated_analyst_runner(
                    analyst_type, node, tool_nodes[analyst_type]
                ),
            )

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
        # Run selected analysts in parallel and join before the research debate.
        analyst_graph_nodes = []
        for analyst_type in selected_analysts:
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            analyst_graph_nodes.append(current_analyst)
            workflow.add_edge(START, current_analyst)

        workflow.add_edge(analyst_graph_nodes, "Bull Researcher")

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
