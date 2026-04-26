"""Consultant chat endpoint — advisory only, no executable fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tradingagents.web import runner

router = APIRouter(prefix="/api/analysis", tags=["consultant"])


class ConsultantChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []


def create_llm_client(*args: Any, **kwargs: Any) -> Any:
    from tradingagents.llm_clients.factory import create_llm_client as _create_llm_client

    return _create_llm_client(*args, **kwargs)


def chat_trade_review(*args: Any, **kwargs: Any) -> Any:
    from tradingagents.agents.utils.llm_support import chat_trade_review as _chat_trade_review

    return _chat_trade_review(*args, **kwargs)


@router.post("/{run_id}/consultant/chat")
def consultant_chat(run_id: str, req: ConsultantChatRequest) -> Dict[str, Any]:
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if not run.report_sections:
        raise HTTPException(
            status_code=409,
            detail="Run has no report context yet; wait until analysis is further along",
        )

    llm_client = create_llm_client(
        provider=run.llm_provider,
        model=run.quick_think_llm,
    )
    llm = llm_client.get_llm() if hasattr(llm_client, "get_llm") else llm_client

    context: Dict[str, Any] = {
        "ticker": run.ticker,
        "analysis_date": run.analysis_date,
        "execution_mode": run.execution_mode,
        **run.report_sections,
    }
    if run.final_order_intent:
        context["order_intent"] = run.final_order_intent
    if run.stats:
        context["stats"] = run.stats

    # Build message history in the format chat_trade_review expects
    messages: List[Dict[str, str]] = list(req.history) + [
        {"role": "user", "content": req.message}
    ]

    response = chat_trade_review(llm, context, messages)

    result = response.to_dict()
    # Strip blocking field — this endpoint is advisory only
    result.pop("blocking", None)
    return result
