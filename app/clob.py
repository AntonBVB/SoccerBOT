from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

try:
    from py_clob_client.client import ClobClient
except Exception:  # package/import compatibility guard
    ClobClient = None


@dataclass
class OrderBookTop:
    best_bid_yes: float
    best_ask_yes: float


class CLOBGateway:
    def __init__(self, host: str, private_key: str, dry_run: bool):
        self.host = host
        self.private_key = private_key
        self.dry_run = dry_run
        self.client = None
        if ClobClient and private_key:
            try:
                self.client = ClobClient(host=host, key=private_key)
            except Exception as exc:
                logger.error("CLOB init failed: %s", exc)

    def available_usdc(self) -> float:
        if self.dry_run or not self.client:
            return 1_000.0
        try:
            balance = self.client.get_balance_allowance()
            return float(balance.get("available", 0.0))
        except Exception as exc:
            logger.error("Balance fetch failed: %s", exc)
            return 0.0

    def get_orderbook_top(self, token_id: str) -> OrderBookTop | None:
        if not self.client:
            return None
        try:
            ob = self.client.get_order_book(token_id)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            if not bids or not asks:
                return None
            return OrderBookTop(float(bids[0]["price"]), float(asks[0]["price"]))
        except Exception as exc:
            logger.warning("Orderbook unavailable token=%s: %s", token_id, exc)
            return None

    def place_limit(self, token_id: str, side: str, price: float, size: float, neg_risk: bool) -> str | None:
        if self.dry_run:
            return f"dry-{token_id}-{side}-{price}-{size}"
        if not self.client:
            return None
        try:
            order = self.client.create_order(token_id=token_id, side=side, price=price, size=size, neg_risk=neg_risk)
            posted = self.client.post_order(order)
            return str(posted.get("orderID") or posted.get("id"))
        except Exception as exc:
            logger.error("Order rejected: %s", exc)
            return None

    def cancel(self, order_id: str) -> bool:
        if self.dry_run:
            return True
        if not self.client:
            return False
        try:
            self.client.cancel(order_id)
            return True
        except Exception:
            return False

    def get_fills(self, order_id: str) -> list[dict[str, Any]]:
        if self.dry_run or not self.client:
            return []
        try:
            return self.client.get_fills(order_id=order_id)
        except Exception:
            return []

    def open_orders(self) -> list[dict[str, Any]]:
        if self.dry_run or not self.client:
            return []
        try:
            return self.client.get_orders(status="OPEN")
        except Exception:
            return []
