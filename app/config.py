from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    private_key: str
    gamma_base_url: str
    entry_min: float
    entry_max: float
    take_profit_delta: float
    max_spread: float
    min_total_volume: float
    buy_cost_usd: float
    min_available_usdc: float
    open_window_hours: int
    fast_mode_before_start_minutes: int
    prematch_poll_seconds: int
    fast_poll_seconds: int
    discovery_seconds: int
    reconcile_seconds: int
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    daily_report_time_msk: str
    dry_run: bool
    log_level: str
    sqlite_path: Path


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings(
        private_key=os.getenv("PRIVATE_KEY", ""),
        gamma_base_url=os.getenv("GAMMA_BASE_URL", "https://gamma-api.polymarket.com"),
        entry_min=float(os.getenv("ENTRY_MIN", "0.73")),
        entry_max=float(os.getenv("ENTRY_MAX", "0.83")),
        take_profit_delta=float(os.getenv("TAKE_PROFIT_DELTA", "0.05")),
        max_spread=float(os.getenv("MAX_SPREAD", "0.03")),
        min_total_volume=float(os.getenv("MIN_TOTAL_VOLUME", "20000")),
        buy_cost_usd=float(os.getenv("BUY_COST_USD", "5")),
        min_available_usdc=float(os.getenv("MIN_AVAILABLE_USDC", "6")),
        open_window_hours=int(os.getenv("OPEN_WINDOW_HOURS", "4")),
        fast_mode_before_start_minutes=int(os.getenv("FAST_MODE_BEFORE_START_MINUTES", "3")),
        prematch_poll_seconds=int(os.getenv("PREMATCH_POLL_SECONDS", "60")),
        fast_poll_seconds=int(os.getenv("FAST_POLL_SECONDS", "15")),
        discovery_seconds=int(os.getenv("DISCOVERY_SECONDS", "3600")),
        reconcile_seconds=int(os.getenv("RECONCILE_SECONDS", "600")),
        telegram_enabled=_get_bool("TELEGRAM_ENABLED", True),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        daily_report_time_msk=os.getenv("DAILY_REPORT_TIME_MSK", "10:00"),
        dry_run=_get_bool("DRY_RUN", False),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        sqlite_path=Path(os.getenv("SQLITE_PATH", "data/bot_state.db")),
    )
