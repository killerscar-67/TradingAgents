# Day-Trade Workflow Implementation Plan

## Summary
Build `docs/ux-design-daytrade-workflow.md` as UX phases `9-13` on the existing FastAPI + React web UI. The implementation keeps the current single-ticker analysis runner as the per-ticker primitive, adds workflow/session APIs around it, and stores workflow metadata in SQLite while large reports remain in `results_dir`.

## Key Changes
- **Frontend:** Replace the single-form app with a desktop sidebar workflow: Market, Screen, Analyze, Strategy, Backtest, History, Settings. Add shared workflow state, inherited-from chips, live Market connection states, batch progress cards, strategy tables, export/stage dialogs, and backtest charts.
- **Backend:** Add typed FastAPI routes for market overview/live quotes, screening, baskets, batch analysis, strategy planning, Futu stage-only broker export, backtests, settings, watchlists, presets, and history.
- **DB:** Add stdlib SQLite storage at `TRADINGAGENTS_WEB_DB` or `~/.tradingagents/web.sqlite3`; no ORM dependency. Tables: `schema_version`, `settings`, `workflow_sessions`, `watchlists`, `screening_runs/results`, `baskets/items`, `analysis_batches/items`, `strategy_presets/runs`, `backtest_runs`, `broker_stage_requests`.
- **Safety:** Futu integration only stages orders and never submits. Backtests force `execution_mode="quant_strict"` and must not construct an LLM client.

## Public Interfaces
- Add API surface:
  `GET /api/market/overview`, `WS /api/market/live`, `POST /api/screening/runs`, `POST /api/baskets`, `POST /api/batches`, `GET /api/batches/{id}/events`, `POST /api/strategies/from-batch`, `POST /api/broker/futu/stage`, `POST /api/backtests`, `GET /api/backtests/{id}/events`, `GET/PUT /api/settings`, `GET/POST /api/watchlists`, `GET/POST /api/strategy-presets`, `GET /api/history`.
- Add mirrored TypeScript types in `web/src/types.ts`; keep them manually maintained for v1.
- Add workflow/backend models for `MarketOverview`, `ScreeningRun`, `TickerBasket`, `AnalysisBatch`, `TradePlan`, `StrategyPreset`, `BacktestRun`, `WorkflowSession`, `SettingsSnapshot`, and `HistoryEntry`.

### Phase 10 contract notes

- `workflow_sessions` is a first-class persistence surface, not an internal implementation detail. Each session stores the current workflow stage, home market, inherited upstream artifacts, selected basket/strategy/backtest references, and the last-opened screen so the desktop workflow can resume exactly where the user left it.
- `GET /api/history` must return a unified history feed covering batch analyses, saved strategy plans, backtest runs, staged broker exports, and legacy single-ticker archives already stored on disk. SQLite stores metadata and paths; large report markdown and JSON remain in `results_dir`.
- `GET/PUT /api/settings` must cover at minimum: home market, data vendor choice, economic-calendar source, live-quote mode, model/provider selections, default workflow shortcut universe, broker staging settings, and cost/runtime preferences used by the screen and batch estimates.
- The UX design doc is the source of truth for History filters/actions, Settings sections, and workflow-session resume behavior. Phase 10 should not invent alternate shapes.

## Agent Allocation
- **Codex, reviewed by Claude Code:** update [scripts/review.sh](/Users/josephwong/TradingAgents/scripts/review.sh) and [scripts/run_phase.sh](/Users/josephwong/TradingAgents/scripts/run_phase.sh); implement backend workflow APIs, deterministic market/screening/strategy/backtest orchestration, and Futu stage-only adapter.
- **Copilot, reviewed by Codex:** implement SQLite storage, idempotent schema initialization, settings/watchlists/presets/history persistence, archive compatibility, and mechanical route/test wiring.
- **Claude Code, reviewed by Copilot:** implement the React desktop workflow, screen UX, shared state/hooks, charts/tables/dialogs, copy states, frontend tests, and responsive constraints for desktop-only layouts.

## Phase Map For Scripts
- **Phase 9:** Codex owner, Claude reviewer. Tooling update plus backend API contracts and route skeletons.
- **Phase 10:** Copilot owner, Codex reviewer. SQLite storage, settings, watchlists, presets, history metadata.
- **Phase 11:** Codex owner, Claude reviewer. Market overview/live quote service, screening, baskets, batch runner, strategy planner, Futu staging, quant-strict backtest routes.
- **Phase 12:** Claude Code owner, Copilot reviewer. Frontend workflow screens and integration with the new APIs.
- **Phase 13:** Copilot owner, Codex reviewer. End-to-end hardening, legacy archive compatibility, docs/handoffs, and focused regression cleanup.

Script updates:
- Extend phase validation from `0..6` to `0..13`.
- Preserve existing phase behavior for `0..8`.
- For phases `9..13`, use `docs/ux-design-daytrade-workflow.md` as the plan source and emit phase-specific context instead of parsing `plan-quantStrictDaytradeArchitecture.prompt.md`.
- Add reviewer scopes/non-goals for UX phases.
- Add phase-specific validation commands: Python web tests, quant/backtest safety tests, `bash -n` for scripts, and `npm --prefix web test && npm --prefix web run build`.

## Test Plan
- Backend: `python -m unittest tests.test_web_api tests.test_web_runner tests.test_quant_prefilter tests.test_execution tests.test_backtest -v`.
- New DB/API tests: schema initialization, CRUD, archive hydration, batch status transitions, backtest no-LLM guard, Futu stage-only behavior.
- Frontend: `npm --prefix web test` and `npm --prefix web run build`.
- Script checks: `bash -n scripts/review.sh scripts/run_phase.sh`; verify phases `9-13` route to the expected owner/reviewer and produce correct manual Copilot instructions.

## Assumptions
- Use SQLite, not JSON-only persistence, because watchlists, presets, workflow sessions, and history need queryable metadata.
- Keep existing report markdown/JSON artifacts on disk; DB stores metadata and paths.
- Default home market is `US`; the one-click workflow shortcut screens the top 10 names from the default universe for the selected home market (`S&P 500` for US, `HSI` for HK, `Nikkei 225` for JP, etc.).
- Desktop-only means no mobile navigation or breakpoint-specific layouts in v1.
