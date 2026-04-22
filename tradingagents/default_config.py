import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")


def _safe_int_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "backend_url": "https://api.openai.com/v1",
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Execution mode for downstream order intent generation.
    # llm_assisted: keep legacy LLM-extracted decision path
    # quant_strict: deterministic quant contract drives order intent
    "execution_mode": os.getenv("TRADINGAGENTS_EXECUTION_MODE", "llm_assisted"),
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Quant prefilter cache controls
    "quant_prefilter_cache_ttl_days": _safe_int_env("TRADINGAGENTS_QUANT_CACHE_TTL_DAYS", 1),
    "quant_prefilter_refresh_cache": False,
    # Intraday data configuration
    "intraday_cache_dir": os.getenv(
        "TRADINGAGENTS_INTRADAY_CACHE_DIR",
        os.path.join(_TRADINGAGENTS_HOME, "cache", "intraday"),
    ),
    "intraday_default_session": os.getenv("TRADINGAGENTS_INTRADAY_SESSION", "regular"),
    "intraday_refresh_cache": False,
    # Quant engine (Phase 2) — regime classifier
    "adx_period": 14,
    "atr_period": 14,
    "bb_period": 20,
    "adx_trending_threshold": 25.0,
    "adx_ranging_threshold": 20.0,
    "min_atr_pct": 0.001,
    "min_volume": 100_000,
    "htf_sma_period": 20,
    "htf_bias_neutral_pct": 0.005,
    # Quant engine (Phase 2) — breakout entry
    "breakout_lookback": 20,
    "breakout_volume_factor": 1.5,
    # Quant engine (Phase 2) — mean reversion entry
    "rsi_period": 14,
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "mr_sma_period": 20,
    "mr_stretch_std": 2.0,
    "mr_min_stretch_pct": 0.01,
    # Quant engine (Phase 2) — validation filters (set False to disable)
    "validation_momentum": True,
    "validation_squeeze": True,
    "validation_sr_proximity": True,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal_period": 9,
    "bb_std": 2.0,
    "kc_period": 20,
    "kc_atr_factor": 1.5,
    "kc_atr_period": 14,
    "sr_lookback": 50,
    "sr_swing_width": 5,
    "sr_proximity_pct": 0.005,
    # Quant engine (Phase 2) — engine dispatch override
    # "auto" uses regime-based dispatch; "breakout" or "mean_reversion" forces engine
    "entry_mode": "auto",
    # Risk and sizing (Phase 3)
    # Fixed fractional: risk this fraction of equity per trade
    "risk_per_trade_pct": 0.01,
    # ATR multiples for initial stop distance from entry
    "atr_stop_mult": 2.0,
    # ATR multiples of profit needed to trigger break-even stop move
    "breakeven_atr_mult": 1.0,
    # ATR multiples for trailing stop distance
    "trailing_atr_mult": 1.5,
    # Single-position notional cap as fraction of equity
    "max_position_size_pct": 0.10,
    # Aggregate exposure cap as fraction of equity
    "max_exposure_pct": 0.20,
    # Daily loss cap: block new orders when net_pnl <= -(equity * this)
    "max_daily_loss_pct": 0.02,
    # Kill switch: permanently halt orders for the day when breached
    "kill_switch_daily_loss_pct": 0.03,
    # Backtest and walk-forward (Phase 6)
    # Number of warmup bars before the engine is queried in bar-replay
    "backtest_warmup_bars": 60,
    # One-way slippage fraction applied to fill prices (0.05%)
    "backtest_slippage_pct": 0.0005,
    # Flat dollar commission per order (paid at entry and again at exit)
    "backtest_commission": 1.0,
    # 15-minute bars per trading day for Sharpe annualisation (6.5 h × 4)
    "bars_per_day": 26,
    # Minimum 4h bars required before the engine generates signals
    "min_4h_bars": 30,
    # Walk-forward: number of IS/OOS folds
    "walkforward_n_folds": 5,
    # Walk-forward: fraction of each fold used as in-sample
    "walkforward_in_sample_ratio": 0.7,
    # Paper gate: minimum annualised Sharpe required for promotion
    "paper_gate_min_sharpe": 0.5,
    # Paper gate: maximum peak-to-trough drawdown fraction allowed
    "paper_gate_max_drawdown_pct": 0.05,
    # Paper gate: minimum completed trades required for a PASS verdict
    "paper_gate_min_trades": 1,
    # Execution guards (Phase 4)
    # Reject orders larger than this fraction of the latest bar volume
    "max_order_volume_pct": 0.01,
    # Reject orders whose expected slippage exceeds this fraction
    "max_slippage_pct": 0.005,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
        "intraday_data": "yfinance",         # Options: yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
