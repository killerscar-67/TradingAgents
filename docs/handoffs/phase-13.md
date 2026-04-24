# Phase 13

## What was built

- Phase 13 hardening deliverables: hardened workflow history compatibility for mixed legacy and workflow metadata payloads.
- Phase 13 hardening deliverables: added null-safe and fallback-safe parsing for stored JSON metadata in workflow storage.
- Phase 13 hardening deliverables: added workflow history filtering and sorting safeguards for optional legacy fields.
- Phase 13 hardening deliverables: expanded phase tooling support so fix-notes automation accepts phase numbers through 13.
- Phase 13 hardening deliverables: added workflow contract tests for legacy history compatibility and case-insensitive item type filtering.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: added line-mode charting and timeframe controls to `TradingChart`, then switched backtest equity curves and market home-index panels to line charts.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: added workflow auto-advance state so the sidebar "Run full workflow" path can progress through the workflow while direct sidebar navigation still disables auto-advance.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded Backtest with 8 KPI cards, locally computed CAGR/Sortino/profit factor/average hold, and a trade log table.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded Batch with latest phase labels, a live event feed, Stop all confirmation, failed-ticker Retry/Skip actions, and a progressive Strategy CTA.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded Screening with selectable result rows, select-all, basket summary panel, universe selection, strategy radios, and planned client-side filter toggles.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded Strategy with R:R display, portfolio/risk controls, notes, Copy CSV, and Export CSV.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded History with search, type/status filters, and secondary row actions.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded Settings with Workflow Defaults, Futu/OpenD broker connection test, and Watchlists & Presets placeholder sections.
- Integrated UI scope delivered across Phase 12 and finalized in Phase 13 verification: expanded Market with home-index line chart, sector heatmap, and medium/high-impact economic calendar.

## Contracts exposed to next phase

- `TradingChart` accepts `mode="line"`, `lineData`, `timeframe`, and `onTimeframeChange` while preserving existing candlestick defaults.
- Workflow context now exposes `autoAdvance` and `setAutoAdvance`; user-initiated sidebar navigation disables auto-advance.
- `BatchEvent` accepts optional `phase`.
- `BacktestKpi` accepts optional `cagr_pct`, `sortino`, `profit_factor`, and `avg_hold_bars`; `TradeLogEntry` accepts optional `bars`.
- `AppSettings` accepts optional workflow/broker defaults: `top_n`, `score_floor`, `risk_per_trade_pct`, `portfolio_size`, `allow_shorts`, `futu_host`, and `futu_port`.
- `GET /api/history` now tolerates legacy run objects with missing optional fields (`status`, `completed_at`) and skips invalid entries missing `run_id`.
- `GET /api/history?item_type=...` now matches item type case-insensitively while preserving existing response shape.
- Workflow store JSON decoding now returns defined fallbacks when malformed payloads are encountered.
- No existing endpoint paths or top-level response keys were changed.

## Config keys added

- No new persisted backend config keys were added.
- UI-level settings alias mapping: `top_n` maps to `workflow_defaults.top_n`.
- UI-level settings alias mapping: `score_floor` maps to `workflow_defaults.min_score`.
- UI-level settings alias mapping: `risk_per_trade_pct` maps to `workflow_defaults.risk_per_trade` (percent presentation in UI).
- UI-level settings alias mapping: `portfolio_size` maps to `workflow_defaults.portfolio_size`.
- UI-level settings alias mapping: `allow_shorts` maps to `workflow_defaults.allow_shorts`.
- UI-level settings alias mapping: `futu_host` maps to `broker.futu.host`.
- UI-level settings alias mapping: `futu_port` maps to `broker.futu.port`.

## Test command

- `npm --prefix web test -- --run`
- `npm --prefix web run build`
- `tradingagent_venv/bin/python -m unittest tests.test_web_workflow_contracts -v`
- `tradingagent_venv/bin/python -m unittest tests.test_web_api tests.test_web_runner -v`
- `tradingagent_venv/bin/python -m unittest tests.test_quant_prefilter tests.test_execution tests.test_backtest -v`
- `bash -n scripts/review.sh scripts/run_phase.sh scripts/add_fix_notes.sh`

## Known limitations / deferred decisions

- Market chart, sector, calendar, batch stop/retry, and broker ping endpoints are consumed using planned REST paths; graceful empty states are retained when backends return placeholder or unavailable data.
- Screening filter toggles other than strategy/universe are UI-only until backend support is added.
- Strategy portfolio/risk controls recompute display values locally and do not persist sizing changes.
- History secondary actions expose UI affordances; deeper workflow context restoration remains a next-phase task.
- Frontend test suite currently passes with React `act(...)` warnings in asynchronous screen tests (Batch and Market), tracked as non-blocking test hygiene debt.
- Existing schema-version guard remains strict (`schema_version` must match current version); no migration path was introduced in this phase.
- Compatibility fallback currently treats malformed JSON payloads as absent data rather than preserving raw payloads for diagnostics.

## What the reviewer must focus on

- Verify Phase 13 UI additions do not invent incompatible backend contracts or break Phase 12 placeholder flows.
- Verify line chart mode still supports price lines and markers for future chart overlays.
- Verify auto-advance does not trap users after direct sidebar navigation.
- Verify CSV copy/export and Futu staging remain stage-only workflows.
- Verify no regressions in `GET /api/history` behavior for current Phase 9-12 workflows.
- Verify legacy analysis items with partial fields remain visible and sortable in history responses.
- Verify malformed JSON payloads in SQLite metadata surfaces fail open to safe defaults rather than raising.
- Confirm `scripts/add_fix_notes.sh` phase validation now matches `0..13` expectations used by phase tooling.

## Fix notes

- Pending review cycle.
