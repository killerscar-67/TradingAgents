import unittest

from tradingagents.graph.signal_processing import SignalProcessor
from tradingagents.quant.contracts import (
    QuantSignalContract,
    TradeRating,
    parse_execution_mode,
    rating_from_quant_signal,
)


class _DummyLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _messages):
        class _Resp:
            def __init__(self, content: str):
                self.content = content

        return _Resp(self._content)


class _FailLLM:
    def invoke(self, _messages):
        raise AssertionError("LLM should not be called in quant_strict mode")


class ExecutionContractTests(unittest.TestCase):
    def test_quant_signal_contract_parses_payload(self):
        payload = '{"signal":"buy","score":0.7,"confidence":0.6,"summary":"ok"}'
        contract = QuantSignalContract.from_raw("AAPL", "2026-04-21", payload)
        self.assertEqual(contract.signal.value, "buy")
        self.assertEqual(contract.score, 0.7)
        self.assertEqual(contract.confidence, 0.6)

    def test_signal_processor_quant_strict_raises(self):
        processor = SignalProcessor(_FailLLM())
        with self.assertRaises(RuntimeError):
            processor.process_signal("Final decision: SELL", execution_mode="quant_strict")

    def test_signal_processor_llm_assisted_uses_llm(self):
        processor = SignalProcessor(_DummyLLM("BUY"))
        rating = processor.process_signal("ignored", execution_mode="llm_assisted")
        self.assertEqual(rating, TradeRating.BUY.value)

    def test_signal_processor_llm_assisted_raises_on_malformed_output(self):
        processor = SignalProcessor(_DummyLLM("no actionable rating"))
        with self.assertRaises(ValueError):
            processor.process_signal("ignored", execution_mode="llm_assisted")

    def test_signal_processor_llm_assisted_raises_on_ambiguous_output(self):
        processor = SignalProcessor(_DummyLLM("Do not BUY; HOLD"))
        with self.assertRaises(ValueError):
            processor.process_signal("ignored", execution_mode="llm_assisted")

    def test_parse_execution_mode_defaults_to_llm_assisted(self):
        self.assertEqual(parse_execution_mode("invalid-mode"), "llm_assisted")

    def test_rating_from_quant_signal_maps_hold(self):
        contract = QuantSignalContract.from_raw("AAPL", "2026-04-21", {"signal": "hold"})
        self.assertEqual(rating_from_quant_signal(contract.signal), TradeRating.HOLD)

    def test_quant_signal_contract_missing_score_maps_to_negative_infinity(self):
        contract = QuantSignalContract.from_raw("AAPL", "2026-04-21", {"summary": "n/a"})
        self.assertEqual(contract.score, float("-inf"))
