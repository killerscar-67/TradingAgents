from typing import Annotated, Optional

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_YFin_intraday_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .intraday_indicators import get_intraday_indicators_window
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .intraday import get_intraday_bars as _get_intraday_bars_yfinance

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data",
            "get_intraday_stock_data",
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators",
            "get_intraday_indicators",
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "intraday_data": {
        "description": "Intraday OHLCV bar data (15m, 4h)",
        "tools": [
            "get_intraday_bars",
        ]
    },
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # intraday tools (yfinance only in v1; AV intraday not wired)
    "get_intraday_stock_data": {
        "yfinance": get_YFin_intraday_online,
    },
    "get_intraday_indicators": {
        "yfinance": get_intraday_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # intraday_data
    "get_intraday_bars": {
        "yfinance": _get_intraday_bars_yfinance,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Only rate limits trigger fallback

    raise RuntimeError(f"No available vendor for '{method}'")


def get_intraday_bars(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    as_of=None,
    session: Optional[str] = None,
    cache_dir=None,
    refresh_cache: bool = False,
):
    """Route intraday bar requests through the configured vendor.

    Uses the ``intraday_data`` vendor from config (default: ``yfinance``).
    All arguments are forwarded to the underlying vendor implementation.
    See :func:`tradingagents.dataflows.intraday.get_intraday_bars` for full
    parameter documentation.
    """
    config = get_config()
    resolved_session = session or config.get("intraday_default_session", "regular")
    resolved_cache_dir = cache_dir or config.get("intraday_cache_dir")
    resolved_refresh_cache = refresh_cache or bool(config.get("intraday_refresh_cache", False))
    vendor = config.get("data_vendors", {}).get("intraday_data", "yfinance")
    # tool-level override takes precedence
    vendor = config.get("tool_vendors", {}).get("get_intraday_bars", vendor)
    impl = VENDOR_METHODS["get_intraday_bars"].get(vendor)
    if impl is None:
        raise NotImplementedError(f"Vendor {vendor!r} is not available for get_intraday_bars")
    return impl(
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        as_of=as_of,
        session=resolved_session,
        cache_dir=resolved_cache_dir,
        refresh_cache=resolved_refresh_cache,
    )