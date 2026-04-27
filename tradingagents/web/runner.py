"""Shared analysis runner for CLI and web UI (Phase 9).

AnalysisRunner owns the LangGraph streaming loop, event emission, and
run_state.json persistence.  The CLI calls run_sync(); FastAPI calls
run_background() which drives run_sync() in a thread.
"""

from __future__ import annotations

import datetime
import json
import queue
import threading
import traceback
import uuid
from dataclasses import fields
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.web.models import AnalysisRun, RunStatus, SseEvent


# Sentinel placed in per-run event queues when the run is done.
_DONE = object()

# Registry: run_id -> (AnalysisRun, Queue[SseEvent | _DONE])
_registry: Dict[str, tuple] = {}
_registry_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def create_run(
    ticker: str,
    analysis_date: str,
    selected_analysts: List[str],
    execution_mode: str,
    llm_provider: str,
    deep_think_llm: str,
    quick_think_llm: str,
    trading_style: str = "swing",
    intraday_interval: Optional[str] = None,
    trade_datetime: Optional[str] = None,
    include_extended_hours: Optional[bool] = None,
) -> AnalysisRun:
    run_id = str(uuid.uuid4())
    run = AnalysisRun(
        run_id=run_id,
        ticker=ticker,
        analysis_date=analysis_date,
        selected_analysts=selected_analysts,
        execution_mode=execution_mode,
        llm_provider=llm_provider,
        deep_think_llm=deep_think_llm,
        quick_think_llm=quick_think_llm,
        created_at=_now(),
        trading_style=trading_style,
        intraday_interval=intraday_interval,
        trade_datetime=trade_datetime,
        include_extended_hours=include_extended_hours,
    )
    q: queue.Queue = queue.Queue()
    with _registry_lock:
        _registry[run_id] = (run, q)
    return run


def get_run(run_id: str) -> Optional[AnalysisRun]:
    with _registry_lock:
        entry = _registry.get(run_id)
    if entry:
        return entry[0]
    return load_run_from_disk(run_id)


def get_event_queue(run_id: str) -> Optional[queue.Queue]:
    with _registry_lock:
        entry = _registry.get(run_id)
    return entry[1] if entry else None


def run_background(run_id: str, config: Optional[Dict[str, Any]] = None) -> None:
    """Start analysis in a daemon thread; returns immediately."""
    t = threading.Thread(target=_run_thread, args=(run_id, config), daemon=True)
    t.start()


def list_runs() -> List[AnalysisRun]:
    """Return known web runs from memory and persisted run_state.json files."""
    runs: Dict[str, AnalysisRun] = {}
    for run in _load_runs_from_disk():
        runs[run.run_id] = run

    with _registry_lock:
        for run, _ in _registry.values():
            runs[run.run_id] = run

    return sorted(
        runs.values(),
        key=lambda r: r.completed_at or r.started_at or r.created_at,
        reverse=True,
    )


def load_run_from_disk(run_id: str) -> Optional[AnalysisRun]:
    """Load a persisted run into memory so archived reports can be revisited."""
    for run in _load_runs_from_disk():
        if run.run_id == run_id:
            _register_run(run)
            return run
    return None


# ---------------------------------------------------------------------------
# Core streaming loop — shared by CLI (run_sync) and background thread
# ---------------------------------------------------------------------------

def run_sync(
    run_id: str,
    config: Optional[Dict[str, Any]] = None,
    on_chunk: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_event: Optional[Callable[[SseEvent], None]] = None,
    _graph_factory: Optional[Callable] = None,
    _stats_factory: Optional[Callable] = None,
    _save_report: Optional[Callable] = None,
) -> Optional[AnalysisRun]:
    """Drive the LangGraph stream and call on_chunk/on_event for each update.

    Returns the final AnalysisRun (or None if run_id unknown).
    """
    run = get_run(run_id)
    if run is None:
        return None

    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    cfg["llm_provider"] = run.llm_provider
    cfg["deep_think_llm"] = run.deep_think_llm
    cfg["quick_think_llm"] = run.quick_think_llm
    cfg["execution_mode"] = run.execution_mode
    cfg["trading_style"] = run.trading_style
    if run.intraday_interval:
        cfg["intraday_interval"] = run.intraday_interval
    if run.trade_datetime:
        cfg["trade_datetime"] = run.trade_datetime
    if run.include_extended_hours is not None:
        cfg["include_extended_hours"] = run.include_extended_hours

    if _graph_factory is None:
        # Lazy import so web module can be imported without installing all deps.
        from tradingagents.graph.trading_graph import TradingAgentsGraph as GraphClass
    else:
        GraphClass = _graph_factory

    if _stats_factory is None:
        from cli.stats_handler import StatsCallbackHandler as StatsClass
    else:
        StatsClass = _stats_factory

    if _save_report is None:
        from cli.main import save_report_to_disk as save_fn
    else:
        save_fn = _save_report

    _update_run(run, status="running", started_at=_now())
    _emit(run_id, "status", {"status": "running"})

    stats_handler = StatsClass()

    try:
        graph = GraphClass(
            selected_analysts=run.selected_analysts,
            config=cfg,
        )

        graph_trade_date = run.trade_datetime if run.trading_style == "daytrade" and run.trade_datetime else run.analysis_date
        init_state = graph.propagator.create_initial_state(
            run.ticker,
            graph_trade_date,
            trading_style=run.trading_style,
        )
        args = graph.propagator.get_graph_args(callbacks=[stats_handler])

        seq = [0]
        trace = []

        for chunk in graph.graph.stream(init_state, **args):
            trace.append(chunk)

            # Emit agent/report events derived from chunk
            _process_chunk(run_id, chunk, seq)

            if on_chunk:
                on_chunk(chunk)

        final_state = trace[-1] if trace else {}

        # Build order intent
        order_intent: Dict[str, Any] = {}
        final_decision = final_state.get("final_trade_decision", "")
        if final_decision:
            try:
                intent_dict = graph.build_order_intent(
                    run.ticker,
                    run.analysis_date,
                    final_decision,
                )
                order_intent = intent_dict if isinstance(intent_dict, dict) else intent_dict.to_dict()
            except Exception:
                pass

        # Collect report sections
        report_section_keys = [
            "market_report",
            "sentiment_report",
            "news_report",
            "fundamentals_report",
            "investment_plan",
            "trader_investment_plan",
            "final_trade_decision",
        ]
        for key in report_section_keys:
            val = final_state.get(key)
            if val:
                run.report_sections[key] = val

        if run.trading_style == "daytrade":
            decisions = final_state.get("intraday_decisions") or []
            run.intraday_decisions = decisions if isinstance(decisions, list) else []
            run.session_phase = final_state.get("session_phase") or run.session_phase
            run.data_session_date = final_state.get("data_session_date") or run.data_session_date
            if final_state.get("trade_datetime"):
                run.trade_datetime = final_state.get("trade_datetime")

        # Debate sections
        inv_debate = final_state.get("investment_debate_state") or {}
        if isinstance(inv_debate, dict):
            for sub in ("bull_history", "bear_history", "judge_decision"):
                val = inv_debate.get(sub)
                if val:
                    run.report_sections[f"investment_debate_{sub}"] = val

        risk_debate = final_state.get("risk_debate_state") or {}
        if isinstance(risk_debate, dict):
            for sub in ("aggressive_history", "conservative_history", "neutral_history", "judge_decision"):
                val = risk_debate.get(sub)
                if val:
                    run.report_sections[f"risk_debate_{sub}"] = val

        # Save reports to disk
        results_dir = Path(cfg.get("results_dir", DEFAULT_CONFIG["results_dir"])).expanduser()
        web_run_dir = results_dir / run.ticker / run.analysis_date / "web_runs" / run_id
        reports_dir = web_run_dir / "reports"
        try:
            save_fn(final_state, run.ticker, reports_dir)
            run.report_paths = {
                str(p.relative_to(reports_dir)): str(p)
                for p in reports_dir.rglob("*.md")
            }
        except Exception:
            pass

        run.stats = stats_handler.get_stats()
        run.final_order_intent = order_intent or None

        _emit(run_id, "final_state", {
            "order_intent": order_intent,
            "stats": run.stats,
        })
        _update_run(run, status="completed", completed_at=_now())
        _emit(run_id, "status", {"status": "completed"})

        # Persist run state
        _write_run_state(run, web_run_dir)

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        run.errors.append(error_msg)
        _emit(run_id, "error", {"message": error_msg})
        _update_run(run, status="error", completed_at=_now())
        _emit(run_id, "status", {"status": "error"})
        _write_run_state(run, _fallback_run_dir(cfg, run))

    finally:
        q = get_event_queue(run_id)
        if q is not None:
            q.put(_DONE)

    if on_event:
        pass  # on_event is called inside _emit — nothing extra needed

    return run


def load_report_sections_from_events(run_id: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    for event_dict in load_events_from_disk(run_id):
        if not isinstance(event_dict, dict) or event_dict.get("type") != "report_section":
            continue
        payload = event_dict.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        key = payload.get("key")
        content = payload.get("content")
        if isinstance(key, str) and isinstance(content, str) and content.strip():
            sections[key] = content
    return sections


def infer_resume_phase(report_sections: Dict[str, str]) -> Optional[str]:
    if report_sections.get("final_trade_decision"):
        return None
    if (
        report_sections.get("trader_investment_plan")
        or report_sections.get("risk_debate_aggressive_history")
        or report_sections.get("risk_debate_conservative_history")
        or report_sections.get("risk_debate_neutral_history")
    ):
        return "risk"
    if report_sections.get("investment_debate_judge_decision") or report_sections.get("investment_plan"):
        return "trader"
    if any(
        report_sections.get(key)
        for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report")
    ):
        return "research"
    return None


def run_resumed_sync(
    run_id: str,
    resume_from: str,
    checkpoint_sections: Dict[str, str],
    config: Optional[Dict[str, Any]] = None,
    _graph_factory: Optional[Callable] = None,
    _save_report: Optional[Callable] = None,
) -> Optional[AnalysisRun]:
    run = get_run(run_id)
    if run is None:
        return None

    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    cfg["llm_provider"] = run.llm_provider
    cfg["deep_think_llm"] = run.deep_think_llm
    cfg["quick_think_llm"] = run.quick_think_llm
    cfg["execution_mode"] = run.execution_mode
    cfg["trading_style"] = run.trading_style
    if run.intraday_interval:
        cfg["intraday_interval"] = run.intraday_interval
    if run.trade_datetime:
        cfg["trade_datetime"] = run.trade_datetime
    if run.include_extended_hours is not None:
        cfg["include_extended_hours"] = run.include_extended_hours

    if _graph_factory is None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph as GraphClass
    else:
        GraphClass = _graph_factory

    if _save_report is None:
        from cli.main import save_report_to_disk as save_fn
    else:
        save_fn = _save_report

    from tradingagents.agents import (
        create_aggressive_debator,
        create_bear_researcher,
        create_bull_researcher,
        create_conservative_debator,
        create_neutral_debator,
        create_portfolio_manager,
        create_research_manager,
        create_trader,
    )

    def apply_update(state: Dict[str, Any], update: Dict[str, Any]) -> None:
        for key, value in update.items():
            state[key] = value

    def emit_section(key: str, content: str) -> None:
        if content:
            _emit(run_id, "report_section", {"key": key, "content": content})

    def emit_agent(agent: str) -> None:
        _emit(run_id, "agent_status", {"agent": agent, "status": "completed"})

    def run_research_phase(graph, state: Dict[str, Any]) -> None:
        bull_node = create_bull_researcher(graph.quick_thinking_llm, graph.bull_memory)
        bear_node = create_bear_researcher(graph.quick_thinking_llm, graph.bear_memory)
        manager_node = create_research_manager(graph.deep_thinking_llm, graph.invest_judge_memory)

        while True:
            next_step = graph.conditional_logic.should_continue_debate(state)
            if next_step == "Research Manager":
                apply_update(state, manager_node(state))
                debate = state.get("investment_debate_state") or {}
                emit_section("investment_debate_bull_history", debate.get("bull_history", ""))
                emit_section("investment_debate_bear_history", debate.get("bear_history", ""))
                emit_section("investment_debate_judge_decision", debate.get("judge_decision", ""))
                emit_agent("Research Manager")
                break
            if next_step == "Bull Researcher":
                apply_update(state, bull_node(state))
                debate = state.get("investment_debate_state") or {}
                emit_section("investment_debate_bull_history", debate.get("bull_history", ""))
                emit_agent("Bull Researcher")
                continue
            apply_update(state, bear_node(state))
            debate = state.get("investment_debate_state") or {}
            emit_section("investment_debate_bear_history", debate.get("bear_history", ""))
            emit_agent("Bear Researcher")

    def run_trader_phase(graph, state: Dict[str, Any]) -> None:
        trader_node = create_trader(graph.quick_thinking_llm, graph.trader_memory)
        apply_update(state, trader_node(state))
        emit_section("trader_investment_plan", str(state.get("trader_investment_plan", "")))
        emit_agent("Trader")

    def run_risk_phase(graph, state: Dict[str, Any]) -> None:
        aggressive_node = create_aggressive_debator(graph.quick_thinking_llm)
        conservative_node = create_conservative_debator(graph.quick_thinking_llm)
        neutral_node = create_neutral_debator(graph.quick_thinking_llm)
        portfolio_node = create_portfolio_manager(graph.deep_thinking_llm, graph.portfolio_manager_memory)

        while True:
            next_step = graph.conditional_logic.should_continue_risk_analysis(state)
            if next_step == "Portfolio Manager":
                apply_update(state, portfolio_node(state))
                debate = state.get("risk_debate_state") or {}
                emit_section("risk_debate_aggressive_history", debate.get("aggressive_history", ""))
                emit_section("risk_debate_conservative_history", debate.get("conservative_history", ""))
                emit_section("risk_debate_neutral_history", debate.get("neutral_history", ""))
                emit_section("risk_debate_judge_decision", debate.get("judge_decision", ""))
                emit_section("final_trade_decision", str(state.get("final_trade_decision", "")))
                emit_agent("Portfolio Manager")
                break
            if next_step == "Aggressive Analyst":
                apply_update(state, aggressive_node(state))
                debate = state.get("risk_debate_state") or {}
                emit_section("risk_debate_aggressive_history", debate.get("aggressive_history", ""))
                emit_agent("Aggressive Analyst")
                continue
            if next_step == "Conservative Analyst":
                apply_update(state, conservative_node(state))
                debate = state.get("risk_debate_state") or {}
                emit_section("risk_debate_conservative_history", debate.get("conservative_history", ""))
                emit_agent("Conservative Analyst")
                continue
            apply_update(state, neutral_node(state))
            debate = state.get("risk_debate_state") or {}
            emit_section("risk_debate_neutral_history", debate.get("neutral_history", ""))
            emit_agent("Neutral Analyst")

    _update_run(run, status="running", started_at=_now())
    _emit(run_id, "status", {"status": "running"})

    try:
        graph = GraphClass(
            selected_analysts=run.selected_analysts,
            config=cfg,
        )

        graph_trade_date = run.trade_datetime if run.trading_style == "daytrade" and run.trade_datetime else run.analysis_date
        state = graph.propagator.create_initial_state(
            run.ticker,
            graph_trade_date,
            trading_style=run.trading_style,
        )
        state["market_report"] = checkpoint_sections.get("market_report", "")
        state["sentiment_report"] = checkpoint_sections.get("sentiment_report", "")
        state["news_report"] = checkpoint_sections.get("news_report", "")
        state["fundamentals_report"] = checkpoint_sections.get("fundamentals_report", "")
        state["investment_plan"] = checkpoint_sections.get("investment_plan") or checkpoint_sections.get("investment_debate_judge_decision", "")
        state["trader_investment_plan"] = checkpoint_sections.get("trader_investment_plan", "")

        if resume_from == "research":
            run_research_phase(graph, state)
            run_trader_phase(graph, state)
            run_risk_phase(graph, state)
        elif resume_from == "trader":
            run_trader_phase(graph, state)
            run_risk_phase(graph, state)
        elif resume_from == "risk":
            run_risk_phase(graph, state)
        else:
            raise RuntimeError(f"unsupported resume phase: {resume_from}")

        final_state = state
        order_intent: Dict[str, Any] = {}
        final_decision = final_state.get("final_trade_decision", "")
        if final_decision:
            try:
                intent_dict = graph.build_order_intent(
                    run.ticker,
                    run.analysis_date,
                    final_decision,
                )
                order_intent = intent_dict if isinstance(intent_dict, dict) else intent_dict.to_dict()
            except Exception:
                pass

        report_section_keys = [
            "market_report",
            "sentiment_report",
            "news_report",
            "fundamentals_report",
            "investment_plan",
            "trader_investment_plan",
            "final_trade_decision",
        ]
        run.report_sections = {}
        for key in report_section_keys:
            val = final_state.get(key)
            if val:
                run.report_sections[key] = val

        inv_debate = final_state.get("investment_debate_state") or {}
        if isinstance(inv_debate, dict):
            for sub in ("bull_history", "bear_history", "judge_decision"):
                val = inv_debate.get(sub)
                if val:
                    run.report_sections[f"investment_debate_{sub}"] = val

        risk_debate = final_state.get("risk_debate_state") or {}
        if isinstance(risk_debate, dict):
            for sub in ("aggressive_history", "conservative_history", "neutral_history", "judge_decision"):
                val = risk_debate.get(sub)
                if val:
                    run.report_sections[f"risk_debate_{sub}"] = val

        results_dir = Path(cfg.get("results_dir", DEFAULT_CONFIG["results_dir"])).expanduser()
        web_run_dir = results_dir / run.ticker / run.analysis_date / "web_runs" / run_id
        reports_dir = web_run_dir / "reports"
        try:
            save_fn(final_state, run.ticker, reports_dir)
            run.report_paths = {
                str(p.relative_to(reports_dir)): str(p)
                for p in reports_dir.rglob("*.md")
            }
        except Exception:
            pass

        run.stats = {}
        run.final_order_intent = order_intent or None
        _emit(run_id, "final_state", {"order_intent": order_intent, "stats": run.stats})
        _update_run(run, status="completed", completed_at=_now())
        _emit(run_id, "status", {"status": "completed"})
        _write_run_state(run, web_run_dir)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        run.errors.append(error_msg)
        _emit(run_id, "error", {"message": error_msg})
        _update_run(run, status="error", completed_at=_now())
        _emit(run_id, "status", {"status": "error"})
        _write_run_state(run, _fallback_run_dir(cfg, run))
    finally:
        q = get_event_queue(run_id)
        if q is not None:
            q.put(_DONE)

    return run


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_thread(run_id: str, config: Optional[Dict[str, Any]]) -> None:
    run_sync(run_id, config=config)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _update_run(run: AnalysisRun, **kwargs: Any) -> None:
    for k, v in kwargs.items():
        setattr(run, k, v)


def _emit(run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    q = get_event_queue(run_id)
    if q is None:
        return
    with _registry_lock:
        entry = _registry.get(run_id)
        if entry is None:
            return
        run, _ = entry
        # Use a simple incrementing counter stored on the run object
        seq = getattr(run, "_seq", 0)
        seq += 1
        object.__setattr__(run, "_seq", seq) if hasattr(run, "__slots__") else setattr(run, "_seq", seq)

    event = SseEvent(
        type=event_type,  # type: ignore[arg-type]
        run_id=run_id,
        sequence=seq,
        payload=payload,
    )
    q.put(event)
    _append_event_to_log(run_id, event)


def _process_chunk(run_id: str, chunk: Dict[str, Any], seq: list) -> None:
    """Derive and emit typed events from a LangGraph state chunk."""
    # Agent reports
    report_map = {
        "market_report": "Market Analyst",
        "sentiment_report": "Social Analyst",
        "news_report": "News Analyst",
        "fundamentals_report": "Fundamentals Analyst",
        "trader_investment_plan": "Trader",
    }
    for key, agent_name in report_map.items():
        if chunk.get(key):
            _emit(run_id, "report_section", {"key": key, "content": chunk[key]})
            _emit(run_id, "agent_status", {"agent": agent_name, "status": "completed"})

    # Research debate
    inv = chunk.get("investment_debate_state")
    if inv and isinstance(inv, dict):
        for sub_key in ("bull_history", "bear_history", "judge_decision"):
            if inv.get(sub_key):
                _emit(run_id, "report_section", {
                    "key": f"investment_debate_{sub_key}",
                    "content": inv[sub_key],
                })
        if inv.get("judge_decision"):
            _emit(run_id, "agent_status", {"agent": "Research Manager", "status": "completed"})

    # Risk debate
    risk = chunk.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        for sub_key in ("aggressive_history", "conservative_history", "neutral_history", "judge_decision"):
            if risk.get(sub_key):
                _emit(run_id, "report_section", {
                    "key": f"risk_debate_{sub_key}",
                    "content": risk[sub_key],
                })
        if risk.get("judge_decision"):
            _emit(run_id, "agent_status", {"agent": "Portfolio Manager", "status": "completed"})

    # Final decision
    if chunk.get("final_trade_decision"):
        _emit(run_id, "report_section", {
            "key": "final_trade_decision",
            "content": chunk["final_trade_decision"],
        })

    # Messages
    for msg in chunk.get("messages", []):
        content = getattr(msg, "content", None)
        if content and str(content).strip():
            _emit(run_id, "message", {
                "role": type(msg).__name__.replace("Message", "").lower(),
                "content": str(content)[:2000],
            })
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            _emit(run_id, "tool_call", {"name": name, "args": args})


def _write_run_state(run: AnalysisRun, run_dir: Path) -> None:
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        state_file = run_dir / "run_state.json"
        data = run.to_dict()
        data.pop("_seq", None)
        state_file.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass


def _append_event_to_log(run_id: str, event: SseEvent) -> None:
    run = get_run(run_id)
    if run is None:
        return
    cfg = DEFAULT_CONFIG
    results_dir = Path(cfg.get("results_dir", "~/.tradingagents/logs")).expanduser()
    log_file = (
        results_dir / run.ticker / run.analysis_date / "web_runs" / run_id / "events.ndjson"
    )
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a") as f:
            f.write(json.dumps(event.to_dict(), default=str) + "\n")
    except Exception:
        pass


def _fallback_run_dir(cfg: Dict[str, Any], run: AnalysisRun) -> Path:
    results_dir = Path(cfg.get("results_dir", "~/.tradingagents/logs")).expanduser()
    return results_dir / run.ticker / run.analysis_date / "web_runs" / run.run_id


def _register_run(run: AnalysisRun) -> None:
    with _registry_lock:
        if run.run_id not in _registry:
            _registry[run.run_id] = (run, queue.Queue())


def _load_runs_from_disk() -> List[AnalysisRun]:
    results_dir = Path(DEFAULT_CONFIG.get("results_dir", "~/.tradingagents/logs")).expanduser()
    if not results_dir.exists():
        return []

    runs: List[AnalysisRun] = []
    for state_file in results_dir.rglob("run_state.json"):
        run = _read_run_state(state_file)
        if run is not None:
            runs.append(run)
    return runs


def _read_run_state(state_file: Path) -> Optional[AnalysisRun]:
    try:
        raw = json.loads(state_file.read_text())
        allowed = {f.name for f in fields(AnalysisRun)}
        data = {k: v for k, v in raw.items() if k in allowed}
        return AnalysisRun(**data)
    except Exception:
        return None


def load_events_from_disk(run_id: str) -> list:
    """Replay stored events from events.ndjson (for SSE reconnect)."""
    run = get_run(run_id)
    if run is None:
        return []
    results_dir = Path(DEFAULT_CONFIG.get("results_dir", "~/.tradingagents/logs")).expanduser()
    log_file = (
        results_dir / run.ticker / run.analysis_date / "web_runs" / run_id / "events.ndjson"
    )
    if not log_file.exists():
        return []
    events = []
    for line in log_file.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events
