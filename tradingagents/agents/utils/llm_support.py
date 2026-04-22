"""Support-only LLM helpers for Phase 5.

These helpers produce structured annotations for human review and journaling.
They do not derive, block, size, or submit orders.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple


_ANOMALY_KEYS = (
    "event_risk",
    "liquidity_risk",
    "data_quality_risk",
    "news_risk",
)

__all__ = [
    "AnomalyWatch",
    "PostTradeAttribution",
    "PreTradeBrief",
    "annotate_order_intent_with_support",
    "build_post_trade_attribution",
    "build_pre_trade_brief",
    "watch_anomalies",
]


@dataclass(frozen=True)
class PreTradeBrief:
    summary: str = ""
    catalysts: Tuple[str, ...] = ()
    event_risks: Tuple[str, ...] = ()
    blocking: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["catalysts"] = list(self.catalysts)
        payload["event_risks"] = list(self.event_risks)
        return payload


@dataclass(frozen=True)
class AnomalyWatch:
    flags: Mapping[str, bool]
    summary: str = ""
    blocking: bool = False
    error: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "flags", MappingProxyType(dict(self.flags)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flags": dict(self.flags),
            "summary": self.summary,
            "blocking": self.blocking,
            "error": self.error,
        }


@dataclass(frozen=True)
class PostTradeAttribution:
    summary: str = ""
    factors: Tuple[str, ...] = ()
    lessons: Tuple[str, ...] = ()
    blocking: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["factors"] = list(self.factors)
        payload["lessons"] = list(self.lessons)
        return payload


def build_pre_trade_brief(llm: Any, context: Mapping[str, Any]) -> PreTradeBrief:
    """Return catalyst and event-risk context; never an executable decision."""
    payload, error = _invoke_json(llm, "pre_trade_brief", context)
    if error:
        return PreTradeBrief(error=error)
    return PreTradeBrief(
        summary=str(payload.get("summary", "")),
        catalysts=_string_tuple(payload.get("catalysts")),
        event_risks=_string_tuple(payload.get("event_risks")),
    )


def watch_anomalies(llm: Any, context: Mapping[str, Any]) -> AnomalyWatch:
    """Return binary risk flags only; malformed or non-binary flags become False."""
    payload, error = _invoke_json(llm, "anomaly_watch", context)
    if error:
        return AnomalyWatch(flags=_empty_flags(), error=error)

    raw_flags = payload.get("flags", {})
    if not isinstance(raw_flags, dict):
        return AnomalyWatch(
            flags=_empty_flags(),
            summary=str(payload.get("summary", "")),
            error="malformed flags",
        )

    flags = _empty_flags()
    non_binary = False
    for key in _ANOMALY_KEYS:
        value = raw_flags.get(key, False)
        if type(value) is bool:
            flags[key] = value
        elif key in raw_flags:
            non_binary = True

    if non_binary:
        flags = _empty_flags()
    return AnomalyWatch(
        flags=flags,
        summary=str(payload.get("summary", "")),
        error="non-binary anomaly flag" if non_binary else None,
    )


def build_post_trade_attribution(llm: Any, context: Mapping[str, Any]) -> PostTradeAttribution:
    """Return a structured journal entry; provider failures are contained."""
    payload, error = _invoke_json(llm, "post_trade_attribution", context)
    if error:
        return PostTradeAttribution(error=error)
    return PostTradeAttribution(
        summary=str(payload.get("summary", "")),
        factors=_string_tuple(payload.get("factors")),
        lessons=_string_tuple(payload.get("lessons")),
    )


def annotate_order_intent_with_support(
    order_intent: Mapping[str, Any],
    *,
    pre_trade_brief: Optional[PreTradeBrief] = None,
    anomaly_watch: Optional[AnomalyWatch] = None,
) -> Dict[str, Any]:
    """Attach support annotations without changing execution fields."""
    annotated = copy.deepcopy(dict(order_intent))
    annotations = dict(annotated.get("annotations", {}))
    support = dict(annotations.get("llm_support", {}))
    if pre_trade_brief is not None:
        support["pre_trade_brief"] = pre_trade_brief.to_dict()
    if anomaly_watch is not None:
        support["anomaly_watch"] = anomaly_watch.to_dict()
    annotations["llm_support"] = support
    annotated["annotations"] = annotations
    return annotated


def _invoke_json(llm: Any, task: str, context: Mapping[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    prompt = _build_prompt(task, context)
    try:
        response = llm.invoke(prompt)
    except Exception as exc:
        return {}, str(exc)

    content = getattr(response, "content", response)
    if isinstance(content, dict):
        return dict(content), None
    try:
        payload = json.loads(str(content))
    except Exception:
        return {}, "malformed JSON response"
    if not isinstance(payload, dict):
        return {}, "malformed JSON response"
    return payload, None


def _build_prompt(task: str, context: Mapping[str, Any]) -> str:
    return (
        f"Task: {task}\n"
        "Return one JSON object only. Do not include executable trading decisions.\n"
        f"Context: {json.dumps(dict(context), sort_keys=True, default=str)}"
    )


def _string_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item is not None and str(item))


def _empty_flags() -> Dict[str, bool]:
    return {key: False for key in _ANOMALY_KEYS}
