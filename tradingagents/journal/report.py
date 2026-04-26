"""Pre-canned analytics over the journal store.

All reports return markdown-friendly strings (consistent with how the rest
of TradingAgents renders analyst output).
"""
from __future__ import annotations

from typing import Optional

from .journal import Journal


def expectancy_by_strategy(journal: Journal, since: Optional[str] = None) -> str:
    """Per-strategy hit rate, average R, expectancy."""
    where = "WHERE d.created_at >= ?" if since else ""
    params: tuple = (since,) if since else ()
    rows = journal.query(
        f"""
        SELECT
            d.strategy_tag AS strategy,
            COUNT(o.id) AS n,
            SUM(CASE WHEN o.r_multiple > 0 THEN 1 ELSE 0 END) AS wins,
            AVG(o.r_multiple) AS avg_r,
            SUM(o.pnl) AS total_pnl
        FROM decisions d
        JOIN actions a ON a.decision_id = d.id
        JOIN outcomes o ON o.action_id = a.id
        {where}
        GROUP BY d.strategy_tag
        ORDER BY n DESC
        """,
        params,
    )
    if not rows:
        return "No closed trades to report yet."
    lines = ["| Strategy | Trades | Wins | Hit Rate | Avg R | Total PnL |",
             "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        n = r["n"] or 0
        wins = r["wins"] or 0
        hit = (wins / n * 100) if n else 0
        avg_r = r["avg_r"] or 0
        pnl = r["total_pnl"] or 0
        lines.append(
            f"| {r['strategy'] or 'unknown'} | {n} | {wins} | {hit:.1f}% | {avg_r:.2f} | {pnl:.2f} |"
        )
    return "\n".join(lines)


def agent_vs_human(journal: Journal, since: Optional[str] = None) -> str:
    """Compare actor performance on closed trades."""
    where = "WHERE d.created_at >= ?" if since else ""
    params: tuple = (since,) if since else ()
    rows = journal.query(
        f"""
        SELECT
            a.actor AS actor,
            COUNT(o.id) AS n,
            AVG(o.r_multiple) AS avg_r,
            SUM(o.pnl) AS total_pnl
        FROM decisions d
        JOIN actions a ON a.decision_id = d.id
        JOIN outcomes o ON o.action_id = a.id
        {where}
        GROUP BY a.actor
        """,
        params,
    )
    if not rows:
        return "No closed trades to compare."
    lines = ["| Actor | Trades | Avg R | Total PnL |", "|---|---:|---:|---:|"]
    for r in rows:
        lines.append(
            f"| {r['actor']} | {r['n']} | {(r['avg_r'] or 0):.2f} | {(r['total_pnl'] or 0):.2f} |"
        )
    return "\n".join(lines)


def session_phase_pnl(journal: Journal) -> str:
    """Group closed trades by the session phase the decision was made in."""
    rows = journal.query(
        """
        SELECT
            d.session_phase AS phase,
            COUNT(o.id) AS n,
            AVG(o.r_multiple) AS avg_r,
            SUM(o.pnl) AS total_pnl
        FROM decisions d
        JOIN actions a ON a.decision_id = d.id
        JOIN outcomes o ON o.action_id = a.id
        WHERE d.session_phase IS NOT NULL
        GROUP BY d.session_phase
        ORDER BY n DESC
        """
    )
    if not rows:
        return "No closed trades with session phase to compare."
    lines = ["| Phase | Trades | Avg R | Total PnL |", "|---|---:|---:|---:|"]
    for r in rows:
        lines.append(
            f"| {r['phase']} | {r['n']} | {(r['avg_r'] or 0):.2f} | {(r['total_pnl'] or 0):.2f} |"
        )
    return "\n".join(lines)


def variant_comparison(journal: Journal) -> str:
    """Compare prompt variants (A/B): decisions made + closed-trade performance."""
    rows = journal.query(
        """
        SELECT
            d.variant AS variant,
            COUNT(DISTINCT d.id) AS decisions,
            COUNT(o.id) AS closed,
            AVG(o.r_multiple) AS avg_r,
            SUM(o.pnl) AS total_pnl
        FROM decisions d
        LEFT JOIN actions a ON a.decision_id = d.id
        LEFT JOIN outcomes o ON o.action_id = a.id
        WHERE d.variant IS NOT NULL
        GROUP BY d.variant
        ORDER BY decisions DESC
        """
    )
    if not rows:
        return "No A/B variants in journal yet."
    lines = ["| Variant | Decisions | Closed Trades | Avg R | Total PnL |",
             "|---|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(
            f"| {r['variant']} | {r['decisions']} | {r['closed']} | "
            f"{(r['avg_r'] or 0):.2f} | {(r['total_pnl'] or 0):.2f} |"
        )
    return "\n".join(lines)
