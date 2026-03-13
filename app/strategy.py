from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.clob import CLOBGateway
from app.config import Settings
from app.db import Database
from app.gamma import GammaClient, parse_start_time
from app.telegram import TelegramNotifier

logger = logging.getLogger(__name__)
DRAW_HINTS = ["draw", "tie", "нич", "x"]


class StrategyEngine:
    def __init__(self, settings: Settings, db: Database, gamma: GammaClient, clob: CLOBGateway, telegram: TelegramNotifier):
        self.settings = settings
        self.db = db
        self.gamma = gamma
        self.clob = clob
        self.telegram = telegram

    def log_system(self, level: str, code: str, message: str, market_id: str | None = None, critical_alert: bool = False) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute("INSERT INTO system_log(ts, level, code, message, market_id) VALUES (?, ?, ?, ?, ?)", (now, level, code, message, market_id))
        getattr(logger, level.lower(), logger.info)("%s | %s", code, message)
        if critical_alert:
            try:
                self.telegram.send(f"CRITICAL [{code}] {message}")
            except Exception as exc:
                logger.error("Telegram failed: %s", exc)

    def refresh_tags(self) -> None:
        for row in self.gamma.resolve_tags():
            if not row.tag_id:
                self.log_system("CRITICAL", "TAG_NOT_FOUND", f"Tag not found for {row.league}", critical_alert=True)
                continue
            self.db.execute(
                "INSERT INTO leagues_tags(league_name, tag_id, updated_at) VALUES (?, ?, ?) ON CONFLICT(league_name) DO UPDATE SET tag_id=excluded.tag_id, updated_at=excluded.updated_at",
                (row.league, row.tag_id, datetime.now(timezone.utc).isoformat()),
            )

    def discovery(self) -> None:
        tags = self.db.fetchall("SELECT league_name, tag_id FROM leagues_tags")
        for tag in tags:
            for event in self.gamma.iter_events(tag["tag_id"]):
                self._store_event_tree(tag["league_name"], event)

    def _store_event_tree(self, league_name: str, event: dict) -> None:
        event_id = str(event.get("id"))
        if not event_id:
            return
        start_dt = parse_start_time(event)
        self.db.execute(
            "INSERT INTO events(event_id, league_name, start_time, status, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_id) DO UPDATE SET league_name=excluded.league_name, start_time=excluded.start_time, status=excluded.status, updated_at=excluded.updated_at",
            (event_id, league_name, start_dt.isoformat() if start_dt else None, str(event.get("status", "")), datetime.now(timezone.utc).isoformat()),
        )
        for m in event.get("markets", []) or []:
            self._store_market(event_id, m)

    def _store_market(self, event_id: str, market: dict) -> None:
        market_id = str(market.get("id"))
        if not market_id:
            return
        outcomes = market.get("outcomes") or []
        if len(outcomes) != 3:
            return
        draw_idxs = [i for i, out in enumerate(outcomes) if self._is_draw(str(out.get("name", out)))]
        if len(draw_idxs) != 1:
            return
        draw_idx = draw_idxs[0]
        tokens = market.get("clobTokenIds") or market.get("tokenIds") or []
        if len(tokens) != 3:
            self.log_system("CRITICAL", "TOKEN_ID_MISSING", f"Market {market_id}: token ids unavailable", market_id, True)
            return
        enable_orderbook = market.get("enableOrderBook", True)
        if enable_orderbook is False:
            return
        tick_size = float(market.get("tickSize") or 0.01)
        neg_risk = bool(market.get("negRisk", market.get("neg_risk", False)))
        self.db.execute(
            "INSERT INTO markets(market_id, event_id, question, slug, total_volume, enable_orderbook, neg_risk, tick_size, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(market_id) DO UPDATE SET total_volume=excluded.total_volume, enable_orderbook=excluded.enable_orderbook, neg_risk=excluded.neg_risk, tick_size=excluded.tick_size, updated_at=excluded.updated_at",
            (market_id, event_id, market.get("question", ""), market.get("slug", ""), float(market.get("volume", market.get("totalVolume", 0)) or 0), int(bool(enable_orderbook)), int(neg_risk), tick_size, datetime.now(timezone.utc).isoformat()),
        )
        for i, out in enumerate(outcomes):
            self.db.execute(
                "INSERT INTO outcomes(market_id, outcome_index, outcome_name, is_draw, token_id, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(market_id, outcome_index) DO UPDATE SET outcome_name=excluded.outcome_name, is_draw=excluded.is_draw, token_id=excluded.token_id, updated_at=excluded.updated_at",
                (market_id, i, str(out.get("name", out)), int(i == draw_idx), str(tokens[i]), datetime.now(timezone.utc).isoformat()),
            )

    def _is_draw(self, name: str) -> bool:
        lname = name.lower().strip()
        return any(h in lname for h in DRAW_HINTS)

    def prematch_scan(self) -> None:
        usdc = self.clob.available_usdc()
        rows = self.db.fetchall(
            """
            SELECT m.market_id, m.total_volume, m.tick_size, m.neg_risk, e.start_time
            FROM markets m JOIN events e ON e.event_id = m.event_id
            WHERE m.enable_orderbook=1
            """
        )
        now = datetime.now(timezone.utc)
        for market in rows:
            start_time = datetime.fromisoformat(market["start_time"]) if market["start_time"] else None
            if not start_time or now < start_time - timedelta(hours=self.settings.open_window_hours):
                continue
            if float(market["total_volume"] or 0) <= self.settings.min_total_volume:
                continue
            if self._has_position_or_open_entry(market["market_id"]):
                continue
            team_outcomes = self.db.fetchall("SELECT outcome_name, token_id FROM outcomes WHERE market_id=? AND is_draw=0", (market["market_id"],))
            eligible = []
            for out in team_outcomes:
                book = self.clob.get_orderbook_top(out["token_id"])
                if not book:
                    continue
                best_ask_no = 1 - book.best_bid_yes
                spread_no = book.best_ask_yes - book.best_bid_yes
                if self.settings.entry_min <= best_ask_no <= self.settings.entry_max and spread_no <= self.settings.max_spread:
                    eligible.append((out, book, best_ask_no, spread_no))
            if len(eligible) != 1:
                continue
            if usdc < self.settings.min_available_usdc:
                self.log_system("CRITICAL", "INSUFFICIENT_BALANCE", f"USDC {usdc} < {self.settings.min_available_usdc}", market["market_id"], True)
                continue
            out, book, best_ask_no, _ = eligible[0]
            shares = self._round_down(self.settings.buy_cost_usd / best_ask_no, 0.01)
            if shares < 0.01:
                continue
            price = self._round_down(book.best_bid_yes, float(market["tick_size"] or 0.01))
            order_id = self.clob.place_limit(out["token_id"], "SELL", price, shares, bool(market["neg_risk"]))
            if not order_id:
                self.log_system("CRITICAL", "ENTRY_REJECTED", f"Entry rejected for market {market['market_id']}", market["market_id"], True)
                continue
            now_s = now.isoformat()
            self.db.execute(
                "INSERT INTO orders(order_id, market_id, token_id, kind, side, price, size, status, created_at, updated_at) VALUES (?, ?, ?, 'ENTRY', 'SELL', ?, ?, 'OPEN', ?, ?)",
                (order_id, market["market_id"], out["token_id"], price, shares, now_s, now_s),
            )

    def handle_live_and_tp(self) -> None:
        rows = self.db.fetchall(
            """
            SELECT o.order_id, o.market_id, o.token_id, out.outcome_name, e.start_time, m.tick_size, m.neg_risk
            FROM orders o
            JOIN events e ON e.event_id=(SELECT event_id FROM markets WHERE market_id=o.market_id)
            JOIN outcomes out ON out.market_id=o.market_id AND out.token_id=o.token_id
            JOIN markets m ON m.market_id=o.market_id
            WHERE o.kind='ENTRY' AND o.status='OPEN'
            """
        )
        now = datetime.now(timezone.utc)
        for row in rows:
            start = datetime.fromisoformat(row["start_time"]) if row["start_time"] else None
            if not start or now < start:
                continue
            self.clob.cancel(row["order_id"])
            fills = self.clob.get_fills(row["order_id"])
            filled = sum(float(f.get("size", 0)) for f in fills)
            if filled <= 0:
                self.db.execute("UPDATE orders SET status='CANCELED', updated_at=? WHERE order_id=?", (now.isoformat(), row["order_id"]))
                continue
            vwap_no = sum((1 - float(f.get("price", 0))) * float(f.get("size", 0)) for f in fills) / filled
            position_id = str(uuid4())
            live_at = now.isoformat()
            self.db.execute(
                "INSERT INTO positions(position_id, market_id, token_id, outcome_name, shares, vwap_buy_no, live_detected_at, tp_order_id, status, opened_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'OPEN', ?, NULL)",
                (position_id, row["market_id"], row["token_id"], row["outcome_name"], filled, vwap_no, live_at, live_at),
            )
            self.db.execute("UPDATE orders SET status='CANCELED', updated_at=? WHERE order_id=?", (now.isoformat(), row["order_id"]))

        positions = self.db.fetchall("SELECT * FROM positions WHERE status='OPEN' AND tp_order_id IS NULL")
        for p in positions:
            live_at = datetime.fromisoformat(p["live_detected_at"])
            if now < live_at + timedelta(seconds=15):
                continue
            target_no = p["vwap_buy_no"] + self.settings.take_profit_delta
            price_yes_buy = min(0.99, max(0.01, 1 - target_no))
            tick = self.db.fetchone("SELECT tick_size, neg_risk FROM markets WHERE market_id=?", (p["market_id"],))
            if not tick:
                self.log_system("CRITICAL", "TICK_MISSING", f"Tick missing for {p['market_id']}", p["market_id"], True)
                continue
            price_yes_buy = self._round_down(price_yes_buy, float(tick["tick_size"] or 0.01))
            size = self._round_down(float(p["shares"]), 0.01)
            order_id = self.clob.place_limit(p["token_id"], "BUY", price_yes_buy, size, bool(tick["neg_risk"]))
            if not order_id:
                self.log_system("CRITICAL", "TP_REJECTED", f"TP rejected for {p['market_id']}", p["market_id"], True)
                continue
            ts = now.isoformat()
            self.db.execute(
                "INSERT INTO orders(order_id, market_id, token_id, kind, side, price, size, status, created_at, updated_at) VALUES (?, ?, ?, 'TP', 'BUY', ?, ?, 'OPEN', ?, ?)",
                (order_id, p["market_id"], p["token_id"], price_yes_buy, size, ts, ts),
            )
            self.db.execute("UPDATE positions SET tp_order_id=? WHERE position_id=?", (order_id, p["position_id"]))

    def reconcile(self) -> None:
        clob_orders = {str(o.get('id') or o.get('orderID')): o for o in self.clob.open_orders()}
        for oid, order in clob_orders.items():
            db_order = self.db.fetchone("SELECT order_id FROM orders WHERE order_id=?", (oid,))
            if db_order:
                continue
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute(
                "INSERT INTO orders(order_id, market_id, token_id, kind, side, price, size, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)",
                (oid, str(order.get("market_id", "")), str(order.get("asset_id", "")), "UNKNOWN", str(order.get("side", "")), float(order.get("price", 0)), float(order.get("size", 0)), now, now),
            )
        db_open = self.db.fetchall("SELECT order_id FROM orders WHERE status='OPEN'")
        for row in db_open:
            if row["order_id"] not in clob_orders:
                self.db.execute("UPDATE orders SET status='CANCELED', updated_at=? WHERE order_id=?", (datetime.now(timezone.utc).isoformat(), row["order_id"]))

    @staticmethod
    def _round_down(value: float, step: float) -> float:
        if step <= 0:
            return value
        return (value // step) * step

    def daily_report(self) -> None:
        today = datetime.now(timezone.utc) - timedelta(days=1)
        fills_n = self.db.fetchone("SELECT COUNT(*) AS c FROM fills WHERE ts >= ?", (today.isoformat(),))["c"]
        open_pos = self.db.fetchone("SELECT COUNT(*) AS c FROM positions WHERE status='OPEN'")["c"]
        open_orders = self.db.fetchone("SELECT COUNT(*) AS c FROM orders WHERE status='OPEN'")["c"]
        errors = self.db.fetchone("SELECT COUNT(*) AS c FROM system_log WHERE level IN ('ERROR','CRITICAL') AND ts >= ?", (today.isoformat(),))["c"]
        msg = f"Daily report\nFills: {fills_n}\nOpen positions: {open_pos}\nOpen orders: {open_orders}\nErrors: {errors}"
        try:
            self.telegram.send(msg)
        except Exception as exc:
            logger.warning("Daily report send failed: %s", exc)
