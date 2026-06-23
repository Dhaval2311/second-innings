"""Cross-source deduplication for Second Innings."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Job


def _normalize_company(name: str) -> str:
    """Lowercase, remove legal suffixes and punctuation."""
    name = name.lower().strip()
    for suffix in [" pvt ltd", " pvt. ltd", " private limited", " limited",
                   " inc", " corp", " llc", " ltd", " technologies", " solutions",
                   " software", " systems", " services", " tech"]:
        name = name.removesuffix(suffix)
    return re.sub(r"[^a-z0-9 ]", " ", name).strip()


def _normalize_role(role: str) -> str:
    """Lowercase, remove seniority qualifiers for fuzzy match."""
    role = role.lower().strip()
    for prefix in ["senior ", "sr. ", "sr ", "lead ", "principal ", "staff ", "junior ", "jr. "]:
        role = role.removeprefix(prefix)
    return re.sub(r"[^a-z0-9 ]", " ", role).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def detect_cross_source_duplicates(
    new_jobs: list["Job"],
    existing_jobs: list["Job"],
    company_threshold: float = 0.85,
    role_threshold: float = 0.80,
) -> list["Job"]:
    """
    For each new job, check if an existing job from a DIFFERENT source
    looks like the same posting (same company + similar role).
    If so, set new_job.duplicate_of = existing_job.source_url so the
    apply pipeline skips double-applying.
    Returns new_jobs list with duplicate_of set where detected.
    """
    # Build lookup of existing jobs by normalised company key
    existing_by_company: dict[str, list["Job"]] = {}
    for job in existing_jobs:
        key = _normalize_company(job.company)
        existing_by_company.setdefault(key, []).append(job)

    for new_job in new_jobs:
        if new_job.duplicate_of:
            continue  # Already flagged
        new_co = _normalize_company(new_job.company)
        new_role = _normalize_role(new_job.role)

        # Check existing jobs from different sources
        candidates = existing_by_company.get(new_co, [])
        for existing in candidates:
            if existing.source == new_job.source:
                continue  # Same source — URL dedup handles it
            existing_role = _normalize_role(existing.role)
            if _similarity(new_role, existing_role) >= role_threshold:
                # Prefer the higher-scored job as canonical
                if existing.score >= new_job.score:
                    new_job.duplicate_of = existing.source_url
                else:
                    # New job is better — mark existing as duplicate (update later)
                    pass
                break

    return new_jobs
