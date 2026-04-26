import unittest
import warnings
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI
from openai import APIConnectionError

from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI


class OpenAIClientTests(unittest.TestCase):
    def test_connection_error_returns_conservative_hold_message(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        error = APIConnectionError(request=request)
        llm = NormalizedChatOpenAI(model="gpt-5.4", api_key="test-key")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with patch.object(ChatOpenAI, "invoke", side_effect=error):
                response = llm.invoke("decide")

        self.assertIn("HOLD", response.content)
        self.assertIn("LLM provider connection error", response.content)
        self.assertEqual(len(caught), 1)
        self.assertIn("connection error", str(caught[0].message))


if __name__ == "__main__":
    unittest.main()
