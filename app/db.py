from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


class Database:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leagues_tags (
                    league_name TEXT PRIMARY KEY,
                    tag_id TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    league_name TEXT,
                    start_time TEXT,
                    status TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS markets (
                    market_id TEXT PRIMARY KEY,
                    event_id TEXT,
                    question TEXT,
                    slug TEXT,
                    total_volume REAL,
                    enable_orderbook INTEGER,
                    neg_risk INTEGER,
                    tick_size REAL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS outcomes (
                    market_id TEXT,
                    outcome_index INTEGER,
                    outcome_name TEXT,
                    is_draw INTEGER,
                    token_id TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (market_id, outcome_index)
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    market_id TEXT,
                    token_id TEXT,
                    outcome_name TEXT,
                    best_bid_yes REAL,
                    best_ask_yes REAL,
                    best_ask_no REAL,
                    spread REAL,
                    eligible_at TEXT,
                    PRIMARY KEY (market_id, token_id)
                );
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    market_id TEXT,
                    token_id TEXT,
                    kind TEXT,
                    side TEXT,
                    price REAL,
                    size REAL,
                    status TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS fills (
                    fill_id TEXT PRIMARY KEY,
                    order_id TEXT,
                    price_yes REAL,
                    size REAL,
                    ts TEXT
                );
                CREATE TABLE IF NOT EXISTS positions (
                    position_id TEXT PRIMARY KEY,
                    market_id TEXT,
                    token_id TEXT,
                    outcome_name TEXT,
                    shares REAL,
                    vwap_buy_no REAL,
                    live_detected_at TEXT,
                    tp_order_id TEXT,
                    status TEXT,
                    opened_at TEXT,
                    closed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS system_log (
                    ts TEXT,
                    level TEXT,
                    code TEXT,
                    message TEXT,
                    market_id TEXT
                );
                """
            )

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> None:
        with self.connect() as conn:
            conn.executemany(sql, params)

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()
