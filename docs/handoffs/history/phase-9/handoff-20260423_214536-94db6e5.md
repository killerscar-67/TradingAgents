# Phase 9 Handoff — Day-Trade Workflow Contracts
Agent: Codex
Date: 2026-04-23

## What was built

- `scripts/review.sh`: extended phase validation and reviewer routing through Phase 13, with UX-specific review scopes and non-goals.
- `scripts/run_phase.sh`: added UX phase context generation from `docs/ux-design-daytrade-workflow.md`, owner routing for phases 9-13, and UX validation commands.
- `tradingagents/web/models.py`: added typed dataclass contracts for the market overview, screening run, basket, batch, trade plan, strategy preset, and backtest run.
- `tradingagents/web/routes/workflow.py`: added Phase 9 route skeletons for the full day-trade workflow API surface.
- `tradingagents/web/app.py`: registered the workflow router.
- `tests/test_web_workflow_contracts.py`: added contract tests for the new API surface and safety flags.

## Contracts exposed to next phase

- `GET /api/market/overview` and `WS /api/market/live`: return the Market screen response shape, including index tiles, regime, and stream metadata.
- `POST /api/screening/runs`, `POST /api/baskets`, `POST /api/batches`, `GET /api/batches/{id}/events`: establish screening, basket, and batch-analysis contracts.
- `POST /api/strategies/from-batch`, `POST /api/broker/futu/stage`: establish trade-plan and stage-only Futu contracts.
- `POST /api/backtests`, `GET /api/backtests/{id}/events`: establish quant-strict backtest contracts; the skeleton response force-labels `execution_mode="quant_strict"` and `llm_constructed=false`.
- `GET/PUT /api/settings`, `GET/POST /api/watchlists`, `GET/POST /api/strategy-presets`, `GET /api/history`: establish metadata/history contracts for Phase 10 persistence.

## Config keys added

- None. Phase 10 should add `TRADINGAGENTS_WEB_DB` handling with SQLite persistence.

## Test command

```
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_web_workflow_contracts tests.test_web_api tests.test_web_runner -v
bash -n scripts/review.sh scripts/run_phase.sh
```

Expected: workflow contract tests pass; existing web API/runner tests remain green; script syntax checks pass.

## Known limitations / deferred decisions

- Routes intentionally return `status="contract_ready"` placeholder bodies for non-Market workflow mutations. SQLite persistence is deferred to Phase 10.
- Deterministic screening, batch orchestration, strategy planning, Futu client implementation, and real quant-strict backtest execution are deferred to Phase 11.
- React workflow screens are not changed in Phase 9; frontend implementation is deferred to Phase 12.
- The Market WebSocket sends a single contract snapshot and closes. Streaming quote integration is deferred to Phase 11.

## What the reviewer must focus on

- Verify phase `9..13` owner/reviewer routing is correct and old phase behavior remains intact.
- Verify new API paths are registered without conflicting with existing `/api/analysis`, consultant, or model routes.
- Verify Futu and backtest skeletons preserve the safety contract: stage-only broker behavior and no LLM construction in backtest contracts.
- Verify Phase 9 does not introduce SQLite persistence or frontend changes that belong to later phases.

## Fix notes

- None.
