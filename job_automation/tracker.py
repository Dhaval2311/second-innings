from __future__ import annotations

import csv
from pathlib import Path

from .models import TRACKER_COLUMNS, Job


def load_tracker(path: Path) -> list[Job]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [Job.from_row(r) for r in rows]


def save_tracker(path: Path, jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_COLUMNS)
        writer.writeheader()
        for job in jobs:
            writer.writerow(job.to_row())


def merge_jobs(existing: list[Job], new_jobs: list[Job]) -> list[Job]:
    by_url: dict[str, Job] = {j.source_url: j for j in existing if j.source_url}
    for job in new_jobs:
        if not job.source_url:
            continue
        if job.source_url in by_url:
            old = by_url[job.source_url]
            job.applied_date = old.applied_date or job.applied_date
            if old.status in {"applied", "applied_needs_verification", "skipped", "failed"}:
                job.status = old.status
            job.notes = job.notes or old.notes
        by_url[job.source_url] = job
    merged = list(by_url.values())
    merged.sort(key=lambda j: (j.status != "priority", j.status != "shortlist", -j.score))
    return merged


def write_shortlist(path: Path, jobs: list[Job], limit: int = 100) -> None:
    lines = [
        "# Job Shortlist",
        "",
        f"Generated automatically. Top {limit} jobs by score.",
        "",
    ]
    for i, job in enumerate(jobs[:limit], 1):
        lines.extend(
            [
                f"## {i}. {job.role} - {job.company}",
                f"- Status: {job.status}",
                f"- Source: {job.source}",
                f"- Score: {job.score}",
                f"- Location: {job.location}",
                f"- Experience: {job.experience}",
                f"- Posted: {job.posted}",
                f"- Work mode: {job.work_mode}",
                f"- Match: {job.core_match}",
                f"- Link: {job.source_url}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def update_job_status(
    jobs: list[Job],
    url: str,
    status: str,
    applied_date: str = "",
    note: str = "",
    next_action: str = "",
) -> None:
    for job in jobs:
        if job.source_url == url:
            job.status = status
            if applied_date:
                job.applied_date = applied_date
            if note:
                job.notes = f"{job.notes}; {note}".strip("; ")
            if next_action:
                job.next_action = next_action
            break