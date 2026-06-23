from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Page

from ..models import Job
from .base import BaseScraper

logger = logging.getLogger(__name__)

CUTSHORT_BASE = "https://cutshort.io"

# Job card selectors — Cutshort uses hashed/generated CSS class names;
# we try multiple patterns in order of reliability.
CARD_SELECTORS = [
    ".job-card",
    "[data-test='job-card']",
    "[data-test='jobCard']",
    "div[class*='JobCard']",
    "div[class*='job-card']",
    "div[class*='jobCard']",
    "article[class*='job']",
    # Broad fallbacks
    "div[class*='card'][class*='job']",
    "li[class*='job']",
]

ROLE_SELECTORS = [
    "[data-test='job-title']",
    "[data-test='jobTitle']",
    ".job-title",
    "[class*='jobTitle']",
    "[class*='job-title']",
    "[class*='title']",
    "h2",
    "h3",
    "strong",
]

COMPANY_SELECTORS = [
    "[data-test='company-name']",
    "[data-test='companyName']",
    ".company-name",
    "[class*='companyName']",
    "[class*='company-name']",
    "[class*='company']",
    "h4",
]

LOCATION_SELECTORS = [
    "[data-test='location']",
    "[class*='location']",
    "[class*='Location']",
    "span[class*='city']",
    "span[class*='place']",
]

EXPERIENCE_SELECTORS = [
    "[data-test='experience']",
    "[class*='experience']",
    "[class*='exp']",
    "span[class*='year']",
]

POSTED_SELECTORS = [
    "time",
    "[class*='posted']",
    "[class*='date']",
    "[class*='time']",
]

DESCRIPTION_SELECTORS = [
    "[data-test='job-description']",
    "[class*='description']",
    "[class*='jobDescription']",
    "div[class*='details']",
    "section[class*='content']",
    "div[class*='content']",
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

# Posted text patterns that indicate staleness (>30 days)
_STALE_RE = re.compile(r"\b(month|30\+\s*day|over\s*a\s*month|[2-9]\d+\s*days?)\b", re.I)


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


class CutshortScraper(BaseScraper):
    """Browser-based scraper for Cutshort.io job listings."""

    source_name = "Cutshort"

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        """Navigate to a Cutshort search URL, scrape and optionally enrich jobs."""
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            logger.warning("Cutshort: failed to load %s: %s", search_url, exc)
            return []

        # Allow dynamic content to settle
        await page.wait_for_timeout(3500)

        # Scroll down several times to load paginated/lazy jobs
        await self._scroll_and_load(page)

        jobs: list[Job] = []
        seen: set[str] = set()
        max_jobs = self._max_jobs()

        # Identify card container using fallback selectors
        cards_locator = None
        for sel in CARD_SELECTORS:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                if count > 0:
                    cards_locator = loc
                    logger.debug("Cutshort: using card selector %r (%d cards)", sel, count)
                    break
            except Exception:
                continue

        if cards_locator is None:
            logger.warning("Cutshort: no job cards found on %s", search_url)
            return []

        card_count = await cards_locator.count()
        logger.info("Cutshort [%s]: found %d cards", label, card_count)

        for i in range(card_count):
            if len(jobs) >= max_jobs:
                break
            card = cards_locator.nth(i)
            try:
                job = await self._parse_card(card, search_url, label, seen)
                if job is not None:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Cutshort: card %d parse error: %s", i, exc)
                continue

        # Optionally enrich jobs by navigating to detail pages
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
        """Extract structured fields from a single Cutshort job card."""
        role = await _text_from_selectors(card, ROLE_SELECTORS)
        company = await _text_from_selectors(card, COMPANY_SELECTORS)

        if not role or not company:
            # Last resort: try to parse card text directly
            try:
                full_text = (await card.inner_text()).strip()
                lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
                if len(lines) >= 2:
                    role = role or lines[0]
                    company = company or lines[1]
            except Exception:
                pass

        if not role or not company:
            return None

        # Build job URL from a card link
        job_url = ""
        try:
            link = card.locator("a[href*='/job'], a[href*='/jobs/'], a").first
            if await link.count():
                href = await link.get_attribute("href") or ""
                if href:
                    if href.startswith("/"):
                        href = f"{CUTSHORT_BASE}{href}"
                    job_url = href.split("?")[0].strip()
        except Exception:
            pass

        # Fallback URL built from company/role slug
        if not job_url:
            slug = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")
            job_url = f"{CUTSHORT_BASE}/jobs/{slug}"

        if job_url in seen:
            return None
        seen.add(job_url)

        location = await _text_from_selectors(card, LOCATION_SELECTORS)
        experience = await _text_from_selectors(card, EXPERIENCE_SELECTORS)
        posted = await _text_from_selectors(card, POSTED_SELECTORS)

        # Freshness gate
        if _is_stale_posted(posted):
            logger.debug("Cutshort: skipping stale posting: %r posted=%r", role, posted)
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
            experience=experience.strip(),
            posted=posted.strip(),
            work_mode=work_mode,
            apply_type="easy_apply",
            search_label=label,
            notes=f"Search: {label}; Cutshort",
            next_action="Apply via Cutshort",
        )

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        """Navigate to the job detail page to pull JD text and skills."""
        try:
            await page.goto(job.source_url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(2000)

            description = await _text_from_selectors(page, DESCRIPTION_SELECTORS)
            if description:
                job.jd_text = description
                desc_lower = description.lower()
                job.skills = [kw for kw in SKILL_KEYWORDS if kw in desc_lower]

            # Refine role / company / location from detail page
            role = await _text_from_selectors(page, ["h1"] + ROLE_SELECTORS)
            if role:
                job.role = role.strip()

            company = await _text_from_selectors(page, COMPANY_SELECTORS)
            if company:
                job.company = company.strip()

            location = await _text_from_selectors(page, LOCATION_SELECTORS)
            if location:
                job.location = location.strip()

            experience = await _text_from_selectors(page, EXPERIENCE_SELECTORS)
            if experience:
                job.experience = experience.strip()

            job.notes = f"{job.notes}; Cutshort detail enriched".strip("; ")
        except Exception as exc:
            logger.debug("Cutshort: enrich error for %s: %s", job.source_url, exc)
        return job

    async def _scroll_and_load(self, page: Page, rounds: int = 8) -> None:
        """Scroll down multiple times to trigger lazy-loading of more job cards."""
        prev_height = 0
        for _ in range(rounds):
            try:
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(1200)
                curr_height: int = await page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    # No new content loaded; stop early
                    break
                prev_height = curr_height
            except Exception:
                break
