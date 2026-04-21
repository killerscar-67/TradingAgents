import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Literal, Optional

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
