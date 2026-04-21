# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install .
# or with uv
uv pip install .

# Run the CLI
tradingagents
python -m cli.main

# Run all tests
tradingagent_venv/bin/python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v

# Run a single test file
tradingagent_venv/bin/python -m unittest tests.test_execution_contracts -v

# Run a single test case
tradingagent_venv/bin/python -m unittest tests.test_execution_contracts.ExecutionContractTests.test_quant_signal_contract_parses_payload -v

# Programmatic usage (no CLI)
python main.py
```

**Always use `tradingagent_venv/bin/python`** as the canonical interpreter for this project.

## Architecture

### Execution Flow

1. **Entry**: `TradingAgentsGraph` (`tradingagents/graph/trading_graph.py`) orchestrates everything. Call `ta.propagate(ticker, date)` to run a full analysis cycle.
2. **Prefiltering**: Before analysis, `score_tickers_with_quant()` (`graph/prefilter.py`) runs quant signals on candidate tickers and ranks them. Results are cached by SHA-256 hash of params in `~/.tradingagents/cache/`.
3. **Graph execution**: LangGraph drives agent state through `Propagator` (state init), analyst agents, researcher debate, trader, risk management, and portfolio manager in sequence.
4. **Signal processing**: `SignalProcessor` (`graph/signal_processing.py`) extracts a `TradeRating` (BUY/OVERWEIGHT/HOLD/UNDERWEIGHT/SELL) from agent output. In `quant_strict` mode it uses deterministic regex; in `llm_assisted` mode it calls the quick LLM.
5. **Reflection**: `ta.reflect_and_remember(position_returns)` triggers post-trade memory updates.

### Two Execution Modes

Controlled by `config["execution_mode"]` or env `TRADINGAGENTS_EXECUTION_MODE`:

- **`llm_assisted`** (default): LLM extracts the final trade rating from narrative output.
- **`quant_strict`**: Deterministic path — `QuantSignalContract` drives `OrderIntentContract`, no LLM involved in the decision. Avoids non-determinism for backtesting.

### Agent Teams

- **Analyst Team** (`tradingagents/agents/analysts/`): market, social/sentiment, news, fundamentals — each fetches data and writes a report into `AgentState`.
- **Researcher Team** (`agents/researchers/`): Bull and Bear researchers debate the analyst reports; Research Manager adjudicates.
- **Trader** (`agents/trader/`): synthesizes reports into a trading proposal.
- **Risk Management** (`agents/risk_mgmt/`): aggressive/neutral/conservative analysts debate; produces risk assessment.
- **Portfolio Manager** (`agents/managers/`): final approve/reject decision.

### Key Abstractions

- **`AgentState`** (`agents/utils/agent_states.py`): LangGraph state dict carrying all reports and debate histories across the graph.
- **`QuantSignalContract` / `OrderIntentContract`** (`tradingagents/quant/contracts.py`): typed dataclasses enforcing quant signal format. Use `QuantSignalContract.from_raw()` to parse LLM/tool output.
- **`create_llm_client(provider, model, ...)`** (`llm_clients/factory.py`): returns a `BaseLLMClient`. Providers: `openai`, `anthropic`, `google`, `azure`, `xai`, `deepseek`, `qwen`, `glm`, `ollama`, `openrouter`. OpenAI-compatible providers all go through `OpenAIClient`.
- **Data vendors** (`tradingagents/dataflows/`): `yfinance` (default, no key needed) or `alpha_vantage`. Configured per-category in `config["data_vendors"]` with optional tool-level overrides in `config["tool_vendors"]`.

### Configuration

`DEFAULT_CONFIG` (`tradingagents/default_config.py`) is the single source of truth. All paths default under `~/.tradingagents/` (cache and logs). Override by passing a modified copy as `config=` to `TradingAgentsGraph`.

Key config fields:
- `llm_provider`, `deep_think_llm`, `quick_think_llm` — model selection
- `execution_mode` — `"llm_assisted"` or `"quant_strict"`
- `max_debate_rounds`, `max_risk_discuss_rounds` — agent debate depth
- `quant_prefilter_cache_ttl_days`, `quant_prefilter_refresh_cache` — cache controls
- `intraday_cache_dir`, `intraday_default_session`, `intraday_refresh_cache` — Phase 1 intraday data
- `entry_mode` — `"auto"` (regime-driven), `"breakout"`, or `"mean_reversion"` to force engine
- `validation_momentum/squeeze/sr_proximity` — toggle individual Phase 2 validation filters
- `output_language` — language for analyst reports (internal debate always English)

### Phase-based Development

The repo follows a phased implementation plan (`plan-quantStrictDaytradeArchitecture.prompt.md`). Use `scripts/run_phase.sh <0-6>` to run a phase with the canonical venv. Each completed phase produces a handoff doc in `docs/handoffs/phase-N.md`.

### Review Fix Notes Protocol

After applying fixes requested by a review, always record a separate fix-notes artifact and link it from the phase handoff:

```bash
scripts/add_fix_notes.sh <phase-number> <review-file> [title]
```

Examples:

```bash
scripts/add_fix_notes.sh 0 reviews/phase-0-review.md "Applied review-directed fixes"
scripts/add_fix_notes.sh 1 reviews/phase-1/review-YYYYMMDD_HHMMSS-<sha>.md "Re-review fixes"
```

This command writes `docs/handoffs/history/phase-N/fix-notes-*.md` and updates `docs/handoffs/phase-N.md` under `## Fix notes` with a timestamped link.
