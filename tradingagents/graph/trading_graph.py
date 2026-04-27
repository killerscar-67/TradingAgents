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
from tradingagents.agents.utils.intraday_tools import (
    get_intraday_stock_data,
    get_intraday_indicators,
    get_session_context,
)

from tradingagents.journal import Journal

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor
from .prefilter import score_tickers_with_quant
from tradingagents.quant.contracts import (
    DailyLossState,
    EntryEngine,
    EntrySignal,
    ExecutionMode,
    OrderIntentContract,
    PositionSizeContract,
    QuantSignalContract,
    QuantSignalLabel,
    TradeRating,
    parse_execution_mode,
    rating_from_quant_signal,
)
from tradingagents.quant.risk import check_risk_gates, size_position


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

        # Daytrade mode: enforce analyst-set policy and force debate off.
        self.trading_style = self.config.get("trading_style", "swing")
        if self.trading_style == "daytrade":
            selected_analysts = self._enforce_daytrade_analysts(selected_analysts)
            # Intraday decisions need to be fast — skip the bull/bear debate entirely.
            # User can re-enable by setting trading_style=swing.
            self.config["max_debate_rounds"] = 0

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

        # Trading journal (best-effort; never blocks runs)
        self.journal: Optional[Journal] = None
        if self.config.get("journal_enabled", False):
            try:
                self.journal = Journal(self.config["journal_path"])
            except Exception as e:  # noqa: BLE001
                print(f"[journal] init failed: {e}; journaling disabled for this run")
                self.journal = None

        # Set up the graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {
            "timeout": self.config.get("llm_timeout", 300),
            "retry_attempts": self.config.get("llm_retry_attempts", 3),
        }
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
            "intraday_market": ToolNode(
                [
                    get_intraday_stock_data,
                    get_intraday_indicators,
                    get_session_context,
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

    # Allowed analyst categories per trading style.
    _DAYTRADE_PERMITTED_ANALYSTS = {"intraday_market", "news"}

    def _enforce_daytrade_analysts(self, selected_analysts: List[str]) -> List[str]:
        """Apply the daytrade analyst policy.

        Strict mode (default): drop swing-only analysts (fundamentals, social, market)
        and substitute `market` with `intraday_market`. Raise if the resulting set
        is empty.

        Permissive mode (`allow_mismatched_analysts=True`): only swap `market`
        for `intraday_market`; everything else passes through.
        """
        strict = self.config.get("daytrade_strict_analysts", True)
        allow_mismatched = self.config.get("allow_mismatched_analysts", False)

        result: List[str] = []
        for a in selected_analysts:
            if a == "market":
                result.append("intraday_market")
            elif a == "intraday_market":
                result.append("intraday_market")
            elif a in self._DAYTRADE_PERMITTED_ANALYSTS:
                result.append(a)
            elif strict and not allow_mismatched:
                # Drop silently with a console-visible warning.
                print(f"[daytrade] Dropping analyst '{a}' (use allow_mismatched_analysts=True to override).")
            else:
                result.append(a)

        # Ensure intraday_market is present — it's the analyst that produces the setup.
        if "intraday_market" not in result:
            result.insert(0, "intraday_market")

        return result

    def propagate(
        self,
        company_name,
        trade_date,
        quant_contract: Optional["QuantSignalContract"] = None,
    ):
        """Run the trading agents graph for a company on a specific date.

        Args:
            company_name: Ticker symbol or company identifier.
            trade_date: Date string (YYYY-MM-DD) or date object. In daytrade mode,
                may also be a full ISO 8601 datetime (e.g. "2025-04-24T10:30:00-04:00");
                session context is resolved automatically and bars walk back to the
                previous session when called outside extended hours.
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
            company_name, trade_date, trading_style=self.trading_style,
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

        # Journal the structured intraday decision(s) — best-effort, swing runs unaffected.
        if self.journal is not None and self.trading_style == "daytrade":
            decisions = final_state.get("intraday_decisions") or []
            if decisions:
                self.journal.record_decision_safely(
                    symbol=company_name,
                    trading_style=self.trading_style,
                    decisions=decisions,
                    state=final_state,
                    config=self.config,
                    also_log_agent_action=True,
                )

        # Build the quant order intent (from feature/quant). When quant_contract is
        # supplied, the live quant fetch is skipped for deterministic prefilter-driven runs.
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
        risk_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a typed order intent contract for execution and downstream automation.

        Args:
            symbol: Ticker symbol.
            trade_date: Date string (YYYY-MM-DD).
            final_trade_decision_text: Raw LLM final trade decision text.
            quant_contract: Optional pre-scored QuantSignalContract.  When provided
                in quant_strict mode the live quant fetch is skipped, ensuring the
                order intent is derived from the same signal used during prefiltering.
            risk_context: Optional runtime sizing and exposure inputs. When supplied
                in quant_strict mode, position sizing and pre-trade risk gates are
                applied before returning the order intent.
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
            intent = self._apply_quant_risk_controls(
                symbol,
                trade_date,
                intent,
                quant_contract,
                risk_context=risk_context,
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

    def _coerce_entry_signal(self, payload: Any) -> Optional[EntrySignal]:
        if isinstance(payload, EntrySignal):
            return payload
        if not isinstance(payload, dict):
            return None

        engine_value = str(payload.get("engine", "")).strip().lower()
        direction = str(payload.get("direction", "")).strip().lower()
        if engine_value not in {item.value for item in EntryEngine}:
            return None
        if direction not in {"long", "short"}:
            return None
        try:
            strength = float(payload.get("strength", 0.0))
        except (TypeError, ValueError):
            strength = 0.0

        return EntrySignal(
            engine=EntryEngine(engine_value),
            direction=direction,
            strength=strength,
            reason=str(payload.get("reason", "")),
        )

    def _coerce_daily_loss_state(self, payload: Any, trade_date: str) -> DailyLossState:
        if isinstance(payload, DailyLossState):
            return payload
        if isinstance(payload, dict):
            return DailyLossState(
                date=str(payload.get("date", trade_date)),
                net_pnl=float(payload.get("net_pnl", 0.0)),
                kill_switch=bool(payload.get("kill_switch", False)),
                trade_count=int(payload.get("trade_count", 0)),
            )
        return DailyLossState.new_day(trade_date)

    def _apply_quant_risk_controls(
        self,
        symbol: str,
        trade_date: str,
        intent: OrderIntentContract,
        quant_contract: QuantSignalContract,
        risk_context: Optional[Dict[str, Any]] = None,
    ) -> OrderIntentContract:
        context = risk_context or self.config.get("risk_context") or {}
        if not context or intent.blocked:
            return intent

        entry_signal = self._coerce_entry_signal(
            context.get("entry_signal")
            or (quant_contract.raw.get("entry") if isinstance(quant_contract.raw, dict) else None)
        )

        metadata = quant_contract.raw.get("metadata", {}) if isinstance(quant_contract.raw, dict) else {}
        entry_price = context.get("entry_price", metadata.get("close"))
        atr_15m = context.get("atr_15m")
        account_equity = context.get("account_equity")

        if entry_signal is None or entry_price is None or atr_15m is None or account_equity is None:
            return intent

        daily_loss_state = self._coerce_daily_loss_state(context.get("daily_loss_state"), trade_date)
        try:
            current_exposure = float(context.get("current_exposure", 0.0))
            size_contract = size_position(
                entry_signal,
                float(entry_price),
                float(atr_15m),
                float(account_equity),
                self.config,
            )
            size_contract = PositionSizeContract(
                symbol=symbol,
                direction=size_contract.direction,
                quantity=size_contract.quantity,
                entry_price=size_contract.entry_price,
                notional=size_contract.notional,
                stop_price=size_contract.stop_price,
                risk_amount=size_contract.risk_amount,
                method=size_contract.method,
            )
            risk_gate = check_risk_gates(
                size_contract,
                daily_loss_state,
                current_exposure,
                float(account_equity),
                self.config,
            )
        except (TypeError, ValueError) as exc:
            risk_annotations = dict(intent.annotations)
            risk_annotations["risk"] = {
                "applied": False,
                "error": str(exc),
            }
            return OrderIntentContract(
                symbol=intent.symbol,
                trade_date=intent.trade_date,
                rating=intent.rating,
                source=intent.source,
                execution_mode=intent.execution_mode,
                blocked=True,
                reason=f"Risk sizing failed: {exc}",
                annotations=risk_annotations,
            )

        risk_annotations = dict(intent.annotations)
        risk_annotations["risk"] = {
            "applied": True,
            "size_contract": size_contract.to_dict(),
            "gate": risk_gate.to_dict(),
        }
        return OrderIntentContract(
            symbol=intent.symbol,
            trade_date=intent.trade_date,
            rating=intent.rating,
            source=intent.source,
            execution_mode=intent.execution_mode,
            blocked=intent.blocked or not risk_gate.allowed,
            reason=risk_gate.reason if not risk_gate.allowed else intent.reason,
            annotations=risk_annotations,
        )

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
