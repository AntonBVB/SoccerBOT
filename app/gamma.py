from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

LEAGUE_KEYWORDS = {
    "EPL": ["premier league", "epl", "english premier league"],
    "Bundesliga": ["bundesliga"],
    "La Liga": ["la liga", "laliga", "primera", "spanish la liga"],
    "Serie A": ["serie a", "seria a", "italy serie a"],
    "Ligue 1": ["ligue 1", "french ligue 1"],
    "UCL": ["champions league", "uefa champions league", "ucl"],
    "UEL": ["europa league", "uefa europa league", "uel"],
    "Eredivisie": ["eredivisie"],
    "Primeira Liga": ["primeira liga", "portuguese primeira liga"],
}


@dataclass
class LeagueTag:
    league: str
    tag_id: str | None


class GammaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    @retry(
        wait=wait_exponential(min=1, max=16),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        with httpx.Client(timeout=20) as client:
            resp = client.get(f"{self.base_url}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    def resolve_tags(self) -> list[LeagueTag]:
        tags = []
        for endpoint in ("/tags", "/sports"):
            try:
                data = self.get_json(endpoint)
                if isinstance(data, list):
                    tags.extend(data)
            except Exception as exc:
                logger.warning("Failed loading %s: %s", endpoint, exc)
        resolved: list[LeagueTag] = []
        for league, keywords in LEAGUE_KEYWORDS.items():
            tag_id = self._best_tag(tags, keywords)
            resolved.append(LeagueTag(league, tag_id))
        return resolved

    @staticmethod
    def _best_tag(tags: list[dict[str, Any]], keywords: list[str]) -> str | None:
        for tag in tags:
            hay = f"{tag.get('name', '')} {tag.get('slug', '')}".lower()
            if any(k in hay for k in keywords):
                tag_id = tag.get("id") or tag.get("tagId") or tag.get("slug")
                if tag_id is not None:
                    return str(tag_id)
        return None

    def iter_events(self, tag_id: str):
        offset = 0
        limit = 100
        while True:
            data = self.get_json("/events", params={"active": "true", "closed": "false", "tag_id": tag_id, "limit": limit, "offset": offset})
            if not isinstance(data, list) or not data:
                return
            for item in data:
                yield item
            if len(data) < limit:
                return
            offset += limit


def parse_start_time(event: dict[str, Any]) -> datetime | None:
    raw = event.get("startDate") or event.get("start_time") or event.get("startTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
