
from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    build_instrument_context,
    cap_debate_history,
    get_context_cfg,
)


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        past_memory_str = "".join(rec["recommendation"] + "\n\n" for rec in past_memories)

        ctx = get_context_cfg()
        mode = ctx["mode"]
        state_brief = state.get("analysis_brief") or {}
        if mode == "compact":
            if not state_brief:
                state_brief = build_analysis_brief(
                    market_research_report,
                    sentiment_report,
                    news_report,
                    fundamentals_report,
                    max_chars=ctx["brief_max_chars"],
                )
            history_section = cap_debate_history(
                history,
                max_chars=ctx["debate_max_chars"],
                preserve_latest_chars=ctx["debate_preserve_chars"],
            )
            analysis_block = (
                "\n**Analysis Summary:**\n"
                f"Market: {state_brief['market']}\n"
                f"Sentiment: {state_brief['sentiment']}\n"
                f"News: {state_brief['news']}\n"
                f"Fundamentals: {state_brief['fundamentals']}\n"
            )
        else:
            history_section = history
            analysis_block = ""

        prompt = f"""As the portfolio manager and debate facilitator, your role is to critically evaluate this round of debate and make a definitive decision: align with the bear analyst, the bull analyst, or choose Hold only if it is strongly justified based on the arguments presented.

Summarize the key points from both sides concisely, focusing on the most compelling evidence or reasoning. Your recommendation—Buy, Sell, or Hold—must be clear and actionable. Avoid defaulting to Hold simply because both sides have valid points; commit to a stance grounded in the debate's strongest arguments.

Additionally, develop a detailed investment plan for the trader. This should include:

Your Recommendation: A decisive stance supported by the most convincing arguments.
Rationale: An explanation of why these arguments lead to your conclusion.
Strategic Actions: Concrete steps for implementing the recommendation.
Take into account your past mistakes on similar situations. Use these insights to refine your decision-making and ensure you are learning and improving. Present your analysis conversationally, as if speaking naturally, without special formatting.

Here are your past reflections on mistakes:
\"{past_memory_str}\"

{instrument_context}
{analysis_block}
Here is the debate:
Debate History:
{history_section}"""
        response = llm.invoke(prompt)

        new_investment_debate_state = {
            "judge_decision": response.content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": response.content,
            "count": investment_debate_state["count"],
        }

        update = {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": response.content,
        }
        if mode == "compact" and state_brief:
            update["analysis_brief"] = state_brief
        return update

    return research_manager_node
