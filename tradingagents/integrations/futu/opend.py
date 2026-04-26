"""Stage-only Futu OpenD adapter.

The adapter never submits live orders. It only validates connectivity and
returns deterministic staged payloads for downstream review.
"""

from __future__ import annotations

import socket
from typing import Any, Dict, List


class FutuStageOnlyAdapter:
    def __init__(self, *, host: str, port: int, enabled: bool):
        self.host = host
        self.port = port
        self.enabled = enabled

    def ping(self) -> str:
        if not self.enabled:
            return f"Futu disabled. Enable broker.futu.enabled in Settings."
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                return f"Connected to Futu OpenD at {self.host}:{self.port}"
        except OSError as exc:
            raise RuntimeError(f"Cannot reach Futu OpenD at {self.host}:{self.port}: {exc}") from exc

    def stage_orders(self, stage_id: str, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "status": "failed",
                "headline": "Futu staging is disabled",
                "error": "Enable broker.futu.enabled in Settings before staging orders.",
                "stage_only": True,
                "submits_orders": False,
                "orders": [],
            }
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                pass
        except OSError as exc:
            return {
                "status": "failed",
                "headline": "Futu OpenD is unreachable",
                "error": f"Could not connect to {self.host}:{self.port} ({exc})",
                "stage_only": True,
                "submits_orders": False,
                "orders": [],
            }

        staged_orders = []
        for index, order in enumerate(orders, start=1):
            staged_orders.append(
                {
                    **order,
                    "broker_ref": f"{stage_id}-order-{index}",
                    "staged": True,
                    "submitted": False,
                }
            )
        return {
            "status": "staged",
            "headline": f"{len(staged_orders)} orders staged for review",
            "stage_only": True,
            "submits_orders": False,
            "orders": staged_orders,
        }
