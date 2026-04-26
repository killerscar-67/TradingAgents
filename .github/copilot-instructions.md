# Copilot Instructions

This repository is a Python package for the TradingAgents multi-agent trading framework. Core code lives in `tradingagents/`, the Typer CLI lives in `cli/`, and tests use the standard `unittest` runner under `tests/`.

Use the project virtual environment when present:

```bash
tradingagent_venv/bin/python -m unittest discover tests -v
```

For focused validation, prefer the smallest relevant test command first, then run full discovery after the subsystem passes.

## Phase 8 Copilot Scope

Phase 8 is coordinated through `plan-quantStrictDaytradeArchitecture.prompt.md` until implementation is complete and a real handoff is written. Copilot owns bounded mechanical refactors, tool-output compaction, and telemetry instrumentation.

Read these files first:

- `tradingagents/quant/risk.py`
- `tradingagents/quant/backtest.py`
- `tradingagents/quant/execution.py`
- `tradingagents/dataflows/y_finance.py`
- `tradingagents/dataflows/yfinance_news.py`
- `cli/stats_handler.py`
- `cli/main.py`
- `tests/test_backtest.py`
- `tests/test_risk.py`
- `tests/test_execution.py`

Copilot should implement:

- Reuse `size_position` and `compute_stops` inside the backtest path.
- Compact OHLCV, financial statement, indicator, and news tool outputs under config-controlled caps.
- Extend token stats from aggregate totals to per-agent/per-stage totals while keeping existing aggregate totals.

## Phase 8 Boundaries

Do not edit these areas unless `plan-quantStrictDaytradeArchitecture.prompt.md` is updated to coordinate the overlap:

- Quant signal ownership in `tradingagents/agents/utils/quant_tools.py`.
- Quant contract semantics in `tradingagents/quant/contracts.py`.
- Graph decision/rating extraction in `tradingagents/graph/`.
- Agent prompt rewrites in `tradingagents/agents/`.

Make small mechanical patches only. Avoid broad prompt rewrites and do not change executable trading semantics. Quant remains the source of truth for executable rating, sizing, stops, blocked status, and risk reasons; LLM agents remain advisory/explanatory.

## Token-Saving Workflow

- Use `rg` before opening files.
- Open focused line ranges instead of entire large files.
- Do not paste full reports, logs, generated JSON, or dataframe/CSV output into prompts.
- Summarize findings and cite file paths.
- Use fake LLMs for graph/unit tests unless testing provider adapters.
- Run focused tests before full test discovery.
