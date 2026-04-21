import unittest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.graph.signal_processing import SignalProcessor
from tradingagents.quant.contracts import (
    EntryEngine,
    EntrySignal,
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

    def test_build_order_intent_blocks_when_kill_switch_is_active(self):
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.execution_mode = "quant_strict"
        graph.config = {}

        quant_contract = QuantSignalContract.from_raw(
            "AAPL",
            "2026-04-21",
            {"signal": "buy", "score": 0.9, "summary": "ok"},
        )

        intent = TradingAgentsGraph.build_order_intent(
            graph,
            "AAPL",
            "2026-04-21",
            "ignored",
            quant_contract=quant_contract,
            risk_context={
                "entry_signal": EntrySignal(
                    engine=EntryEngine.BREAKOUT,
                    direction="long",
                    strength=0.8,
                    reason="test",
                ),
                "entry_price": 100.0,
                "atr_15m": 1.0,
                "account_equity": 100_000.0,
                "current_exposure": 0.0,
                "daily_loss_state": {
                    "date": "2026-04-21",
                    "net_pnl": -3_500.0,
                    "kill_switch": True,
                    "trade_count": 3,
                },
            },
        )

        self.assertTrue(intent["blocked"])
        self.assertIn("kill switch", intent["reason"])
        self.assertTrue(intent["annotations"]["risk"]["gate"]["kill_switch"])

    def test_build_order_intent_blocks_when_exposure_cap_is_exceeded(self):
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.execution_mode = "quant_strict"
        graph.config = {}

        quant_contract = QuantSignalContract.from_raw(
            "AAPL",
            "2026-04-21",
            {"signal": "buy", "score": 0.9, "summary": "ok"},
        )

        intent = TradingAgentsGraph.build_order_intent(
            graph,
            "AAPL",
            "2026-04-21",
            "ignored",
            quant_contract=quant_contract,
            risk_context={
                "entry_signal": EntrySignal(
                    engine=EntryEngine.BREAKOUT,
                    direction="long",
                    strength=0.8,
                    reason="test",
                ),
                "entry_price": 100.0,
                "atr_15m": 1.0,
                "account_equity": 100_000.0,
                "current_exposure": 15_001.0,
                "daily_loss_state": {
                    "date": "2026-04-21",
                    "net_pnl": 0.0,
                    "kill_switch": False,
                    "trade_count": 0,
                },
            },
        )

        self.assertTrue(intent["blocked"])
        self.assertIn("exposure cap", intent["reason"])
