# LLM Clients - Consistency Improvements

## Issues to Fix

### 1. ~~`validate_model()` is never called~~ (Fixed)
- All clients now call `self.warn_if_unknown_model()` at the top of `get_llm()`, emitting a `RuntimeWarning` for unknown models without blocking execution.

### 2. ~~Inconsistent parameter handling~~ (Fixed)
- GoogleClient now accepts unified `api_key` and maps it to `google_api_key`

### 3. ~~`base_url` accepted but ignored~~ (Fixed)
- All clients now pass `base_url` to their respective LLM constructors

### 4. ~~Update validators.py with models from CLI~~ (Fixed)
- Synced in v0.2.2

---

## Open Issues (found in phase 8 review)

### 5. Google `thinking_budget` mapping is coarse
- File: `google_client.py` lines 56–57
- `thinking_level="high"` maps to `thinking_budget=-1` (dynamic); anything else maps to `0` (disabled).
- Intermediate values (`"low"`, `"minimal"`, `"medium"`) for Gemini 2.5 models are silently collapsed to disabled.
- **Fix**: Add explicit mapping `{"minimal": 0, "low": 128, "medium": 1024, "high": -1}` or document the limitation.

### 6. Unknown providers silently pass validation
- File: `validators.py` line 23–24
- `if provider_lower not in VALID_MODELS: return True` — an unknown provider name (e.g., a typo like `"opanai"`) passes validation silently.
- Intentional design (allows custom/future providers) but creates confusing late failures.
- **Fix**: At minimum, log a warning when provider is not in `VALID_MODELS`.

### 7. `propagate()` lacks error handling
- File: `trading_graph.py` lines 206–216
- In debug mode: `trace[-1]` raises `IndexError` if the graph produces zero output chunks.
- Neither `graph.stream()` nor `graph.invoke()` is wrapped in try/except, so LLM or network errors surface as raw exceptions with no context about which ticker/date failed.
- **Fix**: Guard `trace[-1]` with a length check; wrap the stream/invoke block in a try/except that annotates the error with `company_name` and `trade_date`.

### 8. `_log_state()` uses direct dict access on nested state
- File: `trading_graph.py` lines 236–254
- Keys such as `investment_debate_state["bull_history"]` and `risk_debate_state["aggressive_history"]` are accessed without `.get()` fallback.
- If an analyst is skipped or a debate round is short-circuited, missing keys will raise `KeyError` and crash the logging step.
- **Fix**: Replace all nested accesses with `.get("key", "")` or provide default values in `Propagator.create_initial_state()`.

### 9. Azure client env-var requirements undocumented in README
- File: `azure_client.py` lines 27–30
- `AzureOpenAIClient` silently relies on four env vars: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, `OPENAI_API_VERSION`.
- README only says "copy `.env.enterprise.example`" with no listing of required keys.
- **Fix**: Document required Azure env vars in README and/or raise a clear error if they are missing at client instantiation.
