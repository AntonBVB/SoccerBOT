from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, settings: Settings):
        self.enabled = settings.telegram_enabled and bool(settings.telegram_bot_token and settings.telegram_chat_id)
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    @retry(wait=wait_exponential(min=1, max=15), stop=stop_after_attempt(3), reraise=True)
    def send(self, text: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json={"chat_id": self.chat_id, "text": text})
            resp.raise_for_status()
        logger.info("Telegram alert sent")
