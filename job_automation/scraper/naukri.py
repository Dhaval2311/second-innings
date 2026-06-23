from __future__ import annotations

import re

from playwright.async_api import Page

from ..browser import safe_goto, text_from_selectors
from ..models import Job
from .base import BaseScraper


class NaukriScraper(BaseScraper):
    source_name = "Naukri"

    async def scrape_search(self, page: Page, search_url: str, label: str) -> list[Job]:
        await safe_goto(page, search_url)
        jobs: list[Job] = []
        seen: set[str] = set()
        max_jobs = self._max_jobs()

        for _ in range(5):
            cards = page.locator("div.cust-job-tuple, article.jobTuple")
            count = await cards.count()
            for i in range(count):
                if len(jobs) >= max_jobs:
                    break
                card = cards.nth(i)
                try:
                    title_el = card.locator("a.title, h2 a, a[title]").first
                    if await title_el.count() == 0:
                        continue
                    role = (await title_el.inner_text()).strip()
                    href = await title_el.get_attribute("href") or ""
                    if not href or href in seen:
                        continue
                    seen.add(href)

                    company = await text_from_selectors(
                        card,
                        [".comp-name", ".companyInfo .emp-name", "a.comp-name"],
                    )
                    experience = await text_from_selectors(card, [".expwdth", ".experience"])
                    location = await text_from_selectors(card, [".locWdth", ".location"])
                    posted = await text_from_selectors(card, [".job-post-day", ".type"])

                    work_mode = "remote" if "remote" in location.lower() or "remote" in role.lower() else ""

                    job = Job(
                        source=self.source_name,
                        company=company,
                        role=role,
                        source_url=href if href.startswith("http") else f"https://www.naukri.com{href}",
                        location=location,
                        experience=experience,
                        posted=posted,
                        work_mode=work_mode,
                        apply_type="easy_apply",
                        search_label=label,
                        notes=f"Search: {label}",
                    )
                    jobs.append(job)
                except Exception:
                    continue

            if len(jobs) >= max_jobs:
                break

            next_btn = page.locator("a.frt.paginate, a.styles_btn-secondary__2MyXt, a[aria-label='Next']").first
            if await next_btn.count() == 0:
                break
            try:
                await next_btn.click(timeout=3000)
                await page.wait_for_timeout(2000)
            except Exception:
                break

        if self.scraper_cfg.get("enrich_details", True):
            enriched = []
            for job in jobs[: min(len(jobs), 15)]:
                enriched.append(await self._enrich_job(page, job))
            enriched.extend(jobs[15:])
            return enriched
        return jobs

    async def _enrich_job(self, page: Page, job: Job) -> Job:
        try:
            await safe_goto(page, job.source_url)
            body = (await page.locator("body").inner_text()).lower()

            skills = []
            for sel in [".styles_chip__7YCfG", ".key-skill a", ".chips-container a"]:
                loc = page.locator(sel)
                n = await loc.count()
                for i in range(min(n, 30)):
                    t = (await loc.nth(i).inner_text()).strip().lower()
                    if t and len(t) < 40:
                        skills.append(t)

            exp = await text_from_selectors(page, [".styles_jhc__exp__k_sOi", ".exp", ".styles_jhc__exp__W5ion"])
            if exp:
                job.experience = exp
            loc = await text_from_selectors(page, [".styles_jhc__loc__W_pVs", ".loc", ".styles_jhc__loc__W5ion"])
            if loc:
                job.location = loc
            posted = await text_from_selectors(page, [".styles_jhc__posted__W5ion", ".styles_jhc__posted__W5ion span"])
            if posted:
                job.posted = posted

            openings_m = re.search(r"openings?\s*:\s*(\d+)", body, re.I)
            if openings_m:
                job.openings = openings_m.group(1)
            applicants_m = re.search(r"applicants?\s*:\s*([^\\n]+)", body, re.I)
            if applicants_m:
                job.applicants = applicants_m.group(1).strip()[:20]

            if "remote" in body:
                job.work_mode = "remote"

            job.skills = list(dict.fromkeys(skills))
            job.notes = f"{job.notes}; Naukri detail enriched".strip("; ")
        except Exception:
            pass
        return job