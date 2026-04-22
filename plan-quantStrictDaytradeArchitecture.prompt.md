## Plan: Quant-Strict Daytrade Architecture

Updated to your latest direction: no swing lane for now, 15m-4h strict quant execution only, with LLM as support-only.

TL;DR: keep the current quant prefilter and caching as the front gate, then build a deterministic intraday quant core (regime → entry → validation → risk → execution), and isolate LLM to context/anomaly/post-trade reporting so it never controls orders.

**Steps**
1. Phase 0: Lock execution contracts — **Agent: Copilot**
1. Add explicit execution mode `quant_strict` in config and CLI.
2. Define deterministic output contracts for signal and order intent (no text parsing for execution).
3. Make LLM outputs non-blocking annotations only.

2. Phase 1: Intraday data foundation — **Agent: Codex (scaffold) + Copilot (wire)**
1. Add intraday bar module for 15m and 4h with timezone/session alignment.
2. Extend vendor routing for intraday data.
3. Add deterministic intraday cache behavior and validations.
4. Depends on phase 0.

3. Phase 2: Deterministic quant engine — **Agent: Claude Code**
1. Implement regime classifier: trending/ranging/consolidation + tradability filter.
2. Implement directional filter: HTF bias constraints for stocks/crypto.
3. Implement dual entry engines: breakout and mean reversion.
4. Implement validation filters: momentum acceleration, squeeze gate, SR proximity.
5. Depends on phase 1.

4. Phase 3: Hard risk and sizing — **Agent: Claude Code**
1. Implement position sizing (fixed fractional first, optional capped Kelly later).
2. Implement ATR stop, break-even trigger, trailing exits by engine type.
3. Add exposure caps, max daily loss, kill switch checks.
4. Replace execution dependence on LLM parsing in strict mode.
5. Depends on phase 2.

5. Phase 4: Execution and portfolio state — **Agent: Codex**
1. Add broker adapter abstraction and paper adapter first.
2. Add order manager and portfolio state reconciliation.
3. Enforce pre-trade guards: liquidity, slippage threshold, exposure, daily loss.
4. Depends on phases 2 and 3.

6. Phase 5: LLM support modules (non-execution) — **Agent: Codex**
1. Pre-trade brief: catalyst/event risk summary.
2. Anomaly watcher: binary risk flags.
3. Post-trade attribution: structured journaling.
4. Parallel with phase 4 after phase 0 contracts are fixed.

7. Phase 6: Validation gates — **Agent: Claude Code**
1. Bar-replay backtest for 15m and 4h with commission/slippage.
2. Walk-forward validation and paper-trading gate.
3. Promote to live only after performance and reliability thresholds are met.
4. Depends on phases 2 through 4.

8. Phase 7: Conversational trade-review consultant — **Agent: Codex**
1. Add a conversation-only review assistant that can answer questions about a completed or proposed trade using the existing context, support annotations, fills, and portfolio state.
2. Return structured advisory responses for rationale review, risk critique, post-trade learning, and follow-up questions.
3. Preserve the support-only boundary: consultant output cannot create, block, size, modify, or submit orders.
4. Depends on phases 4 and 5; can run after validation gates if the paper-trading workflow needs conversation over replay results.

9. Phase 8: Quant merge and token optimization — **Agents: Codex + Claude Code + Copilot**
1. Merge overlapping quant and original TradingAgents responsibilities so quant owns executable trading facts and agents own interpretation/explanation.
2. Implement in order: quant merge, risk/backtest/tool-output merge, then compact context/token optimization.
3. Use the Phase 8 coordination section in this file as the source of truth before implementation. Do not create `docs/handoffs/phase-8.md` until Phase 8 implementation is complete and ready for review.
4. Depends on phases 0 through 7.

**Phase 8 Coordination — Quant Merge And Token Optimization**

Goal: merge overlapping quant and legacy TradingAgents responsibilities first, then reduce agent token usage on top of the cleaner flow. Quant owns executable trading facts; agents own interpretation and explanation.

Merge order:

1. Quant merge.
2. Risk/backtest/tool-output merge.
3. Compact context/token optimization.

Phase 8 code changes should not start until `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and this Phase 8 section are present in the branch.

| Agent | Lane | Owned files | Focused tests |
|---|---|---|---|
| Codex | Quant executable layer | `tradingagents/quant/contracts.py`, `tradingagents/quant/engine.py`, `tradingagents/agents/utils/quant_tools.py`, `tradingagents/graph/trading_graph.py`, `tradingagents/graph/signal_processing.py` | `tests/test_execution_contracts.py`, `tests/test_quant_tool.py` |
| Claude Code | Agent context and prompt layer | `tradingagents/agents/utils/agent_states.py`, `tradingagents/agents/utils/agent_utils.py`, `tradingagents/agents/researchers/`, `tradingagents/agents/trader/`, `tradingagents/agents/risk_mgmt/`, `tradingagents/agents/managers/portfolio_manager.py` | compact-context graph/unit tests |
| Copilot | Risk reuse, tool output, telemetry | `tradingagents/quant/risk.py`, `tradingagents/quant/backtest.py`, `tradingagents/quant/execution.py`, `tradingagents/dataflows/y_finance.py`, `tradingagents/dataflows/yfinance_news.py`, `cli/stats_handler.py`, `cli/main.py` | `tests/test_backtest.py`, `tests/test_risk.py`, `tests/test_execution.py` |

Required reading:

- Codex reads first: `tradingagents/quant/contracts.py`, `tradingagents/quant/engine.py`, `tradingagents/agents/utils/quant_tools.py`, `tradingagents/graph/trading_graph.py`, `tradingagents/graph/signal_processing.py`, `tests/test_execution_contracts.py`, and `tests/test_quant_tool.py`.
- Claude Code reads first: `tradingagents/agents/utils/agent_states.py`, `tradingagents/agents/utils/agent_utils.py`, `tradingagents/agents/researchers/bull_researcher.py`, `tradingagents/agents/researchers/bear_researcher.py`, `tradingagents/agents/trader/trader.py`, `tradingagents/agents/risk_mgmt/aggressive_debator.py`, `tradingagents/agents/risk_mgmt/conservative_debator.py`, `tradingagents/agents/risk_mgmt/neutral_debator.py`, and `tradingagents/agents/managers/portfolio_manager.py`.
- Copilot reads first: `tradingagents/quant/risk.py`, `tradingagents/quant/backtest.py`, `tradingagents/quant/execution.py`, `tradingagents/dataflows/y_finance.py`, `tradingagents/dataflows/yfinance_news.py`, `cli/stats_handler.py`, `cli/main.py`, `tests/test_backtest.py`, `tests/test_risk.py`, and `tests/test_execution.py`.

Acceptance criteria:

- `get_quant_signals` emits `QuantSignalContract`-compatible payloads and uses `run_quant_engine` when intraday bars are available.
- The old MA/RSI signal path is retained only as an explicit fallback.
- `Rating:` lines are parsed deterministically before any LLM extraction in `llm_assisted` mode.
- `quant_strict` continues to avoid LLM calls for executable decisions.
- Backtest sizing and stops reuse `tradingagents.quant.risk`.
- Tool outputs are bounded by config-controlled caps.
- Token telemetry preserves existing aggregate totals and adds per-agent/per-stage totals.
- Downstream agents use compact `analysis_brief` context by default.
- `context_mode="full"` preserves legacy full-report prompt behavior.
- Fake LLMs are used for graph/unit tests unless the test targets provider adapters.

Validation matrix:

```bash
# Codex focused validation
tradingagent_venv/bin/python -m unittest tests.test_execution_contracts tests.test_quant_tool -v

# Claude Code focused validation
tradingagent_venv/bin/python -m unittest tests.test_compact_context -v

# Copilot focused validation
tradingagent_venv/bin/python -m unittest tests.test_backtest tests.test_risk tests.test_execution -v

# Full regression validation
tradingagent_venv/bin/python -m unittest discover tests -v
```

Conflict rules:

- Do not edit another agent's owned files without updating this Phase 8 section first.
- If a cross-lane change is unavoidable, document the reason here before implementation and run both agents' focused test sets.
- Prefer additive compatibility over removal. Keep public graph return shapes and existing contracts stable unless a test and this plan explicitly cover the change.
- Preserve exact ticker symbols and exchange suffixes in all prompt/context compaction work.
- Never let LLM output set executable rating, quantity, stops, blocked status, or risk-gate results in `quant_strict`.

Token-saving development rules:

- Use `rg` before opening files and read focused line ranges.
- Do not paste full reports, logs, generated JSON, or dataframe/CSV output into prompts.
- Summarize findings and cite file paths.
- Run focused tests before full test discovery.
- Keep prompts compact; pass structured quant/risk context instead of repeated full prose where possible.

**Handoff Protocol**

The agent completing each phase MUST produce a handoff note at `docs/handoffs/phase-<N>.md` before the reviewer starts. This replaces the need for any agent to read full source to get context. Format:

```
# Phase <N> Handoff — <title>
Agent: <who built it>
Date: <ISO date>

## What was built
- <file>: <one-line purpose, key public functions/classes with signatures>

## Contracts exposed to next phase
- <typed interface name>: <what it represents, where it lives>

## Config keys added
- <key>: <type>, default <value>, env override <VAR>

## Test command
<exact command to run tests for this phase>
Expected: <N> tests, all OK

## Known limitations / deferred decisions
- <anything the next agent or reviewer must be aware of>

## What the reviewer must focus on
- <specific concerns based on review scope table>
```

Reviewer reads only the handoff note + the diff (via `git diff main...phase/<N>`). Next-phase agent reads only the handoff note(s) of all prior phases — not the source files — to understand the contracts and config surface they depend on.

**Relevant files**
- [tradingagents/graph/trading_graph.py](tradingagents/graph/trading_graph.py) — add strict quant routing and keep LLM support routing.
- [tradingagents/graph/prefilter.py](tradingagents/graph/prefilter.py) — keep as universe gate and cache controller.
- [tradingagents/default_config.py](tradingagents/default_config.py) — add execution mode and quant/risk parameters.
- [cli/main.py](cli/main.py) — expose strict-mode and run controls.
- [tradingagents/graph/signal_processing.py](tradingagents/graph/signal_processing.py) — non-execution use only in strict mode.
- [tradingagents/agents/utils/quant_tools.py](tradingagents/agents/utils/quant_tools.py) — wrapper over deterministic quant modules.
- [tradingagents/dataflows/interface.py](tradingagents/dataflows/interface.py) — route intraday fetch calls.
- [tradingagents/agents/utils/llm_support.py](tradingagents/agents/utils/llm_support.py) — support-only LLM annotations and conversational trade-review consultant.
- [tests/test_quant_tool.py](tests/test_quant_tool.py) — evolve for new quant boundaries.
- [tests/test_quant_prefilter.py](tests/test_quant_prefilter.py) — retain cache TTL/refresh guarantees.

**Verification**
1. Unit tests for regime, entry, validation, sizing, and risk modules.
2. Determinism test: same inputs produce same outputs.
3. Integration test: prefilter → quant signal → risk gate → order intent.
4. Replay simulation with friction for 15m and 4h.
5. Paper execution lifecycle and portfolio reconciliation tests.
6. Conversation safety test: trade-review consultant cannot emit executable order mutations or non-binary risk controls.

**Code Review Allocation**

| Phase | Author | Reviewer | Rationale |
|---|---|---|---|
| 0 — Contracts + mode switch | Copilot | Claude Code | Contracts are invariants; Claude reasons about edge cases and type correctness deeply |
| 1 — Intraday data | Codex + Copilot | Claude Code | Data pipeline correctness, timezone edge cases, cache invalidation logic |
| 2 — Quant engine | Claude Code | Copilot | Copilot has full repo context to catch wiring/naming mismatches with existing code |
| 3 — Risk + sizing | Claude Code | Copilot | Verify integration with Phase 0 contracts and config keys |
| 4 — Broker + order manager | Codex | Claude Code | Order lifecycle has subtle state-machine correctness issues |
| 5 — LLM support modules | Codex | Copilot | Verify outputs are truly non-blocking and match Phase 0 annotation contracts |
| 6 — Backtest + paper gate | Claude Code | Codex | Codex spots simulation bias (lookahead, data leakage) as second perspective |
| 7 — Conversational trade review | Codex | Copilot | Verify consultant responses remain advisory, context-grounded, and disconnected from order execution |

Cross-cutting rule: any phase touching `trading_graph.py`, `prefilter.py`, or `default_config.py` — Copilot reviews regardless.

**Review Automation**

Yes, the review trigger can be automated. Recommended approach: a local shell script `scripts/review.sh <phase>` called from a git post-commit hook or a GitHub Actions workflow on push to `phase/<N>` branches.

How each reviewer is invoked:
- Claude Code: `claude --print "Review the following files for phase <N>. Scope: <scope>. Files: ..." < diff.txt` — runs headlessly, outputs findings to `reviews/phase-<N>.md`
- Copilot: VS Code task defined in `.vscode/tasks.json` invoking `gh copilot explain` with the diff piped in, or triggered manually in-editor for inline review
- Codex: `codex "Review this code. Scope: <scope>" --file <file>` — scripted via OpenAI CLI

Automation flow per phase:
1. Author agent finishes work, all tests pass locally.
2. Author commits to branch `phase/<N>` and pushes.
3. CI/hook runs `scripts/review.sh <N>`: extracts git diff, invokes reviewer CLI, saves output to `reviews/phase-<N>-review.md`.
4. Reviewer findings are posted as PR comments (if using GitHub) or opened as a file for triage.
5. Author agent addresses findings, re-runs tests, re-pushes; CI re-triggers review.
6. Phase is merged only when reviewer output contains no blocking findings.

Automation limits: Copilot review is best done interactively in VS Code rather than fully headless. Claude Code and Codex are fully scriptable via CLI.

**Review Scope**

| Phase | Reviewer | Scope |
|---|---|---|
| 0 | Claude Code | Contract completeness: all execution paths use typed contracts, no `str` parsing for orders, config defaults are safe, LLM outputs are annotation-only with no side effects |
| 1 | Claude Code | Timezone correctness and session boundary handling, cache key collision safety, no stale bar data on market open, vendor fallback behavior |
| 2 | Copilot | Determinism (same input → identical output), no hidden mutable state, signal logic matches spec, regime/entry/validation module boundaries are clean |
| 3 | Copilot | Sizing formula correctness, kill switch reachability on every code path, no float precision traps in stop calculations, exposure caps enforced before order |
| 4 | Claude Code | Order state machine completeness, idempotency of submit/cancel/fill operations, pre-trade guard ordering, paper adapter faithfully models slippage |
| 5 | Copilot | LLM output never reaches order path, structured output parsing is safe against malformed responses, anomaly flags are binary with no ambiguity |
| 6 | Codex | No lookahead bias (no future bar data accessible), commission and slippage modeling is realistic, walk-forward windows have no leakage between folds |
| 7 | Copilot | Conversation output is advisory only, uses provided trade context, safely handles prompt injection/malformed responses, and cannot mutate order intent or portfolio state |

**Acceptance Criteria**

Project-level (all must pass before any live promotion):
1. All phases pass unit + integration tests with zero failures.
2. Determinism: 100 runs of quant engine with identical inputs produce identical outputs.
3. No LLM-controlled order: audit log of a full paper session shows zero order decisions sourced from LLM output.
4. Kill switch: triggers correctly and halts all order submission within one bar on max daily loss breach.
5. Paper gate: 2 consecutive weeks of paper trading with session Sharpe > 0.5 and max intraday drawdown < 5%.

Per-phase acceptance criteria:
- Phase 0: `execution_mode=quant_strict` routes all order paths through typed contracts; `mypy --strict` passes on contracts module; existing 10 tests still pass.
- Phase 1: 15m and 4h bars fetch correctly for NYSE/crypto sessions; cache returns identical DataFrame on repeat call with same key; no data beyond current bar is accessible.
- Phase 2: Regime classifier returns one of {trending, ranging, consolidation} with reproducible label for fixed seed data; entry engine emits typed `EntrySignal` or `NoSignal`; validation filters are independently togglable.
- Phase 3: Position size is deterministic given account equity and ATR; stop loss never exceeds configured max risk per trade; daily loss accumulator correctly gates new orders after limit hit.
- Phase 4: Paper adapter fills at next-bar open with configured slippage; order manager reconciles fills without duplication; portfolio state matches sum of all fills.
- Phase 5: Pre-trade brief and attribution are fire-and-forget; anomaly watcher emits `bool` flag only; none of the three modules can block or modify an order.
- Phase 6: Backtest equity curve matches manual spot-check on 3 known trades; walk-forward out-of-sample Sharpe > 0 on 80% of folds; paper gate runs without error for full 2-week window.
- Phase 7: Trade-review consultant answers follow-up questions from supplied trade context; responses are structured, advisory, and unable to change order intent, risk gates, fills, or portfolio state.

**Decisions**
- Included:
1. 15m-4h strict quant execution.
2. LLM support-only for daytrade.
3. Parameter-exposed architecture for optimization.
4. Conversational trade-review consultant for research, journaling, and post-trade learning.
- Excluded:
1. Swing-lane implementation for now.
2. LLM-driven order decisions.
3. Production live trading before paper gate passes.
