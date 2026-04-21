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
