from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    cap_debate_history,
    get_context_cfg,
)


def create_bear_researcher(llm, memory):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")
        current_response = investment_debate_state.get("current_response", "")

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
            context_block = (
                f"Market: {state_brief['market']}\n"
                f"Sentiment: {state_brief['sentiment']}\n"
                f"News: {state_brief['news']}\n"
                f"Fundamentals: {state_brief['fundamentals']}"
            )
            history_block = cap_debate_history(
                history,
                max_chars=ctx["debate_max_chars"],
                preserve_latest_chars=ctx["debate_preserve_chars"],
            )
        else:
            context_block = (
                f"Market research report: {market_research_report}\n"
                f"Social media sentiment report: {sentiment_report}\n"
                f"Latest world affairs news: {news_report}\n"
                f"Company fundamentals report: {fundamentals_report}"
            )
            history_block = history

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        past_memory_str = "".join(rec["recommendation"] + "\n\n" for rec in past_memories)

        prompt = f"""You are a Bear Analyst making the case against investing in the stock. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:
- Risks and Challenges: Highlight market saturation, financial instability, or macroeconomic threats.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news.
- Bull Counterpoints: Critically analyze the bull argument, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument conversationally, directly engaging with the bull analyst's points.

Resources available:
{context_block}
Conversation history of the debate: {history_block}
Last bull argument: {current_response}
Reflections from similar situations and lessons learned: {past_memory_str}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate. You must also address reflections and learn from lessons and mistakes you made in the past.
"""

        response = llm.invoke(prompt)
        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        update = {"investment_debate_state": new_investment_debate_state}
        if mode == "compact" and state_brief:
            update["analysis_brief"] = state_brief
        return update

    return bear_node
