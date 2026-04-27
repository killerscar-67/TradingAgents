from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    build_instrument_context,
    cap_debate_history,
    get_context_cfg,
    get_language_instruction,
)


def create_portfolio_manager(llm, memory):
    def portfolio_manager_node(state) -> dict:

        instrument_context = build_instrument_context(state["company_of_interest"])

        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state["history"]

        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        ctx = get_context_cfg()
        mode = ctx["mode"]
        state_brief = state.get("analysis_brief") or {}
        if mode == "compact" and not state_brief:
            state_brief = build_analysis_brief(
                market_research_report, sentiment_report, news_report, fundamentals_report,
                max_chars=ctx["brief_max_chars"],
            )

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        past_memory_str = "".join(rec["recommendation"] + "\n\n" for rec in past_memories)

        if mode == "compact":
            analysis_block = (
                f"\n**Analysis Summary:**\n"
                f"Market: {state_brief['market']}\n"
                f"Sentiment: {state_brief['sentiment']}\n"
                f"News: {state_brief['news']}\n"
                f"Fundamentals: {state_brief['fundamentals']}\n"
            )
            history_section = cap_debate_history(
                history,
                max_chars=ctx["debate_max_chars"],
                preserve_latest_chars=ctx["debate_preserve_chars"],
            )
        else:
            analysis_block = ""
            history_section = history

        prompt = f"""As the Portfolio Manager, synthesize the risk analysts' debate and deliver the final trading decision.

{instrument_context}

---

**Rating Scale** (use exactly one):
- **Buy**: Strong conviction to enter or add to position
- **Overweight**: Favorable outlook, gradually increase exposure
- **Hold**: Maintain current position, no action needed
- **Underweight**: Reduce exposure, take partial profits
- **Sell**: Exit position or avoid entry

**Context:**
- Research Manager's investment plan: **{research_plan}**
- Trader's transaction proposal: **{trader_plan}**
- Lessons from past decisions: **{past_memory_str}**{analysis_block}
**Required Output Structure:**
1. **Rating**: State one of Buy / Overweight / Hold / Underweight / Sell.
2. **Executive Summary**: A concise action plan covering entry strategy, position sizing, key risk levels, and time horizon.
3. **Investment Thesis**: Detailed reasoning anchored in the analysts' debate and past reflections.

---

**Risk Analysts Debate History:**
{history_section}

---

Be decisive and ground every conclusion in specific evidence from the analysts.{get_language_instruction()}"""

        response = llm.invoke(prompt)

        new_risk_debate_state = {
            "judge_decision": response.content,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        update = {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": response.content,
        }
        if mode == "compact" and state_brief:
            update["analysis_brief"] = state_brief
        return update

    return portfolio_manager_node
