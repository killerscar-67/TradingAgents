import json
from datetime import datetime, timedelta
from typing import Annotated

import yfinance as yf
from langchain_core.tools import tool

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.interface import get_intraday_bars
from tradingagents.quant.engine import run_quant_engine

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover - handled at runtime
    vbt = None


def _contract_payload(contract) -> dict:
    payload = contract.to_dict()
    # Keep the legacy key alongside the typed contract key for callers that
    # still display or cache the old payload shape.
    payload["curr_date"] = contract.trade_date
    return payload


def _try_intraday_quant_engine(
    symbol: str,
    curr_date: str,
    lookback_days: int,
) -> str | None:
    """Return deterministic engine payload when intraday bars are available.

    The legacy daily MA/RSI screen remains the explicit fallback for providers
    or historical ranges where intraday bars cannot be fetched.
    """
    cfg = get_config()
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    intraday_lookback = min(max(int(lookback_days), 1), 59)
    start_dt = end_dt - timedelta(days=intraday_lookback)
    start = start_dt.strftime("%Y-%m-%d")
    end = curr_date

    try:
        bars_15m = get_intraday_bars(
            symbol,
            "15m",
            start,
            end,
            session=cfg.get("intraday_default_session", "regular"),
            cache_dir=cfg.get("intraday_cache_dir"),
            refresh_cache=bool(cfg.get("intraday_refresh_cache", False)),
        )
        bars_4h = get_intraday_bars(
            symbol,
            "4h",
            start,
            end,
            session=cfg.get("intraday_default_session", "regular"),
            cache_dir=cfg.get("intraday_cache_dir"),
            refresh_cache=bool(cfg.get("intraday_refresh_cache", False)),
        )
    except Exception:
        return None

    if bars_15m.empty or bars_4h.empty:
        return None

    contract = run_quant_engine(symbol, curr_date, bars_15m, bars_4h, cfg)
    return json.dumps(_contract_payload(contract))


@tool
def get_quant_signals(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    lookback_days: Annotated[int, "How many calendar days to look back"] = 252,
    fast_window: Annotated[int, "Fast moving average window"] = 20,
    slow_window: Annotated[int, "Slow moving average window"] = 50,
    rsi_window: Annotated[int, "RSI window length"] = 14,
) -> str:
    """Generate a lightweight quant signal summary using indicator calculations.

    Prefer the deterministic intraday quant engine when 15m and 4h bars are
    available. If intraday data cannot be fetched, fall back explicitly to the
    legacy daily MA/RSI screen so the default quant path remains functional.
    """

    engine_payload = _try_intraday_quant_engine(symbol, curr_date, lookback_days)
    if engine_payload is not None:
        return engine_payload

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback_days)
    history = yf.download(
        symbol,
        start=start_dt.strftime("%Y-%m-%d"),
        # End is exclusive so trading-day screens do not include same-day bars.
        end=end_dt.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )

    if history.empty or "Close" not in history:
        return json.dumps(
            {
                "error": "No price history returned",
                "symbol": symbol,
                "curr_date": curr_date,
            }
        )

    close = history["Close"].dropna()
    if len(close) < max(slow_window, rsi_window) + 2:
        return json.dumps(
            {
                "error": "Insufficient history for quant signal",
                "symbol": symbol,
                "curr_date": curr_date,
                "observations": int(len(close)),
            }
        )

    if vbt is not None:
        fast_ma = vbt.MA.run(close, window=fast_window).ma
        slow_ma = vbt.MA.run(close, window=slow_window).ma
        rsi = vbt.RSI.run(close, window=rsi_window).rsi
    else:
        fast_ma = close.rolling(window=fast_window, min_periods=fast_window).mean()
        slow_ma = close.rolling(window=slow_window, min_periods=slow_window).mean()

        delta = close.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        avg_gain = gains.rolling(window=rsi_window, min_periods=rsi_window).mean()
        avg_loss = losses.rolling(window=rsi_window, min_periods=rsi_window).mean()
        # Preserve RSI extremes in edge cases:
        # - avg_gain > 0, avg_loss == 0 -> RSI 100
        # - avg_gain == 0, avg_loss > 0 -> RSI 0
        # - avg_gain == 0, avg_loss == 0 -> neutral (filled to 50 below)
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0)

    latest_price = float(close.iloc[-1])
    latest_fast = float(fast_ma.iloc[-1])
    latest_slow = float(slow_ma.iloc[-1])
    latest_rsi = float(rsi.iloc[-1])
    monthly_return = float(close.pct_change(21).iloc[-1]) if len(close) > 21 else 0.0

    ma_score = 1.0 if latest_fast > latest_slow else -1.0
    rsi_score = 1.0 if latest_rsi < 35 else -1.0 if latest_rsi > 65 else 0.0
    momentum_score = 1.0 if monthly_return > 0 else -1.0 if monthly_return < 0 else 0.0
    total_score = (0.5 * ma_score) + (0.25 * rsi_score) + (0.25 * momentum_score)

    if total_score >= 0.5:
        signal = "buy"
    elif total_score <= -0.5:
        signal = "sell"
    else:
        signal = "hold"

    confidence = min(abs(total_score), 1.0)
    summary = (
        f"{symbol} quant screen on {curr_date}: signal={signal.upper()}, "
        f"score={total_score:.2f}, confidence={confidence:.2f}, "
        f"close={latest_price:.2f}, fast_ma={latest_fast:.2f}, slow_ma={latest_slow:.2f}, "
        f"rsi={latest_rsi:.2f}, monthly_return={monthly_return:.2%}."
    )

    return json.dumps(
        {
            "symbol": symbol,
            "curr_date": curr_date,
            "signal": signal,
            "score": round(total_score, 4),
            "confidence": round(confidence, 4),
            "summary": summary,
            "metadata": {
                "close": round(latest_price, 4),
                "fast_ma": round(latest_fast, 4),
                "slow_ma": round(latest_slow, 4),
                "rsi": round(latest_rsi, 4),
                "monthly_return": round(monthly_return, 6),
                "fast_window": fast_window,
                "slow_window": slow_window,
                "rsi_window": rsi_window,
                "lookback_days": lookback_days,
            },
        }
    )
