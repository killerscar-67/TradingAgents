# TradingAgents/graph/signal_processing.py

import re
from typing import Any

from tradingagents.quant.contracts import ExecutionMode, TradeRating, parse_execution_mode, rating_from_text


class SignalProcessor:
    """Processes trading signals to extract actionable decisions."""

    def __init__(self, quick_thinking_llm: Any):
        """Initialize with an LLM for processing."""
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str, execution_mode: ExecutionMode = "llm_assisted") -> str:
        """
        Process a full trading signal to extract the core decision.

        Args:
            full_signal: Complete trading signal text

        Returns:
            Extracted rating (BUY, OVERWEIGHT, HOLD, UNDERWEIGHT, or SELL)
        """
        mode = parse_execution_mode(execution_mode)
        if mode == "quant_strict":
            raise RuntimeError(
                "process_signal must not be used for execution in quant_strict mode; "
                "use build_order_intent with a QuantSignalContract instead."
            )

        messages = [
            (
                "system",
                "You are an efficient assistant that extracts the trading decision from analyst reports. "
                "Extract the rating as exactly one of: BUY, OVERWEIGHT, HOLD, UNDERWEIGHT, SELL. "
                "Output only the single rating word, nothing else.",
            ),
            ("human", full_signal),
        ]
        llm_output = self.quick_thinking_llm.invoke(messages).content
        try:
            return TradeRating(str(llm_output).strip().upper()).value
        except ValueError:
            output_text = str(llm_output)
            if not re.search(r"\b(BUY|OVERWEIGHT|HOLD|UNDERWEIGHT|SELL)\b", output_text.upper()):
                raise ValueError("LLM output did not contain a valid trade rating")
            return rating_from_text(output_text).value
