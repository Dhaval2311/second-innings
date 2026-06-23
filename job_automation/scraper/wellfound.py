from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Page

from ..models import Job
from .base import BaseScraper

logger = logging.getLogger(__name__)

WELLFOUND_BASE = "https://wellfound.com"

# Selectors tried in order — Wellfound uses hashed CSS class names that change,
# so we keep multiple fallbacks ranked by specificity.
CARD_SELECTORS = [
    "div[data-test='JobListing']",
    "div[data-test='job-listing']",
    ".styles_jobListingCard__9E56G",
    "div[class*='JobListing']",
    "article[class*='job']",
    "div[class*='jobCard']",
    # Generic last-resort
    "div[class*='listing']",
]

ROLE_SELECTORS = [
    "h2[class*='title']",
    "h2[class*='role']",
    "h2",
    ".styles_title",
    "[class*='jobTitle']",
    "[data-test='job-title']",
    "strong",
]

COMPANY_SELECTORS = [
    ".styles_companyName",
    "[class*='companyName']",
    "[class*='company']",
    "[data-test='company-name']",
    "a[class*='company']",
    "h3",
]

LOCATION_SELECTORS = [
    ".styles_location",
    "[class*='location']",
    "[class*='Location']",
    "[data-test='location']",
    "span[class*='geo']",
]

POSTED_SELECTORS = [
    "time",
    "[class*='posted']",
    "[class*='date']",
    "span[class*='time']",
]

DESCRIPTION_SELECTORS = [
    ".styles_description",
    "[class*='description']",
    "section[class*='jd']",
    "div[class*='jobDescription']",
    "div[class*='content']",
    "article section",
]

SKILL_KEYWORDS = [
    "sql",
    "python",
    "spark",
    "pyspark",
    "etl",
    "snowflake",
    "databricks",
    "aws",
    "azure",
    "airflow",
    "tableau",
    "power bi",
    "dbt",
    "kafka",
    "bigquery",
    "redshift",
    "looker",
]

# Posted text that indicates a stale listing
_STALE_RE = re.compile(r"\b(month|30\+\s*day|over\s*a\s*month)\b", re.I)


def _is_stale_posted(posted: str) -> bool:
    """Return True if the posted string indicates a listing older than ~30 days."""
    if not posted:
        return False
    return bool(_STALE_RE.search(posted))


async def _text_from_selectors(locator_root: Any, selectors: list[str]) -> str:
    """Try each selector in order, returning the first non-empty text found."""
    for sel in selectors:
        try:
            loc = locator_root.locator(sel).first
            if await loc.count():
                text = (await loc.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


class WellfoundScraper(BaseScraper):
    """Browser-based scraper for Wellfound (formerly AngelList Talent)."""

    source_name = "Wellfound"

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        """Navigate to a Wellfound search URL, extract and optionally enrich job listings."""
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            logger.warning("Wellfound: failed to load %s: %s", search_url, exc)
            return []

        # Wait for some content to appear
        await page.wait_for_timeout(3000)

        # Scroll down to trigger lazy-loaded cards
        await self._scroll_page(page)

        jobs: list[Job] = []
        seen: set[str] = set()
        max_jobs = self._max_jobs()

        # Find the card container using fallback selectors
        cards_locator = None
        for sel in CARD_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                if count > 0:
                    cards_locator = loc
                    logger.debug("Wellfound: using card selector %r (%d cards)", sel, count)
                    break
            except Exception:
                continue

        if cards_locator is None:
            logger.warning("Wellfound: no job cards found on %s", search_url)
            return []

        card_count = await cards_locator.count()
        logger.info("Wellfound [%s]: found %d cards", label, card_count)

        for i in range(card_count):
            if len(jobs) >= max_jobs:
                break
            card = cards_locator.nth(i)
            try:
                job = await self._parse_card(card, search_url, label, seen)
                if job is not None:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Wellfound: card %d parse error: %s", i, exc)
                continue

        # Optionally enrich with full JD text by clicking each card
        if self.scraper_cfg.get("enrich_details", True):
            enrich_limit = int(self.scraper_cfg.get("enrich_limit_per_search", 8))
            enriched: list[Job] = []
            for job in jobs[:enrich_limit]:
                enriched.append(await self._enrich_job(page, job))
            enriched.extend(jobs[enrich_limit:])
            return enriched

        return jobs

    async def _parse_card(
        self,
        card: Any,
        search_url: str,
        label: str,
        seen: set[str],
    ) -> Job | None:
        """Extract fields from a single job card element."""
        role = await _text_from_selectors(card, ROLE_SELECTORS)
        company = await _text_from_selectors(card, COMPANY_SELECTORS)

        if not role or not company:
            return None

        # Try to get URL from a link inside the card
        job_url = ""
        try:
            link = card.locator("a[href*='/jobs/'], a[href*='/role/'], a").first
            if await link.count():
                href = await link.get_attribute("href") or ""
                if href:
                    if href.startswith("/"):
                        href = f"{WELLFOUND_BASE}{href}"
                    job_url = href.split("?")[0].strip()
        except Exception:
            pass

        if not job_url:
            job_url = f"{search_url}#company={company.replace(' ', '-').lower()}"

        if job_url in seen:
            return None
        seen.add(job_url)

        location = await _text_from_selectors(card, LOCATION_SELECTORS)
        posted = await _text_from_selectors(card, POSTED_SELECTORS)

        # Freshness check
        if _is_stale_posted(posted):
            logger.debug("Wellfound: skipping stale posting: %r posted=%r", role, posted)
            return None

        work_mode = "remote"
        if location:
            loc_lower = location.lower()
            if "remote" in loc_lower:
                work_mode = "remote"
            elif "hybrid" in loc_lower:
                work_mode = "hybrid"
            elif any(c.isalpha() for c in location):
                work_mode = "onsite"

        return Job(
            source=self.source_name,
            company=company.strip(),
            role=role.strip(),
            source_url=job_url,
            location=location.strip(),
            posted=posted.strip(),
            work_mode=work_mode,
            apply_type="easy_apply",
            search_label=label,
            notes=f"Search: {label}; Wellfound",
            next_action="Apply via Wellfound",
        )

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        """Click into the job listing to pull the full JD text and skills."""
        try:
            await page.goto(job.source_url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(2000)

            description = await _text_from_selectors(page, DESCRIPTION_SELECTORS)
            if description:
                job.jd_text = description
                desc_lower = description.lower()
                job.skills = [kw for kw in SKILL_KEYWORDS if kw in desc_lower]

            # Try to refine role / company / location from detail page
            role = await _text_from_selectors(page, ["h1"] + ROLE_SELECTORS)
            if role:
                job.role = role.strip()

            company = await _text_from_selectors(page, COMPANY_SELECTORS)
            if company:
                job.company = company.strip()

            location = await _text_from_selectors(page, LOCATION_SELECTORS)
            if location:
                job.location = location.strip()

            job.notes = f"{job.notes}; Wellfound detail enriched".strip("; ")
        except Exception as exc:
            logger.debug("Wellfound: enrich error for %s: %s", job.source_url, exc)
        return job

    async def _scroll_page(self, page: Page, rounds: int = 6) -> None:
        """Scroll down multiple times to trigger lazy-loaded job cards."""
        for _ in range(rounds):
            try:
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(1000)
            except Exception:
                break
