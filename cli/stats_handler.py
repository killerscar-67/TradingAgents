import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.messages import AIMessage


class StatsCallbackHandler(BaseCallbackHandler):
    """Callback handler that tracks LLM calls, tool calls, and token usage."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.per_agent: Dict[str, Dict[str, int]] = {}
        self.per_stage: Dict[str, Dict[str, int]] = {}
        self._pending_scopes: Dict[str, Tuple[str, str]] = {}

    @staticmethod
    def _empty_bucket() -> Dict[str, int]:
        return {
            "llm_calls": 0,
            "tool_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }

    @staticmethod
    def _normalize_label(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    def _infer_stage(self, agent_name: str, metadata: Dict[str, Any]) -> str:
        explicit_stage = self._normalize_label(metadata.get("stage"))
        if explicit_stage:
            return explicit_stage.lower().replace(" ", "_")

        label = agent_name.lower()
        if "portfolio manager" in label:
            return "portfolio"
        if any(term in label for term in ("market analyst", "social analyst", "news analyst", "fundamentals analyst")):
            return "analyst"
        if any(term in label for term in ("bull researcher", "bear researcher", "research manager")):
            return "research"
        if label == "trader" or " trader" in label:
            return "trader"
        if any(term in label for term in ("aggressive analyst", "conservative analyst", "neutral analyst", "risk")):
            return "risk"
        return "unknown"

    def _resolve_scope(self, serialized: Dict[str, Any], **kwargs: Any) -> Tuple[str, str]:
        metadata = kwargs.get("metadata") or {}
        tags = kwargs.get("tags") or []

        candidates = [
            metadata.get("langgraph_node"),
            metadata.get("agent"),
            metadata.get("node_name"),
            kwargs.get("name"),
            kwargs.get("run_name"),
        ]

        for tag in tags:
            tag_text = self._normalize_label(tag)
            if not tag_text:
                continue
            if ":" in tag_text:
                prefix, _, value = tag_text.partition(":")
                if prefix in {"langgraph_node", "agent", "node_name"} and value.strip():
                    candidates.append(value.strip())
            elif not tag_text.startswith(("seq:step", "map:key", "graph:", "parent:")):
                candidates.append(tag_text)

        candidates.append(serialized.get("name") if isinstance(serialized, dict) else None)

        for candidate in candidates:
            agent_name = self._normalize_label(candidate)
            if agent_name and agent_name.lower() not in {"chatopenai", "chatmodel", "llm"}:
                return agent_name, self._infer_stage(agent_name, metadata)

        return "unknown", self._infer_stage("unknown", metadata)

    def _get_bucket(self, store: Dict[str, Dict[str, int]], key: str) -> Dict[str, int]:
        if key not in store:
            store[key] = self._empty_bucket()
        return store[key]

    def _increment_scope_metric(self, agent_name: str, stage_name: str, metric: str, amount: int = 1) -> None:
        self._get_bucket(self.per_agent, agent_name)[metric] += amount
        self._get_bucket(self.per_stage, stage_name)[metric] += amount

    def _record_start(self, serialized: Dict[str, Any], metric: str, **kwargs: Any) -> None:
        agent_name, stage_name = self._resolve_scope(serialized, **kwargs)
        run_id = kwargs.get("run_id")
        if run_id is not None:
            self._pending_scopes[str(run_id)] = (agent_name, stage_name)
        self._increment_scope_metric(agent_name, stage_name, metric)

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when an LLM starts."""
        with self._lock:
            self.llm_calls += 1
            self._record_start(serialized, "llm_calls", **kwargs)

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when a chat model starts."""
        with self._lock:
            self.llm_calls += 1
            self._record_start(serialized, "llm_calls", **kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from LLM response."""
        run_id = kwargs.get("run_id")
        with self._lock:
            if run_id is not None:
                agent_name, stage_name = self._pending_scopes.pop(str(run_id), ("unknown", "unknown"))
            else:
                agent_name, stage_name = ("unknown", "unknown")

        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        if usage_metadata:
            with self._lock:
                input_tokens = int(usage_metadata.get("input_tokens", 0) or 0)
                output_tokens = int(usage_metadata.get("output_tokens", 0) or 0)
                self.tokens_in += input_tokens
                self.tokens_out += output_tokens
                self._increment_scope_metric(agent_name, stage_name, "tokens_in", input_tokens)
                self._increment_scope_metric(agent_name, stage_name, "tokens_out", output_tokens)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        """Drain pending scope state for failed LLM runs."""
        run_id = kwargs.get("run_id")
        if run_id is None:
            return
        with self._lock:
            self._pending_scopes.pop(str(run_id), None)

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Increment tool call counter when a tool starts."""
        with self._lock:
            self.tool_calls += 1
            agent_name, stage_name = self._resolve_scope(serialized, **kwargs)
            self._increment_scope_metric(agent_name, stage_name, "tool_calls")

    def get_stats(self) -> Dict[str, Any]:
        """Return current statistics."""
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "per_agent": {key: dict(value) for key, value in self.per_agent.items()},
                "per_stage": {key: dict(value) for key, value in self.per_stage.items()},
            }
