"""Phase 9 tests for day-trade workflow API contracts."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.env_patch = patch.dict(
            os.environ,
            {"TRADINGAGENTS_WEB_DB": os.path.join(self.temp_dir.name, "workflow.sqlite3")},
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

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
        self.assertEqual(screening.json()["status"], "ready")
        self.assertTrue(screening.json()["run_id"].startswith("screening-"))
        self.assertTrue(screening.json()["workflow_session_id"].startswith("session-"))

        basket = self.client.post(
            "/api/baskets",
            json={
                "symbols": ["AAPL", "NVDA"],
                "source_screening_run_id": screening.json()["run_id"],
            },
        )
        self.assertEqual(basket.status_code, 200)
        self.assertTrue(basket.json()["basket_id"].startswith("basket-"))
        self.assertEqual(basket.json()["workflow_session_id"], screening.json()["workflow_session_id"])

        batch = self.client.post(
            "/api/batches",
            json={
                "basket_id": basket.json()["basket_id"],
                "workflow_session_id": basket.json()["workflow_session_id"],
                "symbols": ["AAPL"],
                "analysis_date": "2026-04-23",
            },
        )
        self.assertEqual(batch.status_code, 200)
        self.assertTrue(batch.json()["batch_id"].startswith("batch-"))
        self.assertEqual(batch.json()["workflow_session_id"], screening.json()["workflow_session_id"])

        strategy = self.client.post(
            "/api/strategies/from-batch",
            json={
                "batch_id": batch.json()["batch_id"],
                "workflow_session_id": batch.json()["workflow_session_id"],
            },
        )
        self.assertEqual(strategy.status_code, 200)
        self.assertTrue(strategy.json()["strategy_id"].startswith("strategy-"))
        self.assertEqual(strategy.json()["workflow_session_id"], screening.json()["workflow_session_id"])

    def test_batch_events_sse_contract(self):
        resp = self.client.get("/api/batches/phase-9-contract/events")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
        self.assertIn('"type": "batch_status"', resp.text)
        self.assertIn('"batch_id": "phase-9-contract"', resp.text)

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
            "config": {"execution_mode": "llm_assisted", "walkforward_n_folds": 5},
        })
        self.assertEqual(resp.status_code, 200)
        request = resp.json()["request"]
        self.assertEqual(request["execution_mode"], "quant_strict")
        self.assertFalse(request["llm_constructed"])
        self.assertNotIn("execution_mode", request["config"])
        self.assertEqual(request["config"]["walkforward_n_folds"], 5)

    def test_settings_watchlists_presets_and_history_contracts(self):
        initial_settings = self.client.get("/api/settings")
        self.assertEqual(initial_settings.status_code, 200)
        self.assertEqual(initial_settings.json()["home_market"], "US")

        updated = self.client.put(
            "/api/settings",
            json={"values": {"home_market": "JP", "broker": {"futu": {"enabled": True}}}},
        )
        self.assertEqual(updated.status_code, 200)
        reloaded = self.client.get("/api/settings")
        self.assertEqual(reloaded.json()["home_market"], "JP")
        self.assertTrue(reloaded.json()["broker"]["futu"]["enabled"])

        self.assertEqual(self.client.get("/api/watchlists").json()["watchlists"], [])
        created_watchlist = self.client.post(
            "/api/watchlists",
            json={"name": "Test", "symbols": ["msft", " NVDA "]},
        )
        self.assertEqual(created_watchlist.status_code, 200)
        watchlists = self.client.get("/api/watchlists").json()["watchlists"]
        self.assertEqual(len(watchlists), 1)
        self.assertEqual(watchlists[0]["name"], "Test")
        self.assertEqual(watchlists[0]["symbols"], ["MSFT", "NVDA"])

        self.assertEqual(self.client.get("/api/strategy-presets").json()["presets"], [])
        created_preset = self.client.post(
            "/api/strategy-presets",
            json={"name": "Breakout", "portfolio_size": 250000, "risk_per_trade": 0.02},
        )
        self.assertEqual(created_preset.status_code, 200)
        presets = self.client.get("/api/strategy-presets").json()["presets"]
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0]["name"], "Breakout")
        self.assertEqual(presets[0]["portfolio_size"], 250000)

        screening = self.client.post(
            "/api/screening/runs",
            json={"universe": "Nikkei 225", "strategy": "auto", "trade_date": "2026-04-23", "top_n": 5, "min_score": 0.6},
        ).json()
        basket = self.client.post(
            "/api/baskets",
            json={"name": "JP Leaders", "symbols": ["7203.T", "9984.T"], "source_screening_run_id": screening["run_id"]},
        ).json()
        batch = self.client.post(
            "/api/batches",
            json={
                "basket_id": basket["basket_id"],
                "workflow_session_id": basket["workflow_session_id"],
                "symbols": ["7203.T"],
                "analysis_date": "2026-04-23",
            },
        ).json()
        strategy = self.client.post(
            "/api/strategies/from-batch",
            json={"batch_id": batch["batch_id"], "workflow_session_id": batch["workflow_session_id"]},
        ).json()
        backtest = self.client.post(
            "/api/backtests",
            json={
                "strategy_id": strategy["strategy_id"],
                "workflow_session_id": strategy["workflow_session_id"],
                "symbols": ["AAPL"],
                "start_date": "2026-01-01",
                "end_date": "2026-04-23",
            },
        ).json()
        stage = self.client.post(
            "/api/broker/futu/stage",
            json={
                "strategy_id": strategy["strategy_id"],
                "workflow_session_id": strategy["workflow_session_id"],
                "orders": [{"symbol": "AAPL", "side": "buy", "quantity": 10}],
            },
        ).json()

        legacy_run = type(
            "LegacyRun",
            (),
            {
                "run_id": "legacy-1",
                "ticker": "MSFT",
                "status": "completed",
                "created_at": "2026-04-20T12:00:00+00:00",
                "completed_at": "2026-04-20T12:30:00+00:00",
            },
        )()
        with patch("tradingagents.web.runner.list_runs", return_value=[legacy_run]):
            history = self.client.get("/api/history")
        self.assertEqual(history.status_code, 200)
        items = history.json()["items"]
        self.assertEqual(history.json()["total"], len(items))
        self.assertTrue(any(item["type"] == "legacy_analysis" and item["id"] == "legacy-1" for item in items))
        self.assertTrue(any(item["type"] == "screening_run" and item["id"] == screening["run_id"] for item in items))
        self.assertTrue(any(item["type"] == "basket" and item["id"] == basket["basket_id"] for item in items))
        self.assertTrue(any(item["type"] == "batch_analysis" and item["id"] == batch["batch_id"] for item in items))
        self.assertTrue(any(item["type"] == "strategy_plan" and item["id"] == strategy["strategy_id"] for item in items))
        self.assertTrue(any(item["type"] == "backtest_run" and item["id"] == backtest["backtest_id"] for item in items))
        self.assertTrue(any(item["type"] == "broker_stage_request" and item["id"] == stage["stage_id"] for item in items))
        linked_items = [
            item for item in items if item["id"] in {
                screening["run_id"],
                basket["basket_id"],
                batch["batch_id"],
                strategy["strategy_id"],
                backtest["backtest_id"],
                stage["stage_id"],
            }
        ]
        self.assertTrue(all(item["workflow_session_id"] == screening["workflow_session_id"] for item in linked_items))

        session_list = self.client.get("/api/workflow-sessions")
        self.assertEqual(session_list.status_code, 200)
        self.assertEqual(session_list.json()["total"], 1)
        self.assertEqual(session_list.json()["sessions"][0]["session_id"], screening["workflow_session_id"])

        session_detail = self.client.get(f"/api/workflow-sessions/{screening['workflow_session_id']}")
        self.assertEqual(session_detail.status_code, 200)
        self.assertEqual(session_detail.json()["session"]["batch_id"], batch["batch_id"])
        self.assertEqual(session_detail.json()["session"]["strategy_id"], strategy["strategy_id"])
        self.assertEqual(session_detail.json()["session"]["backtest_id"], backtest["backtest_id"])

        archived = self.client.put(
            f"/api/workflow-sessions/{screening['workflow_session_id']}",
            json={"current_screen": "history", "status": "archived"},
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["session"]["current_screen"], "history")
        self.assertEqual(archived.json()["session"]["status"], "archived")

        active_sessions = self.client.get("/api/workflow-sessions")
        self.assertEqual(active_sessions.json()["total"], 0)
        archived_sessions = self.client.get("/api/workflow-sessions?include_archived=true")
        self.assertEqual(archived_sessions.json()["total"], 1)

        filtered_history = self.client.get("/api/history", params={"item_type": "strategy_plan", "q": strategy["strategy_id"]})
        self.assertEqual(filtered_history.status_code, 200)
        filtered_items = filtered_history.json()["items"]
        self.assertEqual(len(filtered_items), 1)
        self.assertEqual(filtered_items[0]["id"], strategy["strategy_id"])

        grouped_history = self.client.get(
            "/api/history",
            params={
                "group_by": "workflow_session",
                "market": "JP",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
            },
        )
        self.assertEqual(grouped_history.status_code, 200)
        self.assertEqual(grouped_history.json()["group_by"], "workflow_session")
        groups = grouped_history.json()["groups"]
        self.assertTrue(any(group["workflow_session_id"] == screening["workflow_session_id"] for group in groups))
        session_group = next(group for group in groups if group["workflow_session_id"] == screening["workflow_session_id"])
        grouped_ids = {item["id"] for item in session_group["items"]}
        self.assertTrue({screening["run_id"], basket["basket_id"], batch["batch_id"], strategy["strategy_id"], backtest["backtest_id"], stage["stage_id"]}.issubset(grouped_ids))

    def test_reused_session_keeps_original_home_market(self):
        screening = self.client.post(
            "/api/screening/runs",
            json={
                "universe": "S&P 500",
                "strategy": "auto",
                "trade_date": "2026-04-23",
                "top_n": 5,
                "min_score": 0.6,
            },
        ).json()
        session_id = screening["workflow_session_id"]

        self.client.put("/api/settings", json={"values": {"home_market": "JP"}})

        basket = self.client.post(
            "/api/baskets",
            json={
                "name": "Carry Over",
                "symbols": ["AAPL", "NVDA"],
                "workflow_session_id": session_id,
                "source_screening_run_id": screening["run_id"],
            },
        ).json()

        session_detail = self.client.get(f"/api/workflow-sessions/{session_id}")
        self.assertEqual(session_detail.status_code, 200)
        self.assertEqual(session_detail.json()["session"]["home_market"], "US")
        self.assertEqual(session_detail.json()["session"]["settings_snapshot"]["home_market"], "US")

        history = self.client.get("/api/history", params={"group_by": "workflow_session", "market": "US"})
        self.assertEqual(history.status_code, 200)
        us_group = next(
            group for group in history.json()["groups"] if group["workflow_session_id"] == session_id
        )
        us_ids = {item["id"] for item in us_group["items"]}
        self.assertIn(screening["run_id"], us_ids)
        self.assertIn(basket["basket_id"], us_ids)

        jp_history = self.client.get("/api/history", params={"group_by": "workflow_session", "market": "JP", "q": session_id})
        self.assertEqual(jp_history.status_code, 200)
        self.assertFalse(any(group["workflow_session_id"] == session_id for group in jp_history.json().get("groups", [])))


class WorkflowStorageTests(unittest.TestCase):
    def test_existing_unversioned_database_raises_migration_guard(self):
        from tradingagents.web.storage import WorkflowStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "legacy.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE settings (singleton_id INTEGER PRIMARY KEY, values_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.commit()
            conn.close()

            with self.assertRaisesRegex(RuntimeError, "missing schema_version metadata"):
                WorkflowStore(Path(db_path))

            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            conn.close()
            self.assertEqual([row[0] for row in rows], ["settings"])

    def test_new_database_records_schema_version(self):
        from tradingagents.web.storage import WorkflowStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "fresh.sqlite3")
            store = WorkflowStore(Path(db_path))
            self.assertIsNotNone(store)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT version FROM schema_version WHERE singleton_id = 1"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["version"], 1)


if __name__ == "__main__":
    unittest.main()
