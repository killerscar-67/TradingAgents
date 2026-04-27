from concurrent.futures import ThreadPoolExecutor
from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.quant_tools import (
    get_quant_signals
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


_HISTORY_MARKER = "\n…[history truncated]…\n"


def cap_debate_history(
    history: str,
    max_chars: int = 2000,
    preserve_latest_chars: int = 600,
) -> str:
    """Keep the tail of debate history within max_chars.

    Preserves the most-recent preserve_latest_chars verbatim, then fills any
    remaining budget with the earliest content (separated by a gap marker).
    The returned string is always at most ``max_chars`` characters: when the
    caller passes a preserve budget greater than ``max_chars`` we clamp it so
    the result still respects the cap.
    """
    if not history or len(history) <= max_chars:
        return history
    marker_len = len(_HISTORY_MARKER)
    # Reserve room for the marker; clamp the tail budget so head+marker+tail
    # cannot exceed max_chars even when preserve_latest_chars is huge.
    preserve = max(0, min(preserve_latest_chars, max_chars - marker_len))
    tail = history[-preserve:] if preserve else ""
    head_budget = max_chars - preserve - marker_len
    if head_budget > 0:
        head = history[:head_budget].rstrip()
        return head + _HISTORY_MARKER + tail
    return _HISTORY_MARKER.lstrip() + tail

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


        


# ---------------------------------------------------------------------------
# Self-contained ReAct loop for analyst nodes.
# Replaces the previous LangGraph tool-node round-trip pattern, so analysts no
# longer share the state["messages"] field and can run concurrently from a
# single parallel-analyst graph node.
# ---------------------------------------------------------------------------

ANALYST_LOOP_MAX_ITERATIONS = 12


def run_analyst_loop(chain, tools, initial_message: str = "Begin your analysis."):
    """Run an analyst's ReAct tool-calling loop with a private message list.

    Returns the final assistant text. Tool failures are surfaced to the LLM as
    ToolMessage content so it can recover or proceed.
    """
    tools_by_name = {t.name: t for t in tools}
    messages = [HumanMessage(content=initial_message)]

    for _ in range(ANALYST_LOOP_MAX_ITERATIONS):
        result = chain.invoke(messages)
        messages.append(result)
        tool_calls = getattr(result, "tool_calls", None) or []
        if not tool_calls:
            return result.content or ""
        for tc in tool_calls:
            tool = tools_by_name.get(tc["name"])
            if tool is None:
                messages.append(ToolMessage(
                    content=f"Tool '{tc['name']}' is not available.",
                    tool_call_id=tc["id"],
                ))
                continue
            try:
                output = tool.invoke(tc["args"])
            except Exception as exc:  # noqa: BLE001 - surface to LLM
                output = f"Error from {tc['name']}: {exc}"
            messages.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))

    return getattr(messages[-1], "content", "") or ""


def create_parallel_analysts_node(analyst_nodes: dict):
    """Wrap multiple analyst node functions into one parallel LangGraph node.

    Each underlying analyst runs in its own thread (LLM/tool calls are I/O
    bound, so the GIL is released). Each writes to a distinct ``*_report``
    state field, so update merging is conflict-free.
    """
    if not analyst_nodes:
        raise ValueError("create_parallel_analysts_node requires at least one analyst")

    def parallel_node(state):
        if len(analyst_nodes) == 1:
            (only_node,) = analyst_nodes.values()
            return only_node(state)

        merged: dict = {}
        sources: dict = {}  # state-key -> first analyst that wrote it
        with ThreadPoolExecutor(max_workers=len(analyst_nodes)) as executor:
            futures = {
                name: executor.submit(node, state)
                for name, node in analyst_nodes.items()
            }
            for name, future in futures.items():
                try:
                    update = future.result()
                except Exception as exc:  # noqa: BLE001 - keep partial results
                    update = {f"{name}_report": f"[{name} analyst failed: {exc}]"}
                if not update:
                    continue
                for key in update:
                    if key in sources:
                        # Two analysts writing the same state field would
                        # silently drop one. setup_graph already rejects
                        # known collisions (e.g. market + intraday_market);
                        # surface anything else loudly.
                        raise RuntimeError(
                            f"Parallel analyst '{name}' writes state field "
                            f"'{key}' already produced by analyst "
                            f"'{sources[key]}'. Either pick non-overlapping "
                            f"analysts or namespace the output."
                        )
                    sources[key] = name
                merged.update(update)
        return merged

    return parallel_node
