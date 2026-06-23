from __future__ import annotations

from urllib.parse import urlparse

from playwright.async_api import Page

from ..browser import safe_goto, text_from_selectors
from ..models import Job
from .base import BaseScraper


class GenericScraper(BaseScraper):
    """Fallback scraper for arbitrary job board URLs in config."""

    source_name = "Other"

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        await safe_goto(page, search_url)
        host = urlparse(search_url).netloc.replace("www.", "")
        jobs: list[Job] = []
        seen: set[str] = set()
        max_jobs = self._max_jobs()

        links = page.locator("a[href*='job'], a[href*='career'], a[href*='position']")
        count = await links.count()
        for i in range(count):
            if len(jobs) >= max_jobs:
                break
            link = links.nth(i)
            try:
                href = await link.get_attribute("href") or ""
                if not href.startswith("http"):
                    continue
                if href in seen:
                    continue
                text = (await link.inner_text()).strip()
                if len(text) < 8 or len(text) > 120:
                    continue
                seen.add(href)
                jobs.append(
                    Job(
                        source=host,
                        company=host,
                        role=text,
                        source_url=href,
                        search_label=label,
                        notes=f"Generic scrape from {host}; label={label}",
                    )
                )
            except Exception:
                continue
        return jobs

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        await safe_goto(page, job.source_url)
        desc = await text_from_selectors(page, ["main", "article", "body"])
        if desc:
            blob = desc.lower()
            for kw in ["sql", "python", "spark", "data engineer", "data analyst"]:
                if kw in blob:
                    job.skills.append(kw)
        return job