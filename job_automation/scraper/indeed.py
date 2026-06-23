from __future__ import annotations

from playwright.async_api import Page

from ..browser import safe_goto, text_from_selectors
from ..models import Job
from .base import BaseScraper


class IndeedScraper(BaseScraper):
    source_name = "Indeed"

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        await safe_goto(page, search_url)
        jobs: list[Job] = []
        seen: set[str] = set()
        max_jobs = self._max_jobs()

        cards = page.locator("div.job_seen_beacon, div.cardOutline, td.resultContent")
        count = await cards.count()
        for i in range(count):
            if len(jobs) >= max_jobs:
                break
            card = cards.nth(i)
            try:
                link = card.locator("a.jcs-JobTitle, h2.jobTitle a, a[data-jk]").first
                if await link.count() == 0:
                    continue
                href = await link.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = f"https://in.indeed.com{href}"
                if not href or href in seen:
                    continue
                seen.add(href)

                role = (await link.inner_text()).strip()
                company = await text_from_selectors(
                    card,
                    ["[data-testid='company-name']", ".companyName", "span.companyName"],
                )
                location = await text_from_selectors(
                    card,
                    ["[data-testid='text-location']", ".companyLocation", "div.companyLocation"],
                )
                posted = await text_from_selectors(card, [".date", "span.date"])

                jobs.append(
                    Job(
                        source=self.source_name,
                        company=company,
                        role=role,
                        source_url=href,
                        location=location,
                        posted=posted,
                        work_mode="remote" if "remote" in location.lower() else "",
                        apply_type="easy_apply",
                        search_label=label,
                        notes=f"Search: {label}; Indeed search result",
                    )
                )
            except Exception:
                continue
        return jobs

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        try:
            await safe_goto(page, job.source_url)
            desc = await text_from_selectors(
                page,
                ["#jobDescriptionText", ".jobsearch-JobComponent-description"],
            )
            if desc:
                blob = desc.lower()
                for kw in ["sql", "python", "spark", "pyspark", "etl", "snowflake", "databricks"]:
                    if kw in blob:
                        job.skills.append(kw)
                job.notes = f"{job.notes}; Indeed detail enriched".strip("; ")
        except Exception:
            pass
        return job