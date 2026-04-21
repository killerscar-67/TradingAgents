# Phase 1 Handoff — Intraday Data Foundation

Agent: Copilot
Date: 2026-04-21

## What was built

- `tradingagents/dataflows/intraday.py`: Intraday bar fetch module. Key public functions:
    - `get_intraday_bars(symbol, interval, start, end, as_of=None, session="regular", vendor="yfinance", cache_dir=None, refresh_cache=False) -> pd.DataFrame` — cached fetch; UTC-aware DatetimeIndex
    - `fetch_intraday_bars(symbol, interval, start, end, as_of=None, session="regular", vendor="yfinance") -> pd.DataFrame` — no-cache variant
    - `IntradayInterval = Literal["15m", "4h"]`, `IntradaySession = Literal["regular", "extended", "crypto"]`
    - Internal helpers: `_align_session(df, session)`, `_enforce_no_lookahead(df, as_of)`, `_resample_1h_to_4h(df)`, `_cache_key(...)`, `_load_cache(path)`, `_save_cache(path, df)`
    - 4h bars resampled from 1h (yfinance has no native 4h); session filter applied before resampling to avoid cross-session candles
    - Cache key: SHA-256 of `{v, symbol, interval, start, end, session}`; `as_of` excluded (trimming applied post-load)
    - Cache format: parquet under `~/.tradingagents/cache/intraday/`; requires `pyarrow`
    - `alpha_vantage` vendor raises `NotImplementedError` (stub)
- `tradingagents/dataflows/interface.py`: Added `"intraday_data"` category to `TOOLS_CATEGORIES`, `"get_intraday_bars"` entry in `VENDOR_METHODS`, and public `get_intraday_bars(symbol, interval, start, end, as_of, session, cache_dir, refresh_cache)` routing function that respects `config["data_vendors"]["intraday_data"]` and `config["tool_vendors"]["get_intraday_bars"]`
- `tradingagents/default_config.py`: Added `intraday_cache_dir`, `intraday_default_session`, `intraday_refresh_cache` keys and `"intraday_data": "yfinance"` in `data_vendors`
- `pyproject.toml`: Added `pyarrow>=14.0.0` to required dependencies (parquet engine; was absent from the venv)
- `tests/test_intraday.py`: 13 acceptance tests — cache determinism, no-lookahead, session alignment, input validation

## Contracts exposed to next phase

- `get_intraday_bars(symbol, interval, start, end, as_of, session, vendor, cache_dir, refresh_cache) -> pd.DataFrame`: lives in `tradingagents.dataflows.intraday`. Returns UTC-aware DatetimeIndex DataFrame with columns `[Open, High, Low, Close, Volume]`. Enforces `as_of` cutoff (no-lookahead). Phase 2 quant engine should call this for regime and entry bar data.
- `tradingagents.dataflows.interface.get_intraday_bars(...)`: vendor-routed wrapper; Phase 2 may call either form directly.

## Config keys added

- `intraday_cache_dir`: `str`, default `~/.tradingagents/cache/intraday`, env override `TRADINGAGENTS_INTRADAY_CACHE_DIR`
- `intraday_default_session`: `str`, default `"regular"`, env override `TRADINGAGENTS_INTRADAY_SESSION`
- `intraday_refresh_cache`: `bool`, default `False` (no env override; set programmatically)
- `data_vendors["intraday_data"]`: `str`, default `"yfinance"` (override via `tool_vendors["get_intraday_bars"]`)

## Test command

```
tradingagent_venv/bin/python -m unittest tests.test_intraday tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation tests.test_execution_contracts -v
```
Expected: 33 tests, all OK

## Known limitations / deferred decisions

- `alpha_vantage` intraday vendor raises `NotImplementedError`; no alpha_vantage intraday endpoint exists in the current integration. Deferred to a later phase if needed.
- yfinance 15m bars are limited to the last 60 days by the upstream API; no error is surfaced if `start` is older (empty DataFrame returned silently).
- No TTL-based cache expiry for intraday cache. Freshness is controlled by bypassing cache reads **and writes** for live/current date ranges (`_is_live_end_date(end)` guard) and by `refresh_cache=True`.
- `_align_session` regular-session open mask uses `hour > 9 or (hour == 9 and minute >= 30)`. yfinance 1h bars are labelled at the top of the hour; the bar covering 09:00–10:00 ET has `hour=9, minute=0` and is excluded. **Phase 2 callers must not rely on 4h candles capturing the 09:30 open** — the first included 1h bar is 10:00 ET.
- 4h UTC-midnight bucket alignment yields at most 1 usable NYSE-session candle per day; the interval is best suited for crypto (24h) sessions.
- `_is_live_end_date` compares naive date objects; `end` is treated as a UTC calendar date. Callers in UTC-ahead timezones passing a local-time date string may see unexpected live/historical classification.

## What the reviewer must focus on

- **Timezone correctness**: verify `_align_session` handles DST transitions (ET clocks back/forward) without dropping or duplicating bars at session boundaries
- **Session boundary handling**: confirm regular session 09:30–16:00 ET filter is inclusive at open and exclusive at close (bar at exactly 16:00 ET should be excluded)
- **Cache key collision safety**: confirm SHA-256 truncation to 20 hex chars (80 bits) is collision-safe for realistic ticker/interval/date combinations
- **No stale bar data on market open**: confirm `_enforce_no_lookahead` strictly strips bars with `index >= as_of` (not `>`)
- **Vendor fallback behavior**: `interface.get_intraday_bars` does not use the generic `route_to_vendor` fallback chain — confirm this is intentional and error handling is adequate
- **4h resampling correctness**: verify `_resample_1h_to_4h` OHLCV aggregation (open=first, high=max, low=min, close=last, volume=sum) and that `dropna(how="all")` does not silently discard partial candles

## Fix notes

**Round 1** (review-20260421_164340): Partial 4h boundary candles — added `counts >= _MIN_BARS_PER_4H_CANDLE` filter in `_resample_1h_to_4h`. `intraday_default_session` config key unwired — added `resolved_session = session or config.get(...)` in `interface.get_intraday_bars`. Added DST spring-forward test.

**Round 2** (review-20260421_165039): `intraday_cache_dir` config key dead — added `resolved_cache_dir = cache_dir or config.get(...)` in interface. `intraday_refresh_cache` unused — added `resolved_refresh_cache = refresh_cache or config.get(...)` in interface.

**Round 3** (review-20260421_165646): Stale live-date cache write — added `_is_live_end_date(end)` guard on both cache read and write paths. Added `test_live_end_date_fetch_is_not_persisted_to_cache` regression test.

**Round 4** (review-20260421_170058): DST fall-back coverage — added `test_regular_session_around_dst_fallback` (2026-11-02). Verified `.vscode/settings.json` is single-object JSON. Verified `requirements.txt` still contains `.`.

**Round 5** (review-20260421_171123): TOCTOU race — `_is_live_end_date(end)` was called twice without storing the result; captured once into `is_live` local variable used for both the read-guard and the write-guard.
