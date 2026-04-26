from tradingagents.agents.utils.agent_utils import (
    build_analysis_brief,
    cap_debate_history,
    get_context_cfg,
)


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

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

        prompt = f"""As the Aggressive Risk Analyst, your role is to actively champion high-reward, high-risk opportunities, emphasizing bold strategies and competitive advantages. When evaluating the trader's decision or plan, focus intently on the potential upside, growth potential, and innovative benefits—even when these come with elevated risk. Use the provided market data and sentiment analysis to strengthen your arguments and challenge the opposing views. Specifically, respond directly to each point made by the conservative and neutral analysts, countering with data-driven rebuttals and persuasive reasoning. Highlight where their caution might miss critical opportunities or where their assumptions may be overly conservative. Here is the trader's decision:

{trader_decision}

Your task is to create a compelling case for the trader's decision by questioning and critiquing the conservative and neutral stances to demonstrate why your high-reward perspective offers the best path forward. Incorporate insights from the following sources into your arguments:

{context_block}
Here is the current conversation history: {history_block} Here are the last arguments from the conservative analyst: {current_conservative_response} Here are the last arguments from the neutral analyst: {current_neutral_response}. If there are no responses from the other viewpoints yet, present your own argument based on the available data.

Engage actively by addressing any specific concerns raised, refuting the weaknesses in their logic, and asserting the benefits of risk-taking to outpace market norms. Maintain a focus on debating and persuading, not just presenting data. Challenge each counterpoint to underscore why a high-risk approach is optimal. Output conversationally as if you are speaking without any special formatting."""

        response = llm.invoke(prompt)
        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": current_conservative_response,
            "current_neutral_response": risk_debate_state.get("current_neutral_response", ""),
            "count": risk_debate_state["count"] + 1,
        }

        update = {"risk_debate_state": new_risk_debate_state}
        if mode == "compact" and state_brief:
            update["analysis_brief"] = state_brief
        return update

    return aggressive_node
