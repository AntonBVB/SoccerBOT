from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from app.clob import CLOBGateway
from app.config import load_settings
from app.db import Database
from app.gamma import GammaClient
from app.logging_utils import setup_logging
from app.strategy import StrategyEngine
from app.telegram import TelegramNotifier


logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()
    settings = load_settings()
    setup_logging(settings.log_level)

    db = Database(settings.sqlite_path)
    gamma = GammaClient(settings.gamma_base_url)
    clob = CLOBGateway("https://clob.polymarket.com", settings.private_key, settings.dry_run)
    telegram = TelegramNotifier(settings)
    engine = StrategyEngine(settings, db, gamma, clob, telegram)

    scheduler = BlockingScheduler(timezone="UTC")

    def safe_run(name: str, fn):
        def _inner():
            try:
                logger.info("Run task: %s at %s", name, datetime.utcnow().isoformat())
                fn()
            except Exception as exc:
                engine.log_system("CRITICAL", "TASK_CRASH", f"Task {name} crashed: {exc}", critical_alert=True)

        return _inner

    scheduler.add_job(safe_run("refresh_tags", engine.refresh_tags), "interval", hours=24, next_run_time=datetime.utcnow())
    scheduler.add_job(safe_run("discovery", engine.discovery), "interval", seconds=settings.discovery_seconds, next_run_time=datetime.utcnow())
    scheduler.add_job(safe_run("prematch", engine.prematch_scan), "interval", seconds=settings.prematch_poll_seconds, next_run_time=datetime.utcnow())
    scheduler.add_job(safe_run("fast_live_tp", engine.handle_live_and_tp), "interval", seconds=settings.fast_poll_seconds, next_run_time=datetime.utcnow())
    scheduler.add_job(safe_run("reconcile", engine.reconcile), "interval", seconds=settings.reconcile_seconds, next_run_time=datetime.utcnow())

    hh, mm = settings.daily_report_time_msk.split(":")
    scheduler.add_job(safe_run("daily_report", engine.daily_report), CronTrigger(hour=int(hh) - 3, minute=int(mm)))

    def _shutdown(signum, frame):
        logger.info("Signal %s received, shutting down", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Bot started")
    scheduler.start()


if __name__ == "__main__":
    main()
