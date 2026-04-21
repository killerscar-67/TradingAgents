# TradingAgents/graph/trading_graph.py

import os
from pathlib import Path
import json
from datetime import date
from typing import Dict, Any, Tuple, List, Optional

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_quant_signals,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news
)

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor
from .prefilter import score_tickers_with_quant
from tradingagents.quant.contracts import (
    ExecutionMode,
    OrderIntentContract,
    QuantSignalContract,
    QuantSignalLabel,
    TradeRating,
    parse_execution_mode,
    rating_from_quant_signal,
)


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []
        self.execution_mode: ExecutionMode = parse_execution_mode(self.config.get("execution_mode"))

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        # Initialize memories
        self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
        self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
        self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
        self.portfolio_manager_memory = FinancialSituationMemory("portfolio_manager_memory", self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.bull_memory,
            self.bear_memory,
            self.trader_memory,
            self.invest_judge_memory,
            self.portfolio_manager_memory,
            self.conditional_logic,
        )

        self.propagator = Propagator()
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                    get_quant_signals,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def propagate(
        self,
        company_name,
        trade_date,
        quant_contract: Optional["QuantSignalContract"] = None,
    ):
        """Run the trading agents graph for a company on a specific date.

        Args:
            company_name: Ticker symbol or company identifier.
            trade_date: Date string (YYYY-MM-DD) or date object.
            quant_contract: Optional pre-scored QuantSignalContract. When provided
                in quant_strict mode, the live quant fetch is skipped so the
                returned order intent is derived from the same signal used during
                prefiltering, preserving determinism.

        Returns:
            (final_state, order_intent) where order_intent is the full dict from
            OrderIntentContract.to_dict(), including 'rating' and 'blocked'.
        """

        self.ticker = company_name

        # Initialize state
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date
        )
        args = self.propagator.get_graph_args()

        if self.debug:
            # Debug mode with tracing
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)

            final_state = trace[-1]
        else:
            # Standard mode without tracing
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection
        self.curr_state = final_state

        # Log state
        self._log_state(trade_date, final_state)

        order_intent = self.build_order_intent(
            company_name,
            str(trade_date),
            final_state["final_trade_decision"],
            quant_contract=quant_contract,
        )

        return final_state, order_intent

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file
        directory = Path(self.config["results_dir"]) / self.ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        self.reflector.reflect_bull_researcher(
            self.curr_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            self.curr_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            self.curr_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            self.curr_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_portfolio_manager(
            self.curr_state, returns_losses, self.portfolio_manager_memory
        )

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal, execution_mode=self.execution_mode)

    def build_order_intent(
        self,
        symbol: str,
        trade_date: str,
        final_trade_decision_text: str,
        quant_contract: Optional[QuantSignalContract] = None,
    ) -> Dict[str, Any]:
        """Build a typed order intent contract for execution and downstream automation.

        Args:
            symbol: Ticker symbol.
            trade_date: Date string (YYYY-MM-DD).
            final_trade_decision_text: Raw LLM final trade decision text.
            quant_contract: Optional pre-scored QuantSignalContract.  When provided
                in quant_strict mode the live quant fetch is skipped, ensuring the
                order intent is derived from the same signal used during prefiltering.
        """
        if self.execution_mode == "quant_strict":
            if quant_contract is None:
                raw_quant = get_quant_signals.func(symbol, trade_date)
                quant_contract = QuantSignalContract.from_raw(symbol, trade_date, raw_quant)
            rating = rating_from_quant_signal(quant_contract.signal)
            intent = OrderIntentContract(
                symbol=symbol,
                trade_date=trade_date,
                rating=rating,
                source="quant_strict",
                execution_mode="quant_strict",
                blocked=quant_contract.error is not None or quant_contract.signal == QuantSignalLabel.UNKNOWN,
                reason=quant_contract.error or ("Unknown quant signal." if quant_contract.signal == QuantSignalLabel.UNKNOWN else "Strict quant mode decision."),
                annotations={
                    "llm_final_trade_decision": final_trade_decision_text,
                    "quant_signal": quant_contract.to_dict(),
                },
            )
            return intent.to_dict()

        try:
            extracted = self.process_signal(final_trade_decision_text)
            rating = TradeRating(extracted)
            extraction_failed = False
        except ValueError:
            rating = TradeRating.HOLD
            extraction_failed = True
        intent = OrderIntentContract(
            symbol=symbol,
            trade_date=trade_date,
            rating=rating,
            source="llm_assisted",
            execution_mode="llm_assisted",
            blocked=extraction_failed,
            reason="LLM extraction fallback to HOLD." if extraction_failed else "LLM-assisted decision extraction.",
            annotations={
                "llm_final_trade_decision": final_trade_decision_text,
            },
        )
        return intent.to_dict()

    def rank_tickers_with_quant(
        self,
        tickers: List[str],
        trade_date: str,
        top_n: int = 10,
        quant_kwargs: Optional[Dict[str, Any]] = None,
        cache_dir: Optional[str] = None,
        cache_ttl_days: Optional[int] = None,
        refresh_cache: Optional[bool] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Rank a ticker universe with quant signals and choose top-N candidates."""
        cache_root = cache_dir or os.path.join(self.config["data_cache_dir"], "quant_prefilter")
        if cache_ttl_days is None:
            cache_ttl_days = self.config.get("quant_prefilter_cache_ttl_days", 1)
        if refresh_cache is None:
            refresh_cache = bool(self.config.get("quant_prefilter_refresh_cache", False))
        return score_tickers_with_quant(
            tickers=tickers,
            trade_date=trade_date,
            top_n=top_n,
            quant_kwargs=quant_kwargs,
            cache_dir=cache_root,
            cache_ttl_days=cache_ttl_days,
            refresh_cache=refresh_cache,
        )

    def propagate_prefiltered_universe(
        self,
        tickers: List[str],
        trade_date: str,
        top_n: int = 10,
        quant_kwargs: Optional[Dict[str, Any]] = None,
        cache_dir: Optional[str] = None,
        cache_ttl_days: Optional[int] = None,
        refresh_cache: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Run quant-first filtering, then analyze only selected symbols via the LLM graph."""
        prefilter = self.rank_tickers_with_quant(
            tickers=tickers,
            trade_date=trade_date,
            top_n=top_n,
            quant_kwargs=quant_kwargs,
            cache_dir=cache_dir,
            cache_ttl_days=cache_ttl_days,
            refresh_cache=refresh_cache,
        )

        analysis = {}
        for item in prefilter["selected"]:
            symbol = item["symbol"]
            # Reconstruct the pre-scored contract so build_order_intent in
            # quant_strict mode reuses it instead of making a second live fetch.
            cached_contract = QuantSignalContract.from_dict(item["contract"])
            final_state, order_intent = self.propagate(
                symbol, trade_date, quant_contract=cached_contract
            )
            analysis[symbol] = {
                "quant": item,
                "order_intent": order_intent,
                "blocked": order_intent.get("blocked", False),
                "final_state": final_state,
            }

        return {
            "prefilter": prefilter,
            "analysis": analysis,
        }
