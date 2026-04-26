"""Trading journal: schema migration, round-trip, analytics."""
from __future__ import annotations

import os
import tempfile
import unittest

from tradingagents.journal import Journal
from tradingagents.journal.report import (
    agent_vs_human,
    expectancy_by_strategy,
    variant_comparison,
)


class JournalRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = self.tmp.name
        self.j = Journal(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def _dummy_state(self):
        return {
            "trade_datetime": "2025-04-24T10:30:00-04:00",
            "session_phase": "morning",
            "data_session_date": "2025-04-24",
        }

    def _dummy_decision(self, **overrides):
        d = {
            "setup_name": "vwap_reclaim",
            "bias": "long",
            "entry": 542.10,
            "stop": 541.50,
            "target1": 543.00,
            "target2": 544.00,
            "time_stop": "11:30 ET",
            "confidence": "high",
            "invalidation": "Close below 541.50",
            "rationale": "Reclaimed VWAP on rising rel volume",
            "variant": "default",
            "raw": "...",
        }
        d.update(overrides)
        return d

    def test_init_db_is_idempotent(self):
        Journal(self.path)
        Journal(self.path)  # should not raise

    def test_decision_action_outcome_round_trip(self):
        did = self.j.record_decision(
            "SPY", "daytrade", self._dummy_decision(), self._dummy_state(), {}
        )
        self.assertGreater(did, 0)

        aid = self.j.record_action(did, actor="human", taken=True,
                                    fill_price=542.10, size=100)
        self.assertGreater(aid, 0)

        oid = self.j.record_outcome(aid, exit_price=543.20, exit_time="2025-04-24T11:00:00-04:00",
                                     exit_reason="target")
        self.assertGreater(oid, 0)

        outcomes = self.j.query("SELECT * FROM outcomes WHERE id = ?", (oid,))
        self.assertEqual(len(outcomes), 1)
        # PnL derived: (543.20 - 542.10) * 100 = 110.0
        self.assertAlmostEqual(outcomes[0]["pnl"], 110.0, places=2)
        # R = (543.20 - 542.10) / abs(542.10 - 541.50) = 1.10 / 0.60 ≈ 1.833
        self.assertAlmostEqual(outcomes[0]["r_multiple"], 1.10 / 0.60, places=2)

    def test_actor_validation(self):
        did = self.j.record_decision(
            "SPY", "daytrade", self._dummy_decision(), self._dummy_state(), {}
        )
        with self.assertRaises(ValueError):
            self.j.record_action(did, actor="bot", fill_price=1.0)


class JournalReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = self.tmp.name
        self.j = Journal(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def _seed(self, setup="vwap_reclaim", actor="human", variant="default",
              entry=100.0, stop=99.0, exit_p=101.5):
        state = {
            "trade_datetime": "2025-04-24T10:30:00-04:00",
            "session_phase": "morning",
            "data_session_date": "2025-04-24",
        }
        decision = {
            "setup_name": setup, "bias": "long", "entry": entry, "stop": stop,
            "target1": 101.0, "target2": 102.0, "time_stop": "11:30 ET",
            "confidence": "high", "invalidation": "x", "rationale": "y",
            "variant": variant, "raw": "...",
        }
        did = self.j.record_decision("SPY", "daytrade", decision, state, {})
        aid = self.j.record_action(did, actor=actor, fill_price=entry, size=100)
        self.j.record_outcome(aid, exit_price=exit_p,
                              exit_time="2025-04-24T11:00:00-04:00",
                              exit_reason="target")
        return did, aid

    def test_expectancy_groups_by_strategy(self):
        self._seed(setup="vwap_reclaim")
        self._seed(setup="vwap_reclaim", exit_p=99.5)  # loser
        self._seed(setup="orb_breakout", exit_p=102.0)
        out = expectancy_by_strategy(self.j)
        self.assertIn("vwap_reclaim", out)
        self.assertIn("orb_breakout", out)

    def test_agent_vs_human_groups_by_actor(self):
        self._seed(actor="human")
        self._seed(actor="agent")
        out = agent_vs_human(self.j)
        self.assertIn("human", out)
        self.assertIn("agent", out)

    def test_variant_comparison(self):
        self._seed(variant="aggressive")
        self._seed(variant="conservative")
        out = variant_comparison(self.j)
        self.assertIn("aggressive", out)
        self.assertIn("conservative", out)


if __name__ == "__main__":
    unittest.main()
