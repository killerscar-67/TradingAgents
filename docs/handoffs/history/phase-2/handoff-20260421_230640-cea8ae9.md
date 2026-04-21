# Phase 2 Handoff — Deterministic Quant Engine

Agent: Claude Code
Date: 2026-04-21

## What was built

- `tradingagents/quant/regime.py`: Regime classifier. Key public function:
    - `classify(bars: pd.DataFrame, config: dict | None) -> RegimeContract`
    - Computes ADX (Wilder smoothing) + ATR from 4h bars.
    - Labels regime as `trending` (ADX ≥ 25), `ranging` (ADX ≤ 20), or `consolidation` (low ADX + tight Bollinger width).
    - Tradability gate: ATR% ≥ `min_atr_pct` AND average volume ≥ `min_volume`.
    - HTF directional bias: `bullish` / `bearish` / `neutral` relative to SMA(20).
    - Helper exports: `compute_atr()`, `compute_adx()` — reusable by Phase 3.

- `tradingagents/quant/entry.py`: Dual entry engines. Key public functions:
    - `run_breakout(bars, config) -> EntrySignal | NoSignal`: N-bar channel (default 20) breakout with volume confirmation (factor 1.5×).
    - `run_mean_reversion(bars, config) -> EntrySignal | NoSignal`: Wilder RSI(14) extreme + price stretched from SMA by `mr_stretch_std` std devs (default 2.0) or `mr_min_stretch_pct` (default 1%), whichever is larger. Both conditions must hold simultaneously.
    - `run_entry(bars, regime, config) -> EntrySignal | NoSignal`: Regime-aware dispatcher. TRENDING → breakout; RANGING → mean reversion; CONSOLIDATION → NoSignal. Applies HTF directional filter.
    - `_direction_allowed(signal, htf_bias) -> bool`: exported helper for engine.py forced-mode paths.

- `tradingagents/quant/validation.py`: Three independently-togglable validation filters:
    - `validate(bars, entry_signal, config) -> ValidationResult`
    - **momentum_acceleration** (`validation_momentum`): MACD histogram must be increasing for long, decreasing for short.
    - **squeeze_gate** (`validation_squeeze`): rejects when Bollinger Bands are fully inside Keltner Channels (TTM Squeeze ON).
    - **sr_proximity** (`validation_sr_proximity`): rejects if price within `sr_proximity_pct` (default 0.5%) of a recent swing high/low (N-bar local extrema scan).

- `tradingagents/quant/engine.py`: Top-level orchestrator:
    - `run_quant_engine(symbol, trade_date, bars_15m, bars_4h, config) -> QuantSignalContract`
    - Pipeline: `regime(bars_4h)` → `entry(bars_15m, regime)` → `validate(bars_15m, entry)` → `QuantSignalContract`.
    - Exceptions in any stage are caught and returned as an error `QuantSignalContract` (never propagated).
    - `config["entry_mode"]`: `"auto"` (default, regime-based), `"breakout"`, or `"mean_reversion"` to force engine.
    - Score: `entry.strength * (filters_passed / filters_total)`, signed by direction. HOLD → score=0.

- `tradingagents/quant/contracts.py`: Added Phase 2 contract types:
    - `RegimeLabel(str, Enum)`: `trending | ranging | consolidation`
    - `EntryEngine(str, Enum)`: `breakout | mean_reversion`
    - `RegimeContract(frozen dataclass)`: `label, tradable, adx, atr, atr_pct, htf_bias`
    - `EntrySignal(frozen dataclass)`: `engine, direction, strength, reason`
    - `NoSignal(frozen dataclass)`: `reason` — explicit typed sentinel (never `None`)
    - `ValidationResult(frozen dataclass)`: `passed, filters_passed, filters_total, reasons: Tuple[str, ...]`
    - All have `.to_dict()` methods.

- `tradingagents/quant/__init__.py`: Exports all new contract types and `run_quant_engine`.

- `tradingagents/default_config.py`: Added 30 new config keys for regime, entry, and validation parameters (all with documented defaults). Key toggles: `validation_momentum`, `validation_squeeze`, `validation_sr_proximity`. Entry dispatch: `entry_mode`.

- `tests/test_quant_engine.py`: 49 new tests covering regime, breakout, mean reversion, directional filter, all three validation filters, engine orchestration, error isolation, and determinism.

## Contracts exposed to next phase

- `run_quant_engine(symbol, trade_date, bars_15m, bars_4h, config) -> QuantSignalContract`: lives in `tradingagents.quant.engine`. Phase 3 (risk + sizing) should call this to obtain a signal before applying position sizing and stop logic.
- `RegimeContract` (`tradingagents.quant.contracts`): carries `atr`, `atr_pct`, and `htf_bias` — Phase 3 can use ATR for stop-distance calculation directly from the regime output.
- `EntrySignal` (`tradingagents.quant.contracts`): carries `direction` and `strength` — Phase 3 uses direction to determine long/short and can use strength to weight sizing.
- `compute_atr(bars, period) -> pd.Series` and `compute_adx(bars, period) -> pd.DataFrame` from `tradingagents.quant.regime` — reusable for Phase 3 ATR-based stop calculations.
- `NoSignal` (`tradingagents.quant.contracts`): typed sentinel, never `None`. Phase 3 must check `isinstance(entry, NoSignal)` before sizing.

## Config keys added

All keys live in `DEFAULT_CONFIG` in `tradingagents/default_config.py`. No env overrides (programmatic-only).

**Regime:**
- `adx_period`: int, default 14
- `atr_period`: int, default 14
- `bb_period`: int, default 20
- `adx_trending_threshold`: float, default 25.0
- `adx_ranging_threshold`: float, default 20.0
- `min_atr_pct`: float, default 0.001
- `min_volume`: float, default 100_000
- `htf_sma_period`: int, default 20
- `htf_bias_neutral_pct`: float, default 0.005

**Breakout entry:**
- `breakout_lookback`: int, default 20
- `breakout_volume_factor`: float, default 1.5

**Mean reversion entry:**
- `rsi_period`: int, default 14
- `rsi_oversold`: float, default 30.0
- `rsi_overbought`: float, default 70.0
- `mr_sma_period`: int, default 20
- `mr_stretch_std`: float, default 2.0
- `mr_min_stretch_pct`: float, default 0.01

**Validation filters:**
- `validation_momentum`: bool, default True
- `validation_squeeze`: bool, default True
- `validation_sr_proximity`: bool, default True
- `macd_fast`: int, default 12
- `macd_slow`: int, default 26
- `macd_signal_period`: int, default 9
- `bb_std`: float, default 2.0
- `kc_period`: int, default 20
- `kc_atr_factor`: float, default 1.5
- `kc_atr_period`: int, default 14
- `sr_lookback`: int, default 50
- `sr_swing_width`: int, default 5
- `sr_proximity_pct`: float, default 0.005

**Engine dispatch:**
- `entry_mode`: str, default `"auto"` (values: `"auto"`, `"breakout"`, `"mean_reversion"`)

## Test command

```
tradingagent_venv/bin/python -m unittest tests.test_intraday tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation tests.test_execution_contracts tests.test_quant_engine -v
```

Expected: 98 tests, all OK.

## Known limitations / deferred decisions

- **4h bars for entry**: `run_quant_engine` takes separate `bars_15m` and `bars_4h`; the caller must fetch both and pass them. No intraday fetch is embedded in the engine (intentional: keeps engine pure/testable).
- **MR stretch threshold**: Default `mr_stretch_std=2.0` requires a sharp price move relative to SMA volatility. For linearly trending data the maximum achievable deviation is ~1.73 std (geometric property of linear series). Callers doing live/backtesting may need `mr_stretch_std=1.5` for MR signals in gradual-trend regimes.
- **SR proximity swing detection**: Uses simple local-extrema scan (`sr_swing_width` half-window). Overlapping SR levels are not clustered; dense SR zones may produce many redundant levels.
- **No integration with Phase 1 intraday fetch**: `run_quant_engine` receives pre-fetched bars. The wiring of `get_intraday_bars` → `run_quant_engine` is left to the Phase 4 execution layer or a thin coordinator function.
- **Volume column is optional**: If bars have no `Volume` column, the volume gate (breakout) and tradability filter pass automatically.
- **ATR-based stop calculation**: Phase 3 should call `regime_mod.compute_atr(bars_15m, config["atr_period"])` directly on 15m bars for stop distances — the `RegimeContract.atr` field is computed on 4h bars and is too coarse for intraday stops.

## What the reviewer must focus on

- **Determinism**: Verify same `bars_15m` and `bars_4h` DataFrames always produce identical `QuantSignalContract` (no mutable state, no datetime.now calls in engine path).
- **No hidden mutable state**: Confirm `regime.py`, `entry.py`, `validation.py` have no module-level mutable variables.
- **Signal logic matches spec**: Verify regime→engine dispatch matches plan (TRENDING=breakout, RANGING=mean_reversion, CONSOLIDATION=NoSignal).
- **Module boundaries**: Confirm `engine.py` does not import from `validation.py` internals (only public `validate()`), and `entry.py` does not import `validation.py`.
- **`_direction_allowed` visibility**: This helper is used by `engine.py` for forced-mode paths; verify it behaves correctly for all three bias values.
- **Error isolation**: Verify that an exception in `regime.classify` or `entry.run_entry` returns an error `QuantSignalContract` without propagating.


## Fix notes
