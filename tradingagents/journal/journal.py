"""Journal API: record decisions, actions, outcomes; query for analysis."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .schema import connect, init_db


def _agent_version_hash(config: Dict[str, Any]) -> str:
    """Stable short hash of the LLM/strategy-relevant config slice."""
    keys = (
        "llm_provider", "deep_think_llm", "quick_think_llm",
        "intraday_interval", "intraday_prompt_variants",
        "max_debate_rounds", "max_risk_discuss_rounds",
    )
    snapshot = {k: config.get(k) for k in keys}
    payload = json.dumps(snapshot, sort_keys=True, default=str).encode()
    return hashlib.sha1(payload).hexdigest()[:10]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Journal:
    """Lightweight wrapper around the journal SQLite store.

    All write methods are best-effort and never raise out of the graph hook
    (see `record_decision_safely`). Read methods may raise — callers are CLI
    code that wants to surface errors clearly.
    """

    def __init__(self, path: str):
        self.path = path
        init_db(self.path)

    # --- Writes -------------------------------------------------------------

    def record_decision(
        self,
        symbol: str,
        trading_style: str,
        decision: Dict[str, Any],
        state: Dict[str, Any],
        config: Dict[str, Any],
    ) -> int:
        """Insert one decision row. Returns the new decision_id."""
        with connect(self.path) as conn:
            cur = conn.execute(
                """
                INSERT INTO decisions (
                    created_at, trade_datetime, symbol, trading_style,
                    session_phase, data_session_date, agent_version, variant,
                    strategy_tag, setup_name, bias, entry, stop, target1, target2,
                    time_stop, confidence, invalidation, rationale, raw_state_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _utcnow_iso(),
                    state.get("trade_datetime") or state.get("trade_date") or "",
                    symbol,
                    trading_style,
                    state.get("session_phase"),
                    state.get("data_session_date"),
                    _agent_version_hash(config),
                    decision.get("variant"),
                    decision.get("setup_name"),  # strategy_tag == setup_name in v1
                    decision.get("setup_name"),
                    decision.get("bias"),
                    _coerce_float(decision.get("entry")),
                    _coerce_float(decision.get("stop")),
                    _coerce_float(decision.get("target1")),
                    _coerce_float(decision.get("target2")),
                    decision.get("time_stop"),
                    decision.get("confidence"),
                    decision.get("invalidation"),
                    decision.get("rationale"),
                    _safe_json(state),
                ),
            )
            return int(cur.lastrowid)

    def record_action(
        self,
        decision_id: int,
        actor: str,
        taken: bool = True,
        fill_price: Optional[float] = None,
        fill_time: Optional[str] = None,
        size: Optional[float] = None,
        notes: Optional[str] = None,
        human_override_reason: Optional[str] = None,
    ) -> int:
        """Record what was actually done. Returns the new action_id."""
        if actor not in ("agent", "human"):
            raise ValueError("actor must be 'agent' or 'human'")
        with connect(self.path) as conn:
            cur = conn.execute(
                """
                INSERT INTO actions (
                    decision_id, actor, taken, fill_price, fill_time, size,
                    notes, human_override_reason
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id, actor, 1 if taken else 0,
                    fill_price, fill_time, size, notes, human_override_reason,
                ),
            )
            return int(cur.lastrowid)

    def record_outcome(
        self,
        action_id: int,
        exit_price: float,
        exit_time: str,
        exit_reason: Optional[str] = None,
        pnl: Optional[float] = None,
        r_multiple: Optional[float] = None,
    ) -> int:
        """Record a closed position. PnL/R are computed if not supplied."""
        if pnl is None or r_multiple is None:
            pnl, r_multiple = self._derive_pnl(action_id, exit_price, pnl, r_multiple)
        with connect(self.path) as conn:
            cur = conn.execute(
                """
                INSERT INTO outcomes (
                    action_id, exit_price, exit_time, exit_reason, pnl, r_multiple
                ) VALUES (?,?,?,?,?,?)
                """,
                (action_id, exit_price, exit_time, exit_reason, pnl, r_multiple),
            )
            return int(cur.lastrowid)

    def record_decision_safely(
        self,
        symbol: str,
        trading_style: str,
        decisions: List[Dict[str, Any]],
        state: Dict[str, Any],
        config: Dict[str, Any],
        also_log_agent_action: bool = False,
    ) -> List[int]:
        """Wrap record_decision with broad exception handling.

        Used by the propagate() hook so a journal failure never breaks an
        analysis run. Returns the list of created decision_ids (empty on error).

        When `also_log_agent_action` is True, an `actions` row with actor='agent'
        is created for the first non-`no_trade` decision so the journal can
        compare the agent's stated intent against any human override later.
        """
        ids: List[int] = []
        try:
            for d in decisions:
                ids.append(self.record_decision(symbol, trading_style, d, state, config))
                if also_log_agent_action and d.get("bias") in ("long", "short"):
                    try:
                        self.record_action(
                            ids[-1], actor="agent", taken=True,
                            fill_price=_coerce_float(d.get("entry")),
                            fill_time=state.get("trade_datetime"),
                            notes=f"variant={d.get('variant')}",
                        )
                    except Exception as e:  # noqa: BLE001
                        # Don't let action-logging failure break decision logging.
                        print(f"[journal] action logging failed: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[journal] record_decision failed: {e}")
        return ids

    # --- Reads --------------------------------------------------------------

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with connect(self.path) as conn:
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def get_decision(self, decision_id: int) -> Optional[Dict[str, Any]]:
        rows = self.query("SELECT * FROM decisions WHERE id = ?", (decision_id,))
        return rows[0] if rows else None

    def get_action(self, action_id: int) -> Optional[Dict[str, Any]]:
        rows = self.query("SELECT * FROM actions WHERE id = ?", (action_id,))
        return rows[0] if rows else None

    # --- Internals ----------------------------------------------------------

    def _derive_pnl(
        self,
        action_id: int,
        exit_price: float,
        existing_pnl: Optional[float],
        existing_r: Optional[float],
    ) -> tuple[Optional[float], Optional[float]]:
        """Compute pnl and r_multiple from the action + decision rows when missing."""
        action = self.get_action(action_id)
        if not action:
            return existing_pnl, existing_r
        decision = self.get_decision(action["decision_id"])
        if not decision:
            return existing_pnl, existing_r

        fill = _coerce_float(action["fill_price"])
        size = _coerce_float(action["size"]) or 0.0
        bias = decision.get("bias")
        entry = _coerce_float(decision.get("entry")) or fill
        stop = _coerce_float(decision.get("stop"))

        pnl = existing_pnl
        if pnl is None and fill is not None:
            sign = 1 if bias == "long" else (-1 if bias == "short" else 0)
            pnl = sign * (exit_price - fill) * size

        r = existing_r
        if r is None and entry is not None and stop is not None and stop != entry:
            risk = abs(entry - stop)
            sign = 1 if bias == "long" else (-1 if bias == "short" else 0)
            r = sign * (exit_price - entry) / risk if risk > 0 else None

        return pnl, r


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json(obj: Any) -> str:
    """JSON-serialize, falling back to repr for unknown types (LangChain messages)."""
    return json.dumps(obj, default=lambda o: repr(o))
