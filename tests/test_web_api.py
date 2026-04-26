"""FastAPI integration tests using TestClient."""

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


def _make_analysis_test_client():
    from fastapi import FastAPI
    from tradingagents.web.routes.analysis import router as analysis_router

    app = FastAPI()
    app.include_router(analysis_router)
    try:
        from tradingagents.web.routes.models import router as models_router
    except ImportError:
        pass
    else:
        app.include_router(models_router)
    return TestClient(app)


def _make_mock_graph(final_decision="HOLD"):
    mock_graph = MagicMock()
    mock_graph.graph.stream.return_value = iter([
        {"messages": [], "market_report": "Market neutral.", "final_trade_decision": final_decision},
    ])
    mock_graph.propagator.create_initial_state.return_value = {}
    mock_graph.propagator.get_graph_args.return_value = {}
    mock_graph.build_order_intent.return_value = {
        "rating": final_decision,
        "blocked": False,
        "source": "llm_assisted",
        "execution_mode": "llm_assisted",
        "reason": "",
        "annotations": {},
        "symbol": "AAPL",
        "trade_date": "2026-04-23",
    }
    return mock_graph


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class CreateAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.client = _make_analysis_test_client()
        self._background = patch("tradingagents.web.runner.run_background")
        self._background.start()
        self.addCleanup(self._background.stop)

    def test_valid_request_returns_run_id(self):
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "2026-04-23",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("run_id", body)
        self.assertIn(body["status"], ("pending", "running"))

    def test_missing_ticker_returns_422(self):
        resp = self.client.post("/api/analysis", json={"analysis_date": "2026-04-23"})
        self.assertEqual(resp.status_code, 422)

    def test_missing_date_returns_422(self):
        resp = self.client.post("/api/analysis", json={"ticker": "AAPL"})
        self.assertEqual(resp.status_code, 422)

    def test_bad_date_format_returns_422(self):
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "23-04-2026",
        })
        self.assertEqual(resp.status_code, 422)

    def test_invalid_execution_mode_returns_422(self):
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "2026-04-23",
            "execution_mode": "magic_mode",
        })
        self.assertEqual(resp.status_code, 422)

    def test_unknown_analyst_returns_422(self):
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "2026-04-23",
            "selected_analysts": ["market", "tarot"],
        })
        self.assertEqual(resp.status_code, 422)

    def test_exchange_suffix_tickers_accepted(self):
        for ticker in ("RY.TO", "HSBA.L", "0700.HK", "7203.T"):
            resp = self.client.post("/api/analysis", json={
                "ticker": ticker,
                "analysis_date": "2026-04-23",
            })
            self.assertEqual(resp.status_code, 200, ticker)
            self.assertIn(resp.json()["status"], ("pending", "running"))


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.client = _make_analysis_test_client()

    def test_get_models_returns_provider_specific_options(self):
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        self.assertIn("providers", body)
        self.assertIn("openai", body["providers"])
        self.assertEqual(body["providers"]["openai"]["deep"][0]["value"], "gpt-5.4")
        self.assertEqual(body["providers"]["openai"]["quick"][0]["value"], "gpt-5.4-mini")
        self.assertIn("anthropic", body["providers"])
        self.assertEqual(body["providers"]["anthropic"]["deep"][0]["value"], "claude-opus-4-6")

    def test_get_models_marks_custom_model_providers(self):
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        providers = resp.json()["providers"]

        self.assertTrue(providers["azure"]["custom"])
        self.assertTrue(providers["openrouter"]["custom"])


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class WebAppEnvLoadingTests(unittest.TestCase):
    def test_web_app_loads_dotenv_on_import(self):
        with patch.dict(os.environ, {"FMP_API_KEY": ""}, clear=False), patch(
            "dotenv.main.find_dotenv",
            return_value="/Users/josephwong/TradingAgents/.env",
        ):
            os.environ.pop("FMP_API_KEY", None)
            import tradingagents.web.app as web_app_module

            importlib.reload(web_app_module)

            self.assertTrue(os.getenv("FMP_API_KEY"))


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class GetAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.client = _make_analysis_test_client()
        self._background = patch("tradingagents.web.runner.run_background")
        self._background.start()
        self.addCleanup(self._background.stop)

    def _create_run(self) -> str:
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "2026-04-23",
        })
        return resp.json()["run_id"]

    def test_get_existing_run(self):
        run_id = self._create_run()
        resp = self.client.get(f"/api/analysis/{run_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["run_id"], run_id)
        self.assertEqual(body["ticker"], "AAPL")

    def test_get_unknown_run_returns_404(self):
        resp = self.client.get("/api/analysis/does-not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_get_archived_run_hydrates_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "archived-run-1"
            state_file = Path(tmp) / "MSFT" / "2026-04-22" / "web_runs" / run_id / "run_state.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(json.dumps({
                "run_id": run_id,
                "ticker": "MSFT",
                "analysis_date": "2026-04-22",
                "selected_analysts": ["market"],
                "execution_mode": "llm_assisted",
                "llm_provider": "anthropic",
                "deep_think_llm": "claude-opus-4-6",
                "quick_think_llm": "claude-sonnet-4-6",
                "created_at": "2026-04-22T10:00:00Z",
                "status": "completed",
                "started_at": "2026-04-22T10:00:01Z",
                "completed_at": "2026-04-22T10:05:00Z",
                "report_sections": {"market_report": "Archived market report."},
                "report_paths": {},
                "stats": {},
                "errors": [],
                "final_order_intent": None,
            }))

            with patch.dict("tradingagents.web.runner.DEFAULT_CONFIG", {"results_dir": tmp}, clear=False):
                resp = self.client.get(f"/api/analysis/{run_id}")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["run_id"], run_id)
        self.assertEqual(body["ticker"], "MSFT")
        self.assertEqual(body["report_sections"]["market_report"], "Archived market report.")


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class ListAnalysisArchivesTests(unittest.TestCase):
    def setUp(self):
        self.client = _make_analysis_test_client()

    def _write_state(self, root: str, run_id: str, ticker: str, created_at: str, status: str = "completed"):
        state_file = Path(root) / ticker / "2026-04-22" / "web_runs" / run_id / "run_state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(json.dumps({
            "run_id": run_id,
            "ticker": ticker,
            "analysis_date": "2026-04-22",
            "selected_analysts": ["market"],
            "execution_mode": "llm_assisted",
            "llm_provider": "openai",
            "deep_think_llm": "gpt-5.4",
            "quick_think_llm": "gpt-5.4-mini",
            "created_at": created_at,
            "status": status,
            "started_at": created_at,
            "completed_at": created_at if status == "completed" else None,
            "report_sections": {"market_report": f"{ticker} report"},
            "report_paths": {},
            "stats": {},
            "errors": [],
            "final_order_intent": None,
        }))

    def test_list_archives_returns_saved_runs_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_state(tmp, "older-run", "AAPL", "2026-04-21T09:00:00Z")
            self._write_state(tmp, "newer-run", "NVDA", "2026-04-22T11:00:00Z")

            with patch.dict("tradingagents.web.runner.DEFAULT_CONFIG", {"results_dir": tmp}, clear=False):
                resp = self.client.get("/api/analysis")

        self.assertEqual(resp.status_code, 200)
        runs = [
            r for r in resp.json()["runs"]
            if r["run_id"] in {"newer-run", "older-run"}
        ]
        run_ids = [r["run_id"] for r in runs]
        self.assertLess(run_ids.index("newer-run"), run_ids.index("older-run"))
        self.assertEqual(runs[0]["ticker"], "NVDA")


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class GetReportsTests(unittest.TestCase):
    def setUp(self):
        self.client = _make_analysis_test_client()
        self._background = patch("tradingagents.web.runner.run_background")
        self._background.start()
        self.addCleanup(self._background.stop)

    def test_reports_empty_before_run_completes(self):
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "2026-04-23",
        })
        run_id = resp.json()["run_id"]
        resp = self.client.get(f"/api/analysis/{run_id}/reports")
        self.assertEqual(resp.status_code, 200)
        # sections may be empty while pending
        self.assertIn("sections", resp.json())

    def test_unknown_run_returns_404(self):
        resp = self.client.get("/api/analysis/bad-id/reports")
        self.assertEqual(resp.status_code, 404)


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed")
class ConsultantChatTests(unittest.TestCase):
    def setUp(self):
        from tradingagents.web.app import create_app
        self.client = TestClient(create_app())
        self._background = patch("tradingagents.web.runner.run_background")
        self._background.start()
        self.addCleanup(self._background.stop)

    def _create_run_with_sections(self):
        from tradingagents.web import runner
        run = runner.create_run(
            ticker="AAPL",
            analysis_date="2026-04-23",
            selected_analysts=["market"],
            execution_mode="llm_assisted",
            llm_provider="openai",
            deep_think_llm="gpt-4o",
            quick_think_llm="gpt-4o-mini",
        )
        run.report_sections["market_report"] = "Apple looks strong this quarter."
        run.status = "completed"
        return run.run_id

    def test_no_context_returns_409(self):
        resp = self.client.post("/api/analysis", json={
            "ticker": "AAPL",
            "analysis_date": "2026-04-23",
        })
        run_id = resp.json()["run_id"]
        resp = self.client.post(f"/api/analysis/{run_id}/consultant/chat", json={
            "message": "Why BUY?",
        })
        self.assertEqual(resp.status_code, 409)

    def test_blocking_field_stripped(self):
        run_id = self._create_run_with_sections()

        mock_response = MagicMock()
        mock_response.to_dict.return_value = {
            "answer": "Because fundamentals are strong.",
            "observations": ["Revenue growing"],
            "follow_up_questions": ["What's the risk?"],
            "referenced_context_keys": ["market_report"],
            "blocking": False,
            "error": None,
        }

        with (
            patch("tradingagents.web.routes.consultant.chat_trade_review", return_value=mock_response),
            patch("tradingagents.web.routes.consultant.create_llm_client", return_value=MagicMock()),
        ):
            resp = self.client.post(f"/api/analysis/{run_id}/consultant/chat", json={
                "message": "Why BUY?",
            })

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn("blocking", body)
        self.assertIn("answer", body)

    def test_consultant_route_uses_runnable_llm_from_client_wrapper(self):
        run_id = self._create_run_with_sections()

        mock_response = MagicMock()
        mock_response.to_dict.return_value = {
            "answer": "The consultant used the quick model.",
            "observations": [],
            "follow_up_questions": [],
            "referenced_context_keys": ["market_report"],
            "blocking": False,
            "error": None,
        }

        llm = object()
        client_wrapper = MagicMock()
        client_wrapper.get_llm.return_value = llm

        with (
            patch("tradingagents.web.routes.consultant.chat_trade_review", return_value=mock_response) as mock_chat,
            patch("tradingagents.web.routes.consultant.create_llm_client", return_value=client_wrapper),
        ):
            resp = self.client.post(f"/api/analysis/{run_id}/consultant/chat", json={
                "message": "Why BUY?",
            })

        self.assertEqual(resp.status_code, 200)
        client_wrapper.get_llm.assert_called_once_with()
        self.assertIs(mock_chat.call_args.args[0], llm)

    def test_archived_consultant_route_uses_runnable_llm_from_client_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "archived-consultant-run"
            state_file = Path(tmp) / "MSFT" / "2026-04-22" / "web_runs" / run_id / "run_state.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(json.dumps({
                "run_id": run_id,
                "ticker": "MSFT",
                "analysis_date": "2026-04-22",
                "selected_analysts": ["market"],
                "execution_mode": "llm_assisted",
                "llm_provider": "openai",
                "deep_think_llm": "gpt-4o",
                "quick_think_llm": "gpt-4o-mini",
                "created_at": "2026-04-22T10:00:00Z",
                "status": "completed",
                "started_at": "2026-04-22T10:00:01Z",
                "completed_at": "2026-04-22T10:05:00Z",
                "report_sections": {"market_report": "Archived market report."},
                "report_paths": {},
                "stats": {},
                "errors": [],
                "final_order_intent": None,
            }))

            mock_response = MagicMock()
            mock_response.to_dict.return_value = {
                "answer": "Archived consultant response.",
                "observations": [],
                "follow_up_questions": [],
                "referenced_context_keys": ["market_report"],
                "blocking": False,
                "error": None,
            }

            llm = object()
            client_wrapper = MagicMock()
            client_wrapper.get_llm.return_value = llm

            with (
                patch.dict("tradingagents.web.runner.DEFAULT_CONFIG", {"results_dir": tmp}, clear=False),
                patch("tradingagents.web.routes.consultant.chat_trade_review", return_value=mock_response) as mock_chat,
                patch("tradingagents.web.routes.consultant.create_llm_client", return_value=client_wrapper),
            ):
                resp = self.client.post(f"/api/analysis/{run_id}/consultant/chat", json={
                    "message": "Why BUY?",
                })

        self.assertEqual(resp.status_code, 200)
        client_wrapper.get_llm.assert_called_once_with()
        self.assertIs(mock_chat.call_args.args[0], llm)

    def test_unknown_run_returns_404(self):
        resp = self.client.post("/api/analysis/no-such-run/consultant/chat", json={
            "message": "Hello",
        })
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
