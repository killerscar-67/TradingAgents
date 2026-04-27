import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

ExecutionMode = Literal["llm_assisted", "quant_strict"]


class TradeRating(str, Enum):
    BUY = "BUY"
    OVERWEIGHT = "OVERWEIGHT"
    HOLD = "HOLD"
    UNDERWEIGHT = "UNDERWEIGHT"
    SELL = "SELL"


class QuantSignalLabel(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuantSignalContract:
    symbol: str
    trade_date: str
    signal: QuantSignalLabel
    score: float
    confidence: Optional[float]
    summary: str = ""
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        symbol: str,
        trade_date: str,
        raw_signal: Any,
    ) -> "QuantSignalContract":
        if isinstance(raw_signal, str):
            try:
                payload = json.loads(raw_signal)
            except Exception:
                payload = {"summary": raw_signal}
        elif isinstance(raw_signal, dict):
            payload = raw_signal
        else:
            payload = {"summary": str(raw_signal)}

        signal_value = str(payload.get("signal", "unknown")).strip().lower()
        if signal_value not in {item.value for item in QuantSignalLabel}:
            signal_value = QuantSignalLabel.UNKNOWN.value

        if payload.get("error"):
            score = float("-inf")
        else:
            raw_score = payload.get("score")
            if raw_score is None:
                score = float("-inf")
            else:
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    score = float("-inf")

        confidence = payload.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = None

        return cls(
            symbol=symbol,
            trade_date=trade_date,
            signal=QuantSignalLabel(signal_value),
            score=score,
            confidence=confidence,
            summary=str(payload.get("summary", "")),
            error=payload.get("error"),
            raw=payload,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuantSignalContract":
        """Reconstruct a QuantSignalContract from the output of to_dict()."""
        return cls(
            symbol=data["symbol"],
            trade_date=data["trade_date"],
            signal=QuantSignalLabel(data["signal"]),
            score=float(data["score"]),
            confidence=data.get("confidence"),
            summary=data.get("summary", ""),
            error=data.get("error"),
            raw=data.get("raw", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderIntentContract:
    symbol: str
    trade_date: str
    rating: TradeRating
    source: Literal["llm_assisted", "quant_strict"]
    execution_mode: ExecutionMode
    blocked: bool = False
    reason: str = ""
    annotations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["rating"] = self.rating.value
        return payload


# ---------------------------------------------------------------------------
# Phase 2: Regime / Entry / Validation contracts
# ---------------------------------------------------------------------------

class RegimeLabel(str, Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    CONSOLIDATION = "consolidation"


class EntryEngine(str, Enum):
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"


@dataclass(frozen=True)
class RegimeContract:
    """Output of the regime classifier."""
    label: RegimeLabel
    tradable: bool
    adx: float
    atr: float
    atr_pct: float
    htf_bias: Literal["bullish", "bearish", "neutral"]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["label"] = self.label.value
        return payload


@dataclass(frozen=True)
class EntrySignal:
    """A confirmed entry opportunity from one of the entry engines."""
    engine: EntryEngine
    direction: Literal["long", "short"]
    strength: float      # 0.0–1.0
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["engine"] = self.engine.value
        return payload


@dataclass(frozen=True)
class NoSignal:
    """Explicit sentinel returned when no entry condition is met."""
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"signal": "none", "reason": self.reason}


@dataclass(frozen=True)
class ValidationResult:
    """Aggregated output of all validation filters."""
    passed: bool
    filters_passed: int
    filters_total: int
    reasons: Tuple[str, ...]   # tuple so the dataclass stays frozen/hashable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "filters_passed": self.filters_passed,
            "filters_total": self.filters_total,
            "reasons": list(self.reasons),
        }



# ---------------------------------------------------------------------------
# Phase 3: Risk / sizing contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionSizeContract:
    """Deterministic position size computed from account equity and ATR stop."""
    symbol: str
    direction: Literal["long", "short"]
    quantity: float        # number of shares/units to buy/sell
    entry_price: float     # reference price used for sizing
    notional: float        # quantity × entry_price
    stop_price: float      # initial hard stop price
    risk_amount: float     # dollar risk = quantity × |entry_price - stop_price|
    method: str            # "fixed_fractional"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StopContract:
    """ATR-based stop levels for a single entry."""
    initial_stop: float          # hard stop price at entry
    breakeven_trigger: float     # price at which to move stop to entry
    trailing_distance: float     # ATR-based trailing stop distance (always positive)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskGateResult:
    """Result of pre-trade risk gate checks."""
    allowed: bool
    reason: str            # empty string when allowed=True
    kill_switch: bool      # True when the kill switch is the reason for blocking

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DailyLossState:
    """Immutable intraday loss tracker. Reconstruct via update_daily_loss()."""
    date: str              # ISO "YYYY-MM-DD"
    net_pnl: float         # running P&L for the day (negative = net loss)
    kill_switch: bool      # True once kill-switch threshold is breached
    trade_count: int       # number of completed trades today

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def new_day(cls, date: str) -> "DailyLossState":
        return cls(date=date, net_pnl=0.0, kill_switch=False, trade_count=0)


def parse_execution_mode(value: Optional[str]) -> ExecutionMode:
    normalized = str(value or "llm_assisted").strip().lower()
    if normalized not in {"llm_assisted", "quant_strict"}:
        return "llm_assisted"
    return normalized  # type: ignore[return-value]


def rating_from_quant_signal(signal: QuantSignalLabel) -> TradeRating:
    if signal == QuantSignalLabel.BUY:
        return TradeRating.BUY
    if signal == QuantSignalLabel.SELL:
        return TradeRating.SELL
    return TradeRating.HOLD


def rating_from_text(text: str) -> TradeRating:
    upper = str(text or "").upper()
    pattern = r"\b(BUY|OVERWEIGHT|HOLD|UNDERWEIGHT|SELL)\b"
    matches = re.findall(pattern, upper)
    if not matches:
        return TradeRating.HOLD
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) > 1:
        raise ValueError(f"Ambiguous rating text: {text!r}")
    return TradeRating(unique_matches[0])
