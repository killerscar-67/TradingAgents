"""LLM model catalog endpoint for the web UI."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

router = APIRouter(prefix="/api/models", tags=["models"])

_CUSTOM_PROVIDERS = ("azure", "openrouter")


def _format_options(options: List[tuple[str, str]]) -> List[Dict[str, str]]:
    return [{"label": label, "value": value} for label, value in options]


@router.get("")
def get_models() -> Dict[str, Any]:
    providers: Dict[str, Dict[str, Any]] = {}
    for provider, mode_options in MODEL_OPTIONS.items():
        providers[provider] = {
            "custom": False,
            "deep": _format_options(mode_options.get("deep", [])),
            "quick": _format_options(mode_options.get("quick", [])),
        }

    for provider in _CUSTOM_PROVIDERS:
        providers[provider] = {
            "custom": True,
            "deep": [],
            "quick": [],
        }

    return {"providers": providers}
