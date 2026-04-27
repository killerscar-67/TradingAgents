import unittest

from tradingagents.quant.execution import (
    BrokerAdapter,
    OrderManager,
    OrderStatus,
    PaperBrokerAdapter,
    PortfolioState,
)
from tradingagents.default_config import DEFAULT_CONFIG


def _order_intent(quantity=10.0, blocked=False, risk_allowed=True):
    return {
        "symbol": "AAPL",
        "trade_date": "2026-04-21",
        "rating": "BUY",
        "blocked": blocked,
        "reason": "test",
        "annotations": {
            "risk": {
                "applied": True,
                "size_contract": {
                    "symbol": "AAPL",
                    "direction": "long",
                    "quantity": quantity,
                    "entry_price": 100.0,
                    "notional": quantity * 100.0,
                    "stop_price": 98.0,
                    "risk_amount": quantity * 2.0,
                    "method": "fixed_fractional",
                },
                "gate": {
                    "allowed": risk_allowed,
                    "reason": "" if risk_allowed else "daily loss cap reached",
                    "kill_switch": not risk_allowed,
                },
            }
        },
    }


def _snapshot(volume=100_000.0, expected_slippage_pct=0.001):
    return {
        "symbol": "AAPL",
        "timestamp": "2026-04-21T14:30:00Z",
        "volume": volume,
        "expected_slippage_pct": expected_slippage_pct,
    }


class PaperExecutionTests(unittest.TestCase):
    def test_paper_adapter_implements_broker_adapter_contract(self):
        self.assertIsInstance(PaperBrokerAdapter(), BrokerAdapter)

    def test_default_config_exposes_execution_guard_thresholds(self):
        self.assertIn("max_order_volume_pct", DEFAULT_CONFIG)
        self.assertIn("max_slippage_pct", DEFAULT_CONFIG)

    def test_order_manager_defaults_to_default_config_thresholds(self):
        manager = OrderManager(PaperBrokerAdapter())

        self.assertEqual(
            manager.config["max_order_volume_pct"],
            DEFAULT_CONFIG["max_order_volume_pct"],
        )
        self.assertEqual(
            manager.config["max_slippage_pct"],
            DEFAULT_CONFIG["max_slippage_pct"],
        )

    def test_paper_adapter_fills_at_next_bar_open_with_slippage_once(self):
        broker = PaperBrokerAdapter(slippage_pct=0.001)
        manager = OrderManager(broker)
        order = manager.submit_order_intent(
            _order_intent(quantity=10.0),
            _snapshot(),
            submitted_at="2026-04-21T14:30:00Z",
        )

        fill = manager.process_next_bar(
            order.order_id,
            {"Open": 101.0, "Volume": 50_000.0},
            timestamp="2026-04-21T14:45:00Z",
        )
        duplicate = manager.process_next_bar(
            order.order_id,
            {"Open": 102.0, "Volume": 50_000.0},
            timestamp="2026-04-21T15:00:00Z",
        )

        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        self.assertEqual(fill.order_id, order.order_id)
        self.assertAlmostEqual(fill.price, 101.101)
        self.assertEqual(fill, duplicate)
        self.assertEqual(len(broker.fills), 1)
        self.assertEqual(broker.get_order(order.order_id).status, OrderStatus.FILLED)

    def test_submit_and_cancel_are_idempotent(self):
        broker = PaperBrokerAdapter()
        manager = OrderManager(broker)

        first = manager.submit_order_intent(
            _order_intent(quantity=5.0),
            _snapshot(),
            submitted_at="2026-04-21T14:30:00Z",
            idempotency_key="same-order",
        )
        second = manager.submit_order_intent(
            _order_intent(quantity=5.0),
            _snapshot(),
            submitted_at="2026-04-21T14:31:00Z",
            idempotency_key="same-order",
        )
        cancelled = broker.cancel_order(first.order_id, reason="user cancel")
        duplicate_cancel = broker.cancel_order(first.order_id, reason="late cancel")

        self.assertEqual(first, second)
        self.assertEqual(cancelled, duplicate_cancel)
        self.assertEqual(cancelled.status, OrderStatus.CANCELLED)
        self.assertEqual(len(broker.orders), 1)

    def test_blocked_intent_with_previous_idempotency_key_still_rejects(self):
        broker = PaperBrokerAdapter()
        manager = OrderManager(broker)

        submitted = manager.submit_order_intent(
            _order_intent(quantity=5.0),
            _snapshot(),
            idempotency_key="same-business-key",
        )
        blocked = manager.submit_order_intent(
            _order_intent(quantity=5.0, blocked=True),
            _snapshot(),
            idempotency_key="same-business-key",
        )

        self.assertEqual(submitted.status, OrderStatus.SUBMITTED)
        self.assertEqual(blocked.status, OrderStatus.REJECTED)
        self.assertIn("intent blocked", blocked.reason)
        self.assertNotEqual(submitted.order_id, blocked.order_id)
        self.assertEqual(broker.get_order(submitted.order_id).status, OrderStatus.SUBMITTED)

    def test_order_manager_rejects_pre_trade_guards_in_priority_order(self):
        manager = OrderManager(
            PaperBrokerAdapter(),
            config={"max_slippage_pct": 0.002, "max_order_volume_pct": 0.01},
        )

        blocked = manager.submit_order_intent(_order_intent(blocked=True), _snapshot())
        risk_blocked = manager.submit_order_intent(_order_intent(risk_allowed=False), _snapshot())
        illiquid = manager.submit_order_intent(_order_intent(quantity=20.0), _snapshot(volume=1_000.0))
        slippage = manager.submit_order_intent(
            _order_intent(quantity=5.0),
            _snapshot(expected_slippage_pct=0.01),
        )

        self.assertEqual(blocked.status, OrderStatus.REJECTED)
        self.assertIn("intent blocked", blocked.reason)
        self.assertEqual(risk_blocked.status, OrderStatus.REJECTED)
        self.assertIn("daily loss cap", risk_blocked.reason)
        self.assertEqual(illiquid.status, OrderStatus.REJECTED)
        self.assertIn("liquidity guard", illiquid.reason)
        self.assertEqual(slippage.status, OrderStatus.REJECTED)
        self.assertIn("slippage guard", slippage.reason)

    def test_zero_quantity_is_rejected_by_liquidity_guard(self):
        manager = OrderManager(PaperBrokerAdapter())

        rejected = manager.submit_order_intent(_order_intent(quantity=0.0), _snapshot())

        self.assertEqual(rejected.status, OrderStatus.REJECTED)
        self.assertIn("liquidity guard: non-positive quantity", rejected.reason)

    def test_portfolio_state_reconciles_cash_positions_and_fills(self):
        portfolio = PortfolioState(cash=10_000.0)
        broker = PaperBrokerAdapter(slippage_pct=0.0)
        order = broker.submit_order(
            symbol="AAPL",
            side="buy",
            quantity=10.0,
            submitted_at="2026-04-21T14:30:00Z",
        )
        fill = broker.process_next_bar(
            order.order_id,
            {"Open": 100.0, "Volume": 50_000.0},
            timestamp="2026-04-21T14:45:00Z",
        )

        updated = portfolio.apply_fill(fill)
        duplicate = updated.apply_fill(fill)

        self.assertAlmostEqual(updated.cash, 9_000.0)
        self.assertAlmostEqual(updated.positions["AAPL"].quantity, 10.0)
        self.assertAlmostEqual(updated.positions["AAPL"].avg_price, 100.0)
        self.assertEqual(updated, duplicate)
        self.assertEqual(len(updated.fills), 1)


if __name__ == "__main__":
    unittest.main()
