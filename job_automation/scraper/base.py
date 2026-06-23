from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from playwright.async_api import Page

from ..models import Job


class BaseScraper(ABC):
    source_name: str = "Generic"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.scraper_cfg = config.get("scraper", {})

    @abstractmethod
    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        raise NotImplementedError

    async def enrich_job(self, page: Page, job: Job) -> Job:
        if not self.scraper_cfg.get("enrich_details", True):
            return job
        return await self._enrich_job(page, job)

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        return job

    def _max_jobs(self) -> int:
        return int(self.scraper_cfg.get("max_jobs_per_search", 30))