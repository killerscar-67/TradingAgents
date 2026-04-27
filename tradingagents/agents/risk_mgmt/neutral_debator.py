from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    cap_debate_history,
    get_context_cfg,
)


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")
        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        trader_decision = state["trader_investment_plan"]

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
                f"Market Research Report: {market_research_report}\n"
                f"Social Media Sentiment Report: {sentiment_report}\n"
                f"Latest World Affairs Report: {news_report}\n"
                f"Company Fundamentals Report: {fundamentals_report}"
            )
            history_block = history

        prompt = f"""As the Neutral Risk Analyst, your role is to provide a balanced perspective, weighing both the potential benefits and risks of the trader's decision or plan. You prioritize a well-rounded approach, evaluating the upsides and downsides while factoring in broader market trends, potential economic shifts, and diversification strategies. Here is the trader's decision:

{trader_decision}

Your task is to challenge both the Aggressive and Conservative Analysts, pointing out where each perspective may be overly optimistic or overly cautious. Use insights from the following data sources to support a moderate, sustainable strategy to adjust the trader's decision:

{context_block}
Here is the current conversation history: {history_block} Here is the last response from the aggressive analyst: {current_aggressive_response} Here is the last response from the conservative analyst: {current_conservative_response}. If there are no responses from the other viewpoints yet, present your own argument based on the available data.

Engage actively by analyzing both sides critically, addressing weaknesses in the aggressive and conservative arguments to advocate for a more balanced approach. Challenge each of their points to illustrate why a moderate risk strategy might offer the best of both worlds. Focus on debating rather than simply presenting data, aiming to show that a balanced view can lead to the most reliable outcomes. Output conversationally as if you are speaking without any special formatting."""

        response = llm.invoke(prompt)
        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": current_aggressive_response,
            "current_conservative_response": current_conservative_response,
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        update = {"risk_debate_state": new_risk_debate_state}
        if mode == "compact" and state_brief:
            update["analysis_brief"] = state_brief
        return update

    return neutral_node
