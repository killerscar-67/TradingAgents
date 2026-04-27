from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )


def get_context_mode() -> str:
    """Return the configured context mode: 'compact' or 'full'."""
    from tradingagents.dataflows.config import get_config
    return get_config().get("context_mode", "compact")


def get_context_cfg() -> dict:
    """Return all compact-context tuning values from config in one call."""
    from tradingagents.dataflows.config import get_config
    cfg = get_config()
    return {
        "mode": cfg.get("context_mode", "compact"),
        "brief_max_chars": int(cfg.get("brief_max_chars", 400)),
        "debate_max_chars": int(cfg.get("debate_max_chars", 2000)),
        "debate_preserve_chars": int(cfg.get("debate_preserve_chars", 600)),
    }


def extract_brief(report: str, max_chars: int = 400) -> str:
    """Truncate a report to max_chars, appending ellipsis if cut."""
    if not report:
        return ""
    report = report.strip()
    if len(report) <= max_chars:
        return report
    return report[:max_chars].rstrip() + "…"


def build_analysis_brief(
    market: str,
    sentiment: str,
    news: str,
    fundamentals: str,
    max_chars: int = 400,
) -> dict:
    """Build compact brief dict keyed by report type."""
    return {
        "market": extract_brief(market, max_chars),
        "sentiment": extract_brief(sentiment, max_chars),
        "news": extract_brief(news, max_chars),
        "fundamentals": extract_brief(fundamentals, max_chars),
    }


def cap_debate_history(
    history: str,
    max_chars: int = 2000,
    preserve_latest_chars: int = 600,
) -> str:
    """Keep the tail of debate history within max_chars.

    Preserves the most-recent preserve_latest_chars verbatim, then fills
    remaining budget with the earliest content (separated by a gap marker).
    """
    if not history or len(history) <= max_chars:
        return history
    tail = history[-preserve_latest_chars:]
    head_budget = max_chars - preserve_latest_chars - 40  # room for marker
    if head_budget > 0:
        head = history[:head_budget].rstrip()
        return head + "\n…[history truncated]…\n" + tail
    return "…[history truncated]…\n" + tail


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
