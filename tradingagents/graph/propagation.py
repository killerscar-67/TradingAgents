# TradingAgents/graph/propagation.py

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.session import resolve_session_context


def _parse_dt(value: str) -> datetime:
    """Parse YYYY-MM-DD or full ISO 8601 (with optional timezone) into datetime."""
    # Accept "2025-04-24", "2025-04-24T10:30", "2025-04-24T10:30:00-04:00".
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        trade_date: Union[str, datetime],
        trading_style: str = "swing",
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph.

        For swing mode, `trade_date` is a YYYY-MM-DD string and intraday
        fields stay empty. For daytrade mode, `trade_date` may be either a
        date string or a full ISO datetime; session context is resolved and
        the bar-loading date may walk back to the previous business day if
        called outside RTH.
        """
        state: Dict[str, Any] = {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "trade_date": "",
            "trade_datetime": "",
            "session_phase": "",
            "minutes_to_close": 0,
            "data_session_date": "",
            "intraday_decisions": [],
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
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
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            "analysis_brief": {},
        }

        if trading_style == "daytrade":
            dt = trade_date if isinstance(trade_date, datetime) else _parse_dt(str(trade_date))
            ctx = resolve_session_context(dt)
            state.update(ctx.as_state_dict())
            # Keep trade_date populated as the data session's date so legacy
            # analysts (news, etc.) selected alongside intraday still work.
            state["trade_date"] = ctx.data_session_date
        else:
            state["trade_date"] = str(trade_date)

        return state

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            callbacks: Optional list of callback handlers for tool execution tracking.
                       Note: LLM callbacks are handled separately via LLM constructor.
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
