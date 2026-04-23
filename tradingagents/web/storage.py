"""SQLite-backed persistence for Phase 10 workflow metadata."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_DB_PATH = Path.home() / ".tradingagents" / "web.sqlite3"
_SCHEMA_VERSION = 2
_STORE_LOCK = threading.Lock()
_STORES: Dict[str, "WorkflowStore"] = {}

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "home_market": "US",
    "output_language": "English",
    "calendar_provider": "fmp",
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "data_vendors": {"market": "yfinance"},
    "live_quote_mode": "delayed_fallback",
    "default_shortcut_universe": {
        "US": "S&P 500",
        "HK": "HSI",
        "JP": "Nikkei 225",
    },
    "workflow_defaults": {
        "top_n": 20,
        "min_score": 0.65,
        "risk_per_trade": 0.01,
        "portfolio_size": 100_000.0,
        "allow_shorts": True,
    },
    "broker": {
        "futu": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 11111,
        }
    },
}


def get_workflow_store() -> "WorkflowStore":
    db_path = str(_resolve_db_path())
    with _STORE_LOCK:
        store = _STORES.get(db_path)
        if store is None:
            store = WorkflowStore(Path(db_path))
            _STORES[db_path] = store
    return store


def _resolve_db_path() -> Path:
    configured = os.getenv("TRADINGAGENTS_WEB_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _DEFAULT_DB_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def _normalize_screen_name(screen_name: str) -> str:
    return screen_name.strip().lower().replace(" ", "_")


def _json_loads(payload: Optional[str], *, fallback: Any) -> Any:
    if not payload:
        return fallback
    return json.loads(payload)


def _existing_user_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class WorkflowStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._init_schema()

    def get_settings(self) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT values_json FROM settings WHERE singleton_id = 1"
            ).fetchone()
        values = _deep_merge(_DEFAULT_SETTINGS, _json_loads(row["values_json"], fallback={}) if row else {})
        values["status"] = "ready"
        return values

    def update_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        merged = _deep_merge(self.get_settings_without_status(), values)
        now = _utc_now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(singleton_id, values_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    values_json = excluded.values_json,
                    updated_at = excluded.updated_at
                """,
                (_json_dumps(merged), now),
            )
            conn.commit()
        merged["status"] = "ready"
        return merged

    def get_settings_without_status(self) -> Dict[str, Any]:
        values = self.get_settings()
        values.pop("status", None)
        return values

    def ensure_workflow_session(
        self,
        *,
        home_market: str,
        current_screen: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _utc_now()
        normalized_screen = _normalize_screen_name(current_screen)
        with self._write_lock, self._connect() as conn:
            if session_id:
                row = conn.execute(
                    "SELECT session_id, current_screen, home_market, status, created_at, updated_at, settings_snapshot_json, screening_run_id, basket_id, batch_id, strategy_id, backtest_id FROM workflow_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE workflow_sessions SET current_screen = ?, updated_at = ? WHERE session_id = ?",
                        (normalized_screen, now, session_id),
                    )
                    conn.commit()
                    return self.get_workflow_session(session_id) or {}

            new_session_id = f"session-{uuid.uuid4().hex[:12]}"
            snapshot = self.get_settings_without_status()
            conn.execute(
                """
                INSERT INTO workflow_sessions(
                    session_id, current_screen, home_market, status, settings_snapshot_json,
                    created_at, updated_at, screening_run_id, basket_id, batch_id, strategy_id, backtest_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
                """,
                (
                    new_session_id,
                    normalized_screen,
                    home_market,
                    "draft",
                    _json_dumps(snapshot),
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_workflow_session(new_session_id) or {}

    def get_workflow_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, current_screen, home_market, status, settings_snapshot_json, created_at, updated_at, screening_run_id, basket_id, batch_id, strategy_id, backtest_id FROM workflow_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return self._session_row_to_dict(row)

    def list_workflow_sessions(
        self,
        *,
        status: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        query = (
            "SELECT session_id, current_screen, home_market, status, settings_snapshot_json, created_at, updated_at, "
            "screening_run_id, basket_id, batch_id, strategy_id, backtest_id "
            "FROM workflow_sessions"
        )
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        elif not include_archived:
            clauses.append("status != 'archived'")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, created_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._session_row_to_dict(row) for row in rows]

    def update_workflow_session(
        self,
        session_id: str,
        *,
        current_screen: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_workflow_session(session_id)
        if existing is None:
            return None
        next_screen = _normalize_screen_name(current_screen) if current_screen else existing["current_screen"]
        next_status = status or existing["status"]
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE workflow_sessions SET current_screen = ?, status = ?, updated_at = ? WHERE session_id = ?",
                (next_screen, next_status, _utc_now(), session_id),
            )
            conn.commit()
        return self.get_workflow_session(session_id)

    def create_screening_run(
        self,
        payload: Dict[str, Any],
        *,
        home_market: str,
        workflow_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = self.ensure_workflow_session(
            home_market=home_market,
            current_screen="screen",
            session_id=workflow_session_id,
        )
        now = _utc_now()
        run = {
            **payload,
            "run_id": f"screening-{uuid.uuid4().hex[:12]}",
            "status": "ready",
            "created_at": now,
            "home_market": session["home_market"],
            "workflow_session_id": session["session_id"],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO screening_runs(
                    run_id, universe, strategy, trade_date, top_n, min_score,
                    filters_json, custom_symbols_json, regime_json, status,
                    created_at, home_market, workflow_session_id, request_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run.get("universe"),
                    run.get("strategy"),
                    run.get("trade_date"),
                    run.get("top_n"),
                    run.get("min_score"),
                    _json_dumps(run.get("filters", {})),
                    _json_dumps(run.get("custom_symbols", [])),
                    _json_dumps(run.get("regime") or {}),
                    run["status"],
                    run["created_at"],
                    run["home_market"],
                    run["workflow_session_id"],
                    _json_dumps(payload),
                    _json_dumps({}),
                ),
            )
            self._update_workflow_session_links(
                conn,
                session_id=run["workflow_session_id"],
                current_screen="screen",
                status="active",
                screening_run_id=run["run_id"],
            )
            conn.commit()
        return run

    def update_screening_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._write_lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT request_json, result_json, status FROM screening_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is None:
                return None
            next_status = status or existing["status"]
            next_result = result if result is not None else _json_loads(existing["result_json"], fallback={})
            conn.execute(
                "UPDATE screening_runs SET status = ?, result_json = ? WHERE run_id = ?",
                (next_status, _json_dumps(next_result), run_id),
            )
            conn.commit()
        return self.get_screening_run(run_id)

    def get_screening_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, universe, strategy, trade_date, top_n, min_score,
                       filters_json, custom_symbols_json, regime_json, status,
                       created_at, home_market, workflow_session_id, request_json, result_json
                FROM screening_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        result = _json_loads(row["result_json"], fallback={})
        return {
            "run_id": row["run_id"],
            "universe": row["universe"],
            "strategy": row["strategy"],
            "trade_date": row["trade_date"],
            "top_n": row["top_n"],
            "min_score": row["min_score"],
            "filters": _json_loads(row["filters_json"], fallback={}),
            "custom_symbols": _json_loads(row["custom_symbols_json"], fallback=[]),
            "regime": _json_loads(row["regime_json"], fallback={}),
            "status": row["status"],
            "created_at": row["created_at"],
            "home_market": row["home_market"],
            "workflow_session_id": row["workflow_session_id"],
            "request": _json_loads(row["request_json"], fallback={}),
            "results": result.get("results", []),
            "result": result,
        }

    def create_basket(
        self,
        payload: Dict[str, Any],
        *,
        home_market: str,
        workflow_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        requested_session_id = workflow_session_id or payload.get("workflow_session_id")
        if not requested_session_id and payload.get("source_screening_run_id"):
            requested_session_id = self._lookup_session_id_for_screening_run(payload["source_screening_run_id"])
        session = self.ensure_workflow_session(
            home_market=home_market,
            current_screen="analyze",
            session_id=requested_session_id,
        )
        now = _utc_now()
        basket = {
            **payload,
            "basket_id": f"basket-{uuid.uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
            "home_market": session["home_market"],
            "workflow_session_id": session["session_id"],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO baskets(
                    basket_id, name, symbols_json, items_json, source_screening_run_id,
                    created_at, updated_at, home_market, workflow_session_id, request_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    basket["basket_id"],
                    basket.get("name"),
                    _json_dumps(basket.get("symbols", [])),
                    _json_dumps(basket.get("items", [])),
                    basket.get("source_screening_run_id"),
                    basket["created_at"],
                    basket["updated_at"],
                    basket["home_market"],
                    basket["workflow_session_id"],
                    _json_dumps(payload),
                ),
            )
            self._update_workflow_session_links(
                conn,
                session_id=basket["workflow_session_id"],
                current_screen="analyze",
                status="active",
                basket_id=basket["basket_id"],
            )
            conn.commit()
        return basket

    def list_watchlists(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT watchlist_id, name, symbols_json, created_at, updated_at FROM watchlists ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
        return [
            {
                "watchlist_id": row["watchlist_id"],
                "name": row["name"],
                "symbols": _json_loads(row["symbols_json"], fallback=[]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def create_watchlist(self, name: str, symbols: List[str]) -> Dict[str, Any]:
        now = _utc_now()
        payload = {
            "watchlist_id": f"watchlist-{uuid.uuid4().hex[:12]}",
            "name": name,
            "symbols": symbols,
            "created_at": now,
            "updated_at": now,
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO watchlists(watchlist_id, name, symbols_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    payload["watchlist_id"],
                    payload["name"],
                    _json_dumps(payload["symbols"]),
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )
            conn.commit()
        return payload

    def list_strategy_presets(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT preset_id, name, portfolio_size, risk_per_trade, allow_shorts, config_json, created_at, updated_at
                FROM strategy_presets
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        return [
            {
                "preset_id": row["preset_id"],
                "name": row["name"],
                "portfolio_size": row["portfolio_size"],
                "risk_per_trade": row["risk_per_trade"],
                "allow_shorts": bool(row["allow_shorts"]),
                "config": _json_loads(row["config_json"], fallback={}),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def create_strategy_preset(
        self,
        name: str,
        portfolio_size: float,
        risk_per_trade: float,
        allow_shorts: bool,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = _utc_now()
        payload = {
            "preset_id": f"preset-{uuid.uuid4().hex[:12]}",
            "name": name,
            "portfolio_size": portfolio_size,
            "risk_per_trade": risk_per_trade,
            "allow_shorts": allow_shorts,
            "config": config,
            "created_at": now,
            "updated_at": now,
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_presets(
                    preset_id, name, portfolio_size, risk_per_trade, allow_shorts, config_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["preset_id"],
                    payload["name"],
                    payload["portfolio_size"],
                    payload["risk_per_trade"],
                    int(payload["allow_shorts"]),
                    _json_dumps(payload["config"]),
                    payload["created_at"],
                    payload["updated_at"],
                ),
            )
            conn.commit()
        return payload

    def create_analysis_batch(
        self,
        payload: Dict[str, Any],
        *,
        home_market: str,
        workflow_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        requested_session_id = workflow_session_id or payload.get("workflow_session_id")
        if not requested_session_id and payload.get("basket_id"):
            requested_session_id = self._lookup_session_id_for_basket(payload["basket_id"])
        session = self.ensure_workflow_session(
            home_market=home_market,
            current_screen="analyze",
            session_id=requested_session_id,
        )
        now = _utc_now()
        batch = {
            **payload,
            "batch_id": f"batch-{uuid.uuid4().hex[:12]}",
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "home_market": session["home_market"],
            "workflow_session_id": session["session_id"],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis_batches(
                    batch_id, basket_id, symbols_json, analysis_date, selected_analysts_json,
                    execution_mode, llm_provider, deep_think_llm, quick_think_llm,
                    status, created_at, updated_at, home_market, workflow_session_id, request_json,
                    items_json, summary_json, events_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch["batch_id"],
                    batch.get("basket_id"),
                    _json_dumps(batch.get("symbols", [])),
                    batch.get("analysis_date"),
                    _json_dumps(batch.get("selected_analysts", [])),
                    batch.get("execution_mode"),
                    batch.get("llm_provider"),
                    batch.get("deep_think_llm"),
                    batch.get("quick_think_llm"),
                    batch["status"],
                    batch["created_at"],
                    batch["updated_at"],
                    batch["home_market"],
                    batch["workflow_session_id"],
                    _json_dumps(payload),
                    _json_dumps([]),
                    _json_dumps({}),
                    _json_dumps([]),
                ),
            )
            self._update_workflow_session_links(
                conn,
                session_id=batch["workflow_session_id"],
                current_screen="strategy",
                status="active",
                basket_id=batch.get("basket_id"),
                batch_id=batch["batch_id"],
            )
            conn.commit()
        return batch

    def update_analysis_batch(
        self,
        batch_id: str,
        *,
        status: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
        summary: Optional[Dict[str, Any]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._write_lock, self._connect() as conn:
            existing = conn.execute(
                """
                SELECT status, items_json, summary_json, events_json
                FROM analysis_batches
                WHERE batch_id = ?
                """,
                (batch_id,),
            ).fetchone()
            if existing is None:
                return None
            conn.execute(
                """
                UPDATE analysis_batches
                SET status = ?, updated_at = ?, items_json = ?, summary_json = ?, events_json = ?
                WHERE batch_id = ?
                """,
                (
                    status or existing["status"],
                    _utc_now(),
                    _json_dumps(items if items is not None else _json_loads(existing["items_json"], fallback=[])),
                    _json_dumps(summary if summary is not None else _json_loads(existing["summary_json"], fallback={})),
                    _json_dumps(events if events is not None else _json_loads(existing["events_json"], fallback=[])),
                    batch_id,
                ),
            )
            conn.commit()
        return self.get_analysis_batch(batch_id)

    def get_analysis_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT batch_id, basket_id, symbols_json, analysis_date, selected_analysts_json,
                       execution_mode, llm_provider, deep_think_llm, quick_think_llm,
                       status, created_at, updated_at, home_market, workflow_session_id, request_json,
                       items_json, summary_json, events_json
                FROM analysis_batches
                WHERE batch_id = ?
                """,
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "batch_id": row["batch_id"],
            "basket_id": row["basket_id"],
            "symbols": _json_loads(row["symbols_json"], fallback=[]),
            "analysis_date": row["analysis_date"],
            "selected_analysts": _json_loads(row["selected_analysts_json"], fallback=[]),
            "execution_mode": row["execution_mode"],
            "llm_provider": row["llm_provider"],
            "deep_think_llm": row["deep_think_llm"],
            "quick_think_llm": row["quick_think_llm"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "home_market": row["home_market"],
            "workflow_session_id": row["workflow_session_id"],
            "request": _json_loads(row["request_json"], fallback={}),
            "items": _json_loads(row["items_json"], fallback=[]),
            "summary": _json_loads(row["summary_json"], fallback={}),
            "events": _json_loads(row["events_json"], fallback=[]),
        }

    def create_strategy_plan(
        self,
        payload: Dict[str, Any],
        *,
        home_market: str,
        workflow_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        requested_session_id = workflow_session_id or payload.get("workflow_session_id")
        if not requested_session_id and payload.get("batch_id"):
            requested_session_id = self._lookup_session_id_for_batch(payload["batch_id"])
        session = self.ensure_workflow_session(
            home_market=home_market,
            current_screen="strategy",
            session_id=requested_session_id,
        )
        now = _utc_now()
        strategy = {
            **payload,
            "strategy_id": f"strategy-{uuid.uuid4().hex[:12]}",
            "name": payload.get("name") or f"Strategy {now[:10]}",
            "created_at": now,
            "home_market": session["home_market"],
            "workflow_session_id": session["session_id"],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_runs(
                    strategy_id, batch_id, name, mode, horizon, portfolio_size,
                    risk_per_trade, allow_shorts, created_at, home_market, workflow_session_id, request_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy["strategy_id"],
                    strategy.get("batch_id"),
                    strategy["name"],
                    strategy.get("mode"),
                    strategy.get("horizon"),
                    strategy.get("portfolio_size"),
                    strategy.get("risk_per_trade"),
                    int(bool(strategy.get("allow_shorts", True))),
                    strategy["created_at"],
                    strategy["home_market"],
                    strategy["workflow_session_id"],
                    _json_dumps(payload),
                    _json_dumps({}),
                ),
            )
            self._update_workflow_session_links(
                conn,
                session_id=strategy["workflow_session_id"],
                current_screen="backtest",
                status="active",
                batch_id=strategy.get("batch_id"),
                strategy_id=strategy["strategy_id"],
            )
            conn.commit()
        return strategy

    def update_strategy_plan(
        self,
        strategy_id: str,
        *,
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        with self._write_lock, self._connect() as conn:
            row = conn.execute(
                "SELECT strategy_id FROM strategy_runs WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE strategy_runs SET result_json = ? WHERE strategy_id = ?",
                (_json_dumps(result), strategy_id),
            )
            conn.commit()
        return self.get_strategy_plan(strategy_id)

    def get_strategy_plan(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT strategy_id, batch_id, name, mode, horizon, portfolio_size, risk_per_trade,
                       allow_shorts, created_at, home_market, workflow_session_id, request_json, result_json
                FROM strategy_runs
                WHERE strategy_id = ?
                """,
                (strategy_id,),
            ).fetchone()
        if row is None:
            return None
        result = _json_loads(row["result_json"], fallback={})
        return {
            "strategy_id": row["strategy_id"],
            "batch_id": row["batch_id"],
            "name": row["name"],
            "mode": row["mode"],
            "horizon": row["horizon"],
            "portfolio_size": row["portfolio_size"],
            "risk_per_trade": row["risk_per_trade"],
            "allow_shorts": bool(row["allow_shorts"]),
            "created_at": row["created_at"],
            "home_market": row["home_market"],
            "workflow_session_id": row["workflow_session_id"],
            "request": _json_loads(row["request_json"], fallback={}),
            "result": result,
            "trades": result.get("trades", []),
            "exposure": result.get("exposure", {}),
            "risk": result.get("risk", {}),
        }

    def create_backtest_run(
        self,
        payload: Dict[str, Any],
        *,
        home_market: str,
        workflow_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        requested_session_id = workflow_session_id or payload.get("workflow_session_id")
        if not requested_session_id and payload.get("strategy_id"):
            requested_session_id = self._lookup_session_id_for_strategy(payload["strategy_id"])
        session = self.ensure_workflow_session(
            home_market=home_market,
            current_screen="backtest",
            session_id=requested_session_id,
        )
        now = _utc_now()
        backtest = {
            **payload,
            "backtest_id": f"backtest-{uuid.uuid4().hex[:12]}",
            "status": "queued",
            "created_at": now,
            "home_market": session["home_market"],
            "workflow_session_id": session["session_id"],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs(
                    backtest_id, strategy_id, symbols_json, start_date, end_date,
                    portfolio_size, config_json, execution_mode, llm_constructed,
                    status, created_at, home_market, workflow_session_id, result_json, error,
                    completed_at, events_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    backtest["backtest_id"],
                    backtest.get("strategy_id"),
                    _json_dumps(backtest.get("symbols", [])),
                    backtest.get("start_date"),
                    backtest.get("end_date"),
                    backtest.get("portfolio_size"),
                    _json_dumps(backtest.get("config", {})),
                    backtest.get("execution_mode"),
                    int(bool(backtest.get("llm_constructed", False))),
                    backtest["status"],
                    backtest["created_at"],
                    backtest["home_market"],
                    backtest["workflow_session_id"],
                    _json_dumps({}),
                    None,
                    None,
                    _json_dumps([]),
                ),
            )
            self._update_workflow_session_links(
                conn,
                session_id=backtest["workflow_session_id"],
                current_screen="backtest",
                status="active",
                strategy_id=backtest.get("strategy_id"),
                backtest_id=backtest["backtest_id"],
            )
            conn.commit()
        return backtest

    def update_backtest_run(
        self,
        backtest_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._write_lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT status, result_json, error, events_json FROM backtest_runs WHERE backtest_id = ?",
                (backtest_id,),
            ).fetchone()
            if existing is None:
                return None
            next_status = status or existing["status"]
            next_result = result if result is not None else _json_loads(existing["result_json"], fallback={})
            next_events = events if events is not None else _json_loads(existing["events_json"], fallback=[])
            completed_at = _utc_now() if next_status in {"completed", "error"} else None
            conn.execute(
                """
                UPDATE backtest_runs
                SET status = ?, result_json = ?, error = ?, completed_at = ?, events_json = ?
                WHERE backtest_id = ?
                """,
                (
                    next_status,
                    _json_dumps(next_result),
                    error,
                    completed_at,
                    _json_dumps(next_events),
                    backtest_id,
                ),
            )
            if next_status in {"completed", "error"}:
                row = conn.execute(
                    "SELECT workflow_session_id, strategy_id FROM backtest_runs WHERE backtest_id = ?",
                    (backtest_id,),
                ).fetchone()
                if row:
                    self._update_workflow_session_links(
                        conn,
                        session_id=row["workflow_session_id"],
                        current_screen="backtest",
                        status="completed",
                        strategy_id=row["strategy_id"],
                        backtest_id=backtest_id,
                    )
            conn.commit()
        return self.get_backtest_run(backtest_id)

    def get_backtest_run(self, backtest_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT backtest_id, strategy_id, symbols_json, start_date, end_date, portfolio_size,
                       config_json, execution_mode, llm_constructed, status, created_at, home_market,
                       workflow_session_id, result_json, error, completed_at, events_json
                FROM backtest_runs
                WHERE backtest_id = ?
                """,
                (backtest_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "backtest_id": row["backtest_id"],
            "strategy_id": row["strategy_id"],
            "symbols": _json_loads(row["symbols_json"], fallback=[]),
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "portfolio_size": row["portfolio_size"],
            "config": _json_loads(row["config_json"], fallback={}),
            "execution_mode": row["execution_mode"],
            "llm_constructed": bool(row["llm_constructed"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "home_market": row["home_market"],
            "workflow_session_id": row["workflow_session_id"],
            "result": _json_loads(row["result_json"], fallback={}),
            "error": row["error"],
            "completed_at": row["completed_at"],
            "events": _json_loads(row["events_json"], fallback=[]),
        }

    def create_broker_stage_request(
        self,
        payload: Dict[str, Any],
        *,
        home_market: str,
        workflow_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        requested_session_id = workflow_session_id or payload.get("workflow_session_id")
        if not requested_session_id and payload.get("strategy_id"):
            requested_session_id = self._lookup_session_id_for_strategy(payload["strategy_id"])
        session = self.ensure_workflow_session(
            home_market=home_market,
            current_screen="strategy",
            session_id=requested_session_id,
        )
        now = _utc_now()
        stage_request = {
            **payload,
            "stage_id": f"stage-{uuid.uuid4().hex[:12]}",
            "status": "staged",
            "created_at": now,
            "home_market": session["home_market"],
            "workflow_session_id": session["session_id"],
        }
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO broker_stage_requests(
                    stage_id, strategy_id, orders_json, stage_only, submits_orders,
                    status, created_at, home_market, workflow_session_id, request_json,
                    response_json, completed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stage_request["stage_id"],
                    stage_request.get("strategy_id"),
                    _json_dumps(stage_request.get("orders", [])),
                    int(bool(stage_request.get("stage_only", True))),
                    int(bool(stage_request.get("submits_orders", False))),
                    stage_request["status"],
                    stage_request["created_at"],
                    stage_request["home_market"],
                    stage_request["workflow_session_id"],
                    _json_dumps(payload),
                    _json_dumps({}),
                    None,
                    None,
                ),
            )
            self._update_workflow_session_links(
                conn,
                session_id=stage_request["workflow_session_id"],
                current_screen="strategy",
                status="completed",
                strategy_id=stage_request.get("strategy_id"),
            )
            conn.commit()
        return stage_request

    def update_broker_stage_request(
        self,
        stage_id: str,
        *,
        status: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._write_lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT status, response_json FROM broker_stage_requests WHERE stage_id = ?",
                (stage_id,),
            ).fetchone()
            if existing is None:
                return None
            next_status = status or existing["status"]
            next_response = response if response is not None else _json_loads(existing["response_json"], fallback={})
            completed_at = _utc_now() if next_status in {"staged", "failed"} else None
            conn.execute(
                """
                UPDATE broker_stage_requests
                SET status = ?, response_json = ?, completed_at = ?, error = ?
                WHERE stage_id = ?
                """,
                (next_status, _json_dumps(next_response), completed_at, error, stage_id),
            )
            conn.commit()
        return self.get_broker_stage_request(stage_id)

    def get_broker_stage_request(self, stage_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT stage_id, strategy_id, orders_json, stage_only, submits_orders, status, created_at,
                       home_market, workflow_session_id, request_json, response_json, completed_at, error
                FROM broker_stage_requests
                WHERE stage_id = ?
                """,
                (stage_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "stage_id": row["stage_id"],
            "strategy_id": row["strategy_id"],
            "orders": _json_loads(row["orders_json"], fallback=[]),
            "stage_only": bool(row["stage_only"]),
            "submits_orders": bool(row["submits_orders"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "home_market": row["home_market"],
            "workflow_session_id": row["workflow_session_id"],
            "request": _json_loads(row["request_json"], fallback={}),
            "response": _json_loads(row["response_json"], fallback={}),
            "completed_at": row["completed_at"],
            "error": row["error"],
        }

    def get_basket(self, basket_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT basket_id, name, symbols_json, items_json, source_screening_run_id,
                       created_at, updated_at, home_market, workflow_session_id, request_json
                FROM baskets
                WHERE basket_id = ?
                """,
                (basket_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "basket_id": row["basket_id"],
            "name": row["name"],
            "symbols": _json_loads(row["symbols_json"], fallback=[]),
            "items": _json_loads(row["items_json"], fallback=[]),
            "source_screening_run_id": row["source_screening_run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "home_market": row["home_market"],
            "workflow_session_id": row["workflow_session_id"],
            "request": _json_loads(row["request_json"], fallback={}),
        }

    def list_history_items(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        with self._connect() as conn:
            items.extend(self._fetch_screening_history(conn))
            items.extend(self._fetch_basket_history(conn))
            items.extend(self._fetch_batch_history(conn))
            items.extend(self._fetch_strategy_history(conn))
            items.extend(self._fetch_backtest_history(conn))
            items.extend(self._fetch_stage_history(conn))
        return sorted(
            items,
            key=lambda item: item.get("completed_at") or item.get("created_at") or "",
            reverse=True,
        )

    def _fetch_screening_history(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT run_id, universe, status, created_at, home_market, workflow_session_id, result_json FROM screening_runs"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            result = _json_loads(row["result_json"], fallback={})
            items.append(
                {
                    "type": "screening_run",
                    "id": row["run_id"],
                    "title": row["universe"] or row["run_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "completed_at": result.get("completed_at") or row["created_at"],
                    "home_market": row["home_market"],
                    "workflow_session_id": row["workflow_session_id"],
                    "summary": result.get("summary"),
                }
            )
        return items

    def _fetch_basket_history(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT basket_id, name, created_at, updated_at, home_market, workflow_session_id FROM baskets"
        ).fetchall()
        return [
            {
                "type": "basket",
                "id": row["basket_id"],
                "title": row["name"] or row["basket_id"],
                "status": "saved",
                "created_at": row["created_at"],
                "completed_at": row["updated_at"],
                "home_market": row["home_market"],
                "workflow_session_id": row["workflow_session_id"],
            }
            for row in rows
        ]

    def _fetch_batch_history(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT batch_id, status, created_at, updated_at, home_market, symbols_json, workflow_session_id, summary_json FROM analysis_batches"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            summary = _json_loads(row["summary_json"], fallback={})
            items.append(
                {
                    "type": "batch_analysis",
                    "id": row["batch_id"],
                    "title": summary.get("title") or ", ".join(_json_loads(row["symbols_json"], fallback=[])) or row["batch_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "completed_at": summary.get("completed_at") or row["updated_at"],
                    "home_market": row["home_market"],
                    "workflow_session_id": row["workflow_session_id"],
                    "summary": summary.get("headline"),
                }
            )
        return items

    def _fetch_strategy_history(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT strategy_id, name, created_at, home_market, workflow_session_id, result_json FROM strategy_runs"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            result = _json_loads(row["result_json"], fallback={})
            items.append(
                {
                    "type": "strategy_plan",
                    "id": row["strategy_id"],
                    "title": row["name"],
                    "status": result.get("status", "saved"),
                    "created_at": row["created_at"],
                    "completed_at": result.get("completed_at") or row["created_at"],
                    "home_market": row["home_market"],
                    "workflow_session_id": row["workflow_session_id"],
                    "summary": result.get("headline"),
                }
            )
        return items

    def _fetch_backtest_history(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT backtest_id, status, created_at, completed_at, home_market, strategy_id, workflow_session_id, result_json FROM backtest_runs"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            result = _json_loads(row["result_json"], fallback={})
            items.append(
                {
                    "type": "backtest_run",
                    "id": row["backtest_id"],
                    "title": row["strategy_id"] or row["backtest_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                    "home_market": row["home_market"],
                    "workflow_session_id": row["workflow_session_id"],
                    "summary": result.get("headline"),
                }
            )
        return items

    def _fetch_stage_history(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT stage_id, status, created_at, completed_at, home_market, strategy_id, workflow_session_id, response_json FROM broker_stage_requests"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            response = _json_loads(row["response_json"], fallback={})
            items.append(
                {
                    "type": "broker_stage_request",
                    "id": row["stage_id"],
                    "title": row["strategy_id"] or row["stage_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"] or row["created_at"],
                    "home_market": row["home_market"],
                    "workflow_session_id": row["workflow_session_id"],
                    "summary": response.get("headline"),
                }
            )
        return items

    def _lookup_session_id_for_screening_run(self, run_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT workflow_session_id FROM screening_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row["workflow_session_id"] if row else None

    def _lookup_session_id_for_basket(self, basket_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT workflow_session_id FROM baskets WHERE basket_id = ?",
                (basket_id,),
            ).fetchone()
        return row["workflow_session_id"] if row else None

    def _lookup_session_id_for_batch(self, batch_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT workflow_session_id FROM analysis_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        return row["workflow_session_id"] if row else None

    def _lookup_session_id_for_strategy(self, strategy_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT workflow_session_id FROM strategy_runs WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return row["workflow_session_id"] if row else None

    def _update_workflow_session_links(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        current_screen: str,
        status: str,
        screening_run_id: Optional[str] = None,
        basket_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        backtest_id: Optional[str] = None,
    ) -> None:
        existing = conn.execute(
            "SELECT screening_run_id, basket_id, batch_id, strategy_id, backtest_id FROM workflow_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not existing:
            return
        now = _utc_now()
        conn.execute(
            """
            UPDATE workflow_sessions
            SET current_screen = ?,
                status = ?,
                updated_at = ?,
                screening_run_id = ?,
                basket_id = ?,
                batch_id = ?,
                strategy_id = ?,
                backtest_id = ?
            WHERE session_id = ?
            """,
            (
                _normalize_screen_name(current_screen),
                status,
                now,
                screening_run_id or existing["screening_run_id"],
                basket_id or existing["basket_id"],
                batch_id or existing["batch_id"],
                strategy_id or existing["strategy_id"],
                backtest_id or existing["backtest_id"],
                session_id,
            ),
        )

    def _session_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "current_screen": row["current_screen"],
            "home_market": row["home_market"],
            "status": row["status"],
            "settings_snapshot": _json_loads(row["settings_snapshot_json"], fallback={}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "screening_run_id": row["screening_run_id"],
            "basket_id": row["basket_id"],
            "batch_id": row["batch_id"],
            "strategy_id": row["strategy_id"],
            "backtest_id": row["backtest_id"],
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._write_lock, self._connect() as conn:
            existing_tables = _existing_user_tables(conn)
            if existing_tables:
                if "schema_version" not in existing_tables:
                    raise RuntimeError(
                        "Existing workflow database is missing schema_version metadata. "
                        "Create a fresh database or add an explicit migration before reuse."
                    )

                version_row = conn.execute(
                    "SELECT version FROM schema_version WHERE singleton_id = 1"
                ).fetchone()
                if version_row is None:
                    raise RuntimeError(
                        "Workflow database schema_version table is present but uninitialized. "
                        "Add an explicit migration before reuse."
                    )
                if version_row["version"] != _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Unsupported workflow database schema version {version_row['version']}; expected {_SCHEMA_VERSION}."
                    )

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    values_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_sessions (
                    session_id TEXT PRIMARY KEY,
                    current_screen TEXT NOT NULL,
                    home_market TEXT NOT NULL,
                    status TEXT NOT NULL,
                    settings_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    screening_run_id TEXT,
                    basket_id TEXT,
                    batch_id TEXT,
                    strategy_id TEXT,
                    backtest_id TEXT
                );

                CREATE TABLE IF NOT EXISTS screening_runs (
                    run_id TEXT PRIMARY KEY,
                    universe TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    top_n INTEGER NOT NULL,
                    min_score REAL NOT NULL,
                    filters_json TEXT NOT NULL,
                    custom_symbols_json TEXT NOT NULL,
                    regime_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    home_market TEXT,
                    workflow_session_id TEXT,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS baskets (
                    basket_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    source_screening_run_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    home_market TEXT,
                    workflow_session_id TEXT,
                    request_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watchlists (
                    watchlist_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_presets (
                    preset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    portfolio_size REAL NOT NULL,
                    risk_per_trade REAL NOT NULL,
                    allow_shorts INTEGER NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_batches (
                    batch_id TEXT PRIMARY KEY,
                    basket_id TEXT,
                    symbols_json TEXT NOT NULL,
                    analysis_date TEXT,
                    selected_analysts_json TEXT NOT NULL,
                    execution_mode TEXT,
                    llm_provider TEXT,
                    deep_think_llm TEXT,
                    quick_think_llm TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    home_market TEXT,
                    workflow_session_id TEXT,
                    request_json TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    events_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategy_runs (
                    strategy_id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    name TEXT NOT NULL,
                    mode TEXT,
                    horizon TEXT,
                    portfolio_size REAL NOT NULL,
                    risk_per_trade REAL NOT NULL,
                    allow_shorts INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    home_market TEXT,
                    workflow_session_id TEXT,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    backtest_id TEXT PRIMARY KEY,
                    strategy_id TEXT,
                    symbols_json TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    portfolio_size REAL NOT NULL,
                    config_json TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    llm_constructed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    home_market TEXT,
                    workflow_session_id TEXT,
                    result_json TEXT NOT NULL,
                    error TEXT,
                    completed_at TEXT,
                    events_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS broker_stage_requests (
                    stage_id TEXT PRIMARY KEY,
                    strategy_id TEXT,
                    orders_json TEXT NOT NULL,
                    stage_only INTEGER NOT NULL,
                    submits_orders INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    home_market TEXT,
                    workflow_session_id TEXT,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT
                );
                """
            )

            version_row = conn.execute(
                "SELECT version FROM schema_version WHERE singleton_id = 1"
            ).fetchone()
            if version_row is None:
                if existing_tables:
                    raise RuntimeError(
                        "Workflow database schema_version table is present but uninitialized. "
                        "Add an explicit migration before reuse."
                    )
                conn.execute(
                    "INSERT INTO schema_version(singleton_id, version, updated_at) VALUES (1, ?, ?)",
                    (_SCHEMA_VERSION, _utc_now()),
                )
            elif version_row["version"] != _SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported workflow database schema version {version_row['version']}; expected {_SCHEMA_VERSION}."
                )

            row = conn.execute(
                "SELECT COUNT(*) AS count FROM settings WHERE singleton_id = 1"
            ).fetchone()
            if row["count"] == 0:
                conn.execute(
                    "INSERT INTO settings(singleton_id, values_json, updated_at) VALUES (1, ?, ?)",
                    (_json_dumps(_DEFAULT_SETTINGS), _utc_now()),
                )
            conn.commit()
