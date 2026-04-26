"""Session-phase + RTH walk-back behavior."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tradingagents.dataflows.session import (
    is_rth,
    minutes_to_close,
    previous_business_day,
    resolve_session_context,
    session_phase,
)


ET = ZoneInfo("America/New_York")


class SessionPhaseTests(unittest.TestCase):
    def test_rth_morning_phase(self):
        dt = datetime(2025, 4, 24, 10, 30, tzinfo=ET)  # Thu 10:30 ET
        self.assertEqual(session_phase(dt), "morning")
        self.assertTrue(is_rth(dt))

    def test_premarket(self):
        dt = datetime(2025, 4, 24, 7, 0, tzinfo=ET)
        self.assertEqual(session_phase(dt), "premarket")
        self.assertFalse(is_rth(dt))

    def test_postmarket(self):
        dt = datetime(2025, 4, 24, 18, 0, tzinfo=ET)
        self.assertEqual(session_phase(dt), "postmarket")

    def test_weekend_closed(self):
        dt = datetime(2025, 4, 26, 12, 0, tzinfo=ET)  # Saturday
        self.assertEqual(session_phase(dt), "closed")
        self.assertFalse(is_rth(dt))

    def test_close_window(self):
        dt = datetime(2025, 4, 24, 15, 58, tzinfo=ET)
        self.assertEqual(session_phase(dt), "close")

    def test_minutes_to_close(self):
        dt = datetime(2025, 4, 24, 15, 30, tzinfo=ET)
        self.assertEqual(minutes_to_close(dt), 30)

    def test_minutes_to_close_weekend(self):
        dt = datetime(2025, 4, 26, 10, 0, tzinfo=ET)
        self.assertEqual(minutes_to_close(dt), 0)

    def test_previous_business_day_skips_weekend(self):
        sat = datetime(2025, 4, 26, 10, 0, tzinfo=ET)
        prev = previous_business_day(sat)
        self.assertIsNotNone(prev)
        self.assertEqual(prev.weekday(), 4)  # Friday
        self.assertEqual(prev.hour, 16)


class SessionContextTests(unittest.TestCase):
    def test_inside_rth_uses_today(self):
        dt = datetime(2025, 4, 24, 10, 30, tzinfo=ET)
        ctx = resolve_session_context(dt)
        self.assertFalse(ctx.walked_back)
        self.assertEqual(ctx.data_session_date, "2025-04-24")
        self.assertEqual(ctx.session_phase, "morning")
        self.assertEqual(ctx.minutes_to_close, 330)

    def test_premarket_walks_back(self):
        dt = datetime(2025, 4, 24, 3, 0, tzinfo=ET)  # Thu 03:00 ET
        ctx = resolve_session_context(dt)
        self.assertTrue(ctx.walked_back)
        self.assertEqual(ctx.data_session_date, "2025-04-23")  # Wed
        self.assertEqual(ctx.session_phase, "closed")  # Requested moment was before premarket
        # data_session_date must reflect data; session_phase reflects the requested dt.

    def test_weekend_walks_back_to_friday(self):
        dt = datetime(2025, 4, 26, 12, 0, tzinfo=ET)  # Saturday
        ctx = resolve_session_context(dt)
        self.assertTrue(ctx.walked_back)
        self.assertEqual(ctx.data_session_date, "2025-04-25")  # Friday

    def test_state_dict_keys(self):
        dt = datetime(2025, 4, 24, 10, 30, tzinfo=ET)
        d = resolve_session_context(dt).as_state_dict()
        self.assertEqual(set(d.keys()),
                         {"trade_datetime", "session_phase", "minutes_to_close", "data_session_date"})


if __name__ == "__main__":
    unittest.main()
