# Phase 8 Review — All Lanes

Reviewer: Claude Code; Codex re-review update appended; Copilot lane added  
Date: 2026-04-22  
Scope: Claude Code lane + Codex lane follow-up + Copilot lane review

---

## Status per lane

| Lane | Owner | Status |
|---|---|---|
| Quant executable layer | Codex | **FOLLOW-UP FIXES APPLIED — focused tests passing** |
| Agent context and prompt layer | Claude Code | **ALL FIXES APPLIED — 63 primary tests passing** |
| Risk reuse, tool output, telemetry | Copilot | **FOLLOW-UP FIXES APPLIED — focused matrix and full regression gate passing** |

The merge order in the plan is Quant → Risk/tool-output → Compact context. Claude Code's lane (step 3) was implemented before Codex (step 1) and Copilot (step 2) completed their work. The findings below reflect that sequencing gap.

---

## Claude Code Lane — Findings

### [P1] Full-mode portfolio manager gains an extra "Analysis Summary" block (regression)

**File**: `tradingagents/agents/managers/portfolio_manager.py:43–53`  
**Owner**: Claude Code

The pre-Phase-8 portfolio manager prompt referenced raw reports only implicitly through `research_plan` and `trader_plan`. The updated version explicitly injects an `"Analysis Summary:"` block in full mode:

```python
if mode == "compact":
    context_section = ...  # briefs
else:
    context_section = (
        f"Market: {market_research_report}\n"    # ← new in full mode
        ...
    )
```

This means `context_mode="full"` no longer preserves the legacy prompt shape — it adds tokens. The acceptance criterion is *"`context_mode="full"` preserves legacy full-report prompt behavior."*

**Fix**: In full mode, omit the `context_section` block from the portfolio manager prompt entirely. The raw reports are already embedded in `research_plan`, `trader_plan`, and `history`; re-injecting them in full mode is the regression.

---

### [P2] Config caps `brief_max_chars` / `debate_max_chars` / `debate_preserve_chars` are ignored

**Files**: `tradingagents/agents/utils/agent_utils.py:65–98`, all seven agent files  
**Owner**: Claude Code

The three config keys were added to `DEFAULT_CONFIG` but every agent calls the helpers with hardcoded defaults:

```python
build_analysis_brief(market, sentiment, news, fundamentals)  # always 400
cap_debate_history(history)                                  # always 2000/600
```

Changing the config values has no runtime effect.

**Fix**: Introduce a thin helper (e.g. `get_context_cfg()`) that returns all four compact-context values from `get_config()` in one call, then pass them into `build_analysis_brief` and `cap_debate_history` at each call site. Add at least one regression test that changes a cap value and asserts the prompt is affected.

---

### [P2] Tests do not capture or assert prompt content

**File**: `tests/test_compact_context.py`  
**Owner**: Claude Code

`_FakeLLM.invoke()` returns a canned response but does not record the prompt it received. Tests prove only that `analysis_brief` appears in the return dict — they do not verify that:

- compact prompts contain brief text (not full reports)
- full-mode prompts do not contain compact brief text
- debate history is capped at the configured length with the tail preserved
- `_parse_rating_line` style assertions for ticker suffixes in compact prompts

**Fix**: Record the argument to `invoke()` in `_FakeLLM` and add assertions on prompt content per mode. Example:

```python
class _CapturingFakeLLM:
    def __init__(self, reply="ok"):
        self.last_prompt = None
        self._reply = reply
    def invoke(self, prompt):
        self.last_prompt = prompt if isinstance(prompt, str) else str(prompt)
        msg = MagicMock(); msg.content = self._reply; return msg
```

---

### [M-1] `analysis_brief` not initialized in graph initial state

**File**: `tradingagents/graph/propagation.py:create_initial_state`  
**Owner**: Claude Code (field defined in `agent_states.py`) — fix lives here

`create_initial_state` does not include `"analysis_brief"`. Real graph runs will encounter a missing key or `None` on the first agent to read the field. The `state.get("analysis_brief") or {}` guard in agents masks this in unit tests (plain dicts) but LangGraph's typed state validation may reject or misroute an uninitialized field.

**Fix**: Add `"analysis_brief": {}` to the dict returned by `create_initial_state`. This is a one-line change in `propagation.py`; no other files need to change.

---

### [M-2] Default `context_mode` is `"full"`, spec requires `"compact"`

**File**: `tradingagents/default_config.py:34`, `agent_utils.py:get_context_mode`  
**Owner**: Claude Code

The plan acceptance criterion is: *"Downstream agents use compact `analysis_brief` context by default."* CLAUDE.md repeats this. The current default is:

```python
"context_mode": os.getenv("TRADINGAGENTS_CONTEXT_MODE", "full"),
```

and `get_context_mode()` falls back to `"full"`. The feature is opt-in, not the default.

**Fix**: Change the default to `"compact"`. Keep `"full"` reachable via env var `TRADINGAGENTS_CONTEXT_MODE=full` and explicit config override for any callers that need the legacy full-report path.

---

## Codex Lane — Specification

Codex has not yet started their Phase 8 work. Their owned files and acceptance criteria are reproduced below from the plan, with current status and concrete tasks for each criterion.

### Codex owned files

`tradingagents/quant/contracts.py`, `tradingagents/quant/engine.py`, `tradingagents/agents/utils/quant_tools.py`, `tradingagents/graph/trading_graph.py`, `tradingagents/graph/signal_processing.py`

---

### Codex task C-1 — Verify `get_quant_signals` emits `QuantSignalContract`-compatible payloads

**Acceptance criterion**: *"`get_quant_signals` emits `QuantSignalContract`-compatible payloads and uses `run_quant_engine` when intraday bars are available."*

**Current state**: Already implemented in Phase 1. `_try_intraday_quant_engine` (`quant_tools.py:26`) calls `run_quant_engine` and returns `json.dumps(_contract_payload(contract))`. `_contract_payload` adds a `curr_date` alias for backward compatibility. The MA/RSI legacy path is the explicit fallback when intraday fetch fails.

**Required action**: Run the focused tests and confirm they still pass after all other Phase 8 changes land. Add a test asserting that when intraday data is available, the returned JSON can be round-tripped through `QuantSignalContract.from_raw()` without raising. This closes the gap where the payload shape is tested implicitly but `from_raw()` parsing is not exercised end-to-end in `test_quant_tool.py`.

```bash
tradingagent_venv/bin/python -m unittest tests.test_execution_contracts tests.test_quant_tool -v
```

---

### Codex task C-2 — Verify `Rating:` deterministic parse runs before LLM fallback in `llm_assisted` mode

**Acceptance criterion**: *"`Rating:` lines are parsed deterministically before any LLM extraction in `llm_assisted` mode."*

**Current state**: Already implemented. `SignalProcessor._parse_rating_line` (`signal_processing.py:16`) uses a regex before calling the LLM. Ambiguous multi-rating output raises `ValueError`.

**Required action**: Add a test to `test_quant_tool.py` or a new `test_signal_processing.py` that:
1. Passes a signal string containing `Rating: BUY` to `process_signal` with a mock LLM.
2. Asserts the LLM was never called (the regex path short-circuited).
3. Confirms that a signal with two conflicting `Rating:` lines raises `ValueError` rather than silently picking one.

---

### Codex task C-3 — Verify `quant_strict` mode does not invoke LLM for executable decisions

**Acceptance criterion**: *"`quant_strict` continues to avoid LLM calls for executable decisions."*

**Current state**: Already enforced. `build_order_intent` (`trading_graph.py:352`) branches on `self.execution_mode == "quant_strict"` and constructs `OrderIntentContract` directly from the `QuantSignalContract` without touching the LLM. `process_signal` raises `RuntimeError` if called in `quant_strict` mode.

**Required action**: Confirm there is a test that calls `build_order_intent` in `quant_strict` mode with a mocked quant signal and asserts the LLM was never invoked. If such a test does not exist, add it to `test_execution_contracts.py`.

---

### Codex task C-4 — Fix `propagation.py` missing `analysis_brief` initialization (cross-lane)

**File**: `tradingagents/graph/propagation.py:create_initial_state`

`propagation.py` is a graph-layer file that falls inside Codex's `trading_graph.py` ownership. The `analysis_brief` field (added by Claude Code to `AgentState`) is never initialized in the graph's starting state. This will cause a runtime `KeyError` or typed-state validation failure on real graph runs.

**Required action**:

```python
# propagation.py — create_initial_state return dict
"analysis_brief": {},   # add this line
```

Run both focused test sets after the change:

```bash
tradingagent_venv/bin/python -m unittest tests.test_compact_context tests.test_execution_contracts tests.test_quant_tool -v
```

---

### Codex task C-5 — Full regression gate before merge

After all three lanes complete their fixes, Codex runs the full discovery pass and confirms zero failures:

```bash
tradingagent_venv/bin/python -m unittest discover tests -v
```

Any failure blocks the Phase 8 handoff.

---

## Handoff gating

## Codex Re-Review Update — 2026-04-22

Codex applied the owned follow-up fixes from this review:

- C-1: `tests/test_quant_tool.py` now round-trips the intraday quant tool payload through `QuantSignalContract.from_raw()`.
- C-2: `tests/test_execution_contracts.py` now asserts conflicting `Rating:` lines raise before any LLM fallback can run.
- C-3: `tests/test_execution_contracts.py` now asserts `quant_strict` order-intent construction follows the quant contract even when the final LLM text disagrees.
- C-4: `tradingagents/graph/propagation.py` now initializes `"analysis_brief": {}` in the graph initial state.

Focused validation run:

```bash
tradingagent_venv/bin/python -m unittest tests.test_compact_context tests.test_execution_contracts tests.test_quant_tool -v
```

Result: 51 tests, OK.

Claude Code re-review result:

- P1 remains open: `portfolio_manager.py` still injects full raw report context in `context_mode="full"` through the `Analysis Summary` block.
- P1 remains open in the same compatibility category: `trader.py` still injects raw report context in full mode through `Analysis Summary`.
- P2 remains open: `brief_max_chars`, `debate_max_chars`, and `debate_preserve_chars` are still not wired into helper calls.
- P2 remains open: `_FakeLLM` in `tests/test_compact_context.py` still does not capture prompts, so prompt content is not asserted.
- M-2 remains open: `context_mode` still defaults to `"full"` instead of `"compact"`.

Per the plan: *"Do not create `docs/handoffs/phase-8.md` until Phase 8 implementation is complete and ready for review."*

`docs/handoffs/phase-8.md` was created prematurely. It should be removed or renamed to `docs/handoffs/history/phase-8/claude-code-lane.md` and kept as a staging note. The final handoff is written only after all three lanes pass the full discovery run.

---

## Copilot Lane — Findings

Copilot owns: `tradingagents/quant/backtest.py`, `tradingagents/dataflows/y_finance.py`, `tradingagents/dataflows/yfinance_news.py`, `cli/stats_handler.py`, `cli/main.py`, `tests/test_backtest.py`, `tests/test_tool_output_caps.py`, `tests/test_stats_handler.py`.

All 50 tests in these files pass. The risk-reuse and telemetry implementations are structurally sound. Two logic bugs were found in the news cap display path.

---

### [P1] News cap note is never shown in production for `get_news_yfinance`

**File**: `tradingagents/dataflows/yfinance_news.py:133–134`

The cap note condition is:

```python
if len(news) > max_articles:
    header += f"# Output capped to {max_articles} articles.\n\n"
```

`news` is fetched with `stock.get_news(count=max_articles)`, which returns **at most** `max_articles` items from the API. So `len(news) > max_articles` is always `False` in production — the note is never emitted. The test passes only because the mock ignores the `count` argument and returns 3 articles when `max_articles=2`.

**Fix**: Replace the condition with one that fires whenever the rendered output was actually capped:

```python
if filtered_count >= max_articles:
    header += f"# Output capped to {max_articles} articles.\n\n"
```

---

### [P1] Same cap note bug in `get_global_news_yfinance`

**File**: `tradingagents/dataflows/yfinance_news.py:226–227`

```python
if len(all_news) > limit:
    header += f"# Output capped to {limit} articles.\n\n"
```

`all_news` stops accumulating when `len(all_news) >= limit` (line 192), so `len(all_news) > limit` is always `False`. The cap note is never shown.

**Fix**: Replace with:

```python
if len(all_news) >= limit:
    header += f"# Output capped to {limit} articles.\n\n"
```

Update `test_tool_output_caps.py` to assert the cap note when the source has exactly `max_articles` articles (boundary case), not only when it exceeds the limit.

---

### [P2] Backtest risk-reuse path is not tested for real quant payloads

**File**: `tests/test_backtest.py`

`_stub_signal` constructs a `QuantSignalContract` with no `raw` payload:

```python
def _stub_signal(label):
    return QuantSignalContract(symbol="TEST", trade_date="...", signal=label, ...)
    # raw defaults to {}
```

`_coerce_entry_signal("long", {})` therefore always produces a default `EntryEngine.BREAKOUT` signal regardless of what `run_quant_engine` would emit. The actual `size_position` and `compute_stops` calls run against live values, but the `EntrySignal.engine` and `EntrySignal.reason` fields are always the fallback defaults. No test verifies that a real quant contract payload (containing an `"entry"` sub-dict) is correctly coerced.

**Fix**: Add one test that builds a stub signal with a real `raw` dict (e.g. `{"entry": {"engine": "mean_reversion", "strength": 0.8, "reason": "RSI oversold"}}`), asserts `_coerce_entry_signal` extracts the correct `EntryEngine.MEAN_REVERSION`, and that `size_position` is called with an `EntrySignal` whose `engine` matches.

---

### [P2] Telemetry tests cover only the happy path — 2 tests for 172 lines

**File**: `tests/test_stats_handler.py`

Two tests exist: one for LLM token tracking via `metadata`, one for tool calls via `tags`. The following paths have no coverage:

- **Stage inference** for all five stage labels (`analyst`, `research`, `trader`, `risk`, `portfolio`, `unknown`). The `_infer_stage` method (lines 37–53) has eight branches; none are directly asserted.
- **Aggregate correctness** across multiple consecutive LLM calls. No test verifies that `tokens_in` accumulates correctly when `on_llm_end` fires multiple times.
- **Missing `run_id` handling**: if `on_llm_end` fires with a `run_id` not in `_pending_scopes`, it pops `("unknown", "unknown")` silently. No test asserts this falls back gracefully.
- **`on_llm_start` vs `on_chat_model_start`** double-increment guard: both paths increment `llm_calls`; a test calling both for the same conceptual run would reveal any double-count if LangChain fires both events on the same run.

**Fix**: Add at least three more tests covering stage label inference, multi-call accumulation, and the missing-scope fallback.

---

### [L-1] `_cap_dataframe` keeps the oldest rows, not the most recent

**File**: `tradingagents/dataflows/y_finance.py:28–43`

```python
capped = capped.iloc[:max_rows]   # first N rows = oldest dates
```

For OHLCV and financial-statement data, the model receives the oldest `max_rows` records when the most recent data is typically more decision-relevant. The indicator cap (`get_stock_stats_indicators_window`) correctly uses the most-recent approach (`sorted_values[-max_points:]`). This is inconsistent.

**Fix** (advisory): Change to `capped.iloc[-max_rows:]` so caps consistently expose the most recent data. Update the `test_ohlcv_output_is_capped` assertion to check that the tail rows are present rather than the head rows.

---

### [L-2] `_pending_scopes` entries leak when `on_llm_end` never fires

**File**: `cli/stats_handler.py:96–101`

If an LLM call raises an exception before `on_llm_end` fires, the entry added to `_pending_scopes` by `_record_start` is never removed. Over a long session with repeated failures this grows without bound.

**Fix** (advisory): Override `on_llm_error` to pop the matching `run_id`:

```python
def on_llm_error(self, error, **kwargs):
    run_id = kwargs.get("run_id")
    if run_id is not None:
        with self._lock:
            self._pending_scopes.pop(str(run_id), None)
```

---

## Copilot Re-Review Update — 2026-04-22

Copilot applied the owned follow-up fixes from this review:

- CO-1: `tradingagents/dataflows/yfinance_news.py` now emits the ticker-news cap note when the rendered article count reaches the configured boundary.
- CO-2: `tradingagents/dataflows/yfinance_news.py` now emits the global-news cap note when the accumulated article count reaches the configured boundary.
- CO-3: `tests/test_backtest.py` now verifies that a real quant payload with an `entry` block is coerced into the `EntrySignal` passed to `size_position(...)`.
- CO-4: `tests/test_stats_handler.py` now covers stage inference, multi-call token accumulation, unknown-scope fallback, and failed-run cleanup.
- CO-L2: `cli/stats_handler.py` now drains `_pending_scopes` on both `on_llm_end` and `on_llm_error`, so failed or metadata-less runs do not retain stale scope state.
- CO-L1: `tradingagents/dataflows/y_finance.py` now keeps the most recent capped rows for OHLCV output and adds regression coverage for tail-row behavior. Financial statement row caps were left unchanged to preserve the existing table semantics used by the current tests and callers.

Focused validation run:

```bash
tradingagent_venv/bin/python -m unittest tests.test_backtest tests.test_tool_output_caps tests.test_stats_handler -v
```

Result: 56 tests, OK.

Broader Copilot validation run:

```bash
tradingagent_venv/bin/python -m unittest tests.test_backtest tests.test_risk tests.test_execution tests.test_tool_output_caps tests.test_stats_handler -v
```

Result: 106 tests, OK.

Full regression gate:

```bash
tradingagent_venv/bin/python -m unittest discover tests -v
```

Result: OK.

Copilot re-review result:

- No open Copilot P1/P2 findings remain from this review.
- The telemetry leak advisory is fixed.
- The row-capping advisory is partially applied: recent-row behavior now covers OHLCV output, while financial statement tables intentionally preserve their prior row-order semantics.

---

## Claude Code Re-Review Update — 2026-04-22

Claude Code applied all outstanding fixes:

- P1 (portfolio manager): Full mode now omits the `analysis_block`; `analysis_block = ""` in else branch. `test_full_mode_no_brief_and_no_analysis_summary` asserts `"Analysis Summary:"` not in prompt.
- P1 (trader): Full mode now omits the `analysis_block`; `analysis_block = ""` in else branch. Regression identified at `trader.py:60` where an unconditional `context_summary` was embedded.
- P2 (config wiring): `get_context_cfg()` introduced; all seven agents call it and pass config-driven values to `build_analysis_brief` and `cap_debate_history`.
- P2 (prompt assertions): `_FakeLLM.last_prompt` added. `TestTraderCompact` now has four prompt-content tests: `test_full_mode_no_analysis_summary_in_prompt`, `test_compact_mode_analysis_summary_in_prompt`, `test_compact_prompt_excludes_full_report`, `test_full_prompt_contains_investment_plan`.
- M-1: `"analysis_brief": {}` confirmed present in `propagation.py:create_initial_state` (applied by Codex C-4).
- M-2: `context_mode` default changed to `"compact"` in `default_config.py` and `get_context_mode()` fallback.

Focused validation:

```bash
tradingagent_venv/bin/python -m unittest tests.test_compact_context tests.test_tool_output_caps -v
```

Result: 47 tests, OK.

Broader validation (primary suites):

```bash
tradingagent_venv/bin/python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation tests.test_compact_context tests.test_tool_output_caps -v
```

Result: 63 tests, OK.

No open Claude Code findings remain.

---

## Summary of required actions

| ID | Owner | Action |
|---|---|---|
| **P1** | **Claude Code** | **DONE — portfolio manager full-mode prompt shape restored; `analysis_block = ""` in full mode** |
| **P1** | **Claude Code** | **DONE — trader full-mode regression fixed; `analysis_block = ""` in full mode** |
| **P2** | **Claude Code** | **DONE — `get_context_cfg()` wires config caps through all seven agents** |
| **P2** | **Claude Code** | **DONE — `TestTraderCompact` now asserts prompt content in both modes (4 new tests)** |
| **M-1** | **Claude Code** | **DONE — `"analysis_brief": {}` in `propagation.py:create_initial_state` (via Codex C-4)** |
| **M-2** | **Claude Code** | **DONE — `context_mode` defaults to `"compact"` in `default_config.py` and `get_context_mode()`** |
| C-1 | Codex | Add `QuantSignalContract.from_raw()` round-trip test in `test_quant_tool.py` |
| C-2 | Codex | Add test asserting LLM is skipped when `Rating:` line is present |
| C-3 | Codex | Add/confirm test asserting LLM is not called in `quant_strict` mode |
| C-4 | Codex | Add `"analysis_brief": {}` to `propagation.py:create_initial_state` (cross-lane fix) |
| C-5 | Codex | Run full `discover tests` regression gate after all lanes merge |
| **CO-1** | **Copilot** | **DONE — `get_news_yfinance` cap note condition fixed and covered by boundary tests** |
| **CO-2** | **Copilot** | **DONE — `get_global_news_yfinance` cap note condition fixed and covered by boundary tests** |
| CO-3 | Copilot | DONE — backtest coverage added for real quant payload → `_coerce_entry_signal` → `size_position` |
| CO-4 | Copilot | DONE — telemetry coverage added for stage inference, multi-call accumulation, unknown-scope fallback, and error cleanup |
| CO-L1 | Copilot | PARTIAL — recent-row capping applied to OHLCV output; financial statement row order intentionally preserved |
| CO-L2 | Copilot | DONE — `on_llm_error` drains `_pending_scopes`; `on_llm_end` also clears stale pending scopes before usage extraction |
| — | All | Delete premature `docs/handoffs/phase-8.md`; re-create only after full gate passes |
