# Phase 11 Handoff — Deterministic Workflow Orchestration
Agent: Codex
Date: 2026-04-23

## What was built

- `tradingagents/web/workflow_service.py`: added the Phase 11 service layer for market overview/regime classification, screening, basket resolution, batch fan-out, deterministic strategy planning, quant-strict backtests, and Futu stage-only orchestration.
- `tradingagents/web/routes/workflow.py`: replaced the remaining Phase 10 contract-only route behavior with real service-backed execution and persisted SSE/event responses.
- `tradingagents/web/storage.py`: expanded the workflow schema to version `2` and now stores screening results, batch items/summaries/events, strategy result snapshots, backtest results/events/completion timestamps, and broker-stage response payloads.
- `tradingagents/integrations/futu/opend.py`: added a stage-only OpenD adapter that probes connectivity and returns staged order references without ever submitting live orders.
- `tests/test_web_workflow_contracts.py`: replaced the placeholder-oriented contract suite with Phase 11 route tests covering market overview, repeating market WebSocket snapshots, deterministic screening, basket hydration, batch execution/events, strategy planning, Futu staging, quant-strict backtests, history integration, settings persistence, and schema guards.

## Contracts exposed to next phase

- `GET /api/market/overview`
  - returns real `indices`, `regime`, `breadth`, `sectors`, `events`, `regions`, and `stream` objects.
  - regime is rule-based from benchmark trend, breadth, volatility, and credit-risk inputs.
- `WS /api/market/live`
  - now emits repeated `market_snapshot` events while connected.
  - supports `interval_seconds` query override for tests and low-latency consumers.
- `POST /api/screening/runs`
  - executes the quant ranking path immediately and returns persisted `results`, `home_market`, and `regime`.
- `POST /api/baskets`
  - now resolves and stores screening-derived item rows, not just raw symbols.
- `POST /api/batches`
  - fans out to the existing single-ticker runner, persists child item rows plus aggregate counts, and returns completed batch metadata.
- `GET /api/batches/{batch_id}/events`
  - streams persisted batch status and child-run milestone events from storage.
- `POST /api/strategies/from-batch`
  - builds a deterministic trade plan using persisted batch ratings plus quant risk sizing/stops.
  - persists full strategy result payloads used by History and Backtest.
- `POST /api/broker/futu/stage`
  - stage-only by construction; never live-submits.
  - returns persisted adapter response metadata and actionable failure details when OpenD is unavailable.
- `POST /api/backtests`
  - executes the quant backtest stack directly from the saved strategy or explicit symbol list.
  - keeps `execution_mode="quant_strict"` and `llm_constructed=false`.
  - persists per-symbol results, aggregate summary, equity curve, optional walk-forward folds, and event history.
- `GET /api/backtests/{backtest_id}/events`
  - streams persisted queued/running/completed symbol and batch-level execution events.

## Schema change

- Workflow SQLite schema version is now `2`.
- Fresh databases are initialized with the expanded Phase 11 result/event columns.
- Existing version `1` databases are rejected by the existing migration guard until an explicit migration exists.

## Test commands

```bash
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_web_workflow_contracts -v
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest discover -s tests -p 'test_web*.py' -v
```

## Known limitations / deferred decisions

- Market overview still uses lightweight static universes and proxy symbols for breadth/sector context; it is deterministic and testable, but not yet a full constituent-wide production feed.
- The batch route executes synchronously through the existing runner. It now persists real child items and events, but it is not yet a background job system with resumable workers.
- The FMP economic calendar integration is implemented as a simple HTTP fetch when `FMP_API_KEY` is present; without a key the calendar surface degrades to an empty list.
- The Futu adapter currently validates reachability and stages deterministic references only. It does not yet map to the full OpenD API surface.

## Reviewer focus

- Verify the schema version bump to `2` is intentional and correctly guarded against reuse of version `1` databases.
- Verify `GET /api/market/overview` classification logic matches the UX thresholds closely enough for the intended home-market behavior.
- Verify screening results, basket items, batch items/events, strategy payloads, backtest payloads, and stage responses all persist and flow into History consistently.
- Verify backtests never hit the web analysis runner or any LLM construction path.
- Verify the Futu adapter remains stage-only under both success and failure paths.
