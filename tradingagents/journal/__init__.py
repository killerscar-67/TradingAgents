"""Trading journal: persistent record of every decision, action, and outcome.

Used to evaluate (a) agent vs human decisions on the same setup,
(b) strategy-tag rollups over time, and (c) parallel prompt-variant A/B tests.
Backed by SQLite — query-friendly with no extra dependencies.
"""
from .journal import Journal
from .schema import init_db

__all__ = ["Journal", "init_db"]
