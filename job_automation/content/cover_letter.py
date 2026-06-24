"""Cover letter generator for Second Innings."""
from __future__ import annotations

import re
import textwrap
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Job

from .ai_client import AIClient


def _build_skills_sentence(profile: dict[str, Any]) -> str:
    """Return a readable sentence about the candidate's top skills."""
    skill_years: dict[str, Any] = profile.get("skill_years") or {}
    if not skill_years:
        return ""
    # Sort by years descending, take top 4
    top = sorted(
        skill_years.items(),
        key=lambda kv: float(kv[1]) if str(kv[1]).replace(".", "").isdigit() else 0,
        reverse=True,
    )[:4]
    parts = [f"{skill} ({yrs} yrs)" for skill, yrs in top]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _template_cover_letter(job: "Job", profile: dict[str, Any]) -> str:
    """
    Return a polished, template-based cover letter built from real profile data.
    Used as fallback when AI is disabled.
    """
    name: str = profile.get("full_name") or "Candidate"
    years: Any = profile.get("years_experience", "")
    location: str = profile.get("current_location", "")
    skills_line: str = _build_skills_sentence(profile)
    notice: Any = profile.get("notice_period_days", "")
    notice_str: str = "immediate" if not notice or str(notice).strip() in ("0", "") else f"{notice} days"

    # Pull a short excerpt of the JD for matching context
    jd_excerpt: str = (job.jd_text or "")[:300].strip()
    jd_note: str = ""
    if jd_excerpt:
        # Grab the first complete sentence from JD for a specific reference
        first_sentence = re.split(r"(?<=[.!?])\s", jd_excerpt)[0]
        jd_note = (
            f" Your posting highlights: \"{first_sentence[:120]}\" "
            f"— this maps closely to my background."
        )

    skills_para: str = (
        f"I bring {years} years of experience"
        f"{f', with deep expertise in {skills_line}' if skills_line else ''}."
    )

    para1 = (
        f"{name} here — a {years}-year engineering professional"
        f"{f' based in {location}' if location else ''} applying for the "
        f"{job.role} role at {job.company}. I'm drawn to this position because it aligns "
        f"precisely with the technical work I've been doing and the problems I want to solve next."
    )

    para2 = (
        f"{skills_para}{jd_note} "
        f"Throughout my career I've consistently delivered outcomes by translating complex "
        f"requirements into reliable, scalable systems — not just writing code, but owning results."
    )

    para3 = (
        f"I'd welcome the opportunity to discuss how my background can contribute to "
        f"{job.company}'s goals. I'm available to join with {notice_str} notice. "
        f"Happy to connect at your convenience — looking forward to the conversation."
    )

    body = "\n\n".join([para1, para2, para3])
    return textwrap.dedent(body).strip()


async def generate_cover_letter(
    job: "Job",
    profile: dict[str, Any],
    ai: AIClient,
    resume_text: str = "",
) -> str:
    """
    Generate a professional 3-paragraph cover letter.

    Strategy:
    - If AI is enabled: build a rich prompt with job + profile + JD excerpt and
      instruct the model to produce a tight, specific, ~250-word letter.
    - If AI is disabled: return a well-written template cover letter built from
      actual profile data (never returns an empty string).

    Tone: confident and specific. No filler openers like "I am writing to express".
    Word ceiling: 250 words.
    """
    ai._init_client()

    if not ai.is_enabled():
        return _template_cover_letter(job, profile)

    # --- Build profile summary for the prompt ---
    name: str = profile.get("full_name") or "Candidate"
    years: Any = profile.get("years_experience", "")
    location: str = profile.get("current_location", "")
    skills_line: str = _build_skills_sentence(profile)
    notice: Any = profile.get("notice_period_days", "")
    notice_str: str = "immediate" if not notice or str(notice).strip() in ("0", "") else f"{notice} days"

    profile_block = (
        f"Name: {name}\n"
        f"Years of experience: {years}\n"
        f"Location: {location}\n"
        f"Top skills: {skills_line or 'See resume'}\n"
        f"Notice period: {notice_str}\n"
    )
    if resume_text:
        profile_block += f"\nResume excerpt:\n{resume_text[:600]}\n"

    jd_block = ""
    if job.jd_text:
        jd_block = f"\nJob description excerpt:\n{job.jd_text[:700]}\n"

    prompt = (
        "Write a professional cover letter for the following job application.\n\n"
        f"Candidate profile:\n{profile_block}\n"
        f"Job: {job.role} at {job.company}\n"
        f"{jd_block}\n"
        "Instructions:\n"
        "- Exactly 3 paragraphs, under 250 words total.\n"
        "- DO NOT use these openers: 'I am writing to express', 'I hope this finds you', "
        "'I am excited to apply', 'I am pleased to'. Start with the candidate's name or a "
        "specific observation about the role.\n"
        "- Paragraph 1: Who the candidate is + one specific reason THIS company/role is the right next step "
        f"(reference something concrete about {job.company} or the {job.role} role — not generic praise).\n"
        "- Paragraph 2: 2-3 specific skills/achievements from the profile that directly address the JD. "
        "Use actual numbers or skill names from the profile, not vague claims.\n"
        "- Paragraph 3: One sentence on value + availability + direct CTA.\n"
        "- Tone: confident, first-person, direct. No buzzwords like 'leverage', 'synergy', 'passionate'.\n"
        "- Body paragraphs only — no 'Dear Hiring Manager', no 'Sincerely'.\n\n"
        "Cover letter:"
    )

    result = await ai.complete(prompt, max_tokens=450)

    # If AI call failed or returned nothing, fall back to template
    if not result or not result.strip():
        return _template_cover_letter(job, profile)

    return result.strip()
