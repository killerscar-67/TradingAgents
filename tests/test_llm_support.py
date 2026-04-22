import unittest

from tradingagents.agents.utils.llm_support import (
    annotate_order_intent_with_support,
    build_post_trade_attribution,
    build_pre_trade_brief,
    watch_anomalies,
)


class _Response:
    def __init__(self, content):
        self.content = content


class _LLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, _messages):
        return _Response(self.content)


class _DictContentLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, _messages):
        return _Response(self.content)


class _FailLLM:
    def invoke(self, _messages):
        raise RuntimeError("provider unavailable")


class LLMSupportTests(unittest.TestCase):
    def test_pre_trade_brief_returns_structured_nonblocking_payload(self):
        brief = build_pre_trade_brief(
            _LLM('{"summary":"earnings risk","catalysts":["earnings"],"event_risks":["gap risk"]}'),
            {"symbol": "AAPL", "trade_date": "2026-04-21"},
        )

        self.assertEqual(brief.summary, "earnings risk")
        self.assertEqual(brief.catalysts, ("earnings",))
        self.assertEqual(brief.event_risks, ("gap risk",))
        self.assertFalse(brief.blocking)
        self.assertIsNone(brief.error)

    def test_pre_trade_brief_contains_malformed_output_without_blocking(self):
        brief = build_pre_trade_brief(_LLM("not json"), {"symbol": "AAPL"})

        self.assertEqual(brief.summary, "")
        self.assertEqual(brief.catalysts, ())
        self.assertFalse(brief.blocking)
        self.assertIn("malformed", brief.error)

    def test_anomaly_watcher_emits_only_binary_flags(self):
        result = watch_anomalies(
            _LLM('{"flags":{"event_risk":"yes","liquidity_risk":1,"data_quality_risk":false},"summary":"watch"}'),
            {"symbol": "AAPL"},
        )

        self.assertEqual(
            result.flags,
            {
                "event_risk": False,
                "liquidity_risk": False,
                "data_quality_risk": False,
                "news_risk": False,
            },
        )
        self.assertTrue(all(type(value) is bool for value in result.flags.values()))
        self.assertIn("non-binary", result.error)

    def test_anomaly_flags_are_immutable_after_construction(self):
        result = watch_anomalies(
            _LLM('{"flags":{"event_risk":true},"summary":"watch"}'),
            {"symbol": "AAPL"},
        )

        with self.assertRaises(TypeError):
            result.flags["event_risk"] = False

    def test_provider_dict_content_is_accepted(self):
        brief = build_pre_trade_brief(
            _DictContentLLM({"summary": "parsed", "catalysts": ["filing"]}),
            {"symbol": "AAPL"},
        )

        self.assertEqual(brief.summary, "parsed")
        self.assertEqual(brief.catalysts, ("filing",))
        self.assertIsNone(brief.error)

    def test_post_trade_attribution_is_fire_and_forget_on_provider_error(self):
        attribution = build_post_trade_attribution(_FailLLM(), {"symbol": "AAPL"})

        self.assertEqual(attribution.summary, "")
        self.assertEqual(attribution.factors, ())
        self.assertEqual(attribution.lessons, ())
        self.assertFalse(attribution.blocking)
        self.assertIn("provider unavailable", attribution.error)

    def test_support_annotation_does_not_modify_execution_fields(self):
        order_intent = {
            "symbol": "AAPL",
            "trade_date": "2026-04-21",
            "rating": "BUY",
            "blocked": False,
            "reason": "",
            "annotations": {"risk": {"gate": {"allowed": True}}},
        }
        brief = build_pre_trade_brief(_LLM('{"summary":"ok"}'), {"symbol": "AAPL"})

        annotated = annotate_order_intent_with_support(order_intent, pre_trade_brief=brief)

        self.assertIsNot(annotated, order_intent)
        self.assertEqual(annotated["rating"], "BUY")
        self.assertFalse(annotated["blocked"])
        self.assertEqual(annotated["reason"], "")
        self.assertEqual(order_intent["annotations"], {"risk": {"gate": {"allowed": True}}})
        self.assertIn("risk", annotated["annotations"])
        self.assertEqual(annotated["annotations"]["risk"], {"gate": {"allowed": True}})
        self.assertIn("llm_support", annotated["annotations"])


if __name__ == "__main__":
    unittest.main()
