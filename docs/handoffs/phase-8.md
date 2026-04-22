# Phase 8 Handoff — Quant Merge, Compact Context, And Token Optimization

**Branch**: `feature/quant`  
**Date**: 2026-04-22  
**Commit base**: 9b500d8

---

## What was built

This branch now contains implemented work from multiple Phase 8 lanes:

- Claude Code lane: compact context and debate-history capping
- Copilot lane: backtest risk-helper reuse, tool-output compaction, and telemetry instrumentation
- Codex lane: deterministic quant-tool / rating-parse work present in branch

### Helpers (`tradingagents/agents/utils/agent_utils.py`)

| Function | Purpose |
|---|---|
| `get_context_mode()` | Reads `config["context_mode"]` (`"full"` or `"compact"`) |
| `extract_brief(report, max_chars=400)` | Truncates a report string to `max_chars`, appends `…` |
| `build_analysis_brief(market, sentiment, news, fundamentals, max_chars=400)` | Returns `dict` with keys `market/sentiment/news/fundamentals`, each truncated |
| `cap_debate_history(history, max_chars=2000, preserve_latest_chars=600)` | Caps debate history: keeps tail verbatim, fills head budget, inserts gap marker |

### State (`tradingagents/agents/utils/agent_states.py`)

Added `analysis_brief: Annotated[dict, ...]` to `AgentState`. Built lazily by the first downstream agent that runs; reused by all subsequent agents. Empty dict when `context_mode="full"` or before any agent has run.

### Config (`tradingagents/default_config.py`)

New keys:

```python
"context_mode":           "full"    # or "compact" (env: TRADINGAGENTS_CONTEXT_MODE)
"brief_max_chars":        400       # chars per brief entry
"debate_max_chars":       2000      # max chars for debate history in prompt
"debate_preserve_chars":  600       # latest chars always preserved verbatim
"tool_output_ohlcv_max_rows":        120
"tool_output_indicator_max_points":  30
"tool_output_fundamentals_max_fields": 18
"tool_output_financial_max_rows":    20
"tool_output_financial_max_cols":    4
"tool_output_news_max_articles":     8
"tool_output_news_summary_max_chars": 280
```

### Quant merge work already present in branch

| File | Change |
|---|---|
| `tradingagents/agents/utils/quant_tools.py` | `get_quant_signals` prefers deterministic intraday engine payloads and falls back explicitly to legacy daily MA/RSI |
| `tradingagents/graph/signal_processing.py` | deterministic `Rating:` line parsing runs before any LLM extraction in `llm_assisted` mode |
| `tests/test_quant_tool.py` | intraday-engine coverage added alongside explicit fallback coverage |
| `tests/test_execution_contracts.py` | direct `Rating:` parse test added |

### Agent updates

All seven downstream agents updated to branch on `get_context_mode()`:

- **`context_mode="full"`** (default): behaves identically to pre-Phase 8 — full reports passed, no `analysis_brief` written to state.
- **`context_mode="compact"`**: uses `build_analysis_brief` / `cap_debate_history`; writes `analysis_brief` back to state so subsequent agents reuse it without rebuilding.

Agents updated:

| File | Change |
|---|---|
| `agents/researchers/bull_researcher.py` | Builds brief; writes to state in compact mode |
| `agents/researchers/bear_researcher.py` | Reuses or builds brief; writes to state |
| `agents/trader/trader.py` | Uses brief in context block |
| `agents/risk_mgmt/aggressive_debator.py` | Uses brief + capped history |
| `agents/risk_mgmt/conservative_debator.py` | Uses brief + capped history |
| `agents/risk_mgmt/neutral_debator.py` | Uses brief + capped history |
| `agents/managers/portfolio_manager.py` | Uses brief + capped history |

### Backtest risk reuse (`tradingagents/quant/backtest.py`)

Backtest entry sizing and initial stop placement now reuse the Phase 3 risk module instead of duplicating the formulas locally.

| File | Change |
|---|---|
| `tradingagents/quant/backtest.py` | entry path now calls `size_position(...)` and `compute_stops(...)` from `tradingagents.quant.risk` |
| `tradingagents/quant/backtest.py` | local sizing helper removed and replaced with `EntrySignal` coercion from quant payload metadata |

This keeps backtest sizing, stop distance, and directional rounding behavior aligned with live quant risk logic.

### Tool-output compaction

The yfinance-backed dataflow tools now cap output under config-controlled budgets to reduce prompt size while keeping legacy return formats intact.

| File | Change |
|---|---|
| `tradingagents/dataflows/y_finance.py` | OHLCV output capped by rows; indicator windows capped by point count; fundamentals capped by field count |
| `tradingagents/dataflows/y_finance.py` | balance sheet / cash flow / income statement / insider transactions capped by rows and columns |
| `tradingagents/dataflows/yfinance_news.py` | ticker news and global news capped by article count; summaries truncated by char budget |
| `tests/test_tool_output_caps.py` | focused coverage for OHLCV, indicator, fundamentals, financial-table, and news caps |

All capped outputs retain the original string/CSV-style interface and add a short header note when truncation occurs.

### Token telemetry (`cli/stats_handler.py`, `cli/main.py`)

Existing aggregate totals are preserved and extended with per-agent / per-stage buckets.

| File | Change |
|---|---|
| `cli/stats_handler.py` | tracks aggregate LLM/tool/token totals plus `per_agent` and `per_stage` metrics |
| `cli/stats_handler.py` | resolves scope from LangGraph metadata/tags and infers stages such as `analyst`, `research`, `trader`, `risk`, `portfolio` |
| `cli/main.py` | footer now surfaces aggregate totals plus the top token-consuming agent and stage |
| `tests/test_stats_handler.py` | focused coverage for per-agent / per-stage token and tool-call accounting |

### Tests (`tests/test_compact_context.py`)

31 tests, all green. Coverage:

- `extract_brief`: length, truncation, empty input
- `build_analysis_brief`: keys, truncation, short pass-through
- `cap_debate_history`: short/long/tail-preservation/empty
- `get_context_mode`: default and override
- Per-agent: compact brief written, full mode no-brief, brief reuse, count incremented

### Additional focused validation

- `tests/test_backtest.py`: verified the backtest still passes after swapping to risk-module sizing/stops reuse
- `tests/test_risk.py`: verified the reused sizing/stop logic remains stable
- `tests/test_execution.py`: confirmed execution guards and paper broker behavior stay unchanged
- `tests/test_tool_output_caps.py`: 5 focused tests for output compaction
- `tests/test_stats_handler.py`: 2 focused tests for per-agent / per-stage telemetry

---

## Backward compatibility

`context_mode` defaults to `"full"`, so existing callers are unaffected. Set `TRADINGAGENTS_CONTEXT_MODE=compact` or pass `config={"context_mode": "compact"}` to activate.

Tool-output compaction preserves existing return types and headers. Callers still receive strings in the same overall format; only oversized sections are truncated with an explicit cap note.

Telemetry preserves the existing aggregate keys:

- `llm_calls`
- `tool_calls`
- `tokens_in`
- `tokens_out`

New consumers can additionally read `per_agent` and `per_stage` from `StatsCallbackHandler.get_stats()`.

---

## Test run

```
tradingagent_venv/bin/python -m unittest tests.test_compact_context -v
# 31 tests, 0 failures

tradingagent_venv/bin/python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v
# 16 tests, 0 failures

tradingagent_venv/bin/python -m unittest tests.test_backtest tests.test_risk -v
# 84 tests, 0 failures

tradingagent_venv/bin/python -m unittest tests.test_tool_output_caps -v
# 5 tests, 0 failures

tradingagent_venv/bin/python -m unittest tests.test_stats_handler -v
# 2 tests, 0 failures

tradingagent_venv/bin/python -m unittest tests.test_backtest tests.test_risk tests.test_execution tests.test_tool_output_caps tests.test_stats_handler -v
# 100 tests, 0 failures
```
