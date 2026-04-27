"""Trading journal endpoints for daytrade web workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.journal import Journal
from tradingagents.journal.report import (
    agent_vs_human,
    expectancy_by_strategy,
    session_phase_pnl,
    variant_comparison,
)


router = APIRouter(prefix="/api/journal", tags=["journal"])

_VALID_REPORTS = {"strategy", "actor", "phase", "variant"}


class JournalActionRequest(BaseModel):
    decision_id: int
    actor: str = "human"
    taken: bool = True
    fill_price: Optional[float] = None
    fill_time: Optional[str] = None
    size: Optional[float] = None
    notes: Optional[str] = None
    override_reason: Optional[str] = None

    @field_validator("actor")
    @classmethod
    def valid_actor(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"agent", "human"}:
            raise ValueError("actor must be agent or human")
        return normalized


class JournalOutcomeRequest(BaseModel):
    action_id: int
    exit_price: float
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    r_multiple: Optional[float] = None


def _journal() -> Journal:
    return Journal(DEFAULT_CONFIG["journal_path"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/decisions")
def list_decisions(
    symbol: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    where = "WHERE symbol = ?" if symbol else ""
    params: tuple[Any, ...] = (symbol.upper(),) if symbol else ()
    rows = _journal().query(
        f"""
        SELECT id, created_at, trade_datetime, symbol, trading_style, session_phase,
               data_session_date, variant, strategy_tag, setup_name, bias, entry,
               stop, target1, target2, time_stop, confidence, invalidation, rationale
        FROM decisions
        {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        params + (limit,),
    )
    return {"status": "ready", "decisions": rows}


@router.post("/actions")
def log_action(req: JournalActionRequest) -> Dict[str, Any]:
    try:
        action_id = _journal().record_action(
            decision_id=req.decision_id,
            actor=req.actor,
            taken=req.taken,
            fill_price=req.fill_price,
            fill_time=req.fill_time or _utc_now(),
            size=req.size,
            notes=req.notes,
            human_override_reason=req.override_reason,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ready", "action_id": action_id}


@router.post("/outcomes")
def log_outcome(req: JournalOutcomeRequest) -> Dict[str, Any]:
    try:
        outcome_id = _journal().record_outcome(
            action_id=req.action_id,
            exit_price=req.exit_price,
            exit_time=req.exit_time or _utc_now(),
            exit_reason=req.exit_reason,
            pnl=req.pnl,
            r_multiple=req.r_multiple,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ready", "outcome_id": outcome_id}


@router.get("/reports")
def get_report(
    by: str = Query(default="strategy"),
    since: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = by.strip().lower()
    if normalized not in _VALID_REPORTS:
        raise HTTPException(status_code=422, detail=f"by must be one of {_VALID_REPORTS}")

    journal = _journal()
    if normalized == "strategy":
        markdown = expectancy_by_strategy(journal, since=since)
    elif normalized == "actor":
        markdown = agent_vs_human(journal, since=since)
    elif normalized == "phase":
        markdown = session_phase_pnl(journal)
    else:
        markdown = variant_comparison(journal)

    return {
        "status": "ready",
        "by": normalized,
        "markdown": markdown,
        "rows": _parse_markdown_table(markdown),
    }


def _parse_markdown_table(markdown: str) -> List[Dict[str, str]]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return []
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: List[Dict[str, str]] = []
    for line in lines[2:]:
        values = [cell.strip() for cell in line.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows
