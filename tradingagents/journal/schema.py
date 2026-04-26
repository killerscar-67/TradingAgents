"""SQLite schema and idempotent migrations for the trading journal."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator


SCHEMA_VERSION = 1


_DDL = [
    # decisions: one row per propagate() call (or per A/B variant within a call).
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        trade_datetime TEXT NOT NULL,
        symbol TEXT NOT NULL,
        trading_style TEXT NOT NULL,
        session_phase TEXT,
        data_session_date TEXT,
        agent_version TEXT,
        variant TEXT,
        strategy_tag TEXT,
        setup_name TEXT,
        bias TEXT,
        entry REAL,
        stop REAL,
        target1 REAL,
        target2 REAL,
        time_stop TEXT,
        confidence TEXT,
        invalidation TEXT,
        rationale TEXT,
        raw_state_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_strategy ON decisions(strategy_tag)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_dt ON decisions(trade_datetime)",
    # actions: what was actually done (agent paper-trade or human fill).
    """
    CREATE TABLE IF NOT EXISTS actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id INTEGER NOT NULL,
        actor TEXT NOT NULL CHECK (actor IN ('agent', 'human')),
        taken INTEGER NOT NULL DEFAULT 1,
        fill_price REAL,
        fill_time TEXT,
        size REAL,
        notes TEXT,
        human_override_reason TEXT,
        FOREIGN KEY (decision_id) REFERENCES decisions(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_actions_decision ON actions(decision_id)",
    "CREATE INDEX IF NOT EXISTS idx_actions_actor ON actions(actor)",
    # outcomes: closed-position results, one per action.
    """
    CREATE TABLE IF NOT EXISTS outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL UNIQUE,
        exit_price REAL NOT NULL,
        exit_time TEXT NOT NULL,
        exit_reason TEXT,
        pnl REAL,
        r_multiple REAL,
        FOREIGN KEY (action_id) REFERENCES actions(id)
    )
    """,
    # strategies: optional named strategy definitions for A/B grouping.
    """
    CREATE TABLE IF NOT EXISTS strategies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        config_snapshot_json TEXT
    )
    """,
    # schema_meta: version tracking for future migrations.
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    """Yield a sqlite3 connection with foreign keys on and rows as dicts."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str) -> None:
    """Create tables if missing and stamp the schema version. Idempotent."""
    with connect(path) as conn:
        for stmt in _DDL:
            conn.execute(stmt)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
