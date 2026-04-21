"""Deterministic paper execution and portfolio reconciliation (Phase 4)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Literal, Optional, Protocol, Tuple, runtime_checkable

from tradingagents.default_config import DEFAULT_CONFIG


class OrderStatus(str, Enum):
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


OrderSide = Literal["buy", "sell"]


@runtime_checkable
class BrokerAdapter(Protocol):
    """Minimal broker interface required by the order manager."""

    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        submitted_at: str = "",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionOrder":
        ...

    def reject_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        reason: str,
        submitted_at: str = "",
        idempotency_key: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionOrder":
        ...

    def cancel_order(self, order_id: str, reason: str = "cancelled") -> "ExecutionOrder":
        ...

    def process_next_bar(
        self,
        order_id: str,
        next_bar: Dict[str, Any],
        timestamp: str = "",
    ) -> "FillContract":
        ...


@dataclass(frozen=True)
class ExecutionOrder:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    status: OrderStatus
    submitted_at: str = ""
    filled_quantity: float = 0.0
    avg_fill_price: Optional[float] = None
    reason: str = ""
    idempotency_key: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "status": self.status.value,
            "submitted_at": self.submitted_at,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FillContract:
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    timestamp: str
    slippage_pct: float
    commission: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "timestamp": self.timestamp,
            "slippage_pct": self.slippage_pct,
            "commission": self.commission,
        }


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_price": self.avg_price,
        }


@dataclass(frozen=True)
class PortfolioState:
    cash: float
    positions: Dict[str, PortfolioPosition] = field(default_factory=dict)
    fills: Tuple[FillContract, ...] = ()

    def apply_fill(self, fill: FillContract) -> "PortfolioState":
        if any(existing.fill_id == fill.fill_id for existing in self.fills):
            return self

        signed_quantity = fill.quantity if fill.side == "buy" else -fill.quantity
        cash_delta = -(fill.quantity * fill.price) if fill.side == "buy" else fill.quantity * fill.price
        cash_delta -= fill.commission

        current = self.positions.get(fill.symbol, PortfolioPosition(symbol=fill.symbol))
        new_quantity = current.quantity + signed_quantity
        if new_quantity == 0:
            new_position = PortfolioPosition(symbol=fill.symbol, quantity=0.0, avg_price=0.0)
        elif current.quantity == 0 or (current.quantity > 0) != (new_quantity > 0):
            new_position = PortfolioPosition(
                symbol=fill.symbol,
                quantity=round(new_quantity, 8),
                avg_price=fill.price,
            )
        elif fill.side == "buy":
            total_cost = current.avg_price * current.quantity + fill.price * fill.quantity
            new_position = PortfolioPosition(
                symbol=fill.symbol,
                quantity=round(new_quantity, 8),
                avg_price=round(total_cost / new_quantity, 8),
            )
        else:
            new_position = PortfolioPosition(
                symbol=fill.symbol,
                quantity=round(new_quantity, 8),
                avg_price=current.avg_price,
            )

        positions = dict(self.positions)
        positions[fill.symbol] = new_position
        return PortfolioState(
            cash=round(self.cash + cash_delta, 8),
            positions=positions,
            fills=self.fills + (fill,),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cash": self.cash,
            "positions": {
                symbol: position.to_dict()
                for symbol, position in self.positions.items()
            },
            "fills": [fill.to_dict() for fill in self.fills],
        }


class PaperBrokerAdapter:
    """In-memory paper broker that fills market orders at the next bar open."""

    def __init__(self, slippage_pct: float = 0.0, commission_per_order: float = 0.0):
        self.slippage_pct = float(slippage_pct)
        self.commission_per_order = float(commission_per_order)
        self.orders: Dict[str, ExecutionOrder] = {}
        self.fills: Dict[str, FillContract] = {}
        self._idempotency_index: Dict[str, str] = {}
        self._sequence = 0

    def _next_order_id(self, idempotency_key: str = "") -> str:
        if idempotency_key:
            digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:12]
            return f"order-{digest}"
        self._sequence += 1
        return f"order-{self._sequence:06d}"

    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        submitted_at: str = "",
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionOrder:
        key = idempotency_key or ""
        if key and key in self._idempotency_index:
            return self.orders[self._idempotency_index[key]]
        if quantity <= 0:
            return self.reject_order(symbol, side, quantity, "quantity must be positive", submitted_at, key, metadata)

        order_id = self._next_order_id(key)
        order = ExecutionOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=round(float(quantity), 8),
            status=OrderStatus.SUBMITTED,
            submitted_at=submitted_at,
            idempotency_key=key,
            metadata=dict(metadata or {}),
        )
        self.orders[order_id] = order
        if key:
            self._idempotency_index[key] = order_id
        return order

    def reject_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        reason: str,
        submitted_at: str = "",
        idempotency_key: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionOrder:
        order_id = self._next_order_id()
        order = ExecutionOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=round(float(quantity), 8),
            status=OrderStatus.REJECTED,
            submitted_at=submitted_at,
            reason=reason,
            idempotency_key=idempotency_key,
            metadata=dict(metadata or {}),
        )
        self.orders[order_id] = order
        if idempotency_key:
            self._idempotency_index[idempotency_key] = order_id
        return order

    def get_order(self, order_id: str) -> ExecutionOrder:
        return self.orders[order_id]

    def cancel_order(self, order_id: str, reason: str = "cancelled") -> ExecutionOrder:
        order = self.orders[order_id]
        if order.status in {OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.REJECTED}:
            return order
        cancelled = replace(order, status=OrderStatus.CANCELLED, reason=reason)
        self.orders[order_id] = cancelled
        return cancelled

    def process_next_bar(
        self,
        order_id: str,
        next_bar: Dict[str, Any],
        timestamp: str = "",
    ) -> FillContract:
        existing_fill = self.fills.get(order_id)
        if existing_fill is not None:
            return existing_fill

        order = self.orders[order_id]
        if order.status != OrderStatus.SUBMITTED:
            raise ValueError(f"order {order_id} is not submitted")

        open_price = float(next_bar.get("Open", next_bar.get("open")))
        if open_price <= 0:
            raise ValueError("next bar open must be positive")

        signed_slippage = self.slippage_pct if order.side == "buy" else -self.slippage_pct
        fill_price = round(open_price * (1.0 + signed_slippage), 8)
        fill = FillContract(
            fill_id=f"fill-{order_id}",
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            timestamp=timestamp,
            slippage_pct=self.slippage_pct,
            commission=self.commission_per_order,
        )
        self.fills[order_id] = fill
        self.orders[order_id] = replace(
            order,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            avg_fill_price=fill_price,
        )
        return fill


class OrderManager:
    """Converts risk-gated order intents into paper broker orders."""

    def __init__(self, broker: BrokerAdapter, config: Optional[Dict[str, Any]] = None):
        self.broker = broker
        self.config = {**DEFAULT_CONFIG, **(config or {})}

    def submit_order_intent(
        self,
        order_intent: Dict[str, Any],
        market_snapshot: Dict[str, Any],
        submitted_at: str = "",
        idempotency_key: Optional[str] = None,
    ) -> ExecutionOrder:
        symbol = str(order_intent.get("symbol") or market_snapshot.get("symbol") or "")
        risk = order_intent.get("annotations", {}).get("risk", {})
        size_contract = risk.get("size_contract", {})
        direction = str(size_contract.get("direction", "long")).lower()
        side: OrderSide = "buy" if direction == "long" else "sell"
        quantity = float(size_contract.get("quantity", 0.0))
        metadata = {"order_intent": order_intent, "market_snapshot": market_snapshot}

        if order_intent.get("blocked"):
            return self.broker.reject_order(
                symbol, side, quantity, f"intent blocked: {order_intent.get('reason', '')}", submitted_at, idempotency_key or "", metadata
            )

        gate = risk.get("gate", {})
        if gate and not bool(gate.get("allowed", False)):
            return self.broker.reject_order(
                symbol, side, quantity, str(gate.get("reason", "risk gate blocked")), submitted_at, idempotency_key or "", metadata
            )

        volume = float(market_snapshot.get("volume", 0.0))
        max_order_volume_pct = float(self.config.get("max_order_volume_pct", 0.01))
        if quantity <= 0:
            return self.broker.reject_order(
                symbol,
                side,
                quantity,
                "liquidity guard: non-positive quantity",
                submitted_at,
                idempotency_key or "",
                metadata,
            )
        if volume <= 0 or quantity > volume * max_order_volume_pct:
            return self.broker.reject_order(
                symbol,
                side,
                quantity,
                f"liquidity guard: quantity={quantity:.8f} exceeds {max_order_volume_pct:.4f} of volume={volume:.2f}",
                submitted_at,
                idempotency_key or "",
                metadata,
            )

        expected_slippage_pct = float(market_snapshot.get("expected_slippage_pct", 0.0))
        max_slippage_pct = float(self.config.get("max_slippage_pct", 0.005))
        if expected_slippage_pct > max_slippage_pct:
            return self.broker.reject_order(
                symbol,
                side,
                quantity,
                f"slippage guard: expected={expected_slippage_pct:.6f} > max={max_slippage_pct:.6f}",
                submitted_at,
                idempotency_key or "",
                metadata,
            )

        return self.broker.submit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            submitted_at=submitted_at,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    def process_next_bar(
        self,
        order_id: str,
        next_bar: Dict[str, Any],
        timestamp: str = "",
    ) -> FillContract:
        return self.broker.process_next_bar(order_id, next_bar, timestamp)
