import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.agents.utils.quant_tools import get_quant_signals
from tradingagents.quant.contracts import QuantSignalContract


_CACHE_VERSION = "v1"


def _is_live_trade_date(trade_date: str) -> bool:
    """Return True if trade_date is today or later in UTC calendar terms."""
    return datetime.strptime(trade_date, "%Y-%m-%d").date() >= datetime.now(timezone.utc).date()


def _to_stable_json(value: Dict[str, Any]) -> str:
    """Serialize params deterministically for hashing and cache keying."""
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)


def _get_cache_path(
    cache_dir: Optional[str],
    symbol: str,
    trade_date: str,
    quant_kwargs: Dict[str, Any],
) -> Optional[Path]:
    if not cache_dir:
        return None

    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)

    params_json = _to_stable_json(quant_kwargs)
    digest_src = f"{_CACHE_VERSION}|{symbol}|{trade_date}|{params_json}"
    digest = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()[:20]
    return cache_root / f"{symbol}_{trade_date}_{digest}.json"


def _load_cached_raw(
    cache_path: Optional[Path],
    symbol: str,
    trade_date: str,
    quant_kwargs: Dict[str, Any],
    ttl_days: Optional[int],
    refresh_cache: bool,
) -> Optional[Dict[str, Any]]:
    if refresh_cache:
        return None
    if not cache_path or not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if payload.get("cache_version") != _CACHE_VERSION:
        return None
    if payload.get("symbol") != symbol:
        return None
    if payload.get("trade_date") != trade_date:
        return None
    if payload.get("params") != _to_stable_json(quant_kwargs):
        return None

    if ttl_days is not None and ttl_days >= 0:
        saved_at = payload.get("saved_at")
        if not isinstance(saved_at, str):
            return None
        try:
            # Accept both explicit UTC and naive ISO variants from older cache files.
            normalized = saved_at.replace("Z", "+00:00")
            saved_dt = datetime.fromisoformat(normalized)
            if saved_dt.tzinfo is None:
                saved_dt = saved_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        if saved_dt < datetime.now(timezone.utc) - timedelta(days=ttl_days):
            return None

    raw = payload.get("raw")
    if isinstance(raw, dict):
        return raw
    return None


def _save_cached_raw(
    cache_path: Optional[Path],
    symbol: str,
    trade_date: str,
    quant_kwargs: Dict[str, Any],
    raw: Dict[str, Any],
) -> None:
    if not cache_path:
        return

    payload = {
        "cache_version": _CACHE_VERSION,
        "symbol": symbol,
        "trade_date": trade_date,
        "params": _to_stable_json(quant_kwargs),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "raw": raw,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def score_tickers_with_quant(
    tickers: List[str],
    trade_date: str,
    top_n: int,
    quant_kwargs: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[str] = None,
    cache_ttl_days: Optional[int] = 1,
    refresh_cache: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """Rank a ticker universe with the quant tool and select top-N for LLM analysis."""
    quant_kwargs = quant_kwargs or {}
    is_live_trade_date = _is_live_trade_date(trade_date)
    cleaned = []
    seen = set()
    for ticker in tickers:
        symbol = ticker.strip().upper()
        if symbol and symbol not in seen:
            cleaned.append(symbol)
            seen.add(symbol)

    scored: List[Dict[str, Any]] = []
    for symbol in cleaned:
        cache_path = _get_cache_path(cache_dir, symbol, trade_date, quant_kwargs)
        use_cache = (not refresh_cache) and (not is_live_trade_date)
        parsed = None
        if use_cache:
            parsed = _load_cached_raw(
                cache_path,
                symbol,
                trade_date,
                quant_kwargs,
                ttl_days=cache_ttl_days,
                refresh_cache=False,
            )
        cache_hit = parsed is not None

        if parsed is None:
            raw = get_quant_signals.func(symbol, trade_date, **quant_kwargs)
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    parsed = {"summary": str(parsed)}
            except Exception:
                parsed = {"summary": str(raw)}
            # Do not persist error payloads; transient upstream failures should
            # not poison the cache for the entire TTL window.
            if (not is_live_trade_date) and (not parsed.get("error")):
                _save_cached_raw(cache_path, symbol, trade_date, quant_kwargs, parsed)

        signal_contract = QuantSignalContract.from_raw(symbol, trade_date, parsed)
        error = signal_contract.error
        score = signal_contract.score if error is None else float("-inf")

        scored.append(
            {
                "symbol": symbol,
                "score": score,
                "signal": signal_contract.signal.value,
                "confidence": signal_contract.confidence,
                "summary": signal_contract.summary,
                "error": error,
                "cache_hit": cache_hit,
                "contract": signal_contract.to_dict(),
                "raw": parsed,
            }
        )

    ranked = sorted(scored, key=lambda item: (item["error"] is not None, -item["score"]))
    selected = [item for item in ranked if item["error"] is None][: max(int(top_n), 1)]

    return {
        "ranked": ranked,
        "selected": selected,
    }
