"""Phase 9 tests for day-trade workflow API contracts."""

import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        from tradingagents.web.app import create_app

        self.client = TestClient(create_app())

    def test_market_overview_contract(self):
        resp = self.client.get("/api/market/overview?home_market=HK&trade_date=2026-04-23")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        self.assertEqual(body["home_market"], "HK")
        self.assertEqual(body["trade_date"], "2026-04-23")
        self.assertIn("indices", body)
        self.assertIn("regime", body)
        self.assertEqual(body["stream"]["transport"], "websocket")

    def test_market_live_websocket_contract(self):
        with self.client.websocket_connect("/api/market/live?home_market=US") as ws:
            event = ws.receive_json()

        self.assertEqual(event["type"], "market_snapshot")
        self.assertEqual(event["payload"]["home_market"], "US")

    def test_screening_basket_batch_strategy_contracts(self):
        screening = self.client.post("/api/screening/runs", json={
            "universe": "S&P 500",
            "strategy": "breakout",
            "trade_date": "2026-04-23",
            "top_n": 10,
            "min_score": 0.65,
        })
        self.assertEqual(screening.status_code, 200)
        self.assertEqual(screening.json()["status"], "contract_ready")

        basket = self.client.post("/api/baskets", json={"symbols": ["AAPL", "NVDA"]})
        self.assertEqual(basket.status_code, 200)
        self.assertEqual(basket.json()["basket_id"], "phase-9-contract")

        batch = self.client.post("/api/batches", json={"symbols": ["AAPL"], "analysis_date": "2026-04-23"})
        self.assertEqual(batch.status_code, 200)
        self.assertEqual(batch.json()["batch_id"], "phase-9-contract")

        strategy = self.client.post("/api/strategies/from-batch", json={"batch_id": "phase-9-contract"})
        self.assertEqual(strategy.status_code, 200)
        self.assertEqual(strategy.json()["strategy_id"], "phase-9-contract")

    def test_futu_stage_contract_is_stage_only(self):
        resp = self.client.post("/api/broker/futu/stage", json={
            "strategy_id": "strategy-1",
            "orders": [{"symbol": "AAPL", "side": "buy", "quantity": 10}],
        })
        self.assertEqual(resp.status_code, 200)
        request = resp.json()["request"]
        self.assertTrue(request["stage_only"])
        self.assertFalse(request["submits_orders"])

    def test_backtest_contract_forces_quant_strict_without_llm(self):
        resp = self.client.post("/api/backtests", json={
            "symbols": ["AAPL"],
            "start_date": "2026-01-01",
            "end_date": "2026-04-23",
            "config": {"execution_mode": "llm_assisted"},
        })
        self.assertEqual(resp.status_code, 200)
        request = resp.json()["request"]
        self.assertEqual(request["execution_mode"], "quant_strict")
        self.assertFalse(request["llm_constructed"])

    def test_settings_watchlists_presets_and_history_contracts(self):
        self.assertEqual(self.client.get("/api/settings").status_code, 200)
        self.assertEqual(self.client.put("/api/settings", json={"values": {"home_market": "JP"}}).status_code, 200)
        self.assertEqual(self.client.get("/api/watchlists").json()["watchlists"], [])
        self.assertEqual(self.client.post("/api/watchlists", json={"name": "Test", "symbols": ["MSFT"]}).status_code, 200)
        self.assertEqual(self.client.get("/api/strategy-presets").json()["presets"], [])
        self.assertEqual(self.client.post("/api/strategy-presets", json={"name": "Breakout"}).status_code, 200)

        with patch("tradingagents.web.runner.list_runs", return_value=[]):
            history = self.client.get("/api/history")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["items"], [])


if __name__ == "__main__":
    unittest.main()
