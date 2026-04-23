# TradingAgents — User Guide & System Reference

> **Disclaimer**: TradingAgents is a research framework. All output is for informational purposes only and is not financial, investment, or trading advice.

---

## Table of Contents

1. What TradingAgents Is
2. Installation
3. Configuration Reference
4. Running the CLI
5. Programmatic Usage
6. System Architecture
7. Execution Modes
8. Context and Token Controls
9. The Quant-Strict Pipeline
10. LLM Support Modules (Non-Execution)
11. Backtest and Validation Gates
12. Key Contracts Reference
13. Environment Variables
14. Running Tests
15. Project Layout

---

## 1. What TradingAgents Is

TradingAgents is a multi-agent trading research framework built on LangGraph. It simulates a trading firm's workflow by deploying specialized LLM-powered agents — fundamentals analysts, sentiment analysts, news analysts, technical analysts, researcher debaters, a trader, risk managers, and a portfolio manager — that collaborate to produce a trade decision for a given ticker and date.

On top of the original LLM-debate core, the framework now includes a full **quant-strict daytrade architecture**: a deterministic 15m/4h intraday quant engine that performs regime classification, entry signal generation, validation filtering, position sizing, risk gating, paper execution, and backtesting — all without any LLM involvement in the execution path. LLM outputs are strictly support-only (pre-trade context, anomaly flags, post-trade attribution).

---

## 2. Installation

**Prerequisites**: Python 3.10+, Git.

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents

# Create and activate a virtual environment
python -m venv tradingagent_venv
source tradingagent_venv/bin/activate   # macOS/Linux
# tradingagent_venv\Scripts\activate   # Windows

# Install
pip install -e .
```

**With Docker**:
```bash
cp .env.example .env   # fill in your API keys
docker compose run --rm tradingagents
```

**With Ollama (local models)**:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

---

## 3. Configuration Reference

All configuration lives in `DEFAULT_CONFIG` in default_config.py. Override by passing a modified copy to `TradingAgentsGraph(config=...)`.

### Core

| Key | Default | Env override | Description |
|---|---|---|---|
| `llm_provider` | `"openai"` | `TRADINGAGENTS_LLM_PROVIDER` | LLM provider: `openai`, `anthropic`, `google`, `xai`, `deepseek`, `qwen`, `glm`, `ollama`, `openrouter`, `azure` |
| `deep_think_llm` | `"gpt-5.4"` | `TRADINGAGENTS_DEEP_THINK_LLM` | Model for complex reasoning tasks |
| `quick_think_llm` | `"gpt-5.4-mini"` | `TRADINGAGENTS_QUICK_THINK_LLM` | Model for quick tasks and extraction |
| `execution_mode` | `"llm_assisted"` | `TRADINGAGENTS_EXECUTION_MODE` | `"llm_assisted"` or `"quant_strict"` |
| `context_mode` | `"compact"` | `TRADINGAGENTS_CONTEXT_MODE` | `"compact"` uses brief handoffs by default; `"full"` restores legacy full-report prompts |
| `output_language` | `"English"` | — | Language for analyst reports; internal debate always English |
| `max_debate_rounds` | `1` | — | Researcher debate rounds |
| `max_risk_discuss_rounds` | `1` | — | Risk management discussion rounds |
| `results_dir` | `~/.tradingagents/logs` | `TRADINGAGENTS_RESULTS_DIR` | Output log directory |
| `data_cache_dir` | `~/.tradingagents/cache` | `TRADINGAGENTS_CACHE_DIR` | Quant prefilter cache |

### Context & Token Controls (Phase 8)

Compact context is the default. Analyst reports are distilled into `analysis_brief` handoffs before downstream researcher, trader, risk, and portfolio prompts. Set `TRADINGAGENTS_CONTEXT_MODE=full` or `config["context_mode"] = "full"` only when you need the pre-Phase-8 full-report prompt shape.

| Key | Default | Description |
|---|---|---|
| `brief_max_chars` | `400` | Maximum characters per market/sentiment/news/fundamentals brief |
| `debate_max_chars` | `2000` | Maximum debate-history characters passed into downstream prompts |
| `debate_preserve_chars` | `600` | Latest debate-history characters preserved verbatim when capping |
| `tool_output_ohlcv_max_rows` | `120` | Maximum OHLCV rows returned by capped data tools |
| `tool_output_indicator_max_points` | `30` | Maximum indicator points returned to agent prompts |
| `tool_output_fundamentals_max_fields` | `18` | Maximum fundamentals fields included in tool output |
| `tool_output_financial_max_rows` | `20` | Maximum financial-statement rows included |
| `tool_output_financial_max_cols` | `4` | Maximum financial-statement columns included |
| `tool_output_news_max_articles` | `8` | Maximum news articles included |
| `tool_output_news_summary_max_chars` | `280` | Maximum characters per news summary |

### Intraday Data (Phase 1)

| Key | Default | Env override | Description |
|---|---|---|---|
| `intraday_cache_dir` | `~/.tradingagents/cache/intraday` | `TRADINGAGENTS_INTRADAY_CACHE_DIR` | Parquet cache for intraday bars |
| `intraday_default_session` | `"regular"` | `TRADINGAGENTS_INTRADAY_SESSION` | `"regular"`, `"extended"`, `"crypto"` |
| `intraday_refresh_cache` | `False` | — | Force re-fetch |
| `quant_prefilter_cache_ttl_days` | `1` | `TRADINGAGENTS_QUANT_CACHE_TTL_DAYS` | Days before prefilter cache expires |

### Regime Classifier (Phase 2)

| Key | Default | Description |
|---|---|---|
| `adx_period` | `14` | ADX window |
| `atr_period` | `14` | ATR window |
| `adx_trending_threshold` | `25.0` | ADX ≥ this → trending |
| `adx_ranging_threshold` | `20.0` | ADX ≤ this → ranging |
| `min_atr_pct` | `0.001` | Minimum ATR% for tradability |
| `min_volume` | `100_000` | Minimum average bar volume |
| `htf_sma_period` | `20` | HTF bias SMA period |
| `entry_mode` | `"auto"` | `"auto"` (regime-driven), `"breakout"`, `"mean_reversion"` |

### Validation Filters (Phase 2)

| Key | Default | Description |
|---|---|---|
| `validation_momentum` | `True` | MACD histogram acceleration filter |
| `validation_squeeze` | `True` | TTM Squeeze gate (reject when BB inside KC) |
| `validation_sr_proximity` | `True` | Support/resistance proximity filter |

### Risk & Sizing (Phase 3)

| Key | Default | Description |
|---|---|---|
| `risk_per_trade_pct` | `0.01` | Equity fraction risked per trade (1%) |
| `atr_stop_mult` | `2.0` | ATR multiples for initial stop |
| `breakeven_atr_mult` | `1.0` | ATR profit needed to trigger break-even |
| `trailing_atr_mult` | `1.5` | ATR multiples for trailing stop |
| `max_position_size_pct` | `0.10` | Maximum single-position notional (10% of equity) |
| `max_exposure_pct` | `0.20` | Maximum aggregate exposure (20% of equity) |
| `max_daily_loss_pct` | `0.02` | Daily loss cap (blocks new orders at 2%) |
| `kill_switch_daily_loss_pct` | `0.03` | Permanent daily halt threshold (3%) |

### Execution Guards (Phase 4)

| Key | Default | Description |
|---|---|---|
| `max_order_volume_pct` | `0.01` | Reject order if qty > 1% of latest bar volume |
| `max_slippage_pct` | `0.005` | Reject if expected slippage > 0.5% |

### Backtest & Walk-Forward (Phase 6)

| Key | Default | Description |
|---|---|---|
| `backtest_warmup_bars` | `60` | Minimum bars before signal generation starts |
| `backtest_slippage_pct` | `0.0005` | One-way slippage per fill (0.05%) |
| `backtest_commission` | `1.0` | Flat dollar commission per order |
| `bars_per_day` | `26` | 15m bars per trading day (for Sharpe annualisation) |
| `walkforward_n_folds` | `5` | Walk-forward fold count |
| `walkforward_in_sample_ratio` | `0.7` | In-sample fraction per fold |
| `paper_gate_min_sharpe` | `0.5` | Minimum session Sharpe for promotion |
| `paper_gate_max_drawdown_pct` | `0.05` | Maximum drawdown for promotion (5%) |
| `paper_gate_min_trades` | `1` | Minimum trades for a PASS verdict |

---

## 4. Running the CLI

```bash
tradingagents          # installed entrypoint
python -m cli.main     # from source
```

The interactive CLI prompts for: ticker(s), analysis date, LLM provider, model, analyst selection, execution mode, and research depth.

**Key CLI flag:**
```bash
tradingagents --execution-mode quant_strict
```

The summary table shows a **Blocked** column — blocked/errored signals are never silently shown as actionable decisions.

---

## 5. Programmatic Usage

### LLM-assisted mode (default execution, compact context)

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-5.4"
config["quick_think_llm"] = "gpt-5.4-mini"
# context_mode defaults to "compact"; use "full" only for legacy prompt comparison.

ta = TradingAgentsGraph(debug=True, config=config)
final_state, order_intent = ta.propagate("NVDA", "2026-01-15")
print(order_intent)
# {"symbol": "NVDA", "rating": "BUY", "blocked": False, ...}
```

### Legacy full-report prompts

```python
config = DEFAULT_CONFIG.copy()
config["context_mode"] = "full"

ta = TradingAgentsGraph(config=config)
final_state, order_intent = ta.propagate("NVDA", "2026-01-15")
# downstream prompts use the legacy full-report context path
```

### Quant-strict mode

```python
config = DEFAULT_CONFIG.copy()
config["execution_mode"] = "quant_strict"

ta = TradingAgentsGraph(config=config)
final_state, order_intent = ta.propagate("NVDA", "2026-01-15")
# order_intent["rating"] derived deterministically from quant contracts
# no LLM involved in the decision
```

### Running backtest

```python
from tradingagents.quant import run_backtest, PaperGate
from tradingagents.dataflows.intraday import get_intraday_bars
from tradingagents.default_config import DEFAULT_CONFIG

bars_15m = get_intraday_bars("NVDA", "15m", "2025-10-01", "2026-01-01")
bars_4h  = get_intraday_bars("NVDA", "4h",  "2025-10-01", "2026-01-01")

result = run_backtest("NVDA", bars_15m, bars_4h, initial_equity=100_000, config=DEFAULT_CONFIG.copy())
print(f"Sharpe: {result.sharpe_ratio}, Max DD: {result.max_drawdown_pct:.1%}, Trades: {result.trade_count}")

gate = PaperGate(min_session_sharpe=0.5, max_intraday_drawdown_pct=0.05)
verdict = gate.evaluate(result)
print(f"Paper gate: {'PASS' if verdict.passed else 'FAIL'} — {verdict.reasons}")
```

### Walk-forward validation

```python
from tradingagents.quant import run_walk_forward

wf = run_walk_forward("NVDA", bars_15m, bars_4h, n_folds=5, in_sample_ratio=0.7, initial_equity=100_000)
print(f"OOS Sharpe positive: {wf.oos_sharpe_positive_pct:.0%}, Mean OOS Sharpe: {wf.mean_oos_sharpe}")
```

### LLM support annotations (non-execution)

```python
from tradingagents.agents.utils.llm_support import (
    build_pre_trade_brief,
    watch_anomalies,
    annotate_order_intent_with_support,
)

brief = build_pre_trade_brief(llm, {"symbol": "NVDA", "trade_date": "2026-01-15"})
anomalies = watch_anomalies(llm, {"symbol": "NVDA"})
# brief.blocking is always False; anomalies.flags are strict booleans

annotated = annotate_order_intent_with_support(order_intent, pre_trade_brief=brief, anomaly_watch=anomalies)
# annotated["annotations"]["llm_support"] contains the support payloads
# annotated["rating"] and annotated["blocked"] are unchanged
```

---

## 6. System Architecture

```
CLI / TradingAgentsGraph
        │
        ├── Quant Prefilter (universe gate + cache)
        │       └── score_tickers_with_quant() → ranked candidates
        │
        ├── LangGraph Agent Pipeline (llm_assisted mode)
        │       ├── Analyst Team (market, sentiment, news, fundamentals)
        │       ├── Compact Context Layer (default)
        │       │       ├── analysis_brief handoffs
        │       │       ├── debate-history capping
        │       │       └── config-controlled tool-output caps
        │       ├── Researcher Team (bull/bear debate → research manager)
        │       ├── Trader Agent
        │       ├── Risk Management (aggressive/neutral/conservative → manager)
        │       └── Portfolio Manager → final approve/reject
        │
        ├── Signal Processor
        │       ├── llm_assisted: deterministic Rating: line parse, then LLM fallback
        │       └── quant_strict:  TradeRating from QuantSignalContract (deterministic)
        │
        ├── Quant Engine
        │       ├── Phase 1: get_intraday_bars() — 15m + 4h with cache
        │       ├── Phase 2: regime.classify() → entry.run_entry() → validation.validate()
        │       ├── Phase 3: risk.size_position() + compute_stops() + check_risk_gates()
        │       └── Phase 4: OrderManager → PaperBrokerAdapter → PortfolioState
        │
        └── LLM Support Modules (both modes, non-execution)
                ├── build_pre_trade_brief()     → PreTradeBrief
                ├── watch_anomalies()            → AnomalyWatch
                └── build_post_trade_attribution() → PostTradeAttribution
```

### Module map

| Path | Purpose |
|---|---|
| trading_graph.py | Top-level orchestrator; `propagate()` and `build_order_intent()` |
| prefilter.py | Quant universe pre-scoring with TTL cache |
| signal_processing.py | Extracts `TradeRating` from agent output |
| analysts | Market, sentiment, news, fundamentals analysts |
| researchers | Bull/bear debate + research manager |
| trader | Trader agent |
| risk_mgmt | Risk management team |
| managers | Portfolio manager |
| agent_utils.py | Shared agent helpers, compact context, tool imports |
| llm_support.py | Non-execution LLM support helpers |
| contracts.py | All typed execution contracts |
| engine.py | Quant pipeline orchestrator |
| regime.py | ADX/ATR regime classifier |
| entry.py | Breakout and mean-reversion entry engines |
| validation.py | Momentum, squeeze, SR proximity filters |
| risk.py | Sizing, stops, daily loss, kill switch |
| execution.py | `OrderManager`, `PaperBrokerAdapter`, `PortfolioState` |
| backtest.py | Bar-replay backtest engine |
| walkforward.py | Walk-forward validation |
| paper_gate.py | Pass/fail promotion gate |
| intraday.py | 15m/4h bar fetch with session alignment and cache |
| interface.py | Vendor routing for all data tools |
| factory.py | `create_llm_client()` — multi-provider factory |
| default_config.py | Single source of truth for all config defaults |

---

## 7. Execution Modes

| | `llm_assisted` (default) | `quant_strict` |
|---|---|---|
| Trade rating source | Deterministic `Rating:` line parse, then LLM extraction fallback | `QuantSignalContract` from quant engine |
| Deterministic? | No | Yes — identical inputs produce identical outputs |
| LLM used in decision? | Yes | No |
| Suitable for backtesting? | No | Yes |
| Order path | `OrderIntentContract` via text extraction | `OrderIntentContract` via typed contracts |

Set via config key `execution_mode` or env var `TRADINGAGENTS_EXECUTION_MODE`.

---

## 8. Context and Token Controls

Phase 8 makes compact context the normal agent handoff path:

1. Analyst reports remain available in state as full text.
2. The first downstream agent builds `analysis_brief` with market, sentiment, news, and fundamentals summaries.
3. Later downstream agents reuse the same brief instead of re-prompting with repeated full reports.
4. Debate histories are capped before prompt construction while preserving the latest turn.
5. Tool outputs are capped at the dataflow boundary, so large OHLCV tables, indicators, financial statements, and news payloads do not flood prompts.

Use `context_mode="full"` only for legacy behavior checks. In full mode, downstream prompts preserve the old full-report path and do not write `analysis_brief` updates.

---

## 9. The Quant-Strict Pipeline

Each bar during live or backtest execution follows this sequence:

```
get_intraday_bars(symbol, "15m" / "4h", ...)
        │
        ▼
run_quant_engine(symbol, trade_date, bars_15m, bars_4h, config)
        │
        ├── regime.classify(bars_4h)          → RegimeContract
        │     trending / ranging / consolidation + tradability + HTF bias
        │
        ├── entry.run_entry(bars_15m, regime)  → EntrySignal | NoSignal
        │     trending  → run_breakout()
        │     ranging   → run_mean_reversion()
        │     consolidation → NoSignal
        │
        ├── validation.validate(bars_15m, entry) → ValidationResult
        │     momentum_acceleration (togglable)
        │     squeeze_gate          (togglable)
        │     sr_proximity          (togglable)
        │
        └── → QuantSignalContract (BUY / SELL / HOLD / error)
                │
                ▼
        risk.size_position(entry_signal, entry_price, atr, equity, config)
                └── → PositionSizeContract

        risk.compute_stops(direction, entry_price, atr, config)
                └── → StopContract

        risk.check_risk_gates(size_contract, daily_loss_state, exposure, equity, config)
                └── → RiskGateResult (allowed=True/False)
                        │
                        ▼ (if allowed)
        OrderManager.submit_order_intent(order_intent, market_snapshot)
                └── PaperBrokerAdapter.submit_order(...)
                        └── fills at next-bar open + slippage
                                └── PortfolioState.apply_fill(fill)
```

**No-lookahead guarantee**: at signal bar `i`, the engine receives only `bars_15m.iloc[:i+1]` and `bars_4h.loc[index <= bars_15m.index[i]]`. Fills execute at bar `i+1`'s open.

---

## 10. LLM Support Modules (Non-Execution)

These modules produce annotations for human review and journaling. They **cannot block, size, modify, or submit orders**.

| Function | Returns | Blocking? |
|---|---|---|
| `build_pre_trade_brief(llm, context)` | `PreTradeBrief` | Never — `blocking=False` always |
| `watch_anomalies(llm, context)` | `AnomalyWatch` | Never — flags are strict `bool` only |
| `build_post_trade_attribution(llm, context)` | `PostTradeAttribution` | Never |
| `annotate_order_intent_with_support(order_intent, ...)` | `dict` (deep copy) | — writes only under `annotations["llm_support"]` |

All provider exceptions and malformed LLM responses are captured in the `error` field; the contract is always returned.

`AnomalyWatch.flags` keys: `event_risk`, `liquidity_risk`, `data_quality_risk`, `news_risk` — each a strict Python `bool`. Non-boolean values from the LLM reset all flags to `False`.

---

## 11. Backtest and Validation Gates

### Backtest friction model

- **Slippage**: buys fill at `next_bar_open × (1 + slippage_pct)`; sells at `next_bar_open × (1 − slippage_pct)`
- **Commission**: flat `commission_per_order` dollars, deducted at entry and again at exit
- **EOD close**: open positions close at the last bar's close with no exit commission

### Walk-forward layout

```
fold_size = total_bars // n_folds
is_size   = max(1, int(fold_size × in_sample_ratio))
oos_size  = fold_size − is_size

Fold k:  IS  = [k×fold_size,          k×fold_size + is_size)
         OOS = [k×fold_size + is_size, (k+1)×fold_size)
```

IS and OOS are strictly adjacent (`is_end == oos_start`); no bar appears in more than one OOS window.

### Paper gate promotion criteria

All three conditions must be met simultaneously (exactly at threshold fails):

- Session Sharpe **>** `paper_gate_min_sharpe` (default 0.5)
- Max drawdown **<** `paper_gate_max_drawdown_pct` (default 5%)
- Trade count **≥** `paper_gate_min_trades` (default 1)

---

## 12. Key Contracts Reference

All contracts live in contracts.py and are exported from `tradingagents.quant`.

| Contract | Key fields | Immutable? |
|---|---|---|
| `QuantSignalContract` | `signal`, `score`, `ticker`, `error` | Yes (frozen) |
| `OrderIntentContract` | `symbol`, `trade_date`, `rating`, `blocked`, `reason`, `execution_mode`, `annotations` | Yes (frozen) |
| `RegimeContract` | `label`, `tradable`, `adx`, `atr`, `htf_bias` | Yes (frozen) |
| `EntrySignal` | `engine`, `direction`, `strength`, `reason` | Yes (frozen) |
| `NoSignal` | `reason` | Yes (frozen) |
| `ValidationResult` | `passed`, `filters_passed`, `filters_total`, `reasons` | Yes (frozen) |
| `PositionSizeContract` | `quantity`, `entry_price`, `notional`, `stop_price`, `risk_amount` | Yes (frozen) |
| `StopContract` | `initial_stop`, `breakeven_trigger`, `trailing_distance` | Yes (frozen) |
| `RiskGateResult` | `allowed`, `reason`, `kill_switch` | Yes (frozen) |
| `DailyLossState` | `date`, `net_pnl`, `kill_switch`, `trade_count` | Yes (frozen) |
| `BacktestResult` | `equity_curve`, `trades`, `sharpe_ratio`, `max_drawdown_pct` | No |
| `PaperGateResult` | `passed`, `session_sharpe`, `max_intraday_drawdown_pct`, `reasons` | Yes (frozen) |
| `PreTradeBrief` | `summary`, `catalysts`, `event_risks`, `blocking`, `error` | Yes (frozen) |
| `AnomalyWatch` | `flags` (immutable mapping), `summary`, `blocking`, `error` | Yes (frozen) |

All contracts expose a `.to_dict()` method for serialisation.

---

## 13. Environment Variables

| Variable | Used for |
|---|---|
| `OPENAI_API_KEY` | OpenAI (also accepted as DashScope key alias) |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) |
| `GOOGLE_API_KEY` | Google (Gemini) |
| `XAI_API_KEY` | xAI (Grok) |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `DASHSCOPE_API_KEY` | Qwen (Alibaba DashScope) |
| `ZHIPU_API_KEY` | GLM (Zhipu) |
| `OPENROUTER_API_KEY` | OpenRouter |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage market data |
| `TRADINGAGENTS_LLM_PROVIDER` | LLM provider override |
| `TRADINGAGENTS_DEEP_THINK_LLM` | Deep-think model override |
| `TRADINGAGENTS_QUICK_THINK_LLM` | Quick-think model override |
| `TRADINGAGENTS_EXECUTION_MODE` | `llm_assisted` or `quant_strict` |
| `TRADINGAGENTS_RESULTS_DIR` | Override results log path |
| `TRADINGAGENTS_CACHE_DIR` | Override quant prefilter cache path |
| `TRADINGAGENTS_INTRADAY_CACHE_DIR` | Override intraday bar cache path |
| `TRADINGAGENTS_INTRADAY_SESSION` | Default session (`regular`/`extended`/`crypto`) |
| `TRADINGAGENTS_QUANT_CACHE_TTL_DAYS` | Prefilter cache TTL in days |

Copy .env.example to .env and fill in your keys. For enterprise providers (Azure, Bedrock) use `.env.enterprise`.

---

## 14. Running Tests

```bash
# Full test suite (all phases)
tradingagent_venv/bin/python -m unittest discover tests -v

# Core regression suite (fast — runs in < 1s)
tradingagent_venv/bin/python -m unittest \
  tests.test_quant_tool \
  tests.test_quant_prefilter \
  tests.test_model_validation -v

# Phase-specific
tradingagent_venv/bin/python -m unittest tests.test_execution_contracts -v  # Phase 0
tradingagent_venv/bin/python -m unittest tests.test_intraday -v              # Phase 1
tradingagent_venv/bin/python -m unittest tests.test_quant_engine -v          # Phase 2
tradingagent_venv/bin/python -m unittest tests.test_risk -v                  # Phase 3
tradingagent_venv/bin/python -m unittest tests.test_execution -v             # Phase 4
tradingagent_venv/bin/python -m unittest tests.test_llm_support -v           # Phase 5
tradingagent_venv/bin/python -m unittest tests.test_backtest -v              # Phase 6
```

No live API keys are required for any test. All tests use mocked or synthetic data.

---

## 15. Project Layout

```
TradingAgents/
├── cli/                        # Typer CLI app
│   ├── main.py                 # Commands and interactive flow
│   ├── config.py               # CLI-level config helpers
│   ├── models.py               # Analyst type enums
│   └── static/welcome.txt      # Welcome screen
├── tradingagents/
│   ├── default_config.py       # All config defaults (single source of truth)
│   ├── agents/
│   │   ├── analysts/           # Fundamentals, market, news, sentiment agents
│   │   ├── researchers/        # Bull, bear, research manager
│   │   ├── trader/             # Trader agent
│   │   ├── risk_mgmt/          # Risk management team
│   │   ├── managers/           # Portfolio manager
│   │   └── utils/
│   │       ├── agent_states.py # LangGraph AgentState dict
│   │       ├── llm_support.py  # Non-execution LLM support helpers (Phase 5)
│   │       └── quant_tools.py  # Quant signal tool wrapper
│   ├── dataflows/
│   │   ├── interface.py        # Vendor routing
│   │   ├── intraday.py         # 15m/4h bar fetch + cache (Phase 1)
│   │   └── ...                 # yfinance, alpha_vantage adapters
│   ├── graph/
│   │   ├── trading_graph.py    # TradingAgentsGraph orchestrator
│   │   ├── prefilter.py        # Quant universe pre-scoring
│   │   └── signal_processing.py
│   ├── llm_clients/
│   │   └── factory.py          # create_llm_client() multi-provider factory
│   └── quant/
│       ├── contracts.py        # All typed execution contracts
│       ├── engine.py           # run_quant_engine() orchestrator
│       ├── regime.py           # Regime classifier (Phase 2)
│       ├── entry.py            # Breakout + mean-reversion engines (Phase 2)
│       ├── validation.py       # Momentum / squeeze / SR filters (Phase 2)
│       ├── risk.py             # Sizing, stops, risk gates (Phase 3)
│       ├── execution.py        # OrderManager, PaperBrokerAdapter (Phase 4)
│       ├── backtest.py         # Bar-replay backtest (Phase 6)
│       ├── walkforward.py      # Walk-forward validation (Phase 6)
│       └── paper_gate.py       # Promotion gate (Phase 6)
├── tests/                      # unittest test suite
├── docs/handoffs/              # Per-phase handoff notes
├── reviews/                    # Per-phase review artifacts
├── scripts/                    # review.sh, run_phase.sh, add_fix_notes.sh
├── main.py                     # Minimal programmatic entry point
└── pyproject.toml
```
