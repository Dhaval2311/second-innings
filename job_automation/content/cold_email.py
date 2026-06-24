"""Cold outreach email generator for Second Innings."""
from __future__ import annotations

import textwrap
from typing import Any

from .ai_client import AIClient


def _build_top_skills(profile: dict[str, Any], n: int = 3) -> str:
    """Return a comma-separated string of the top-N skills by experience years."""
    skill_years: dict[str, Any] = profile.get("skill_years") or {}
    if not skill_years:
        return ""
    top = sorted(
        skill_years.items(),
        key=lambda kv: float(kv[1]) if str(kv[1]).replace(".", "").isdigit() else 0,
        reverse=True,
    )[:n]
    return "/".join(skill for skill, _ in top)


def _template_cold_email(
    company: str,
    role: str,
    profile: dict[str, Any],
    hiring_manager: str = "",
) -> dict[str, str]:
    """
    Return a tight, template-based cold email using real profile data.
    Used as fallback when AI is disabled.
    Returns {'subject': ..., 'body': ...}.
    """
    name: str = profile.get("full_name") or "Candidate"
    years: Any = profile.get("years_experience", "")
    skills_str: str = _build_top_skills(profile, n=3)
    email: str = profile.get("email", "")
    linkedin: str = profile.get("linkedin_url", "")

    # Subject: specific, scannable, mentions skills + company
    if skills_str and years:
        subject = f"{role} — {years}-yr {skills_str} engineer — {company}"
    elif years:
        subject = f"{role} — {years} yrs experience — {company}"
    else:
        subject = f"Interested in {role} at {company} — {name}"

    # Greeting
    greeting = f"Hi {hiring_manager}," if hiring_manager else "Hi,"

    # Body paragraphs
    intro = (
        f"I'm {name}, a {years}-year engineer specialising in "
        f"{skills_str or role} — I came across {company} and "
        f"wanted to reach out directly about the {role} opportunity."
    )

    experience_line = (
        f"I've spent the last {years} years building and shipping "
        f"{'systems with ' + skills_str if skills_str else 'production-grade software'}, "
        f"with a track record of owning outcomes end-to-end rather than just completing tickets."
    )

    cta = (
        f"Would you be open to a 20-minute call to explore fit? "
        f"{'You can reach me at ' + email + '. ' if email else ''}"
        f"{'My LinkedIn: ' + linkedin if linkedin else ''}"
    ).strip()

    body = textwrap.dedent(f"""\
{greeting}

{intro}

{experience_line}

{cta}

Best,
{name}""")

    return {"subject": subject.strip(), "body": body.strip()}


async def generate_cold_email(
    company: str,
    role: str,
    profile: dict[str, Any],
    ai: AIClient,
    hiring_manager: str = "",
    jd_text: str = "",
) -> dict[str, str]:
    """
    Generate a cold outreach email targeting a specific company and role.

    Returns a dict with two keys:
      'subject' — specific, skill-forward subject line (≤ 10 words)
      'body'    — email body, max 150 words, structured as:
                  greeting → 1 intro sentence → 1-2 experience sentences → CTA

    Parameters
    ----------
    company         : Target company name.
    role            : Job title / role being targeted.
    profile         : Candidate profile dict (same schema as config.yaml).
    ai              : Configured AIClient instance.
    hiring_manager  : Recipient name for personalised greeting (optional).
    jd_text         : Job description text for context (optional).
    """
    ai._init_client()

    if not ai.is_enabled():
        return _template_cold_email(company, role, profile, hiring_manager)

    # --- Build the prompt ---
    name: str = profile.get("full_name") or "Candidate"
    years: Any = profile.get("years_experience", "")
    skills_str: str = _build_top_skills(profile, n=4)
    email: str = profile.get("email", "")
    linkedin: str = profile.get("linkedin_url", "")

    profile_block = (
        f"Name: {name}\n"
        f"Years of experience: {years}\n"
        f"Top skills: {skills_str or 'See resume'}\n"
        f"Email: {email}\n"
        f"LinkedIn: {linkedin}\n"
    )

    jd_block = ""
    if jd_text:
        jd_block = f"\nJob description excerpt:\n{jd_text[:500]}\n"

    greeting_instruction = (
        f"Address the email to '{hiring_manager}'."
        if hiring_manager
        else "Use a generic 'Hi,' greeting since we don't know the recipient's name."
    )

    prompt = (
        "Write a cold outreach email for a job seeker. "
        "Return EXACTLY two sections separated by '---':\n"
        "Section 1: Subject line (one line, no label)\n"
        "Section 2: Email body (greeting through sign-off)\n\n"
        f"Candidate profile:\n{profile_block}\n"
        f"Target company: {company}\n"
        f"Target role: {role}\n"
        f"{jd_block}\n"
        "Instructions:\n"
        f"- {greeting_instruction}\n"
        f"- Subject line: specific, include actual skill names and years + '{company}', max 10 words. "
        "Example: 'Backend Engineer — 6 yrs Go/Postgres — Acme Corp'\n"
        "- Body max 150 words. Structure:\n"
        f"  1. One sentence: who you are (name, years, top skills) and why you're reaching out to {company} specifically.\n"
        "  2. One sentence: the most relevant concrete experience for this role — use a real number or outcome.\n"
        "  3. One sentence: CTA for a 20-min call. No 'I hope this email finds you well' or similar.\n"
        "- Sign-off: include name, email, and LinkedIn if provided.\n"
        "- Tone: direct, peer-to-peer, zero sales language. No 'synergy', 'passionate', 'leverage'.\n"
        "- Do NOT start body with 'I am writing to'.\n\n"
        "Output:"
    )

    raw = await ai.complete(prompt, max_tokens=400)

    if not raw or not raw.strip():
        return _template_cold_email(company, role, profile, hiring_manager)

    # Parse the two-section response
    parts = raw.strip().split("---", maxsplit=1)
    if len(parts) == 2:
        subject = parts[0].strip().lstrip("Subject:").strip()
        body = parts[1].strip().lstrip("Body:").strip()
    else:
        # Fallback: treat first line as subject, rest as body
        lines = raw.strip().splitlines()
        subject = lines[0].strip().lstrip("Subject:").strip() if lines else ""
        body = "\n".join(lines[1:]).strip().lstrip("Body:").strip() if len(lines) > 1 else ""

    # Last-resort fallback if parsing produced empty values
    if not subject or not body:
        return _template_cold_email(company, role, profile, hiring_manager)

    return {"subject": subject, "body": body}
