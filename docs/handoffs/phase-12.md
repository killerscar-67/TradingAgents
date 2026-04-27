# Phase 12 Handoff — Frontend Workflow Integration
Agent: Claude Code (initial implementation), Codex (integration fixes)
Date: 2026-04-24

## What was built

- `web/src/App.tsx`, `web/src/components/AppShell.tsx`, `web/src/components/Sidebar.tsx`, and `web/src/contexts/WorkflowContext.tsx` add the workflow shell and client state for `market -> screen -> batch -> strategy -> backtest -> history -> settings`.
- `web/src/components/Dialog.tsx`, `web/src/components/InheritedChip.tsx`, `web/src/components/Tooltip.tsx`, and `web/src/components/TradingChart.tsx` add the shared UI primitives used across the workflow screens.
- `web/src/hooks/useMarketOverview.ts`, `web/src/hooks/useBatchEvents.ts`, `web/src/hooks/useBacktestEvents.ts`, and `web/src/hooks/useSettings.ts` connect the workflow UI to the new Phase 11 API surfaces.
- `web/src/screens/MarketScreen.tsx`, `ScreeningScreen.tsx`, `BatchScreen.tsx`, `StrategyScreen.tsx`, `BacktestScreen.tsx`, `HistoryScreen.tsx`, and `SettingsScreen.tsx` implement the first pass of the workflow screens and their screen-specific CSS modules.
- `web/src/types.ts` now includes the workflow view-model types used by the frontend screens, SSE hooks, settings form, and history feed.
- `web/src/test-setup.ts` and the new screen/context/component test files add frontend coverage for the workflow shell and screen flows.

## Integration fixes applied after review

- `web/src/screens/MarketScreen.tsx`
  - moved `setRegime()` out of render and into an effect to remove the React render-phase state update warning.
- `web/src/contexts/WorkflowContext.tsx`
  - memoized action callbacks so screen effects can safely depend on stable setters.
- `web/src/hooks/useMarketOverview.ts`
  - aligned the live stream client with the backend `market_snapshot` wrapper instead of assuming the WebSocket pushes raw partial payloads.
- `web/src/hooks/useSettings.ts`
  - aligned `PUT /api/settings` with the backend contract by sending `{ "values": ... }` and reading `{ "status": ..., "values": ... }`.
  - strips the client-only `status` field before saving.
- `web/src/hooks/useBatchEvents.ts` and `web/src/screens/BatchScreen.tsx`
  - aligned batch SSE handling with backend `batch_status` and `batch_item` events.
  - switched from the nonexistent `ticker`/`batch_complete` expectation to the real `symbol` field and terminal `status` values.
  - now tracks the last processed event index and applies every newly received `batch_item`, so burst deliveries do not drop intermediate symbol updates.
- `web/src/hooks/useBacktestEvents.ts` and `web/src/screens/BacktestScreen.tsx`
  - aligned backtest SSE handling with backend `backtest_status` and `backtest_symbol` events.
  - stopped waiting for a nonexistent `backtest_complete` event.
  - mapped persisted backtest payloads into the frontend KPI/equity chart view model instead of assuming a frontend-local result shape.
  - now re-fetches `GET /api/backtests/{backtest_id}` after terminal SSE so the persisted detail route is exercised in the normal flow.
- `tradingagents/web/routes/workflow.py`
  - added `GET /api/backtests/{backtest_id}` so the frontend can hydrate a persisted backtest result after SSE completion.
  - `POST /api/backtests` now also returns `strategy_id`, `start_date`, and `end_date` so the frontend backtest view model remains type-safe on the initial response.
- `web/src/screens/StrategyScreen.tsx`
  - mapped backend `trades`/`exposure`/`request` fields into the screen’s `TradePlan` view model instead of expecting `data.plan`.
  - aligned Futu staging with backend `strategy_id`/`workflow_session_id`/`orders` input instead of posting frontend-only `trade_plan` and `tickers` fields.
- `web/src/screens/HistoryScreen.tsx`
  - aligned history loading with the backend envelope response and renders unified history `items` safely instead of assuming a flat `AnalysisRun[]`.
- frontend tests
  - updated mocked contracts to match the real backend request/response shapes.
  - added coverage for History and Settings contract handling.
  - added assertions for the exact staged Futu `orders` payload.
  - added a BacktestScreen regression test that drives terminal SSE and verifies the follow-up `GET /api/backtests/{backtest_id}` fetch.
  - added a BatchScreen regression test that emits multiple `batch_item` events in a burst and verifies both symbol cards update.
- `tests/test_web_workflow_contracts.py`
  - now covers `GET /api/backtests/{backtest_id}` directly, including the stored-record shape and the `404` path for unknown ids.
- `web/src/test-setup.ts`
  - adds jsdom stubs needed by the chart-bearing screen tests so the workflow suite runs cleanly under `vitest`.

## Contracts expected by the Phase 12 frontend

- `GET /api/market/overview`
  - returns a full market overview payload; the frontend currently consumes `regime`, `indices`, and `breadth`.
- `WS /api/market/live`
  - emits `market_snapshot` messages with a nested `payload`.
- `PUT /api/settings`
  - request body must be `{ "values": { ... } }`.
  - response body is `{ "status": "...", "values": { ... } }`.
- `GET /api/batches/{batch_id}/events`
  - emits `batch_status` and `batch_item` events.
  - batch item events use `symbol`, not `ticker`.
- `POST /api/strategies/from-batch`
  - returns `strategy_id`, `trades`, `exposure`, `risk`, and `request`; it does not return a nested `plan` object.
- `POST /api/broker/futu/stage`
  - accepts `strategy_id`, optional `workflow_session_id`, and `orders`.
- `POST /api/backtests`
  - returns the persisted backtest envelope, including `backtest_id`, `strategy_id`, `start_date`, `end_date`, `status`, and initial `result`.
- `GET /api/backtests/{backtest_id}`
  - returns the stored backtest run plus nested `result`.
- `GET /api/backtests/{backtest_id}/events`
  - emits `backtest_status` and `backtest_symbol` events; completion is indicated by `backtest_status.status == "completed"`.
- `GET /api/history`
  - returns an envelope with `items`, `total`, `status`, and optional `groups`.

## Validation

```bash
cd /Users/josephwong/TradingAgents/web && npm test
cd /Users/josephwong/TradingAgents/web && npm run build
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_web_workflow_contracts -v
```

- Result at handoff time: frontend `14` test files passed, `57` tests passed.
- Frontend production build passed.
- Backend workflow contract suite rerun after the follow-up fixes: `12` tests passed.

## Known limitations / deferred decisions

- Screening still keeps the basket selection client-side and does not persist a basket through `POST /api/baskets`; batch launch currently posts `symbols` directly.
- The Screening form still uses a lightweight frontend payload and does not yet pass the full Phase 11 screening request shape through to the backend.
- History now renders the backend envelope safely for all artifact types, but only legacy single-ticker archives currently reopen into the existing `RunDetail` view. Workflow-native reopen actions are not wired yet.
- The Market screen currently renders only part of the backend market payload. Sector heatmap and economic calendar surfaces from the UX spec are still deferred.
- Backtest KPI cards are rendered from the persisted result payload, but some aggregate metrics are still derived client-side when the backend summary omits them.

## Fix notes

- [docs/handoffs/history/phase-12/fix-notes-20260424.md](history/phase-12/fix-notes-20260424.md) — Applied fixes for review [reviews/phase-12/review-20260423_182016-a0a6585.md](../../reviews/phase-12/review-20260423_182016-a0a6585.md): POST backtest response contract, dead GET re-fetch path, BatchScreen burst-event cursor, and Futu orders shape assertion.

## Reviewer focus

- Verify the frontend/backend contract fixes are reflected in the handoff: Settings, Strategy, Batch SSE, Backtest SSE, Backtest detail hydration, History, and Market render timing.
- Verify the additive `GET /api/backtests/{backtest_id}` route is acceptable as the Phase 12 read path for persisted results.
- Verify the documented deferred items are intentional, especially the missing persisted basket flow and the incomplete workflow-native History reopen actions.
