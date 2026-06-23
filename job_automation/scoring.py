"""Updated scoring module — uses jd_text, normalised 0-100 score."""
from __future__ import annotations

from .models import Job
from .content.ai_client import AIClient
from .resume_context import load_resume_text


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("/", " ").replace("-", " ").split())


async def score_job(job: Job, config: dict) -> Job:
    """
    Score a job based on keyword matches in role, skills, AND job description text.
    Score is normalised to 0–100.
    """
    ai_client = AIClient(config)
    resume_path = config.get("profile", {}).get("resume_path", "")
    resume_text = load_resume_text(resume_path)
    scoring = config.get("scoring", {})
    primary = [k.lower() for k in scoring.get("primary_keywords", [])]
    bonus = [k.lower() for k in scoring.get("bonus_keywords", [])]
    priority_threshold = int(scoring.get("priority_threshold", 75))
    shortlist_threshold = int(scoring.get("shortlist_threshold", 45))

    # Build full text blob — jd_text is now included
    blob = normalize(
        " ".join([
            job.role,
            job.company,
            job.location,
            job.experience,
            " ".join(job.skills),
            job.jd_text[:2000],   # cap to avoid runaway matching
            job.notes,
        ])
    )

    matched_primary = [k for k in primary if k in blob]
    matched_bonus = [k for k in bonus if k in blob]

    # Raw score
    raw = len(matched_primary) * 5 + len(matched_bonus) * 2

    # Role title bonus
    if any(t in blob for t in ["data engineer", "senior data analyst", "analytics engineer"]):
        raw += 10

    # Remote bonus
    if "remote" in blob:
        raw += 3

    # Preferred locations bonus
    preferred_locations = [
        loc.strip().lower()
        for loc in config.get("profile", {}).get("preferred_locations", [])
        if loc.strip()
    ]
    if preferred_locations and any(loc in blob for loc in preferred_locations):
        raw += 8

    # Normalise to 0-100 based on a theoretical max
    THEORETICAL_MAX = 40
    normalised = min(round((raw / THEORETICAL_MAX) * 100), 100)

    ai_score = None
    if ai_client.is_enabled():
        ai_score = await ai_client.score_job_relevance(job, resume_text)

    job.score = ai_score if ai_score is not None else normalised
    job.core_match = ", ".join(matched_primary)
    job.bonus_match = ", ".join(matched_bonus)

    # Status assignment — only if not in a preserved terminal state
    preserved_statuses = {
        "pending_external", "applied", "applied_needs_verification",
        "needs_human", "needs_user_input", "company_site_pending", "failed",
    }
    if job.status not in preserved_statuses:
        if job.score >= priority_threshold:
            job.status = "priority"
        elif job.score >= shortlist_threshold:
            job.status = "shortlist"
        else:
            job.status = "review"

    if not job.next_action:
        job.next_action = "Review and apply if relevant"

    return job