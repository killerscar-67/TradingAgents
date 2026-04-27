import hashlib
import os
import pickle
import tempfile
import threading
import time
from typing import Annotated

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
    }
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

# ---------------------------------------------------------------------------
# Disk cache for vendor calls.
# Multiple analysts (and re-runs on the same trade_date) frequently request
# identical data; a process-local lock plus atomic file writes keep the cache
# safe under the parallel-analyst node introduced in setup.py.
# ---------------------------------------------------------------------------

_DATA_CACHE_TTL_SECONDS = 24 * 60 * 60
_cache_locks: dict = {}
_cache_locks_guard = threading.Lock()


def _cache_lock_for(key: str) -> threading.Lock:
    with _cache_locks_guard:
        lock = _cache_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _cache_locks[key] = lock
        return lock


def _make_cache_key(method: str, args, kwargs) -> str:
    raw = repr((method, args, sorted(kwargs.items())))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_cached(cache_path: str):
    try:
        if not os.path.exists(cache_path):
            return None
        if os.path.getmtime(cache_path) + _DATA_CACHE_TTL_SECONDS < time.time():
            return None  # expired
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ValueError):
        return None


def _store_cached(cache_path: str, value) -> None:
    cache_dir = os.path.dirname(cache_path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".cache_", dir=cache_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(value, f)
            os.replace(tmp_path, cache_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        # Cache writes are best-effort; never fail the calling analyst.
        pass


def _vendor_call(method: str, *args, **kwargs):
    """Execute the actual vendor call with fallback. Cache-free."""
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


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to vendor implementations with disk caching and fallback.

    Cache key is hashed from (method, args, kwargs); since callers always pass
    a date arg, results for one trade_date never leak into another. Cache TTL
    is 24h; set ``data_cache_dir`` to "" or None in config to disable.
    """
    config = get_config()
    cache_dir = config.get("data_cache_dir") or ""

    if not cache_dir:
        return _vendor_call(method, *args, **kwargs)

    key = _make_cache_key(method, args, kwargs)
    cache_path = os.path.join(cache_dir, "vendor", f"{key}.pkl")

    cached = _load_cached(cache_path)
    if cached is not None:
        return cached

    # Serialize duplicate concurrent fetches for the same key (parallel
    # analyst node may issue identical requests simultaneously).
    with _cache_lock_for(key):
        cached = _load_cached(cache_path)
        if cached is not None:
            return cached

        result = _vendor_call(method, *args, **kwargs)
        if result is not None:
            _store_cached(cache_path, result)
        return result