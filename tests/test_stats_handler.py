import unittest
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from cli.stats_handler import StatsCallbackHandler


def _response(input_tokens: int, output_tokens: int) -> LLMResult:
    return LLMResult(
        generations=[[
            ChatGeneration(
                message=AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    },
                )
            )
        ]]
    )


class StatsHandlerTests(unittest.TestCase):
    def test_infers_stage_labels_and_respects_explicit_stage(self):
        handler = StatsCallbackHandler()

        cases = [
            ("Market Analyst", {}, "analyst"),
            ("Research Manager", {}, "research"),
            ("Trader", {}, "trader"),
            ("Neutral Analyst", {}, "risk"),
            ("Portfolio Manager", {}, "portfolio"),
            ("Unmapped Agent", {}, "unknown"),
            ("Anything", {"stage": "Risk Team"}, "risk_team"),
        ]

        for agent_name, metadata, expected in cases:
            with self.subTest(agent_name=agent_name, metadata=metadata):
                self.assertEqual(handler._infer_stage(agent_name, metadata), expected)

    def test_tracks_llm_tokens_per_agent_and_stage(self):
        handler = StatsCallbackHandler()
        run_id = uuid4()

        handler.on_chat_model_start(
            {"name": "ChatOpenAI"},
            [[("human", "prompt")]],
            run_id=run_id,
            metadata={"langgraph_node": "Research Manager"},
        )
        handler.on_llm_end(_response(120, 45), run_id=run_id)

        stats = handler.get_stats()

        self.assertEqual(stats["llm_calls"], 1)
        self.assertEqual(stats["tokens_in"], 120)
        self.assertEqual(stats["tokens_out"], 45)
        self.assertEqual(stats["per_agent"]["Research Manager"]["llm_calls"], 1)
        self.assertEqual(stats["per_agent"]["Research Manager"]["tokens_in"], 120)
        self.assertEqual(stats["per_stage"]["research"]["tokens_out"], 45)

    def test_accumulates_multiple_calls_and_falls_back_to_unknown_scope(self):
        handler = StatsCallbackHandler()
        known_run = uuid4()

        handler.on_chat_model_start(
            {"name": "ChatOpenAI"},
            [[("human", "prompt")]],
            run_id=known_run,
            metadata={"langgraph_node": "Research Manager"},
        )
        handler.on_llm_end(_response(120, 45), run_id=known_run)
        handler.on_llm_end(_response(30, 10), run_id=uuid4())

        stats = handler.get_stats()

        self.assertEqual(stats["llm_calls"], 1)
        self.assertEqual(stats["tokens_in"], 150)
        self.assertEqual(stats["tokens_out"], 55)
        self.assertEqual(stats["per_stage"]["research"]["tokens_in"], 120)
        self.assertEqual(stats["per_agent"]["unknown"]["tokens_in"], 30)
        self.assertEqual(stats["per_stage"]["unknown"]["tokens_out"], 10)

    def test_tracks_tool_calls_per_agent_and_stage_from_tags(self):
        handler = StatsCallbackHandler()

        handler.on_tool_start(
            {"name": "get_news"},
            "{}",
            tags=["langgraph_node:Market Analyst"],
        )

        stats = handler.get_stats()

        self.assertEqual(stats["tool_calls"], 1)
        self.assertEqual(stats["per_agent"]["Market Analyst"]["tool_calls"], 1)
        self.assertEqual(stats["per_stage"]["analyst"]["tool_calls"], 1)

    def test_llm_error_clears_pending_scope(self):
        handler = StatsCallbackHandler()
        run_id = uuid4()

        handler.on_chat_model_start(
            {"name": "ChatOpenAI"},
            [[("human", "prompt")]],
            run_id=run_id,
            metadata={"langgraph_node": "Trader"},
        )

        self.assertIn(str(run_id), handler._pending_scopes)

        handler.on_llm_error(RuntimeError("boom"), run_id=run_id)

        self.assertNotIn(str(run_id), handler._pending_scopes)


if __name__ == "__main__":
    unittest.main()