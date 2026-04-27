# Phase 10 Handoff — Workflow Persistence And Unified History
Agent: Copilot
Date: 2026-04-23

## What was built

- `tradingagents/web/storage.py`: added a stdlib SQLite-backed workflow metadata store keyed by `TRADINGAGENTS_WEB_DB` or `~/.tradingagents/web.sqlite3`, with `schema_version` tracking and a fail-fast guard for legacy unversioned databases.
- `tradingagents/web/routes/workflow.py`: replaced the Phase 9 placeholder behavior for settings, screening runs, baskets, watchlists, strategy presets, workflow sessions, and history-producing workflow mutations with persisted storage-backed responses.
- `tests/test_web_workflow_contracts.py`: upgraded the workflow contract test so it asserts persisted workflow behavior, stable IDs, session linkage, session resume APIs, grouped/filterable History behavior, session-market preservation, and schema-version guards instead of accepting empty Phase 9 stub responses.

## Contracts exposed to next phase

- `workflow_sessions`: persisted as a first-class SQLite surface. New workflow artifacts now create or advance a `session_id`, carry `current_screen`, `home_market`, `status`, artifact references, and a settings snapshot for resume behavior.
- `GET /api/workflow-sessions`: lists persisted workflow sessions with optional `status` filtering and `include_archived` support for resume/history UIs.
- `GET /api/workflow-sessions/{session_id}`: returns the stored workflow session record, including artifact references and settings snapshot.
- `PUT /api/workflow-sessions/{session_id}`: updates `current_screen` and/or `status` so the frontend can persist resume position and archive completed sessions.
- `POST /api/screening/runs`: now persists screening-run metadata to SQLite and returns a stable `run_id` plus `workflow_session_id`.
- `POST /api/baskets`: now persists basket metadata to SQLite and returns a stable `basket_id` plus `workflow_session_id`.
- `GET /api/settings`: returns persisted workflow settings merged with defaults, including `home_market`, provider/model selections, workflow defaults, and broker settings.
- `PUT /api/settings`: persists settings updates to SQLite and returns the saved values rather than echoing a stateless request body.
- `GET /api/watchlists` / `POST /api/watchlists`: persist and list saved watchlists with stable `watchlist_id`, normalized symbols, and timestamps.
- `GET /api/strategy-presets` / `POST /api/strategy-presets`: persist and list strategy presets with stable `preset_id`, portfolio/risk fields, config, and timestamps.
- `POST /api/batches`: writes batch-analysis metadata to SQLite, links it to the active workflow session, and exposes that session linkage back to the caller.
- `POST /api/strategies/from-batch`: writes saved strategy-plan metadata to SQLite and links it to the workflow session timeline.
- `POST /api/backtests`: still forces `execution_mode="quant_strict"` and `llm_constructed=false`, stores backtest metadata in SQLite, and marks the linked session as completed.
- `POST /api/broker/futu/stage`: preserves stage-only / non-submit safety flags, stores broker stage metadata in SQLite, and keeps the request linked to the same workflow session.
- `GET /api/history`: returns a unified feed combining persisted Phase 10 workflow artifacts with legacy single-ticker analysis archives from `runner.list_runs()`. Persisted rows include `workflow_session_id`; legacy rows emit `type="legacy_analysis"`. The route now supports filtering by item type, market, status, date range, and text search, plus `group_by=workflow_session` for grouped session timelines.

## Config keys added

- `TRADINGAGENTS_WEB_DB`: optional absolute or `~`-relative SQLite path for workflow metadata persistence.
  - Default: `~/.tradingagents/web.sqlite3`

## Test command

```bash
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_web_workflow_contracts -v
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest discover -s tests -p 'test_web*.py' -v
```

Expected: workflow persistence contracts pass; broader web API, consultant, runner, and workflow tests remain green.

## Known limitations / deferred decisions

- The Market screen remains contract-only; live streaming, deterministic screening, batch orchestration, strategy construction, and real backtest execution are still deferred to later phases.
- React workflow screens are not touched here; frontend persistence integration remains deferred to Phase 12.

## What the reviewer must focus on

- Verify `TRADINGAGENTS_WEB_DB` handling is deterministic and isolated enough for tests and local runs.
- Verify reused workflow sessions preserve their original `home_market` even if global Settings change before the next artifact is created.
- Verify screening runs and baskets now persist with stable IDs instead of returning Phase 9 placeholder bodies.
- Verify workflow artifacts created in sequence share a single `workflow_session_id` when linked through the workflow.
- Verify workflow-session list/detail/update APIs expose enough data for frontend resume and archive flows.
- Verify settings writes survive a follow-up `GET /api/settings` and do not regress default merging for omitted fields.
- Verify watchlists and presets are actually stored and listed, not acknowledged and discarded.
- Verify History includes the new workflow artifact types plus legacy archive rows, that legacy rows use `legacy_analysis` instead of the old `analysis` label, and that filter/group query parameters behave consistently.
- Verify backtest and Futu safety contracts remain intact after persistence wiring: quant-strict only, no LLM construction, stage-only broker behavior.

## Fix notes

- 2026-04-23: Addressed the initial Phase 10 reviewer findings against placeholder behavior in `tradingagents/web/routes/workflow.py`.
  - Persisted settings instead of returning hard-coded defaults and stateless echoes.
  - Persisted watchlists and strategy presets instead of returning empty arrays forever.
  - Added SQLite-backed metadata rows for batch, strategy, backtest, and broker-stage artifacts so History can surface them.
  - Unified the History feed with legacy runner archives and changed the legacy item type to `legacy_analysis`.
  - Tightened the workflow contract test so Phase 10 persistence regressions fail the suite.
- 2026-04-23: Completed the remaining Phase 10 backend slice.
  - Added `workflow_sessions` persistence with settings snapshots, current-screen tracking, and artifact references.
  - Persisted screening runs and baskets instead of returning Phase 9 contract placeholders.
  - Threaded `workflow_session_id` through batch, strategy, backtest, and broker-stage writes so History can reflect a coherent workflow timeline.
  - Extended the workflow contract test to assert stable IDs and shared session linkage across the workflow path.
- 2026-04-23: Finished the Phase 10 backend API surface.
  - Added workflow-session list/detail/update endpoints for resume and archive flows.
  - Added History filtering by item type, market, status, date range, and search text.
  - Added `group_by=workflow_session` so History can return grouped session timelines in one response.
- 2026-04-23: Addressed follow-up storage review findings.
  - Preserved the original session `home_market` when later artifacts reuse an existing `workflow_session_id`, and ensured downstream artifact rows inherit that session market instead of the current global Settings value.
  - Added `schema_version` tracking plus a fail-fast migration guard so reused legacy databases without version metadata are rejected explicitly.