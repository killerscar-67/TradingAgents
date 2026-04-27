"""Data models for the Phase 9 web UI layer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal, Optional


RunStatus = Literal["pending", "running", "completed", "error"]

SseEventType = Literal[
    "status",
    "agent_status",
    "report_section",
    "message",
    "tool_call",
    "final_state",
    "error",
]


@dataclass
class SseEvent:
    type: SseEventType
    run_id: str
    sequence: int
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


@dataclass
class AnalysisRun:
    run_id: str
    ticker: str
    analysis_date: str
    selected_analysts: List[str]
    execution_mode: str
    llm_provider: str
    deep_think_llm: str
    quick_think_llm: str
    created_at: str
    status: RunStatus = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    report_sections: Dict[str, str] = field(default_factory=dict)
    report_paths: Dict[str, str] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    final_order_intent: Optional[Dict[str, Any]] = None
    trading_style: str = "swing"
    intraday_interval: Optional[str] = None
    trade_datetime: Optional[str] = None
    session_phase: Optional[str] = None
    data_session_date: Optional[str] = None
    intraday_decisions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class MarketOverview:
    home_market: str
    trade_date: str
    status: str
    indices: List[Dict[str, Any]]
    regime: Dict[str, Any]
    breadth: Dict[str, Any]
    sectors: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    regions: Dict[str, Dict[str, Any]]
    stream: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScreeningRun:
    run_id: str
    universe: str
    strategy: str
    trade_date: str
    min_score: float
    top_n: int
    filters: Dict[str, Any]
    regime: Dict[str, Any]
    results: List[Dict[str, Any]]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TickerBasket:
    basket_id: str
    name: str
    symbols: List[str]
    items: List[Dict[str, Any]]
    created_at: str
    source_screening_run_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisBatch:
    batch_id: str
    status: str
    items: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    basket_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradePlan:
    strategy_id: str
    name: str
    mode: str
    horizon: str
    portfolio_size: float
    risk_per_trade: float
    allow_shorts: bool
    trades: List[Dict[str, Any]]
    exposure: Dict[str, Any]
    risk: Dict[str, Any]
    created_at: str
    source_batch_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyPreset:
    preset_id: str
    name: str
    portfolio_size: float
    risk_per_trade: float
    allow_shorts: bool
    config: Dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestRun:
    backtest_id: str
    status: str
    config: Dict[str, Any]
    result: Dict[str, Any]
    created_at: str
    strategy_id: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
