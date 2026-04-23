"""Analysis endpoints: create run, poll status, SSE events, report sections."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from tradingagents.web import runner
from tradingagents.web.runner import _DONE, load_events_from_disk

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_VALID_ANALYSTS = {"market", "social", "news", "fundamentals"}
_VALID_EXECUTION_MODES = {"llm_assisted", "quant_strict"}


class CreateAnalysisRequest(BaseModel):
    ticker: str
    analysis_date: str
    selected_analysts: List[str] = ["market", "social", "news", "fundamentals"]
    execution_mode: str = "llm_assisted"
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-4o"
    quick_think_llm: str = "gpt-4o-mini"

    @field_validator("ticker")
    @classmethod
    def ticker_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("ticker must not be empty")
        return v

    @field_validator("analysis_date")
    @classmethod
    def date_format(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("analysis_date must be YYYY-MM-DD")
        return v

    @field_validator("selected_analysts")
    @classmethod
    def valid_analysts(cls, v: List[str]) -> List[str]:
        unknown = set(v) - _VALID_ANALYSTS
        if unknown:
            raise ValueError(f"Unknown analysts: {unknown}")
        return v

    @field_validator("execution_mode")
    @classmethod
    def valid_mode(cls, v: str) -> str:
        if v not in _VALID_EXECUTION_MODES:
            raise ValueError(f"execution_mode must be one of {_VALID_EXECUTION_MODES}")
        return v


@router.get("")
def list_analysis() -> Dict[str, Any]:
    return {"runs": [run.to_dict() for run in runner.list_runs()]}


@router.post("")
def create_analysis(req: CreateAnalysisRequest) -> Dict[str, Any]:
    run = runner.create_run(
        ticker=req.ticker,
        analysis_date=req.analysis_date,
        selected_analysts=req.selected_analysts,
        execution_mode=req.execution_mode,
        llm_provider=req.llm_provider,
        deep_think_llm=req.deep_think_llm,
        quick_think_llm=req.quick_think_llm,
    )
    runner.run_background(run.run_id)
    return {"run_id": run.run_id, "status": run.status}


@router.get("/{run_id}")
def get_analysis(run_id: str) -> Dict[str, Any]:
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@router.get("/{run_id}/reports")
def get_reports(run_id: str) -> Dict[str, Any]:
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"sections": dict(run.report_sections)}


@router.get("/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def generator():
        # Replay stored events first
        for event_dict in load_events_from_disk(run_id):
            yield f"data: {json.dumps(event_dict)}\n\n"

        # If already terminal, nothing more to stream
        if run.status in ("completed", "error"):
            return

        q = runner.get_event_queue(run_id)
        if q is None:
            return

        loop = asyncio.get_event_loop()
        while True:
            try:
                item = await loop.run_in_executor(None, q.get, True, 0.5)
                if item is _DONE:
                    break
                yield f"data: {json.dumps(item.to_dict())}\n\n"
            except Exception:
                # queue.Empty from timeout — keep polling
                if run.status in ("completed", "error"):
                    break

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
