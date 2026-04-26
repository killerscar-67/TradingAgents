"""CLI for the trading journal: log human actions/outcomes and run reports.

Examples:
    python -m cli.journal report --by strategy
    python -m cli.journal log-action --decision-id 42 --taken --fill-price 542.10 --size 100
    python -m cli.journal log-outcome --action-id 17 --exit-price 543.20 --exit-reason target
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.journal import Journal
from tradingagents.journal.report import (
    agent_vs_human,
    expectancy_by_strategy,
    session_phase_pnl,
    variant_comparison,
)

app = typer.Typer(name="journal", help="TradingAgents journal: log fills, outcomes, and reports.")
console = Console()


def _journal(path: Optional[str]) -> Journal:
    return Journal(path or DEFAULT_CONFIG["journal_path"])


@app.command("log-action")
def log_action(
    decision_id: int = typer.Option(..., "--decision-id"),
    actor: str = typer.Option("human", "--actor", help="agent | human"),
    taken: bool = typer.Option(True, "--taken/--skipped"),
    fill_price: Optional[float] = typer.Option(None, "--fill-price"),
    size: Optional[float] = typer.Option(None, "--size"),
    fill_time: Optional[str] = typer.Option(
        None, "--fill-time",
        help="ISO 8601 timestamp; defaults to now (UTC).",
    ),
    notes: Optional[str] = typer.Option(None, "--notes"),
    override_reason: Optional[str] = typer.Option(
        None, "--override-reason",
        help="Why the human deviated from the agent's setup.",
    ),
    db: Optional[str] = typer.Option(None, "--db", help="Override journal path."),
):
    """Record a fill (or skip) against an existing decision."""
    j = _journal(db)
    fill_time = fill_time or datetime.now(timezone.utc).isoformat(timespec="seconds")
    aid = j.record_action(
        decision_id=decision_id,
        actor=actor,
        taken=taken,
        fill_price=fill_price,
        fill_time=fill_time,
        size=size,
        notes=notes,
        human_override_reason=override_reason,
    )
    console.print(f"[green]Action recorded[/green] action_id={aid}")


@app.command("log-outcome")
def log_outcome(
    action_id: int = typer.Option(..., "--action-id"),
    exit_price: float = typer.Option(..., "--exit-price"),
    exit_time: Optional[str] = typer.Option(None, "--exit-time"),
    exit_reason: Optional[str] = typer.Option(
        None, "--exit-reason", help="target | stop | time_stop | manual",
    ),
    pnl: Optional[float] = typer.Option(None, "--pnl"),
    r_multiple: Optional[float] = typer.Option(None, "--r-multiple"),
    db: Optional[str] = typer.Option(None, "--db"),
):
    """Record the close of a position. PnL/R derived from the action+decision when omitted."""
    j = _journal(db)
    exit_time = exit_time or datetime.now(timezone.utc).isoformat(timespec="seconds")
    oid = j.record_outcome(
        action_id=action_id,
        exit_price=exit_price,
        exit_time=exit_time,
        exit_reason=exit_reason,
        pnl=pnl,
        r_multiple=r_multiple,
    )
    console.print(f"[green]Outcome recorded[/green] outcome_id={oid}")


@app.command("report")
def report(
    by: str = typer.Option("strategy", "--by", help="strategy | actor | phase | variant"),
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp lower bound."),
    db: Optional[str] = typer.Option(None, "--db"),
):
    """Render a markdown rollup of journal contents."""
    j = _journal(db)
    if by == "strategy":
        out = expectancy_by_strategy(j, since=since)
    elif by == "actor":
        out = agent_vs_human(j, since=since)
    elif by == "phase":
        out = session_phase_pnl(j)
    elif by == "variant":
        out = variant_comparison(j)
    else:
        raise typer.BadParameter(f"Unknown --by '{by}'. Choose: strategy, actor, phase, variant.")
    console.print(Markdown(out))


@app.command("list-decisions")
def list_decisions(
    symbol: Optional[str] = typer.Option(None, "--symbol"),
    limit: int = typer.Option(20, "--limit"),
    db: Optional[str] = typer.Option(None, "--db"),
):
    """List recent decisions for inspection."""
    j = _journal(db)
    where = "WHERE symbol = ?" if symbol else ""
    params = (symbol,) if symbol else ()
    rows = j.query(
        f"SELECT id, created_at, symbol, trading_style, variant, setup_name, bias, "
        f"entry, stop, target1, confidence FROM decisions {where} "
        f"ORDER BY id DESC LIMIT ?",
        params + (limit,),
    )
    if not rows:
        console.print("[yellow]No decisions found.[/yellow]")
        return
    t = Table(title="Recent decisions")
    for col in ("id", "created_at", "symbol", "style", "variant", "setup", "bias",
                "entry", "stop", "target1", "conf"):
        t.add_column(col)
    for r in rows:
        t.add_row(
            str(r["id"]), r["created_at"], r["symbol"], r["trading_style"],
            r["variant"] or "-", r["setup_name"] or "-", r["bias"] or "-",
            f"{r['entry']:.2f}" if r["entry"] is not None else "-",
            f"{r['stop']:.2f}" if r["stop"] is not None else "-",
            f"{r['target1']:.2f}" if r["target1"] is not None else "-",
            r["confidence"] or "-",
        )
    console.print(t)


if __name__ == "__main__":
    app()
