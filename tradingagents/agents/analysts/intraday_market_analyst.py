"""IntradayMarketAnalyst — produces structured day-trade setups.

Differences from the swing market_analyst:
  - Operates on intraday OHLCV (5m/15m/etc.) and intraday indicators.
  - Forbidden from referencing swing-horizon tools (200 SMA, quarterly fundamentals).
  - Aware of session phase, minutes-to-close, and the requested timestamp.
  - Output schema enforced via prompt: setup_name, bias, entry, stop, target1,
    target2, time_stop, confidence, invalidation, rationale.
  - Supports multi-variant runs for A/B testing: each variant in
    config["intraday_prompt_variants"] produces one decision; the first flows
    into the trader/risk graph, the rest are journal-only.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
    run_analyst_loop,
)
from tradingagents.agents.utils.intraday_tools import (
    get_intraday_indicators,
    get_intraday_stock_data,
    get_session_context,
)
from tradingagents.dataflows.config import get_config


_DECISION_SCHEMA_FIELDS = [
    "setup_name", "bias", "entry", "stop", "target1", "target2",
    "time_stop", "confidence", "invalidation", "rationale",
]


_BASE_INTRADAY_PROMPT = """You are an intraday day-trading assistant. Your job is to identify ONE
high-quality intraday setup using the tools available, or explicitly call no-trade.

You may use ONLY these intraday indicators: vwap, orb_high_5, orb_low_5,
orb_high_15, orb_low_15, orb_high_30, orb_low_30, rel_volume, fast_rsi_7,
fast_stoch_k, fast_stoch_d, fast_macd, fast_macd_signal, fast_macd_hist,
keltner_upper, keltner_lower, session_atr, gap_percent.

You may also call get_session_context(when) to confirm the session phase,
minutes-to-close, and the data session date if uncertain.

DO NOT reference 50/200 SMA, quarterly fundamentals, or any horizon longer
than the current session. Those signals do not move 5-minute bars.

Playbooks to consider (pick one):
  - VWAP reclaim/rejection
  - Opening Range Breakout (ORB) with relative volume confirmation
  - Mean reversion to VWAP on range days
  - Trend continuation on power-hour drives
  - No trade (when setup quality is low or session phase is unfavorable)

Process:
1. Call get_intraday_stock_data once for the current session (interval={interval}).
2. Call get_intraday_indicators for 3-6 indicators relevant to your chosen playbook.
3. Synthesize a setup with concrete price levels.

Output: After your analysis text, append a fenced JSON block with EXACTLY
these keys (use null for fields that don't apply when bias == "no_trade"):

```json
{{
  "setup_name": "vwap_reclaim | orb_breakout | mean_reversion_vwap | power_hour_continuation | no_trade",
  "bias": "long | short | no_trade",
  "entry": 0.0,
  "stop": 0.0,
  "target1": 0.0,
  "target2": 0.0,
  "time_stop": "HH:MM ET cutoff for the trade",
  "confidence": "low | medium | high",
  "invalidation": "what specifically would void this setup",
  "rationale": "1-3 sentence summary"
}}
```
"""


_VARIANT_DIRECTIVES = {
    "default": "",
    "aggressive": (
        "\nYou are the AGGRESSIVE variant: prefer breakout/momentum setups over "
        "mean-reversion when in doubt. Tighter stops, larger targets."
    ),
    "conservative": (
        "\nYou are the CONSERVATIVE variant: require rel_volume > 1.3 and "
        "alignment between fast_macd and VWAP slope before signaling a trade. "
        "Default to no_trade when ambiguous."
    ),
}


def _extract_decision(text: str) -> Dict[str, Any]:
    """Pull the JSON block out of the analyst's response. Best-effort.

    Returns a dict with all _DECISION_SCHEMA_FIELDS (None for missing). The
    raw response is preserved separately so the journal always has a fallback.
    """
    decision: Dict[str, Any] = {k: None for k in _DECISION_SCHEMA_FIELDS}
    if not text:
        return decision

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else None
    if payload is None:
        # Fallback: greedy match on the largest balanced-looking JSON object.
        loose = re.search(r"\{[^{}]*\"setup_name\"[^{}]*\}", text, re.DOTALL)
        payload = loose.group(0) if loose else None
    if payload is None:
        return decision

    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError):
        return decision

    for k in _DECISION_SCHEMA_FIELDS:
        if k in parsed:
            decision[k] = parsed[k]
    return decision


def create_intraday_market_analyst(llm):
    """Factory mirroring create_market_analyst.

    Reads `intraday_prompt_variants` from config to decide how many decisions
    to produce. The first variant's narrative becomes `market_report` (so the
    rest of the graph sees something familiar); all variants are stored as
    structured decisions in `state["intraday_decisions"]` for journaling.
    """

    def intraday_market_analyst_node(state):
        config = get_config()
        interval = config.get("intraday_interval", "5m")
        variants: List[str] = config.get("intraday_prompt_variants", ["default"]) or ["default"]

        instrument_context = build_instrument_context(state["company_of_interest"])
        session_date = state.get("data_session_date") or state.get("trade_date")
        session_phase = state.get("session_phase", "unknown")
        minutes_left = state.get("minutes_to_close", 0)
        requested_dt = state.get("trade_datetime") or state.get("trade_date")

        tools = [get_intraday_stock_data, get_intraday_indicators, get_session_context]

        decisions: List[Dict[str, Any]] = []
        primary_report = ""

        for variant in variants:
            directive = _VARIANT_DIRECTIVES.get(variant, _VARIANT_DIRECTIVES["default"])
            system_message = (
                _BASE_INTRADAY_PROMPT.format(interval=interval)
                + directive
                + get_language_instruction()
            )

            session_brief = (
                f"Session date for bars: {session_date}. "
                f"Requested moment: {requested_dt}. "
                f"Session phase: {session_phase}. "
                f"Minutes to close: {minutes_left}."
            )
            if state.get("session_phase") in ("premarket", "postmarket", "closed"):
                session_brief += (
                    " NOTE: Outside regular trading hours. Use prior-session bars to "
                    "frame a setup for the next open, or signal no_trade."
                )

            prompt = ChatPromptTemplate.from_messages([
                (
                    "system",
                    "You are an intraday trading assistant. Produce ONE setup per call."
                    " You have access to the following tools: {tool_names}.\n{system_message}\n"
                    "{instrument_context}\n{session_brief}\n"
                    "Variant: {variant_name}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ])
            prompt = prompt.partial(system_message=system_message)
            prompt = prompt.partial(tool_names=", ".join(t.name for t in tools))
            prompt = prompt.partial(instrument_context=instrument_context)
            prompt = prompt.partial(session_brief=session_brief)
            prompt = prompt.partial(variant_name=variant)

            chain = prompt | llm.bind_tools(tools)
            text = run_analyst_loop(chain, tools)

            decision = _extract_decision(text if isinstance(text, str) else "")
            decision["variant"] = variant
            decision["raw"] = text if isinstance(text, str) else str(text)
            decisions.append(decision)

            if not primary_report:
                primary_report = decision["raw"]

        return {
            "market_report": primary_report,
            "intraday_decisions": decisions,
        }

    return intraday_market_analyst_node
