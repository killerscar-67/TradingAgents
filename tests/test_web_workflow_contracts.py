"""Phase 11 tests for day-trade workflow API contracts."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

try:
    from fastapi.testclient import TestClient

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


class _FakeSyncThread:
    """Runs the thread target synchronously in the calling thread — keeps tests deterministic."""

    def __init__(self, target=None, args=(), daemon=None, **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        if self._target:
            self._target(*self._args)


def _make_daily_history(*, start: float = 100.0, step: float = 1.0, periods: int = 260) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=periods, freq="B")
    close = pd.Series([start + (step * i) for i in range(periods)], index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )


def _make_yfinance_multiindex_history(symbol: str, *, start: float = 100.0, step: float = 1.0, periods: int = 260) -> pd.DataFrame:
    history = _make_daily_history(start=start, step=step, periods=periods)
    history.columns = pd.MultiIndex.from_product([history.columns, [symbol]], names=["Price", "Ticker"])
    return history


def _make_intraday_bars(*, start: float = 100.0, step: float = 0.2, periods: int = 160, freq: str = "15min") -> pd.DataFrame:
    idx = pd.date_range("2026-03-01", periods=periods, freq=freq, tz="UTC")
    close = pd.Series([start + (step * i) for i in range(periods)], index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.2,
            "Low": close - 0.2,
            "Close": close,
            "Volume": 50_000,
        },
        index=idx,
    )


class _FakeBacktestResult:
    def __init__(self, symbol: str, final_equity: float):
        self.symbol = symbol
        self.initial_equity = 50_000.0
        self.final_equity = final_equity
        self.trade_count = 4
        self.winning_trades = 3
        self.win_rate = 0.75
        self.sharpe_ratio = 1.2
        self.max_drawdown_pct = 0.08
        self.total_return_pct = round(((final_equity / self.initial_equity) - 1.0) * 100.0, 4)
        self.equity_curve = (50_000.0, 50_500.0, final_equity)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "initial_equity": self.initial_equity,
            "final_equity": self.final_equity,
            "trade_count": self.trade_count,
            "winning_trades": self.winning_trades,
            "win_rate": self.win_rate,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "total_return_pct": self.total_return_pct,
            "trades": [],
        }


class _FakeWalkForward:
    def to_dict(self):
        return {
            "n_folds": 3,
            "oos_sharpe_positive_pct": 0.6667,
            "mean_oos_sharpe": 0.91,
            "folds": [{"fold_idx": 0, "oos_trade_count": 2, "oos_total_return_pct": 4.1}],
        }


def _screening_regime(home_market: str = "US"):
    return {
        "home_market": home_market,
        "trade_date": "2026-04-23",
        "status": "ready",
        "indices": [],
        "regime": {
            "label": "Trending bull",
            "confidence": 82,
            "suggested_entry_mode": "breakout",
            "event_risk_flag": False,
        },
        "breadth": {},
        "sectors": [],
        "events": [],
        "regions": {
            "US": {"regime": {"label": "Trending bull", "confidence": 82, "suggested_entry_mode": "breakout", "event_risk_flag": False}},
            "HK": {"regime": {"label": "Choppy / range-bound", "confidence": 55, "suggested_entry_mode": "mean_reversion", "event_risk_flag": False}},
            "JP": {"regime": {"label": "Trending bull", "confidence": 77, "suggested_entry_mode": "breakout", "event_risk_flag": False}},
        },
        "stream": {"status": "delayed_fallback", "transport": "websocket"},
    }


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

    def _mock_market_download(self, symbols, start, end):
        histories = {}
        for symbol in symbols:
            if symbol in {"^VIX", "^VHSI"}:
                histories[symbol] = _make_daily_history(start=12.0, step=0.0)
            elif symbol == "HYG":
                histories[symbol] = _make_daily_history(start=80.0, step=0.3)
            elif symbol == "IEF":
                histories[symbol] = _make_daily_history(start=100.0, step=0.05)
            else:
                histories[symbol] = _make_daily_history(start=100.0, step=1.0)
        return histories

    def _mock_market_download_risk_off(self, symbols, start, end):
        histories = {}
        for symbol in symbols:
            if symbol in {"^VIX", "^VHSI"}:
                histories[symbol] = _make_daily_history(start=35.0, step=0.1)
            elif symbol == "HYG":
                histories[symbol] = _make_daily_history(start=100.0, step=-0.3)
            elif symbol == "IEF":
                histories[symbol] = _make_daily_history(start=90.0, step=0.1)
            else:
                histories[symbol] = _make_daily_history(start=150.0, step=-0.2)
        return histories

    def _quant_contract(self, symbol: str, score: float, signal: str, summary: str):
        from tradingagents.quant.contracts import QuantSignalContract, QuantSignalLabel

        return QuantSignalContract(
            symbol=symbol,
            trade_date="2026-04-23",
            signal=QuantSignalLabel(signal),
            score=score,
            confidence=round(min(max(score, 0.0), 1.0), 4),
            summary=summary,
            raw={"regime": {"atr": 1.2}, "entry": {"engine": "breakout", "direction": "long", "strength": 0.9}, "validation": {"passed": True}},
        )

    def test_market_overview_classifies_trending_bull_and_risk_off(self):
        with patch("tradingagents.web.workflow_service._download_daily_history", side_effect=self._mock_market_download), patch(
            "tradingagents.web.workflow_service._fetch_calendar_events",
            return_value=[{"timestamp": "2026-04-23T14:00:00Z", "title": "FOMC Minutes", "impact": "high", "region": "US"}],
        ):
            resp = self.client.get("/api/market/overview?home_market=US&trade_date=2026-04-23")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["home_market"], "US")
        self.assertEqual(body["regime"]["label"], "Trending bull")
        self.assertEqual(body["regime"]["suggested_entry_mode"], "breakout")
        self.assertTrue(body["regime"]["event_risk_flag"])
        self.assertIn("HK", body["regions"])

        with patch("tradingagents.web.workflow_service._download_daily_history", side_effect=self._mock_market_download_risk_off), patch(
            "tradingagents.web.workflow_service._fetch_calendar_events",
            return_value=[],
        ):
            risk_off = self.client.get("/api/market/overview?home_market=US&trade_date=2026-04-23")
        self.assertEqual(risk_off.status_code, 200)
        self.assertEqual(risk_off.json()["regime"]["label"], "Risk-off")
        self.assertEqual(risk_off.json()["regime"]["suggested_entry_mode"], "auto")

    def test_market_overview_accepts_yfinance_multiindex_history(self):
        def mock_multiindex_download(symbols, start, end):
            histories = {}
            for symbol in symbols:
                step = 0.0 if symbol in {"^VIX", "^VHSI"} else 1.0
                histories[symbol] = _make_yfinance_multiindex_history(symbol, start=100.0, step=step)
            return histories

        with patch("tradingagents.web.workflow_service._download_daily_history", side_effect=mock_multiindex_download), patch(
            "tradingagents.web.workflow_service._fetch_calendar_events",
            return_value=[],
        ):
            resp = self.client.get("/api/market/overview?home_market=US&trade_date=2026-04-23")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["home_market"], "US")
        self.assertGreater(body["indices"][0]["price"], 0)
        self.assertEqual(body["breadth"]["pct_above_50d"], 100.0)

    def test_market_overview_downloads_only_requested_home_market(self):
        calls = []

        def mock_download(symbols, start, end):
            calls.append(list(symbols))
            return self._mock_market_download(symbols, start, end)

        with patch("tradingagents.web.workflow_service._download_daily_history", side_effect=mock_download), patch(
            "tradingagents.web.workflow_service._fetch_calendar_events",
            return_value=[],
        ):
            resp = self.client.get("/api/market/overview?home_market=US&trade_date=2026-04-23")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["home_market"], "US")
        self.assertIn("HK", body["regions"])
        requested_symbols = {symbol for call in calls for symbol in call}
        self.assertIn("^GSPC", requested_symbols)
        self.assertIn("XLK", requested_symbols)
        self.assertIn("HYG", requested_symbols)
        self.assertNotIn("^HSI", requested_symbols)
        self.assertNotIn("^N225", requested_symbols)
        self.assertEqual(len(calls), 1)

    def test_daily_history_skips_known_unavailable_yahoo_symbols(self):
        from tradingagents.web.workflow_service import _download_daily_history

        with patch("tradingagents.web.workflow_service._download_yfinance_daily", return_value=_make_daily_history()) as mock_download:
            histories = _download_daily_history(["^VHSI", "AAPL"], "2026-01-01", "2026-01-31")
        self.assertTrue(histories["^VHSI"].empty)
        self.assertFalse(histories["AAPL"].empty)
        mock_download.assert_called_once()
        self.assertEqual(mock_download.call_args.args[0], "AAPL")

    def test_daily_history_retries_missing_batch_symbol_individually(self):
        from tradingagents.web.workflow_service import _download_daily_history

        def mock_download(symbols, start, end, *, threads):
            if isinstance(symbols, list):
                self.assertEqual(symbols, ["AAPL", "GOOGL"])
                return _make_yfinance_multiindex_history("AAPL", start=100.0, step=1.0)
            self.assertEqual(symbols, "GOOGL")
            self.assertFalse(threads)
            return _make_yfinance_multiindex_history("GOOGL", start=100.0, step=1.0)

        with patch("tradingagents.web.workflow_service._download_yfinance_daily", side_effect=mock_download) as mock_download_fn:
            histories = _download_daily_history(["AAPL", "GOOGL"], "2026-01-01", "2026-01-31")
        self.assertFalse(histories["AAPL"].empty)
        self.assertFalse(histories["GOOGL"].empty)
        self.assertEqual(mock_download_fn.call_count, 2)

    def test_market_chart_route_returns_chunked_daily_candles_and_line_points(self):
        with patch("tradingagents.web.workflow_service._download_daily_history", return_value={"SPY": _make_daily_history()}):
            resp = self.client.get("/api/market/chart?symbol=SPY&interval=1D&limit=40&trade_date=2026-04-23")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["symbol"], "SPY")
        self.assertEqual(body["interval"], "1D")
        self.assertEqual(body["limit"], 40)
        self.assertTrue(body["has_more"])
        self.assertEqual(len(body["points"]), 40)
        self.assertEqual(len(body["bars"]), 40)
        self.assertIn("time", body["points"][0])
        self.assertIn("value", body["points"][0])
        self.assertIn("open", body["bars"][0])
        self.assertIn("close", body["bars"][0])
        self.assertEqual(body["oldest_time"], body["bars"][0]["time"])
        self.assertEqual(body["newest_time"], body["bars"][-1]["time"])

    def test_market_chart_route_supports_cursor_backfill(self):
        history = _make_daily_history(periods=260)

        with patch("tradingagents.web.workflow_service._download_daily_history", return_value={"SPY": history}):
            latest = self.client.get("/api/market/chart?symbol=SPY&interval=1D&limit=20&trade_date=2026-04-23")

        self.assertEqual(latest.status_code, 200)
        latest_body = latest.json()
        oldest_time = latest_body["oldest_time"]
        self.assertIsNotNone(oldest_time)

        with patch("tradingagents.web.workflow_service._download_daily_history", return_value={"SPY": history}):
            older = self.client.get(
                f"/api/market/chart?symbol=SPY&interval=1D&limit=20&before={oldest_time}&trade_date=2026-04-23"
            )

        self.assertEqual(older.status_code, 200)
        older_body = older.json()
        self.assertEqual(older_body["interval"], "1D")
        self.assertLess(older_body["newest_time"], oldest_time)
        self.assertLess(older_body["bars"][-1]["time"], latest_body["bars"][0]["time"])
        self.assertEqual(len(older_body["bars"]), 20)

    def test_market_chart_route_supports_intraday_intervals(self):
        with patch("tradingagents.web.workflow_service.get_intraday_bars", return_value=_make_intraday_bars()):
            resp = self.client.get("/api/market/chart?symbol=SPY&interval=15m&limit=30&trade_date=2026-04-23")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["interval"], "15m")
        self.assertEqual(body["limit"], 30)
        self.assertEqual(len(body["bars"]), 30)
        self.assertEqual(len(body["points"]), 30)
        self.assertIn("high", body["bars"][0])
        self.assertIn("low", body["bars"][0])

    def test_market_chart_route_forwards_intraday_session(self):
        with patch("tradingagents.web.workflow_service.get_intraday_bars", return_value=_make_intraday_bars()) as mock_intraday:
            resp = self.client.get("/api/market/chart?symbol=SPY&interval=15m&session=extended&limit=30&trade_date=2026-04-23")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_intraday.call_args.kwargs["session"], "extended")

    def test_market_live_websocket_streams_multiple_snapshots(self):
        payload = _screening_regime("US")
        with patch("tradingagents.web.routes.workflow.build_market_overview", return_value=payload):
            with self.client.websocket_connect("/api/market/live?home_market=US&interval_seconds=0.01") as ws:
                first = ws.receive_json()
                second = ws.receive_json()
        self.assertEqual(first["type"], "market_snapshot")
        self.assertEqual(second["type"], "market_snapshot")
        self.assertEqual(first["payload"]["home_market"], "US")

    def test_screening_and_basket_persist_ranked_results(self):
        def fake_quant(symbol, trade_date, bars_15m, bars_4h, config=None):
            scores = {
                "AAPL": self._quant_contract("AAPL", 0.92, "buy", "AAPL breakout"),
                "NVDA": self._quant_contract("NVDA", 0.88, "buy", "NVDA breakout"),
                "MSFT": self._quant_contract("MSFT", 0.25, "hold", "MSFT hold"),
            }
            return scores[symbol]

        with patch("tradingagents.web.workflow_service.get_market_overview", return_value=_screening_regime()), patch(
            "tradingagents.web.workflow_service.get_intraday_bars",
            return_value=_make_intraday_bars(),
        ), patch("tradingagents.quant.engine.run_quant_engine", side_effect=fake_quant):
            screening = self.client.post(
                "/api/screening/runs",
                json={
                    "universe": "CUSTOM",
                    "strategy": "auto",
                    "trade_date": "2026-04-23",
                    "top_n": 2,
                    "min_score": 0.5,
                    "custom_symbols": ["AAPL", "MSFT", "NVDA"],
                },
            )
            self.assertEqual(screening.status_code, 200)
            body = screening.json()
            self.assertEqual(body["status"], "completed")
            self.assertEqual([item["symbol"] for item in body["results"]], ["AAPL", "NVDA"])

            basket = self.client.post(
                "/api/baskets",
                json={
                    "name": "US Breakouts",
                    "symbols": ["AAPL", "NVDA"],
                    "source_screening_run_id": body["run_id"],
                },
            )
        self.assertEqual(basket.status_code, 200)
        basket_body = basket.json()
        self.assertEqual(len(basket_body["items"]), 2)
        self.assertEqual(basket_body["items"][0]["symbol"], "AAPL")
        self.assertEqual(basket_body["workflow_session_id"], body["workflow_session_id"])

    def test_batch_strategy_stage_and_history_flow(self):
        run_counter = {"value": 0}

        def fake_quant(symbol, trade_date, bars_15m, bars_4h, config=None):
            mapping = {
                "AAPL": self._quant_contract("AAPL", 0.95, "buy", "AAPL leader"),
                "MSFT": self._quant_contract("MSFT", 0.55, "buy", "MSFT setup"),
                "TSLA": self._quant_contract("TSLA", 0.72, "sell", "TSLA weak"),
            }
            return mapping[symbol]

        def fake_create_run(**kwargs):
            run_counter["value"] += 1
            return SimpleNamespace(run_id=f"run-{run_counter['value']}")

        def fake_run_sync(run_id, config=None):
            mapping = {
                "run-1": SimpleNamespace(
                    status="completed",
                    final_order_intent={"rating": "BUY", "reason": "Strong trend"},
                    report_sections={"final_trade_decision": "BUY AAPL"},
                    errors=[],
                    report_paths={"report.md": "/tmp/report-aapl.md"},
                ),
                "run-2": SimpleNamespace(
                    status="completed",
                    final_order_intent={"rating": "HOLD", "reason": "No edge"},
                    report_sections={"final_trade_decision": "HOLD MSFT"},
                    errors=[],
                    report_paths={"report.md": "/tmp/report-msft.md"},
                ),
                "run-3": SimpleNamespace(
                    status="completed",
                    final_order_intent={"rating": "SELL", "reason": "Weak tape"},
                    report_sections={"final_trade_decision": "SELL TSLA"},
                    errors=[],
                    report_paths={"report.md": "/tmp/report-tsla.md"},
                ),
            }
            return mapping[run_id]

        with patch("tradingagents.web.workflow_service.get_market_overview", return_value=_screening_regime()), patch(
            "tradingagents.web.workflow_service.get_intraday_bars",
            return_value=_make_intraday_bars(),
        ), patch(
            "tradingagents.quant.engine.run_quant_engine",
            side_effect=fake_quant,
        ), patch("tradingagents.web.workflow_service.runner.create_run", side_effect=fake_create_run), patch(
            "tradingagents.web.workflow_service.runner.run_sync",
            side_effect=fake_run_sync,
        ), patch(
            "tradingagents.integrations.futu.opend.FutuStageOnlyAdapter.stage_orders",
            return_value={"status": "staged", "headline": "1 orders staged for review", "stage_only": True, "submits_orders": False, "orders": [{"symbol": "AAPL", "side": "buy", "quantity": 10}]},
        ), patch("tradingagents.web.workflow_service.run_backtest", return_value=_FakeBacktestResult("AAPL", 53_000.0)), patch(
            "tradingagents.web.workflow_service.run_walk_forward",
            return_value=_FakeWalkForward(),
        ), patch("tradingagents.web.workflow_service._thread_cls", new=_FakeSyncThread):
            screening = self.client.post(
                "/api/screening/runs",
                json={
                    "universe": "CUSTOM",
                    "strategy": "auto",
                    "trade_date": "2026-04-23",
                    "top_n": 3,
                    "min_score": 0.0,
                    "custom_symbols": ["AAPL", "MSFT", "TSLA"],
                },
            ).json()
            basket = self.client.post(
                "/api/baskets",
                json={
                    "name": "Mixed Ideas",
                    "symbols": ["AAPL", "MSFT", "TSLA"],
                    "source_screening_run_id": screening["run_id"],
                },
            ).json()
            batch = self.client.post(
                "/api/batches",
                json={
                    "basket_id": basket["basket_id"],
                    "workflow_session_id": basket["workflow_session_id"],
                    "symbols": ["AAPL", "MSFT", "TSLA"],
                    "analysis_date": "2026-04-23",
                },
            )
            self.assertEqual(batch.status_code, 200)
            batch_body = batch.json()
            self.assertEqual(batch_body["status"], "completed")
            self.assertEqual(batch_body["summary"]["counts"]["completed"], 3)
            self.assertEqual(batch_body["items"][0]["rating"], "BUY")

            batch_events = self.client.get(f"/api/batches/{batch_body['batch_id']}/events")
            self.assertEqual(batch_events.status_code, 200)
            self.assertIn('"type": "batch_item"', batch_events.text)

            strategy = self.client.post(
                "/api/strategies/from-batch",
                json={
                    "batch_id": batch_body["batch_id"],
                    "workflow_session_id": batch_body["workflow_session_id"],
                    "allow_shorts": False,
                    "portfolio_size": 100_000,
                    "risk_per_trade": 0.01,
                },
            )
            self.assertEqual(strategy.status_code, 200)
            strategy_body = strategy.json()
            self.assertEqual(len(strategy_body["trades"]), 1)
            self.assertEqual(strategy_body["trades"][0]["symbol"], "AAPL")

            stage = self.client.post(
                "/api/broker/futu/stage",
                json={
                    "strategy_id": strategy_body["strategy_id"],
                    "workflow_session_id": strategy_body["workflow_session_id"],
                },
            )
            self.assertEqual(stage.status_code, 200)
            stage_body = stage.json()
            self.assertEqual(stage_body["status"], "staged")
            self.assertTrue(stage_body["response"]["stage_only"])

            backtest = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy_body["strategy_id"],
                    "workflow_session_id": strategy_body["workflow_session_id"],
                    "symbols": ["AAPL"],
                    "start_date": "2026-01-01",
                    "end_date": "2026-04-23",
                    "config": {"walkforward_n_folds": 3},
                },
            )
            self.assertEqual(backtest.status_code, 200)
            backtest_body = backtest.json()
            self.assertEqual(backtest_body["strategy_id"], strategy_body["strategy_id"])
            self.assertEqual(backtest_body["start_date"], "2026-01-01")
            self.assertEqual(backtest_body["end_date"], "2026-04-23")
            self.assertEqual(backtest_body["request"]["execution_mode"], "quant_strict")
            self.assertFalse(backtest_body["request"]["llm_constructed"])
            self.assertEqual(backtest_body["result"]["summary"]["symbols"], ["AAPL"])

            backtest_events = self.client.get(f"/api/backtests/{backtest_body['backtest_id']}/events")
            self.assertEqual(backtest_events.status_code, 200)
            self.assertIn('"status": "completed"', backtest_events.text)

            legacy_run = SimpleNamespace(
                run_id="legacy-1",
                ticker="MSFT",
                status="completed",
                created_at="2026-04-20T12:00:00+00:00",
                completed_at="2026-04-20T12:30:00+00:00",
            )
            with patch("tradingagents.web.runner.list_runs", return_value=[legacy_run]):
                history = self.client.get("/api/history", params={"group_by": "workflow_session"})
        self.assertEqual(history.status_code, 200)
        grouped = history.json()["groups"]
        session_group = next(group for group in grouped if group["workflow_session_id"] == screening["workflow_session_id"])
        grouped_ids = {item["id"] for item in session_group["items"]}
        self.assertTrue(
            {
                screening["run_id"],
                basket["basket_id"],
                batch_body["batch_id"],
                strategy_body["strategy_id"],
                backtest_body["backtest_id"],
                stage_body["stage_id"],
            }.issubset(grouped_ids)
        )
        all_types = {item["type"] for group in grouped for item in group["items"]}
        self.assertIn("legacy_analysis", all_types)
        self.assertIn("strategy_plan", all_types)

    def test_backtest_route_uses_quant_path_without_web_runner(self):
        from tradingagents.web.storage import get_workflow_store

        store = get_workflow_store()
        strategy = store.create_strategy_plan(
            {
                "batch_id": "batch-seeded",
                "mode": "breakout",
                "horizon": "intraday",
                "portfolio_size": 100_000.0,
                "risk_per_trade": 0.01,
                "allow_shorts": True,
            },
            home_market="US",
        )
        store.update_strategy_plan(
            strategy["strategy_id"],
            result={
                "trades": [{"symbol": "AAPL", "side": "buy", "direction": "long", "entry_mode": "breakout"}],
                "exposure": {},
                "risk": {},
            },
        )

        with patch("tradingagents.web.workflow_service.get_intraday_bars", return_value=_make_intraday_bars()), patch(
            "tradingagents.web.workflow_service.run_backtest",
            return_value=_FakeBacktestResult("AAPL", 52_500.0),
        ), patch(
            "tradingagents.web.workflow_service.run_walk_forward",
            return_value=_FakeWalkForward(),
        ), patch("tradingagents.web.routes.workflow.runner.create_run") as create_run:
            resp = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy["strategy_id"],
                    "symbols": ["AAPL"],
                    "start_date": "2026-01-01",
                    "end_date": "2026-04-23",
                    "config": {"walkforward_n_folds": 3},
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["strategy_id"], strategy["strategy_id"])
        self.assertEqual(body["start_date"], "2026-01-01")
        self.assertEqual(body["end_date"], "2026-04-23")
        self.assertEqual(body["request"]["execution_mode"], "quant_strict")
        self.assertFalse(body["request"]["llm_constructed"])
        self.assertEqual(body["result"]["summary"]["symbols"], ["AAPL"])
        create_run.assert_not_called()

    def test_get_backtest_detail_returns_stored_record_and_404_for_unknown(self):
        from tradingagents.web.storage import get_workflow_store

        store = get_workflow_store()
        strategy = store.create_strategy_plan(
            {
                "batch_id": "batch-detail",
                "mode": "breakout",
                "horizon": "intraday",
                "portfolio_size": 100_000.0,
                "risk_per_trade": 0.01,
                "allow_shorts": True,
            },
            home_market="US",
        )
        store.update_strategy_plan(
            strategy["strategy_id"],
            result={
                "trades": [
                    {
                        "symbol": "AAPL",
                        "side": "buy",
                        "direction": "long",
                        "quantity": 10,
                        "entry_price": 100.0,
                        "stop_price": 95.0,
                        "target_price": 110.0,
                        "notional": 1_000.0,
                        "entry_mode": "breakout",
                    }
                ],
                "exposure": {},
                "risk": {},
            },
        )

        with patch("tradingagents.web.workflow_service.get_intraday_bars", return_value=_make_intraday_bars()), patch(
            "tradingagents.web.workflow_service.run_trade_plan_backtest",
            return_value=_FakeBacktestResult("AAPL", 52_500.0),
        ):
            created = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy["strategy_id"],
                    "start_date": "2026-01-01",
                    "end_date": "2026-04-23",
                },
            )

        self.assertEqual(created.status_code, 200)
        created_body = created.json()

        detail = self.client.get(f"/api/backtests/{created_body['backtest_id']}")
        self.assertEqual(detail.status_code, 200)
        detail_body = detail.json()
        self.assertEqual(detail_body["backtest_id"], created_body["backtest_id"])
        self.assertEqual(detail_body["strategy_id"], strategy["strategy_id"])
        self.assertEqual(detail_body["start_date"], "2026-01-01")
        self.assertEqual(detail_body["end_date"], "2026-04-23")
        self.assertEqual(detail_body["status"], "completed")
        self.assertEqual(detail_body["result"]["summary"]["symbols"], ["AAPL"])
        self.assertIn("events", detail_body)

        missing = self.client.get("/api/backtests/backtest-missing")
        self.assertEqual(missing.status_code, 404)

    def test_saved_strategy_backtest_replays_frozen_trade_plan(self):
        from tradingagents.web.storage import get_workflow_store

        store = get_workflow_store()
        strategy = store.create_strategy_plan(
            {
                "batch_id": "batch-frozen",
                "mode": "breakout",
                "horizon": "intraday",
                "portfolio_size": 100_000.0,
                "risk_per_trade": 0.01,
                "allow_shorts": True,
            },
            home_market="US",
        )
        store.update_strategy_plan(
            strategy["strategy_id"],
            result={
                "trades": [
                    {
                        "symbol": "AAPL",
                        "side": "sell",
                        "direction": "short",
                        "quantity": 25,
                        "entry_price": 105.0,
                        "stop_price": 108.0,
                        "target_price": 99.0,
                        "notional": 2625.0,
                        "entry_mode": "breakout",
                    }
                ],
                "exposure": {},
                "risk": {},
            },
        )

        frozen_bars = _make_intraday_bars(start=106.0, step=-0.5)
        with patch("tradingagents.web.workflow_service.get_intraday_bars", return_value=frozen_bars), patch(
            "tradingagents.web.workflow_service.run_backtest"
        ) as run_backtest_mock, patch(
            "tradingagents.web.workflow_service.run_walk_forward"
        ) as run_walk_forward_mock:
            resp = self.client.post(
                "/api/backtests",
                json={
                    "strategy_id": strategy["strategy_id"],
                    "start_date": "2026-01-01",
                    "end_date": "2026-04-23",
                    "config": {"walkforward_n_folds": 3},
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["result"]["summary"]["source"], "saved_strategy")
        self.assertEqual(body["result"]["per_symbol"][0]["trade_plan"]["direction"], "short")
        self.assertEqual(body["result"]["per_symbol"][0]["trade_plan"]["quantity"], 25)
        self.assertEqual(body["result"]["per_symbol"][0]["trades"][0]["direction"], "short")
        run_backtest_mock.assert_not_called()
        run_walk_forward_mock.assert_not_called()

    def test_stage_futu_fails_when_no_orders_are_stageable(self):
        from tradingagents.web.storage import get_workflow_store

        store = get_workflow_store()
        strategy = store.create_strategy_plan(
            {
                "batch_id": "batch-stage-empty",
                "mode": "breakout",
                "horizon": "intraday",
                "portfolio_size": 100_000.0,
                "risk_per_trade": 0.01,
                "allow_shorts": False,
            },
            home_market="US",
        )
        store.update_strategy_plan(
            strategy["strategy_id"],
            result={
                "trades": [{"symbol": "TSLA", "side": "sell", "direction": "short", "quantity": 5, "entry_price": 100.0}],
                "exposure": {},
                "risk": {},
            },
        )

        with patch("tradingagents.integrations.futu.opend.FutuStageOnlyAdapter.stage_orders") as stage_orders:
            resp = self.client.post(
                "/api/broker/futu/stage",
                json={"strategy_id": strategy["strategy_id"]},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["response"]["headline"], "No orders available to stage")
        stage_orders.assert_not_called()

    def test_batch_status_marks_partial_failure(self):
        run_counter = {"value": 0}

        def fake_create_run(**kwargs):
            run_counter["value"] += 1
            return SimpleNamespace(run_id=f"run-{run_counter['value']}")

        def fake_run_sync(run_id, config=None):
            if run_id == "run-1":
                return SimpleNamespace(
                    status="completed",
                    final_order_intent={"rating": "BUY", "reason": "Strong trend"},
                    report_sections={"final_trade_decision": "BUY AAPL"},
                    errors=[],
                    report_paths={"report.md": "/tmp/report-aapl.md"},
                )
            raise RuntimeError("analysis failed")

        with patch("tradingagents.web.workflow_service.runner.create_run", side_effect=fake_create_run), patch(
            "tradingagents.web.workflow_service.runner.run_sync",
            side_effect=fake_run_sync,
        ), patch("tradingagents.web.workflow_service._thread_cls", new=_FakeSyncThread):
            resp = self.client.post(
                "/api/batches",
                json={
                    "symbols": ["AAPL", "MSFT"],
                    "analysis_date": "2026-04-23",
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "partial_failure")
        self.assertEqual(body["summary"]["counts"]["completed"], 1)
        self.assertEqual(body["summary"]["counts"]["failed"], 1)

    def test_settings_watchlists_presets_and_session_market_persist(self):
        initial_settings = self.client.get("/api/settings")
        self.assertEqual(initial_settings.status_code, 200)
        self.assertEqual(initial_settings.json()["home_market"], "US")

        updated = self.client.put(
            "/api/settings",
            json={"values": {"home_market": "JP", "broker": {"futu": {"enabled": True}}}},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json()["home_market"], "JP")

        self.assertEqual(self.client.get("/api/watchlists").json()["watchlists"], [])
        created_watchlist = self.client.post("/api/watchlists", json={"name": "Test", "symbols": ["msft", " NVDA "]})
        self.assertEqual(created_watchlist.status_code, 200)
        watchlists = self.client.get("/api/watchlists").json()["watchlists"]
        self.assertEqual(watchlists[0]["symbols"], ["MSFT", "NVDA"])

        created_preset = self.client.post(
            "/api/strategy-presets",
            json={"name": "Breakout", "portfolio_size": 250000, "risk_per_trade": 0.02},
        )
        self.assertEqual(created_preset.status_code, 200)
        presets = self.client.get("/api/strategy-presets").json()["presets"]
        self.assertEqual(presets[0]["name"], "Breakout")

        def fake_quant(symbol, trade_date, bars_15m, bars_4h, config=None):
            return self._quant_contract(symbol, 0.9, "buy", "JP leader")

        with patch("tradingagents.web.workflow_service.get_market_overview", return_value=_screening_regime("JP")), patch(
            "tradingagents.web.workflow_service.get_intraday_bars",
            return_value=_make_intraday_bars(),
        ), patch("tradingagents.quant.engine.run_quant_engine", side_effect=fake_quant):
            screening = self.client.post(
                "/api/screening/runs",
                json={"universe": "Nikkei 225", "strategy": "auto", "trade_date": "2026-04-23", "top_n": 5, "min_score": 0.6},
            ).json()

        session_id = screening["workflow_session_id"]
        self.client.put("/api/settings", json={"values": {"home_market": "US"}})

        basket = self.client.post(
            "/api/baskets",
            json={
                "name": "Carry Over",
                "symbols": ["7203.T", "9984.T"],
                "workflow_session_id": session_id,
                "source_screening_run_id": screening["run_id"],
            },
        ).json()

        session_detail = self.client.get(f"/api/workflow-sessions/{session_id}")
        self.assertEqual(session_detail.status_code, 200)
        self.assertEqual(session_detail.json()["session"]["home_market"], "JP")
        self.assertEqual(session_detail.json()["session"]["settings_snapshot"]["home_market"], "JP")

        history = self.client.get("/api/history", params={"group_by": "workflow_session", "market": "JP"})
        self.assertEqual(history.status_code, 200)
        jp_group = next(group for group in history.json()["groups"] if group["workflow_session_id"] == session_id)
        ids = {item["id"] for item in jp_group["items"]}
        self.assertIn(screening["run_id"], ids)
        self.assertIn(basket["basket_id"], ids)

    def test_history_tolerates_legacy_runs_with_missing_optional_fields(self):
        legacy_runs = [
            SimpleNamespace(
                run_id="legacy-minimal-1",
                ticker="IBM",
                created_at="2026-04-19T12:00:00+00:00",
            ),
            SimpleNamespace(
                run_id="legacy-minimal-2",
                ticker="ORCL",
                status="completed",
                created_at="2026-04-20T12:00:00+00:00",
                completed_at=None,
            ),
        ]

        with patch("tradingagents.web.runner.list_runs", return_value=legacy_runs):
            resp = self.client.get("/api/history")

        self.assertEqual(resp.status_code, 200)
        items = [item for item in resp.json()["items"] if item["id"] in {"legacy-minimal-1", "legacy-minimal-2"}]
        self.assertEqual(len(items), 2)
        by_id = {item["id"]: item for item in items}
        self.assertEqual(by_id["legacy-minimal-1"]["status"], "completed")
        self.assertEqual(by_id["legacy-minimal-1"]["completed_at"], "2026-04-19T12:00:00+00:00")

    def test_history_item_type_filter_is_case_insensitive(self):
        legacy_runs = [
            SimpleNamespace(
                run_id="legacy-upper",
                ticker="AAPL",
                status="completed",
                created_at="2026-04-21T12:00:00+00:00",
                completed_at="2026-04-21T12:10:00+00:00",
            )
        ]

        with patch("tradingagents.web.runner.list_runs", return_value=legacy_runs):
            resp = self.client.get("/api/history", params={"item_type": "LEGACY_ANALYSIS"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)
        self.assertEqual(resp.json()["items"][0]["id"], "legacy-upper")


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
            row = conn.execute("SELECT version FROM schema_version WHERE singleton_id = 1").fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["version"], 2)


if __name__ == "__main__":
    unittest.main()
