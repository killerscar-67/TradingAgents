"""Phase 9 day-trade workflow API contracts and route skeletons.

These endpoints establish the public web API shape for the five-screen
day-trade workflow.  Later UX phases replace the placeholder bodies with
SQLite persistence, deterministic orchestration, and frontend integration.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from tradingagents.web import runner
from tradingagents.web.models import MarketOverview


router = APIRouter(tags=["workflow"])

_VALID_STRATEGIES = {"auto", "breakout", "mean_reversion"}
_VALID_HORIZONS = {"intraday", "swing"}


class ScreeningRunRequest(BaseModel):
    universe: str = "S&P 500"
    strategy: str = "auto"
    trade_date: str = Field(default_factory=lambda: date.today().isoformat())
    top_n: int = 20
    min_score: float = 0.65
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
    symbols: List[str]
    analysis_date: str = Field(default_factory=lambda: date.today().isoformat())
    execution_mode: str = "llm_assisted"
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-5.4"
    quick_think_llm: str = "gpt-5.4-mini"


class StrategyFromBatchRequest(BaseModel):
    batch_id: str
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
    orders: List[Dict[str, Any]]


class BacktestRequest(BaseModel):
    strategy_id: Optional[str] = None
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
    finally:
        await websocket.close()


@router.post("/api/screening/runs")
def create_screening_run(req: ScreeningRunRequest) -> Dict[str, Any]:
    return _planned("screening_run", req.model_dump(), run_id="phase-9-contract")


@router.post("/api/baskets")
def create_basket(req: BasketRequest) -> Dict[str, Any]:
    return _planned("basket", req.model_dump(), basket_id="phase-9-contract")


@router.post("/api/batches")
def create_batch(req: BatchRequest) -> Dict[str, Any]:
    return _planned("analysis_batch", req.model_dump(), batch_id="phase-9-contract")


@router.get("/api/batches/{batch_id}/events")
async def stream_batch_events(batch_id: str) -> StreamingResponse:
    async def generator():
        yield f"data: {json.dumps({'type': 'batch_status', 'batch_id': batch_id, 'status': 'contract_ready'})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/api/strategies/from-batch")
def create_strategy_from_batch(req: StrategyFromBatchRequest) -> Dict[str, Any]:
    return _planned("trade_plan", req.model_dump(), strategy_id="phase-9-contract")


@router.post("/api/broker/futu/stage")
def stage_futu_orders(req: FutuStageRequest) -> Dict[str, Any]:
    payload = req.model_dump()
    payload["stage_only"] = True
    payload["submits_orders"] = False
    return _planned("futu_stage_request", payload, stage_id="phase-9-contract")


@router.post("/api/backtests")
def create_backtest(req: BacktestRequest) -> Dict[str, Any]:
    payload = req.model_dump()
    payload["execution_mode"] = "quant_strict"
    payload["llm_constructed"] = False
    return _planned("backtest_run", payload, backtest_id="phase-9-contract")


@router.get("/api/backtests/{backtest_id}/events")
async def stream_backtest_events(backtest_id: str) -> StreamingResponse:
    async def generator():
        yield f"data: {json.dumps({'type': 'backtest_status', 'backtest_id': backtest_id, 'status': 'contract_ready', 'execution_mode': 'quant_strict'})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    return {
        "home_market": "US",
        "output_language": "English",
        "calendar_provider": "fmp",
        "broker": {"futu": {"enabled": False, "host": "127.0.0.1", "port": 11111}},
        "status": "contract_ready",
    }


@router.put("/api/settings")
def update_settings(req: SettingsUpdateRequest) -> Dict[str, Any]:
    return {"status": "contract_ready", "values": req.values}


@router.get("/api/watchlists")
def list_watchlists() -> Dict[str, Any]:
    return {"watchlists": [], "status": "contract_ready"}


@router.post("/api/watchlists")
def create_watchlist(req: WatchlistRequest) -> Dict[str, Any]:
    return _planned("watchlist", req.model_dump(), watchlist_id="phase-9-contract")


@router.get("/api/strategy-presets")
def list_strategy_presets() -> Dict[str, Any]:
    return {"presets": [], "status": "contract_ready"}


@router.post("/api/strategy-presets")
def create_strategy_preset(req: StrategyPresetRequest) -> Dict[str, Any]:
    return _planned("strategy_preset", req.model_dump(), preset_id="phase-9-contract")


@router.get("/api/history")
def get_history() -> Dict[str, Any]:
    analysis_runs = [
        {
            "type": "analysis",
            "id": run.run_id,
            "title": run.ticker,
            "status": run.status,
            "created_at": run.created_at,
        }
        for run in runner.list_runs()
    ]
    return {"items": analysis_runs, "status": "contract_ready"}


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
