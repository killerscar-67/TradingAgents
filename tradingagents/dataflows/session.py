"""Session-phase helpers for intraday/day-trading mode.

Determines where a given moment sits in the US equity trading day, computes
minutes-to-close, and walks back to the most recent trading session when
called outside the extended-hours window. All math is done in the configured session timezone
(default America/New_York).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from .config import get_config


# Regular Trading Hours for US equities/ETFs.
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

# Pre/post market windows yfinance exposes when prepost=True.
PREMARKET_OPEN = time(4, 0)
POSTMARKET_CLOSE = time(20, 0)

# Phase boundaries within RTH (Eastern).
MORNING_END = time(11, 0)
MIDDAY_END = time(14, 0)
POWER_HOUR_START = time(15, 0)


def _session_tz() -> ZoneInfo:
    return ZoneInfo(get_config().get("session_timezone", "America/New_York"))


def to_session_tz(dt: datetime) -> datetime:
    """Localize/convert dt into the session timezone."""
    tz = _session_tz()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def session_phase(dt: datetime) -> str:
    """Classify a moment into a named phase.

    Returns one of: premarket, open, morning, midday, power_hour, close,
    postmarket, closed.
    """
    local = to_session_tz(dt)
    if local.weekday() >= 5:
        return "closed"
    t = local.time()

    if t < PREMARKET_OPEN:
        return "closed"
    if t < RTH_OPEN:
        return "premarket"
    # First 5 minutes after the open is "open" (auction unwind / opening drive).
    if t < time(9, 35):
        return "open"
    if t < MORNING_END:
        return "morning"
    if t < MIDDAY_END:
        return "midday"
    if t < POWER_HOUR_START:
        return "midday"
    # Last 5 minutes treated as "close" (MOC imbalance window).
    if t < time(15, 55):
        return "power_hour"
    if t < RTH_CLOSE:
        return "close"
    if t <= POSTMARKET_CLOSE:
        return "postmarket"
    return "closed"


def minutes_to_close(dt: datetime) -> int:
    """Minutes remaining until 16:00 ET. 0 if already past close or weekend."""
    local = to_session_tz(dt)
    if local.weekday() >= 5:
        return 0
    close_dt = local.replace(hour=RTH_CLOSE.hour, minute=RTH_CLOSE.minute, second=0, microsecond=0)
    delta = close_dt - local
    secs = int(delta.total_seconds())
    return max(0, secs // 60)


def is_rth(dt: datetime) -> bool:
    """True if dt falls inside US RTH (Mon-Fri 09:30-16:00 ET)."""
    local = to_session_tz(dt)
    if local.weekday() >= 5:
        return False
    return RTH_OPEN <= local.time() < RTH_CLOSE


def is_extended_session(dt: datetime) -> bool:
    """True if dt falls inside US premarket/RTH/postmarket hours."""
    local = to_session_tz(dt)
    if local.weekday() >= 5:
        return False
    return PREMARKET_OPEN <= local.time() <= POSTMARKET_CLOSE


def previous_business_day(dt: datetime, max_walk_back_days: int = 5) -> Optional[datetime]:
    """Walk back to the previous business day's RTH close.

    Skips weekends. Does not know about US holidays — those will surface as
    "no data" downstream and the caller can walk back further. Returns the
    dt of that day's 16:00 ET close, or None if exceeded the walk-back budget.
    """
    local = to_session_tz(dt)
    candidate = local - timedelta(days=1)
    walked = 1
    while walked <= max_walk_back_days:
        if candidate.weekday() < 5:
            return candidate.replace(
                hour=RTH_CLOSE.hour, minute=RTH_CLOSE.minute, second=0, microsecond=0
            )
        candidate = candidate - timedelta(days=1)
        walked += 1
    return None


@dataclass
class SessionContext:
    """Immutable snapshot of where a moment sits relative to the trading session."""
    requested_dt: datetime
    effective_dt: datetime
    session_phase: str
    minutes_to_close: int
    data_session_date: str
    walked_back: bool

    def as_state_dict(self) -> dict:
        return {
            "trade_datetime": self.requested_dt.isoformat(),
            "session_phase": self.session_phase,
            "minutes_to_close": self.minutes_to_close,
            "data_session_date": self.data_session_date,
        }


def resolve_session_context(
    dt: datetime,
    max_walk_back_days: int = 5,
) -> SessionContext:
    """Build a SessionContext for dt, walking back only if outside extended hours.

    The data_session_date is the date whose bars should be loaded:
      - Inside premarket/RTH/postmarket: today (in session tz).
      - Closed / weekend: most recent prior business day.

    The session_phase reflects where the *requested* dt sits — so the agent
    knows the user asked at 03:00 ET even though we're showing yesterday's data.
    """
    local = to_session_tz(dt)
    phase = session_phase(local)

    if is_extended_session(local):
        return SessionContext(
            requested_dt=local,
            effective_dt=local,
            session_phase=phase,
            minutes_to_close=minutes_to_close(local),
            data_session_date=local.date().isoformat(),
            walked_back=False,
        )

    # Outside RTH: walk back to the prior business day's close for data.
    prior = previous_business_day(local, max_walk_back_days=max_walk_back_days)
    if prior is None:
        # Fallback — keep requested date so downstream can complain coherently.
        return SessionContext(
            requested_dt=local,
            effective_dt=local,
            session_phase=phase,
            minutes_to_close=0,
            data_session_date=local.date().isoformat(),
            walked_back=False,
        )

    return SessionContext(
        requested_dt=local,
        effective_dt=prior,
        session_phase=phase,
        minutes_to_close=0,
        data_session_date=prior.date().isoformat(),
        walked_back=True,
    )
