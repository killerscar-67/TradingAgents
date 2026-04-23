"""Phase 10 day-trade workflow API routes.

These endpoints keep the Phase 9 contract shape while adding SQLite-backed
metadata persistence for workflow settings, saved lists, and unified history.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from tradingagents.web import runner
from tradingagents.web.models import MarketOverview
from tradingagents.web.storage import get_workflow_store


router = APIRouter(tags=["workflow"])

_VALID_ANALYSTS = {"market", "social", "news", "fundamentals"}
_VALID_STRATEGIES = {"auto", "breakout", "mean_reversion"}
_VALID_HORIZONS = {"intraday", "swing"}
_VALID_SESSION_STATUSES = {"draft", "active", "completed", "archived"}
_VALID_HISTORY_GROUPS = {"none", "workflow_session"}


class ScreeningRunRequest(BaseModel):
    universe: str = "S&P 500"
    strategy: str = "auto"
    trade_date: str = Field(default_factory=lambda: date.today().isoformat())
    top_n: int = 20
    min_score: float = 0.65
    workflow_session_id: Optional[str] = None
    filters: Dict[str, bool] = Field(
        default_factory=lambda: {
            "momentum": True,
            "squeeze": True,
            "sr_proximity": False,
            "volume_surge": True,
        }
    )
    custom_symbols: List[str] = Field(default_factory=list)
    regime: Optional[Dict[str, Any]] = None

    @field_validator("strategy")
    @classmethod
    def valid_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {_VALID_STRATEGIES}")
        return normalized


class BasketRequest(BaseModel):
    symbols: List[str]
    name: str = "Basket"
    workflow_session_id: Optional[str] = None
    source_screening_run_id: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("symbols")
    @classmethod
    def symbols_not_empty(cls, value: List[str]) -> List[str]:
        cleaned = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not cleaned:
            raise ValueError("symbols must contain at least one ticker")
        return cleaned


class BatchRequest(BaseModel):
    basket_id: Optional[str] = None
    workflow_session_id: Optional[str] = None
    symbols: List[str]
    analysis_date: str = Field(default_factory=lambda: date.today().isoformat())
    selected_analysts: List[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    execution_mode: str = "llm_assisted"
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-5.4"
    quick_think_llm: str = "gpt-5.4-mini"

    @field_validator("selected_analysts")
    @classmethod
    def valid_analysts(cls, value: List[str]) -> List[str]:
        unknown = set(value) - _VALID_ANALYSTS
        if unknown:
            raise ValueError(f"Unknown analysts: {unknown}")
        return value


class StrategyFromBatchRequest(BaseModel):
    batch_id: str
    workflow_session_id: Optional[str] = None
    portfolio_size: float = 100_000.0
    risk_per_trade: float = 0.01
    allow_shorts: bool = True
    mode: str = "auto"
    horizon: str = "intraday"

    @field_validator("horizon")
    @classmethod
    def valid_horizon(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _VALID_HORIZONS:
            raise ValueError(f"horizon must be one of {_VALID_HORIZONS}")
        return normalized


class FutuStageRequest(BaseModel):
    strategy_id: Optional[str] = None
    workflow_session_id: Optional[str] = None
    orders: List[Dict[str, Any]]


class BacktestRequest(BaseModel):
    strategy_id: Optional[str] = None
    workflow_session_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    start_date: str
    end_date: str
    portfolio_size: float = 100_000.0
    config: Dict[str, Any] = Field(default_factory=dict)


class SettingsUpdateRequest(BaseModel):
    values: Dict[str, Any]


class WatchlistRequest(BaseModel):
    name: str
    symbols: List[str]


class StrategyPresetRequest(BaseModel):
    name: str
    portfolio_size: float = 100_000.0
    risk_per_trade: float = 0.01
    allow_shorts: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkflowSessionUpdateRequest(BaseModel):
    current_screen: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in _VALID_SESSION_STATUSES:
            raise ValueError(f"status must be one of {_VALID_SESSION_STATUSES}")
        return normalized


@router.get("/api/market/overview")
def get_market_overview(home_market: str = "US", trade_date: Optional[str] = None) -> Dict[str, Any]:
    """Return a deterministic placeholder overview with the final response shape."""
    overview = MarketOverview(
        home_market=home_market.upper() or "US",
        trade_date=trade_date or date.today().isoformat(),
        status="contract_ready",
        indices=[
            {"symbol": "^GSPC", "label": "S&P 500", "price": 0.0, "change_pct": 0.0},
            {"symbol": "^NDX", "label": "NASDAQ 100", "price": 0.0, "change_pct": 0.0},
            {"symbol": "^VIX", "label": "VIX", "price": 0.0, "change_pct": 0.0},
        ],
        regime={
            "label": "Pending data integration",
            "confidence": 0,
            "suggested_entry_mode": "auto",
            "event_risk_flag": False,
        },
        breadth={},
        sectors=[],
        events=[],
        regions={},
        stream={"status": "contract_ready", "transport": "websocket"},
    )
    return overview.to_dict()


@router.websocket("/api/market/live")
async def stream_market_live(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await websocket.send_json(
            {
                "type": "market_snapshot",
                "payload": get_market_overview(
                    home_market=websocket.query_params.get("home_market", "US"),
                    trade_date=websocket.query_params.get("trade_date"),
                ),
            }
        )
        await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        return
    else:
        await websocket.close()


@router.post("/api/screening/runs")
def create_screening_run(req: ScreeningRunRequest) -> Dict[str, Any]:
    store = get_workflow_store()
    home_market = store.get_settings_without_status().get("home_market", "US")
    screening_run = store.create_screening_run(
        req.model_dump(),
        home_market=home_market,
        workflow_session_id=req.workflow_session_id,
    )
    return {
        "kind": "screening_run",
        "status": screening_run["status"],
        "run_id": screening_run["run_id"],
        "workflow_session_id": screening_run["workflow_session_id"],
        "request": req.model_dump(),
    }


@router.post("/api/baskets")
def create_basket(req: BasketRequest) -> Dict[str, Any]:
    store = get_workflow_store()
    home_market = store.get_settings_without_status().get("home_market", "US")
    basket = store.create_basket(
        req.model_dump(),
        home_market=home_market,
        workflow_session_id=req.workflow_session_id,
    )
    return {
        "kind": "basket",
        "status": "ready",
        "basket_id": basket["basket_id"],
        "workflow_session_id": basket["workflow_session_id"],
        "request": req.model_dump(),
    }


@router.post("/api/batches")
def create_batch(req: BatchRequest) -> Dict[str, Any]:
    store = get_workflow_store()
    home_market = store.get_settings_without_status().get("home_market", "US")
    batch = store.create_analysis_batch(
        req.model_dump(),
        home_market=home_market,
        workflow_session_id=req.workflow_session_id,
    )
    return {
        "kind": "analysis_batch",
        "status": batch["status"],
        "batch_id": batch["batch_id"],
        "workflow_session_id": batch["workflow_session_id"],
        "request": req.model_dump(),
    }


@router.get("/api/batches/{batch_id}/events")
async def stream_batch_events(batch_id: str) -> StreamingResponse:
    async def generator():
        yield f"data: {json.dumps({'type': 'batch_status', 'batch_id': batch_id, 'status': 'contract_ready'})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/api/strategies/from-batch")
def create_strategy_from_batch(req: StrategyFromBatchRequest) -> Dict[str, Any]:
    store = get_workflow_store()
    home_market = store.get_settings_without_status().get("home_market", "US")
    strategy = store.create_strategy_plan(
        req.model_dump(),
        home_market=home_market,
        workflow_session_id=req.workflow_session_id,
    )
    return {
        "kind": "trade_plan",
        "status": "ready",
        "strategy_id": strategy["strategy_id"],
        "workflow_session_id": strategy["workflow_session_id"],
        "request": req.model_dump(),
    }


@router.post("/api/broker/futu/stage")
def stage_futu_orders(req: FutuStageRequest) -> Dict[str, Any]:
    payload = req.model_dump()
    payload["stage_only"] = True
    payload["submits_orders"] = False
    store = get_workflow_store()
    home_market = store.get_settings_without_status().get("home_market", "US")
    stage_request = store.create_broker_stage_request(
        payload,
        home_market=home_market,
        workflow_session_id=req.workflow_session_id,
    )
    return {
        "kind": "futu_stage_request",
        "status": stage_request["status"],
        "stage_id": stage_request["stage_id"],
        "workflow_session_id": stage_request["workflow_session_id"],
        "request": payload,
    }


@router.post("/api/backtests")
def create_backtest(req: BacktestRequest) -> Dict[str, Any]:
    payload = req.model_dump()
    config = dict(payload.get("config", {}))
    config.pop("execution_mode", None)
    payload["config"] = config
    payload["execution_mode"] = "quant_strict"
    payload["llm_constructed"] = False
    store = get_workflow_store()
    home_market = store.get_settings_without_status().get("home_market", "US")
    backtest = store.create_backtest_run(
        payload,
        home_market=home_market,
        workflow_session_id=req.workflow_session_id,
    )
    return {
        "kind": "backtest_run",
        "status": backtest["status"],
        "backtest_id": backtest["backtest_id"],
        "workflow_session_id": backtest["workflow_session_id"],
        "request": payload,
    }


@router.get("/api/backtests/{backtest_id}/events")
async def stream_backtest_events(backtest_id: str) -> StreamingResponse:
    async def generator():
        yield f"data: {json.dumps({'type': 'backtest_status', 'backtest_id': backtest_id, 'status': 'contract_ready', 'execution_mode': 'quant_strict'})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    return get_workflow_store().get_settings()


@router.put("/api/settings")
def update_settings(req: SettingsUpdateRequest) -> Dict[str, Any]:
    values = get_workflow_store().update_settings(req.values)
    return {"status": values.pop("status", "ready"), "values": values}


@router.get("/api/watchlists")
def list_watchlists() -> Dict[str, Any]:
    return {"watchlists": get_workflow_store().list_watchlists(), "status": "ready"}


@router.post("/api/watchlists")
def create_watchlist(req: WatchlistRequest) -> Dict[str, Any]:
    cleaned_symbols = [symbol.strip().upper() for symbol in req.symbols if symbol.strip()]
    watchlist = get_workflow_store().create_watchlist(req.name, cleaned_symbols)
    return {"status": "ready", **watchlist}


@router.get("/api/strategy-presets")
def list_strategy_presets() -> Dict[str, Any]:
    return {"presets": get_workflow_store().list_strategy_presets(), "status": "ready"}


@router.post("/api/strategy-presets")
def create_strategy_preset(req: StrategyPresetRequest) -> Dict[str, Any]:
    preset = get_workflow_store().create_strategy_preset(
        name=req.name,
        portfolio_size=req.portfolio_size,
        risk_per_trade=req.risk_per_trade,
        allow_shorts=req.allow_shorts,
        config=req.config,
    )
    return {"status": "ready", **preset}


@router.get("/api/workflow-sessions")
def list_workflow_sessions(
    status: Optional[str] = None,
    include_archived: bool = False,
) -> Dict[str, Any]:
    normalized_status = status.strip().lower() if status else None
    if normalized_status and normalized_status not in _VALID_SESSION_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {_VALID_SESSION_STATUSES}")
    sessions = get_workflow_store().list_workflow_sessions(
        status=normalized_status,
        include_archived=include_archived,
    )
    return {"sessions": sessions, "total": len(sessions), "status": "ready"}


@router.get("/api/workflow-sessions/{session_id}")
def get_workflow_session(session_id: str) -> Dict[str, Any]:
    session = get_workflow_store().get_workflow_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="workflow session not found")
    return {"session": session, "status": "ready"}


@router.put("/api/workflow-sessions/{session_id}")
def update_workflow_session(session_id: str, req: WorkflowSessionUpdateRequest) -> Dict[str, Any]:
    session = get_workflow_store().update_workflow_session(
        session_id,
        current_screen=req.current_screen,
        status=req.status,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="workflow session not found")
    return {"session": session, "status": "ready"}


@router.get("/api/history")
def get_history(
    item_type: Optional[str] = None,
    market: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = Query(default="none"),
) -> Dict[str, Any]:
    normalized_group_by = group_by.strip().lower()
    if normalized_group_by not in _VALID_HISTORY_GROUPS:
        raise HTTPException(status_code=422, detail=f"group_by must be one of {_VALID_HISTORY_GROUPS}")

    items = get_workflow_store().list_history_items()
    items.extend(
        {
            "type": "legacy_analysis",
            "id": run.run_id,
            "title": run.ticker,
            "status": run.status,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "home_market": None,
            "workflow_session_id": None,
        }
        for run in runner.list_runs()
    )
    if item_type:
        items = [item for item in items if item.get("type") == item_type]
    if market:
        market_upper = market.strip().upper()
        items = [item for item in items if (item.get("home_market") or "").upper() == market_upper]
    if status:
        normalized_status = status.strip().lower()
        items = [item for item in items if (item.get("status") or "").lower() == normalized_status]
    if start_date:
        items = [item for item in items if (item.get("created_at") or "")[:10] >= start_date]
    if end_date:
        items = [item for item in items if (item.get("created_at") or "")[:10] <= end_date]
    if q:
        needle = q.strip().lower()
        items = [
            item
            for item in items
            if needle in (item.get("title") or "").lower()
            or needle in (item.get("id") or "").lower()
            or needle in (item.get("workflow_session_id") or "").lower()
        ]
    items.sort(
        key=lambda item: item.get("completed_at") or item.get("created_at") or "",
        reverse=True,
    )

    response: Dict[str, Any] = {
        "items": items,
        "total": len(items),
        "status": "ready",
        "group_by": normalized_group_by,
    }
    if normalized_group_by == "workflow_session":
        session_map = {
            session["session_id"]: session
            for session in get_workflow_store().list_workflow_sessions(include_archived=True)
        }
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            key = item.get("workflow_session_id") or "__ungrouped__"
            grouped.setdefault(key, []).append(item)
        groups: List[Dict[str, Any]] = []
        for key, grouped_items in grouped.items():
            groups.append(
                {
                    "workflow_session_id": None if key == "__ungrouped__" else key,
                    "session": None if key == "__ungrouped__" else session_map.get(key),
                    "items": grouped_items,
                    "latest_at": grouped_items[0].get("completed_at") or grouped_items[0].get("created_at"),
                }
            )
        groups.sort(key=lambda group: group["latest_at"] or "", reverse=True)
        response["groups"] = groups
    return response


def _planned(kind: str, request: Dict[str, Any], **ids: str) -> Dict[str, Any]:
    payload = {
        "kind": kind,
        "status": "contract_ready",
        "phase": 9,
        "implemented_in_phase": "10+",
        "request": request,
    }
    payload.update(ids)
    return payload
