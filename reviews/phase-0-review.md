I have a complete picture. Here is the review.

---

## Phase 0 Review — Execution Contracts

**Reviewer:** Claude · **Date:** 2026-04-21 · **Phase:** 0

---

### Findings

#### MEDIUM — `from_raw` score fallback is `0.0` for non-error payloads with unparseable `score`

**File:** `tradingagents/quant/contracts.py:58–60`

```python
try:
    score = float('-inf') if payload.get("error") else float(payload.get("score", 0.0))
except (TypeError, ValueError):
    score = 0.0   # <── falls here when error is absent but score is malformed
```

**Impact:** A tool response with no `"error"` key but a malformed `"score"` (e.g., `"score": "N/A"`) silently receives `score=0.0`. This puts it at the HOLD boundary and lets it compete for top-N selection against legitimately-scored tickers. The expected safe sentinel is `-inf`.

**Minimal fix:**
```python
except (TypeError, ValueError):
    score = float("-inf")
```

---

#### MEDIUM — `llm_assisted` order intent sets `blocked=False` unconditionally on extraction failure

**File:** `tradingagents/graph/trading_graph.py:363–378`

```python
try:
    rating = TradeRating(extracted)
except ValueError:
    rating = TradeRating.HOLD   # extraction failed → becomes HOLD
intent = OrderIntentContract(
    ...
    blocked=False,              # ← never reflects the failure
    ...
)
```

**Impact:** If LLM output is garbled and the `TradeRating(extracted)` cast fails, the returned intent carries `rating=HOLD, blocked=False` — indistinguishable from a genuine HOLD. Downstream phases that gate on `blocked` will treat an extraction failure as an actionable decision. The `quant_strict` path correctly sets `blocked=quant_contract.error is not None`; `llm_assisted` should mirror this discipline.

**Minimal fix:** Track whether fallback fired:
```python
try:
    rating = TradeRating(extracted)
    extraction_failed = False
except ValueError:
    rating = TradeRating.HOLD
    extraction_failed = True
intent = OrderIntentContract(
    ...
    blocked=extraction_failed,
    reason="LLM extraction fallback to HOLD." if extraction_failed else "LLM-assisted decision.",
    ...
)
```

---

#### MEDIUM — `process_signal` in `quant_strict` mode does regex text parsing without execution guard

**File:** `tradingagents/graph/signal_processing.py:26–28`

```python
if mode == "quant_strict":
    return rating_from_text(full_signal).value   # regex text parse
```

**Impact:** `graph.process_signal()` is a public method. The current `build_order_intent` correctly bypasses it in `quant_strict` mode, but a future phase author calling `graph.process_signal()` gets a text-parsed result silently — violating the "no text parsing for execution" contract. There is nothing in the interface to prevent this mistake.

**Minimal fix:** Raise or warn in strict mode to surface the misuse boundary:
```python
if mode == "quant_strict":
    raise RuntimeError(
        "process_signal must not be used for execution in quant_strict mode; "
        "use build_order_intent with a QuantSignalContract instead."
    )
```

---

#### LOW — `from_dict` does not coerce `score` to `float`

**File:** `tradingagents/quant/contracts.py:87`

```python
score=data["score"],   # no float() conversion
```

`from_raw` always stores a `float`. `from_dict` does not coerce, so integer values (e.g., from manually constructed dicts or future schema drift) propagate as `int`. Type annotations are not enforced at runtime; the sort in `prefilter.py` and any `< / > / ==` comparisons will still work, but code expecting `isinstance(c.score, float)` would silently fail.

**Minimal fix:** `score=float(data["score"])`.

---

#### LOW — `QuantSignalLabel.UNKNOWN` silently maps to `TradeRating.HOLD`

**File:** `tradingagents/quant/contracts.py:122–127`

`rating_from_quant_signal` returns `TradeRating.HOLD` for any signal that is not BUY or SELL, including UNKNOWN. A UNKNOWN signal arises when the quant tool returns an unrecognized label. This is already pushed to the bottom of ranking by the error sort key in `prefilter.py`, but if it somehow enters `build_order_intent` directly it becomes an unblocked HOLD.

**Minimal fix:** Add `QuantSignalLabel.UNKNOWN` to the `blocked` condition in `build_order_intent`:
```python
blocked=quant_contract.error is not None or quant_contract.signal == QuantSignalLabel.UNKNOWN,
```

---

#### LOW — Patch diff for `.vscode/settings.json` shows invalid JSON (two separate objects)

**File:** `.vscode/settings.json` (diff only)

The diff adds two separate top-level JSON objects (syntactically invalid). The on-disk file is valid (all keys merged into one object). The diff is misleading — presumably an editing artifact — but not a runtime issue.

---

### Review of Handoff Claims

| Claim | Verified |
|---|---|
| `quant_strict` order intent derived from typed contract, no LLM | ✓ `build_order_intent` uses `rating_from_quant_signal`, never calls LLM |
| Prefilter contract reused in `propagate_prefiltered_universe` (no second fetch) | ✓ `item["contract"]` exists in scored items; `from_dict` reconstructs and passes as `quant_contract` |
| `propagate` return carries `blocked` | ✓ `order_intent.get("blocked")` present in `propagate_prefiltered_universe` and CLI |
| CLI delegates to `graph.propagate_prefiltered_universe` | ✓ |
| Summary table includes Blocked column | ✓ |
| `--execution-mode` CLI flag with validation warning | ✓ `cli/main.py:1084–1089` |
| `vectorbt` in optional-dependencies | ✓ `pyproject.toml:36` |
| `try/except ImportError` guard in `quant_tools.py` | ✓ |
| Tests cover strict-mode avoidance of LLM | ✓ `_FailLLM` sentinel in `test_execution_contracts` |

---

### Merge Decision: **APPROVE**

The Phase 0 acceptance criteria are met:

- All execution paths in `quant_strict` mode go through typed contracts (`QuantSignalContract` → `OrderIntentContract`); no LLM inference is invoked in the order-intent derivation path.
- `propagate_prefiltered_universe` correctly reuses the prefiltered contract, preserving determinism.
- `blocked` is present in the returned `order_intent_dict` and surfaced by the CLI.
- Config defaults are safe; `execution_mode` defaults to `"llm_assisted"` with env and CLI override.
- Contracts are stable typed interfaces suitable for Phase 1 to build on.

---

### Top 3 Required Fixes Before Phase 1

1. **`from_raw` score fallback** (`contracts.py:60`): Change `score = 0.0` on `except` to `score = float("-inf")` so malformed non-error payloads rank below legitimate signals rather than landing at the HOLD boundary.

2. **`llm_assisted` blocked flag** (`trading_graph.py:363–378`): Set `blocked=True` when `TradeRating(extracted)` raises `ValueError` so extraction failures are distinguishable from genuine HOLD decisions by downstream consumers of `order_intent_dict`.

3. **`process_signal` guard in `quant_strict`** (`signal_processing.py:27–28`): Raise `RuntimeError` instead of silently returning a text-parsed result in `quant_strict` mode. This enforces the "no text parsing for execution" contract at the interface boundary, preventing accidental misuse by future phases.
