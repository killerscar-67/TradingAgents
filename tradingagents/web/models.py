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

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d
