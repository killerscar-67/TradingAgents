import json
from datetime import datetime, timedelta
from typing import Annotated

import yfinance as yf
from langchain_core.tools import tool

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover - handled at runtime
    vbt = None


@tool
def get_quant_signals(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    lookback_days: Annotated[int, "How many calendar days to look back"] = 252,
    fast_window: Annotated[int, "Fast moving average window"] = 20,
    slow_window: Annotated[int, "Slow moving average window"] = 50,
    rsi_window: Annotated[int, "RSI window length"] = 14,
) -> str:
    """Generate a lightweight quant signal summary using vectorbt indicators."""
    if vbt is None:
        return json.dumps(
            {
                "error": "vectorbt is not installed",
                "symbol": symbol,
                "curr_date": curr_date,
            }
        )

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback_days)
    history = yf.download(
        symbol,
        start=start_dt.strftime("%Y-%m-%d"),
        end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
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

    fast_ma = vbt.MA.run(close, window=fast_window).ma
    slow_ma = vbt.MA.run(close, window=slow_window).ma
    rsi = vbt.RSI.run(close, window=rsi_window).rsi

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