from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.async_api import Page

from ..browser import safe_goto
from ..models import Job
from .base import BaseScraper

HIRIST_BASE = "https://www.hirist.tech"

class HiristScraper(BaseScraper):
    source_name = "Hirist"

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        await safe_goto(page, search_url)
        jobs: list[Job] = []
        seen: set[str] = set()

        # Scroll multiple times to trigger infinite load until we hit our configured max_jobs
        max_jobs = self._max_jobs()
        for _ in range(8):
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(1500)
            
            # Fast-fail if we've loaded enough elements (rough check)
            paths = re.findall(r'href="(/j/[^"?]+)', await page.content())
            if len(set(paths)) >= max_jobs * 2:
                break

        html = await page.content()
        paths = re.findall(r'href="(/j/[^"?]+)', html)
        max_jobs = self._max_jobs()

        for path in paths:
            if len(jobs) >= max_jobs:
                break
            url = urljoin(HIRIST_BASE, path.split("&")[0])
            if url in seen:
                continue
            slug = path.split("/j/")[-1]
            title_part = slug.rsplit("-", 1)[0].replace("-", " ")
            seen.add(url)
            company = title_part.split()[0] if title_part else "Hirist"
            jobs.append(
                Job(
                    source=self.source_name,
                    company=company.title(),
                    role=title_part.title(),
                    source_url=url,
                    search_label=label,
                    apply_type="easy_apply",
                    notes=f"Search: {label}; Hirist feed",
                    work_mode="remote",
                )
            )

        if self.scraper_cfg.get("enrich_details", True):
            enrich_limit = int(self.scraper_cfg.get("enrich_limit_per_search", 15))
            enriched = []
            for job in jobs[: min(enrich_limit, len(jobs))]:
                enriched.append(await self._enrich_job(page, job))
            enriched.extend(jobs[enrich_limit:])
            return enriched
        return jobs

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        try:
            await safe_goto(page, job.source_url)
            body = (await page.locator("body").inner_text()).lower()
            for kw in ["sql", "python", "spark", "pyspark", "etl", "snowflake", "databricks", "aws", "azure"]:
                if kw in body:
                    job.skills.append(kw)
            if "remote" in body:
                job.work_mode = "remote"
            loc_m = re.search(r"location[:\s]+([^\n]+)", body, re.I)
            if loc_m:
                job.location = loc_m.group(1).strip()[:80]
            job.notes = f"{job.notes}; Hirist detail enriched".strip("; ")
        except Exception:
            pass
        return job