"""Applier orchestrator — two-lane pipeline (easy_apply automated, company_site tracked)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..browser import BrowserSession
from ..config import resolve_db_path
from ..db import get_repo
from ..models import Job, today_str
from ..site_login import ensure_linkedin_session
from .base import BaseApplier
from .generic import GenericApplier
from .hirist import HiristApplier
from .indeed import IndeedApplier
from .linkedin import LinkedInApplier
from .naukri import NaukriApplier


SKIP_STATUSES = {
    "applied",
    "applied_needs_verification",
    "pending_external",
    "company_site_pending",
    "needs_user_input",
    "needs_human",
    "failed",
}


def pick_applier(job: Job, config: dict[str, Any]) -> BaseApplier:
    host = urlparse(job.source_url).netloc.lower()
    source = job.source.lower()
    if "naukri.com" in host or source == "naukri":
        return NaukriApplier(config)
    if "linkedin.com" in host or source == "linkedin":
        return LinkedInApplier(config)
    if "indeed." in host or source == "indeed":
        return IndeedApplier(config)
    if "hirist.tech" in host or source == "hirist":
        return HiristApplier(config)
    return GenericApplier(config)


def _filter_easy_apply_queue(jobs: list[Job], config: dict[str, Any]) -> list[Job]:
    """Return jobs for the automated Easy Apply lane."""
    applier_cfg = config.get("applier", {})
    allowed_statuses = set(applier_cfg.get("statuses", ["priority", "shortlist"]))
    allowed_sources  = {s.lower() for s in applier_cfg.get("sources", [])}
    max_per_run      = int(applier_cfg.get("max_per_run", 20))

    filtered: list[Job] = []
    for job in jobs:
        if job.apply_type != "easy_apply":
            continue
        if job.status not in allowed_statuses:
            continue
        if job.status in SKIP_STATUSES:
            continue
        if job.applied_date:
            continue
        if job.duplicate_of:
            continue
        if allowed_sources and job.source.lower() not in allowed_sources:
            host = urlparse(job.source_url).netloc.lower()
            if not any(src in host for src in allowed_sources):
                continue
        filtered.append(job)

    filtered.sort(key=lambda j: (-j.score,))
    return filtered[:max_per_run]


def _resolve_status(result, config: dict[str, Any]) -> str:
    if result.tracker_status:
        return result.tracker_status
    if result.already_applied:
        return "applied"
    if result.pending_external:
        return "pending_external"
    if result.needs_user_input:
        return "needs_user_input"
    if result.success:
        return "applied" if not config.get("applier", {}).get("dry_run", True) else "ready_to_apply"
    if result.needs_human:
        return "needs_human"
    return "failed"


async def run_applier(
    config: dict[str, Any],
    base_dir: Path,
) -> dict[str, int]:
    """
    Two-lane apply pipeline:
      Lane 1 (Easy Apply): Automated — browser fills and submits forms.
      Lane 2 (Company Site): No automation — jobs are logged as
                             company_site_pending for manual apply via dashboard.
    """
    db = get_repo(resolve_db_path(config, base_dir))

    # Migrate any pending YAML answers to DB on first run
    yaml_answers = base_dir / "user_answers.yaml"
    if yaml_answers.exists():
        migrated = db.import_yaml_answers(yaml_answers)
        if migrated:
            print(f"[apply] Migrated {migrated} answers from user_answers.yaml → DB")

    all_jobs = db.get_jobs(limit=2000, exclude_duplicate=True)

    # ── Lane 2: Company site — just tag and move on ──────────────────────
    company_site_new = [
        j for j in all_jobs
        if j.apply_type == "company_site" and j.status == "new"
    ]
    for job in company_site_new:
        db.update_job_status(
            job.source_url,
            "company_site_pending",
            next_action="Apply manually via company website, then click Mark Applied in dashboard",
        )
    if company_site_new:
        print(f"[apply] {len(company_site_new)} company-site jobs logged to manual queue")

    # ── Lane 1: Easy Apply — automated ──────────────────────────────────
    easy_queue = _filter_easy_apply_queue(all_jobs, config)
    stats = {"applied": 0, "failed": 0, "skipped": 0, "human": 0,
             "pending_external": 0, "company_site_logged": len(company_site_new)}

    if not easy_queue:
        print("[apply] No easy-apply jobs in queue.")
        return stats

    delay    = int(config.get("applier", {}).get("delay_seconds", 4))
    dry_run  = config.get("applier", {}).get("dry_run", True)
    sources  = [s.lower() for s in config.get("applier", {}).get("sources", [])]

    if dry_run:
        print("[apply] DRY RUN — set applier.dry_run: false to submit applications")

    host_map = {
        "linkedin": ["linkedin.com"], "hirist": ["hirist.tech"],
        "naukri":   ["naukri.com"],   "indeed": ["indeed."],
    }
    prefer_hosts: list[str] = []
    for src in sources:
        prefer_hosts.extend(host_map.get(src, []))

    print(f"\n[apply] Easy Apply queue: {len(easy_queue)} jobs")

    session = BrowserSession(config)
    async with session:
        page = await session.get_work_page(
            prefer_hosts=prefer_hosts or ["linkedin.com", "hirist.tech", "naukri.com"]
        )
        if any(s == "linkedin" for s in sources):
            await ensure_linkedin_session(page)
            print("[apply] LinkedIn session verified.")

        for idx, job in enumerate(easy_queue, 1):
            applier = pick_applier(job, config)
            print(f"\n[{idx}/{len(easy_queue)}] {applier.source_name}: {job.company} — {job.role}")
            print(f"  {job.source_url}")

            try:
                result = await applier.apply(page, job)
                status = _resolve_status(result, config)

                if result.already_applied:
                    db.update_job_status(job.source_url, status, today_str(), result.message)
                    stats["skipped"] += 1
                    print(f"  -> skipped: {result.message}")

                elif result.pending_external:
                    db.update_job_status(
                        job.source_url, status,
                        note=result.message,
                        next_action="Apply on company site manually",
                    )
                    stats["pending_external"] += 1
                    print(f"  -> pending_external: {result.message}")

                elif result.success:
                    applied_date = today_str() if status == "applied" else ""
                    db.update_job_status(job.source_url, status, applied_date, result.message)
                    stats["applied"] += 1
                    print(f"  -> success: {result.message}")

                else:
                    next_action = ""
                    if result.needs_user_input or result.unknown_questions:
                        next_action = "Answer questions in dashboard, then click Retry"
                    elif result.needs_human:
                        next_action = "Apply manually via job link (bot got stuck)"

                    # Log unknown questions to pending_inputs table
                    if result.unknown_questions:
                        for q in result.unknown_questions:
                            db.log_pending_input(
                                job.source_url, q,
                                context=f"{job.company} — {job.role}",
                            )
                        print(f"  -> {len(result.unknown_questions)} question(s) logged to dashboard")

                    db.update_job_status(
                        job.source_url, status, note=result.message, next_action=next_action
                    )
                    if result.needs_human or result.needs_user_input:
                        stats["human"] += 1
                    else:
                        stats["failed"] += 1
                    print(f"  -> {status}: {result.message}")

            except Exception as exc:
                db.update_job_status(job.source_url, "failed", note=str(exc))
                stats["failed"] += 1
                print(f"  -> error: {exc}")

            await asyncio.sleep(delay)

    return stats