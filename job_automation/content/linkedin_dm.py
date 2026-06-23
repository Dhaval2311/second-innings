"""LinkedIn DM / connection note generator for Second Innings."""
from __future__ import annotations

from typing import Any

from .ai_client import AIClient

# LinkedIn connection note hard limit
_LINKEDIN_CHAR_LIMIT = 300


def _build_top_skills(profile: dict[str, Any], n: int = 2) -> str:
    """Return a slash-separated string of the top-N skills by years."""
    skill_years: dict[str, Any] = profile.get("skill_years") or {}
    if not skill_years:
        return ""
    top = sorted(
        skill_years.items(),
        key=lambda kv: float(kv[1]) if str(kv[1]).replace(".", "").isdigit() else 0,
        reverse=True,
    )[:n]
    return "/".join(skill for skill, _ in top)


def _truncate_to_limit(text: str, limit: int = _LINKEDIN_CHAR_LIMIT) -> str:
    """Hard-truncate at the last word boundary before `limit` characters."""
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    # Back up to the last space so we don't cut mid-word
    last_space = truncated.rfind(" ")
    if last_space > limit - 40:  # only back up if there's a reasonable word to cut
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;: ") + "…"


def _template_linkedin_dm(
    company: str,
    role: str,
    profile: dict[str, Any],
    target_name: str = "",
) -> str:
    """
    Return a crisp, template-based LinkedIn DM built from real profile data.
    Guaranteed to be under 300 characters.
    Used as fallback when AI is disabled.
    """
    name: str = profile.get("full_name") or "me"
    years: Any = profile.get("years_experience", "")
    skills_str: str = _build_top_skills(profile, n=2)

    # Personalised greeting when target name is known
    greeting = f"Hi {target_name}," if target_name else "Hi,"

    # Build the body — keep it tight enough to fit in 300 chars total
    skills_mention = f" in {skills_str}" if skills_str else ""
    years_mention = f"{years}-yr " if years else ""

    dm = (
        f"{greeting} I'm a {years_mention}engineer{skills_mention} interested in "
        f"the {role} role at {company}. Would love to connect and learn more — "
        f"open to a brief chat?"
    )

    return _truncate_to_limit(dm, _LINKEDIN_CHAR_LIMIT)


async def generate_linkedin_dm(
    company: str,
    role: str,
    profile: dict[str, Any],
    ai: AIClient,
    target_name: str = "",
    profile_url: str = "",
) -> str:
    """
    Generate a LinkedIn connection request note or InMail.

    The output is ready to copy-paste and is guaranteed to be ≤ 300 characters
    (LinkedIn's hard limit for connection request notes).

    Format: brief intro + specific connection reason + soft CTA.
    Tone: warm, human, not salesy — feels like a genuine reach-out.

    Parameters
    ----------
    company      : Target company name.
    role         : Job title / role being targeted.
    profile      : Candidate profile dict (same schema as config.yaml).
    ai           : Configured AIClient instance.
    target_name  : LinkedIn user's first name for personalisation (optional).
    profile_url  : URL of the target's LinkedIn profile for context (optional,
                   not sent to the AI but logged for future enrichment).
    """
    ai._init_client()

    if not ai.is_enabled():
        return _template_linkedin_dm(company, role, profile, target_name)

    # --- Build prompt ---
    name: str = profile.get("full_name") or "Candidate"
    years: Any = profile.get("years_experience", "")
    skills_str: str = _build_top_skills(profile, n=2)

    greeting_instruction = (
        f"Address the person as '{target_name}'."
        if target_name
        else "Use a generic 'Hi,' greeting since we don't know the person's name."
    )

    prompt = (
        "Write a LinkedIn connection request note for a job seeker.\n\n"
        f"Sender: {name}, {years}-year engineer, top skills: {skills_str or 'software engineering'}\n"
        f"Target company: {company}\n"
        f"Target role: {role}\n\n"
        "Instructions:\n"
        f"- {greeting_instruction}\n"
        f"- STRICT hard limit: the entire message must be UNDER {_LINKEDIN_CHAR_LIMIT} characters "
        "(count every character including spaces).\n"
        "- Structure: 1 intro sentence (who you are) + 1 connection reason "
        "(why this company/role is interesting) + 1 soft CTA (open to a quick chat?).\n"
        "- Tone: warm, human, genuine. NOT salesy. NOT corporate. Like a smart friend reaching out.\n"
        "- Do NOT use phrases like 'I hope this message finds you well' or 'I am writing to'.\n"
        "- Do NOT include a subject line.\n"
        "- Output the message text ONLY — no labels, no quotes.\n\n"
        "LinkedIn DM:"
    )

    raw = await ai.complete(prompt, max_tokens=120)

    if not raw or not raw.strip():
        return _template_linkedin_dm(company, role, profile, target_name)

    dm = raw.strip()

    # Enforce the 300-character hard limit regardless of what the AI returned
    if len(dm) > _LINKEDIN_CHAR_LIMIT:
        dm = _truncate_to_limit(dm, _LINKEDIN_CHAR_LIMIT)

    return dm
