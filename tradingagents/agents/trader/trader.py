import functools

from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    build_instrument_context,
    get_context_cfg,
)


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        ctx = get_context_cfg()
        mode = ctx["mode"]
        state_brief = state.get("analysis_brief") or {}
        if mode == "compact" and not state_brief:
            state_brief = build_analysis_brief(
                market_research_report, sentiment_report, news_report, fundamentals_report,
                max_chars=ctx["brief_max_chars"],
            )

        if mode == "compact":
            analysis_block = (
                f"\nAnalysis Summary:\n"
                f"Market: {state_brief['market']}\n"
                f"Sentiment: {state_brief['sentiment']}\n"
                f"News: {state_brief['news']}\n"
                f"Fundamentals: {state_brief['fundamentals']}\n"
            )
        else:
            analysis_block = ""

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        past_memory_str = (
            "".join(rec["recommendation"] + "\n\n" for rec in past_memories)
            if past_memories
            else "No past memories found."
        )

        context = {
            "role": "user",
            "content": (
                f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. "
                f"{instrument_context} This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. "
                f"Use this plan as a foundation for evaluating your next trading decision.\n\n"
                f"Proposed Investment Plan: {investment_plan}{analysis_block}\n"
                "Leverage these insights to make an informed and strategic decision."
            ),
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "End with a firm decision and always conclude your response with "
                    "'FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**' to confirm your recommendation. "
                    f"Apply lessons from past decisions to strengthen your analysis. "
                    f"Here are reflections from similar situations you traded in and the lessons learned: {past_memory_str}"
                ),
            },
            context,
        ]

        result = llm.invoke(messages)

        update = {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }
        if mode == "compact" and state_brief:
            update["analysis_brief"] = state_brief
        return update

    return functools.partial(trader_node, name="Trader")
