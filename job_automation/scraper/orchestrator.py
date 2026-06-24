"""Scraper orchestrator — DB-backed, two-lane, recent-only, deduplicated."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..browser import BrowserSession
from ..config import get_fresh_only_days, resolve_db_path
from ..db import get_repo
from ..db.dedup import detect_cross_source_duplicates
from ..models import Job
from ..scoring import score_job
from .hirist import HiristScraper
from .indeed import IndeedScraper
from .linkedin import LinkedInScraper
from .naukri import NaukriScraper
from .generic import GenericScraper

# Browser-based scrapers
BROWSER_SCRAPERS: dict[str, type] = {
    "naukri":   NaukriScraper,
    "linkedin":  LinkedInScraper,
    "indeed":    IndeedScraper,
    "hirist":    HiristScraper,
}

async def run_scraper(
    config: dict[str, Any],
    base_dir: Path,
    sources: list[str] | None = None,
) -> list[Job]:
    """
    Main scrape entry point.
    - Runs browser scrapers sequentially on user's Brave window
    - Deduplicates (URL + cross-source fuzzy)
    - Scores every job
    - Upserts to SQLite DB
    - Returns list of truly new jobs (not previously in DB)
    """
    db = get_repo(resolve_db_path(config, base_dir))
    fresh_days = get_fresh_only_days(config)
    scraper_cfg = config.get("scraper", {})
    searches = scraper_cfg.get("searches", {})

    # Determine which sources to run
    config_sources = scraper_cfg.get("sources", None)
    all_sources = list(searches.keys())
    
    # Priority: explicit args > config saved from UI > all available
    selected = sources or config_sources or all_sources
    # Ensure they are lowercase for matching
    selected = [s.lower() for s in selected]

    all_jobs: list[Job] = []

    # ── Browser scrapers ─────────────────────────────────────────────────
    browser_selected = [s for s in selected if s in BROWSER_SCRAPERS and s in searches]
    if browser_selected:
        prefer_hosts = []
        host_map = {
            "linkedin": ["linkedin.com"],
            "hirist":   ["hirist.tech"],
            "naukri":   ["naukri.com"],
            "indeed":   ["indeed."],
        }
        for src in browser_selected:
            prefer_hosts.extend(host_map.get(src, []))

        session = BrowserSession(config)
        async with session:
            page = await session.get_work_page(prefer_hosts=prefer_hosts or None)

            for source_name in browser_selected:
                entries = searches.get(source_name, [])
                scraper_cls = BROWSER_SCRAPERS.get(source_name, GenericScraper)
                scraper = scraper_cls(config)
                print(f"\n[scrape] {scraper.source_name}: {len(entries)} search(es)")

                for entry in entries:
                    if isinstance(entry, str):
                        url, label = entry, source_name
                    else:
                        url   = entry.get("url", "")
                        label = entry.get("label", source_name)
                    if not url:
                        continue

                    print(f"  -> {label}: {url}")
                    t0 = time.time()
                    try:
                        found = await scraper.scrape_search(page, url, label)
                        for job in found:
                            await score_job(job, config)
                        print(f"     found {len(found)} jobs")
                        all_jobs.extend(found)
                        db.log_scrape_run(
                            source_name, label, len(found), 0, 0, time.time() - t0
                        )
                    except Exception as exc:
                        print(f"     error: {exc}")

    # ── Deduplicate within this run (URL) ────────────────────────────────
    deduped: dict[str, Job] = {}
    for job in all_jobs:
        if job.source_url:
            await score_job(job, config)
            deduped[job.source_url] = job
    unique_jobs = list(deduped.values())

    # ── Cross-source fuzzy dedup against existing DB jobs ───────────────
    existing_jobs = db.get_jobs(limit=2000)
    unique_jobs = detect_cross_source_duplicates(unique_jobs, existing_jobs)

    # ── Upsert to DB, count truly new ───────────────────────────────────
    new_count = 0
    dup_count = 0
    for job in unique_jobs:
        is_new = db.upsert_job(job)
        if is_new:
            new_count += 1
        else:
            dup_count += 1

    print(f"\n[scrape] Complete — total: {len(unique_jobs)}, new: {new_count}, updated: {dup_count}")
    return [j for j in unique_jobs if not j.duplicate_of]