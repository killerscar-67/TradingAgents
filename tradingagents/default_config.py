import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

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
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Trading style: "swing" (daily bars, full debate) or "daytrade" (intraday bars,
    # session-aware, debate forced off). Default preserves existing swing behavior.
    "trading_style": "swing",
    # Intraday bar interval used when trading_style == "daytrade".
    # Allowed: "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h".
    "intraday_interval": "5m",
    # IANA timezone for session-phase calculations.
    "session_timezone": "America/New_York",
    # Whether to include premarket/aftermarket bars in intraday fetches.
    "include_extended_hours": False,
    # Strict daytrade analyst set enforcement. When True, daytrade mode rejects
    # analysts that need swing-horizon data (fundamentals/social) unless
    # `allow_mismatched_analysts` is also True.
    "daytrade_strict_analysts": True,
    "allow_mismatched_analysts": False,
    # Intraday prompt variants for A/B comparison. List of variant names; each
    # variant produces a journaled decision. The first variant's decision flows
    # to the trader/risk graph; others are journal-only.
    "intraday_prompt_variants": ["default"],
    # Trading journal (records every decision, action, outcome to SQLite for
    # agent-vs-human and strategy A/B analysis).
    "journal_enabled": True,
    "journal_path": os.path.join(_TRADINGAGENTS_HOME, "journal.sqlite"),
}
