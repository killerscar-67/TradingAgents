import unittest
import warnings

from tradingagents.llm_clients.base_client import BaseLLMClient
from tradingagents.llm_clients.model_catalog import get_known_models
from tradingagents.llm_clients.validators import validate_model


class DummyLLMClient(BaseLLMClient):
    def __init__(self, provider: str, model: str):
        self.provider = provider
        super().__init__(model)
        self._llm = object()

    def get_llm(self):
        self.warn_if_unknown_model()
        return self._llm

    def validate_model(self) -> bool:
        return validate_model(self.provider, self.model)


class ModelValidationTests(unittest.TestCase):
    def test_base_client_invoke_proxies_to_underlying_llm(self):
        class Runnable:
            def __init__(self):
                self.calls = []

            def invoke(self, input, config=None, **kwargs):
                self.calls.append((input, config, kwargs))
                return {"content": "ok"}

        client = DummyLLMClient("openai", "gpt-5.4")
        runnable = Runnable()
        client._llm = runnable

        result = client.invoke("hello", config={"k": 1}, temperature=0.2)

        self.assertEqual(result, {"content": "ok"})
        self.assertEqual(runnable.calls, [("hello", {"k": 1}, {"temperature": 0.2})])

    def test_cli_catalog_models_are_all_validator_approved(self):
        for provider, models in get_known_models().items():
            if provider in ("ollama", "openrouter"):
                continue

            for model in models:
                with self.subTest(provider=provider, model=model):
                    self.assertTrue(validate_model(provider, model))

    def test_unknown_model_emits_warning_for_strict_provider(self):
        client = DummyLLMClient("openai", "not-a-real-openai-model")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client.get_llm()

        self.assertEqual(len(caught), 1)
        self.assertIn("not-a-real-openai-model", str(caught[0].message))
        self.assertIn("openai", str(caught[0].message))

    def test_openrouter_and_ollama_accept_custom_models_without_warning(self):
        for provider in ("openrouter", "ollama"):
            client = DummyLLMClient(provider, "custom-model-name")

            with self.subTest(provider=provider):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    client.get_llm()

                self.assertEqual(caught, [])
