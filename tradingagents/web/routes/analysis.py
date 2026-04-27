"""Analysis endpoints: create run, poll status, SSE events, report sections."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator

from tradingagents.web import runner
from tradingagents.web.models import AnalysisRun
from tradingagents.web.runner import _DONE, load_events_from_disk
from tradingagents.web.storage import get_workflow_store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_VALID_SWING_ANALYSTS = {"market", "social", "news", "fundamentals"}
_VALID_DAYTRADE_ANALYSTS = {"intraday_market", "news"}
_VALID_ANALYSTS = _VALID_SWING_ANALYSTS | _VALID_DAYTRADE_ANALYSTS
_VALID_EXECUTION_MODES = {"llm_assisted", "quant_strict"}
_VALID_TRADING_STYLES = {"swing", "daytrade"}
_VALID_INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}


def _normalize_archived_run_status(status: Any) -> str:
    normalized = str(status or "pending").lower()
    if normalized in {"completed", "error", "pending", "running"}:
        return normalized
    if normalized in {"failed", "partial_failure", "stopped", "not_found"}:
        return "error"
    if normalized in {"queued", "draft"}:
        return "pending"
    return "running"


def _resolve_run(run_id: str) -> Optional[AnalysisRun]:
    run = runner.get_run(run_id)
    if run is not None:
        return run

    archived = get_workflow_store().find_analysis_run_archive(run_id)
    if archived is None:
        return None

    item = archived.get("item") or {}
    request = archived.get("request") or {}
    summary = str(item.get("summary") or item.get("error") or "")
    report_sections = {"final_trade_decision": summary} if summary else {}
    error = item.get("error")
    return AnalysisRun(
        run_id=run_id,
        ticker=str(item.get("symbol") or ""),
        analysis_date=str(archived.get("analysis_date") or request.get("analysis_date") or ""),
        selected_analysts=list(archived.get("selected_analysts") or []),
        execution_mode=str(archived.get("execution_mode") or request.get("execution_mode") or "llm_assisted"),
        llm_provider=str(archived.get("llm_provider") or request.get("llm_provider") or ""),
        deep_think_llm=str(archived.get("deep_think_llm") or request.get("deep_think_llm") or ""),
        quick_think_llm=str(archived.get("quick_think_llm") or request.get("quick_think_llm") or ""),
        created_at=str(archived.get("created_at") or ""),
        status=_normalize_archived_run_status(item.get("status")),
        started_at=item.get("started_at"),
        completed_at=item.get("completed_at") or archived.get("updated_at"),
        report_sections=report_sections,
        report_paths=dict(item.get("report_paths") or {}),
        errors=[str(error)] if error else [],
        final_order_intent=item.get("order_intent") if isinstance(item.get("order_intent"), dict) else None,
        trading_style=str(request.get("trading_style") or "swing"),
        intraday_interval=request.get("intraday_interval"),
        trade_datetime=request.get("trade_datetime"),
    )


class CreateAnalysisRequest(BaseModel):
    ticker: str
    analysis_date: str
    selected_analysts: Optional[List[str]] = None
    execution_mode: str = "llm_assisted"
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-4o"
    quick_think_llm: str = "gpt-4o-mini"
    trading_style: str = "swing"
    intraday_interval: Optional[str] = None
    trade_datetime: Optional[str] = None

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
    def valid_analysts(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
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

    @field_validator("trading_style")
    @classmethod
    def valid_trading_style(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized not in _VALID_TRADING_STYLES:
            raise ValueError(f"trading_style must be one of {_VALID_TRADING_STYLES}")
        return normalized

    @field_validator("intraday_interval")
    @classmethod
    def valid_intraday_interval(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        normalized = v.strip()
        if normalized not in _VALID_INTRADAY_INTERVALS:
            raise ValueError(f"intraday_interval must be one of {_VALID_INTRADAY_INTERVALS}")
        return normalized

    @model_validator(mode="after")
    def normalize_daytrade_fields(self) -> "CreateAnalysisRequest":
        if self.trading_style == "daytrade":
            if self.selected_analysts is None:
                self.selected_analysts = ["intraday_market", "news"]
            unknown = set(self.selected_analysts) - _VALID_DAYTRADE_ANALYSTS
            if unknown:
                raise ValueError(
                    "daytrade selected_analysts may only include intraday_market and news"
                )
            if self.intraday_interval is None:
                self.intraday_interval = "5m"
            if self.trade_datetime is None:
                self.trade_datetime = f"{self.analysis_date}T09:30:00-04:00"
        else:
            if self.selected_analysts is None:
                self.selected_analysts = ["market", "social", "news", "fundamentals"]
            unknown = set(self.selected_analysts) - _VALID_SWING_ANALYSTS
            if unknown:
                raise ValueError("swing selected_analysts may only include market, social, news, and fundamentals")
            self.intraday_interval = None
            self.trade_datetime = None
        return self


@router.get("")
def list_analysis() -> Dict[str, Any]:
    return {"runs": [run.to_dict() for run in runner.list_runs()]}


@router.post("")
def create_analysis(req: CreateAnalysisRequest) -> Dict[str, Any]:
    run = runner.create_run(
        ticker=req.ticker,
        analysis_date=req.analysis_date,
        selected_analysts=req.selected_analysts or [],
        execution_mode=req.execution_mode,
        llm_provider=req.llm_provider,
        deep_think_llm=req.deep_think_llm,
        quick_think_llm=req.quick_think_llm,
        trading_style=req.trading_style,
        intraday_interval=req.intraday_interval,
        trade_datetime=req.trade_datetime,
    )
    runner.run_background(
        run.run_id,
        {
            "trading_style": req.trading_style,
            "intraday_interval": req.intraday_interval,
            "trade_datetime": req.trade_datetime,
        },
    )
    return {"run_id": run.run_id, "status": run.status}


@router.get("/{run_id}")
def get_analysis(run_id: str) -> Dict[str, Any]:
    run = _resolve_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@router.get("/{run_id}/reports")
def get_reports(run_id: str) -> Dict[str, Any]:
    run = _resolve_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"sections": dict(run.report_sections)}


@router.get("/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run = _resolve_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    archived = get_workflow_store().find_analysis_run_archive(run_id)

    async def generator():
        if archived is not None:
            for event_dict in archived.get("events", []):
                yield f"data: {json.dumps(event_dict)}\n\n"
            return

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
