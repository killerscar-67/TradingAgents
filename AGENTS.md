# Repository Guidelines

## Project Structure & Module Organization

This is a Python package for the TradingAgents multi-agent trading framework. Core application code lives in `tradingagents/`: agent roles are under `tradingagents/agents/`, graph orchestration under `tradingagents/graph/`, data providers under `tradingagents/dataflows/`, LLM provider adapters under `tradingagents/llm_clients/`, and quant contracts/tools under `tradingagents/quant/`. The Typer-based command-line app is in `cli/`, with static CLI text in `cli/static/`. Tests are in `tests/`. Documentation and phase handoffs are in `docs/`, review artifacts in `reviews/`, images in `assets/`, and automation scripts in `scripts/`.

## Build, Test, and Development Commands

Use the project virtual environment when present:

```bash
source tradingagent_venv/bin/activate
pip install -e .
python -m cli.main
tradingagents
```

`pip install -e .` installs the package in editable mode. `python -m cli.main` runs the CLI from source; `tradingagents` runs the installed console script. Run tests with:

```bash
python -m unittest discover tests -v
python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v
```

For containerized usage, run `docker compose run --rm tradingagents` after creating an `.env` file with required API keys.

## Coding Style & Naming Conventions

Target Python 3.10+ as defined in `pyproject.toml`. Follow existing Python style: four-space indentation, snake_case functions and modules, PascalCase classes, and uppercase constants. Keep provider-specific logic in `tradingagents/llm_clients/`, market-data logic in `tradingagents/dataflows/`, and shared contracts in `tradingagents/quant/` or `tradingagents/agents/utils/`. Avoid broad refactors when making feature or test changes.

## Testing Guidelines

Tests use the standard `unittest` runner. Name test files `tests/test_*.py` and keep test methods descriptive, for example `test_rejects_invalid_model_config`. Prefer deterministic tests with mocked or local data; do not require live API keys for routine validation. Add focused coverage for changes that affect graph flow, execution contracts, quant filtering, model validation, or data parsing.

## Commit & Pull Request Guidelines

Recent history uses concise subjects, often Conventional Commit prefixes such as `feat:`, `fix:`, and `refactor:`. Keep commits scoped and imperative, for example `fix: normalize memory scores safely`. Pull requests should include a summary, validation commands run, linked issues when applicable, and screenshots only for CLI or visual asset changes. For phase-based work, update `docs/handoffs/phase-<N>.md` and run the relevant `scripts/review.sh <N> [base-ref]` workflow when requested.

## Security & Configuration Tips

Do not commit API keys, `.env` files, cache directories, or generated logs. Configure providers with environment variables such as `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, and `ALPHA_VANTAGE_API_KEY`. Treat all trading output as research tooling, not financial advice.

## Multi-Agent Phase 8 Coordination

Phase 8 merges overlapping quant and legacy TradingAgents responsibilities before reducing agent token usage. Work in this order:

1. Quant merge.
2. Risk/backtest/tool-output merge.
3. Compact context/token optimization.

Use `plan-quantStrictDaytradeArchitecture.prompt.md` as the Phase 8 coordination source of truth until Phase 8 implementation is complete and a real handoff is written. Each agent must read only its assigned files first, then expand context with `rg` only when a direct dependency requires it. Keep write sets separate unless the plan explicitly coordinates an overlap.

### Task Ownership

- Codex owns the deterministic quant executable layer: `tradingagents/quant/contracts.py`, `tradingagents/quant/engine.py`, `tradingagents/agents/utils/quant_tools.py`, `tradingagents/graph/trading_graph.py`, `tradingagents/graph/signal_processing.py`, `tests/test_execution_contracts.py`, and `tests/test_quant_tool.py`.
- Claude Code owns compact agent context and prompt handoffs: `tradingagents/agents/utils/agent_states.py`, `tradingagents/agents/utils/agent_utils.py`, researcher/trader/risk/manager agent nodes, and compact-context graph/unit tests.
- Copilot owns bounded mechanical refactors and instrumentation: `tradingagents/quant/risk.py`, `tradingagents/quant/backtest.py`, `tradingagents/quant/execution.py`, `tradingagents/dataflows/y_finance.py`, `tradingagents/dataflows/yfinance_news.py`, `cli/stats_handler.py`, `cli/main.py`, and related tests.

### Token-Saving Development Rules

- Use `rg` before opening files, and open focused line ranges instead of entire large files.
- Do not paste full reports, logs, generated JSON, or large dataframe/CSV output into prompts.
- Summarize findings and cite file paths instead of copying source blocks.
- Prefer fake LLMs for graph/unit tests unless the test specifically targets provider adapters.
- Run focused tests for the touched subsystem before full test discovery.
