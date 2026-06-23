from __future__ import annotations

import re

from playwright.async_api import Page

from ..browser import safe_goto, text_from_selectors
from ..models import Job
from .base import BaseScraper

STALE_POSTED = re.compile(
    r"\b(\d+\s*\+?\s*days?\s*ago|month|months?\s*ago|weeks?\s*ago)\b",
    re.I,
)

CARD_SELECTOR = "li.scaffold-layout__list-item, li.semantic-search-results-list__list-item"

LIST_PANEL_SELECTORS = [
    "div.scaffold-layout__list",
    "ul.semantic-search-results-list",
    "ul.jobs-search__results-list",
]


class LinkedInScraper(BaseScraper):
    source_name = "LinkedIn"

    def _normalize_job_url(self, href: str) -> str:
        if not href:
            return ""
        href = href.split("?")[0].strip()
        if href.startswith("/"):
            href = f"https://www.linkedin.com{href}"
        href = href.replace("https://in.linkedin.com", "https://www.linkedin.com").replace(
            "http://in.linkedin.com", "https://www.linkedin.com"
        )
        match = re.search(r"(https://www\.linkedin\.com/jobs/view/\d+)", href)
        return match.group(1) + "/" if match else href

    def _parse_card_text(self, text: str) -> tuple[str, str, str]:
        if "|" in text and text.count("|") >= 2:
            parts = [p.strip() for p in text.split("|") if p.strip()]
        else:
            parts = [p.strip() for p in text.splitlines() if p.strip()]
        if len(parts) < 3:
            return "", "", ""

        role = parts[0]
        company_idx = 1
        if len(parts) > 2 and (
            "verification" in parts[1].lower() or parts[1].lower().startswith(role.lower())
        ):
            company_idx = 2

        company = parts[company_idx] if company_idx < len(parts) else ""
        location = parts[company_idx + 1] if company_idx + 1 < len(parts) else ""
        for marker in (
            "actively reviewing",
            "promoted",
            "easy apply",
            "viewed",
            "be an early applicant",
            "connection works",
        ):
            if marker in location.lower():
                location = ""
                break
        return role, company, location

    def _is_easy_apply_search(self, label: str, search_url: str) -> bool:
        return label.startswith("easy-") or "f_AL=true" in search_url or "f_AL%3Dtrue" in search_url

    def _is_stale_posting(self, posted: str) -> bool:
        if not posted:
            return False
        lower = posted.lower().strip()
        if any(token in lower for token in ("hour", "minute", "just now", "today", "1 day", "2 day", "3 day")):
            return False
        if "week" in lower and "weeks" not in lower:
            return False
        return bool(STALE_POSTED.search(lower))

    async def _card_has_easy_apply(self, card) -> bool:
        selectors = [
            ".job-card-container__apply-method",
            ".job-card-list__footer-wrapper",
            "span:has-text('Easy Apply')",
        ]
        for sel in selectors:
            loc = card.locator(sel).first
            try:
                if await loc.count() == 0:
                    continue
                text = (await loc.inner_text()).lower()
                if "easy apply" in text:
                    return True
            except Exception:
                continue
        try:
            card_text = (await card.inner_text()).lower()
            return "easy apply" in card_text
        except Exception:
            return False

    def _tag_apply_type(self, job: Job, apply_type: str) -> Job:
        job.apply_type = apply_type
        job.notes = f"{job.notes}; apply_type:{apply_type}".strip("; ")
        if apply_type == "easy_apply":
            job.next_action = "Auto apply via LinkedIn Easy Apply"
        elif apply_type == "company_site":
            job.status = "company_site_pending"
            job.next_action = "Apply on company site manually"
        return job

    async def _detect_apply_type_on_page(self, page: Page) -> str:
        body = (await page.locator("body").inner_text()).lower()
        easy_selectors = [
            "button.jobs-apply-button:has-text('Easy Apply')",
            "button:has-text('Easy Apply')",
            "a:has-text('Easy Apply')",
            "button[aria-label*='Easy Apply']",
            "a[aria-label*='Easy Apply']",
        ]
        for sel in easy_selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    text = (await loc.inner_text()).lower()
                    aria = (await loc.get_attribute("aria-label") or "").lower()
                    if "easy apply" in text or "easy apply" in aria:
                        return "easy_apply"
            except Exception:
                continue

        if "apply on company website" in body or "on company website" in body:
            return "company_site"

        for sel in ["button:has-text('Apply')", "a:has-text('Apply')"]:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    text = (await loc.inner_text()).lower()
                    if "easy apply" in text:
                        continue
                    return "company_site"
            except Exception:
                continue
        return "unknown"

    async def _goto_search(self, page: Page, search_url: str) -> bool:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        if "/jobs/search" not in page.url:
            return False

        try:
            await page.wait_for_selector(CARD_SELECTOR, timeout=12000)
            return True
        except Exception:
            return False

    async def _scroll_results(self, page: Page) -> None:
        panel = None
        for sel in LIST_PANEL_SELECTORS:
            loc = page.locator(sel).first
            try:
                if await loc.count():
                    panel = loc
                    break
            except Exception:
                continue

        for _ in range(8):
            if panel:
                try:
                    await panel.evaluate("el => el.scrollTop = el.scrollHeight")
                except Exception:
                    await page.mouse.wheel(0, 2000)
            else:
                await page.mouse.wheel(0, 2000)
            await page.wait_for_timeout(1000)

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        loaded = await self._goto_search(page, search_url)
        if not loaded:
            print(f"     warn: could not load search results for {label}")
            return []

        jobs: list[Job] = []
        seen: set[str] = set()
        max_jobs = self._max_jobs()
        easy_search = self._is_easy_apply_search(label, search_url)

        await self._scroll_results(page)

        cards = page.locator(CARD_SELECTOR)
        count = await cards.count()
        for i in range(count):
            if len(jobs) >= max_jobs:
                break
            card = cards.nth(i)
            try:
                link = card.locator(
                    "a.base-card__full-link, a[href*='/jobs/view/'], a.job-card-container__link"
                ).first
                if await link.count() == 0:
                    continue
                href = self._normalize_job_url(await link.get_attribute("href") or "")
                if not href or "/jobs/view/" not in href or href in seen:
                    continue
                seen.add(href)

                card_text = (await card.inner_text()).strip()
                role, company, location = self._parse_card_text(card_text)
                if not role or not company:
                    role = await text_from_selectors(
                        card,
                        [
                            ".base-search-card__title",
                            ".job-card-list__title",
                            "h3",
                            "strong",
                        ],
                    )
                    company = await text_from_selectors(
                        card,
                        [
                            ".base-search-card__subtitle",
                            ".job-card-container__company-name",
                            "h4",
                        ],
                    )
                    if not location:
                        location = await text_from_selectors(
                            card,
                            [
                                ".job-search-card__location",
                                ".job-card-container__metadata-item",
                                ".base-search-card__metadata span",
                            ],
                        )
                if not role or not company:
                    continue
                posted = await text_from_selectors(
                    card,
                    ["time", ".job-search-card__listdate", "time.job-card-container__listed-time"],
                )
                if self._is_stale_posting(posted):
                    continue

                card_easy = easy_search or await self._card_has_easy_apply(card)
                apply_hint = "easy_apply" if card_easy else "unknown"

                job = Job(
                    source=self.source_name,
                    company=company,
                    role=role,
                    source_url=href,
                    location=location,
                    posted=posted,
                    work_mode="remote" if "remote" in location.lower() else "",
                    apply_type=apply_hint,
                    search_label=label,
                    notes=f"Search: {label}; apply_type:{apply_hint}",
                    next_action="Open LinkedIn detail and apply if relevant",
                )
                if card_easy:
                    job.next_action = "Auto apply via LinkedIn Easy Apply"
                jobs.append(job)
            except Exception:
                continue

        if self.scraper_cfg.get("enrich_details", True):
            enrich_limit = int(self.scraper_cfg.get("enrich_limit_per_search", 8))
            enriched: list[Job] = []
            for job in jobs[:enrich_limit]:
                enriched.append(await self._enrich_job(page, job))
            enriched.extend(jobs[enrich_limit:])
            return enriched
        return jobs

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        try:
            await safe_goto(page, job.source_url)
            await page.wait_for_timeout(1500)
            desc = await text_from_selectors(
                page,
                [
                    ".show-more-less-html__markup",
                    ".description__text",
                    "#job-details",
                ],
            )
            if desc:
                blob = desc.lower()
                job.skills = []
                for kw in [
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
                ]:
                    if kw in blob:
                        job.skills.append(kw)

            company = await text_from_selectors(
                page,
                [".job-details-jobs-unified-top-card__company-name a", ".topcard__org-name-link"],
            )
            if company:
                job.company = company
            role = await text_from_selectors(
                page,
                ["h1.t-24", ".job-details-jobs-unified-top-card__job-title h1", "h1"],
            )
            if role:
                job.role = role
            location = await text_from_selectors(
                page,
                [
                    ".job-details-jobs-unified-top-card__primary-description-container",
                    ".topcard__flavor--bullet",
                ],
            )
            if location:
                job.location = location.split("·")[0].strip()

            posted = await text_from_selectors(page, ["time", ".posted-time-ago__text"])
            if posted:
                job.posted = posted

            apply_type = await self._detect_apply_type_on_page(page)
            if "apply_type:easy_apply" in job.notes:
                apply_type = "easy_apply"
            elif apply_type == "unknown" and "apply_type:unknown" in job.notes:
                apply_type = "company_site"

            job.notes = re.sub(r"apply_type:\w+", "", job.notes).strip("; ")
            job = self._tag_apply_type(job, apply_type)
            job.notes = f"{job.notes}; LinkedIn detail enriched".strip("; ")
        except Exception:
            pass
        return job