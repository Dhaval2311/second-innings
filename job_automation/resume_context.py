from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .screening_fields import is_experience_question


@lru_cache(maxsize=1)
def load_resume_text(resume_path: str) -> str:
    path = Path(resume_path).expanduser()
    if not path.exists():
        return ""

    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def pitch_for_role(role: str, company: str, profile: dict, resume_text: str) -> str:
    years = profile.get("years_experience", 7)
    skills = "SQL, Python, Spark/PySpark, ETL/ELT, data warehousing, and cloud data platforms"
    return (
        f"I bring {years} years of experience across data engineering and analytics, with hands-on "
        f"work in {skills}. My background includes building reliable pipelines, data quality checks, "
        f"and analytics enablement for high-volume platforms, which aligns well with the {role} role "
        f"at {company}."
    )


def _city_in_question(question: str) -> str | None:
    cities = [
        "mumbai",
        "bangalore",
        "bengaluru",
        "hyderabad",
        "pune",
        "chennai",
        "delhi",
        "gurugram",
        "gurgaon",
        "noida",
        "kolkata",
        "singapore",
        "london",
        "amsterdam",
        "berlin",
        "stockholm",
    ]
    ql = question.lower()
    for city in cities:
        if city in ql:
            return city
    return None


def screening_answer(
    question: str,
    profile: dict,
    resume_text: str,
    role: str,
    company: str,
) -> str | None:
    """Best-effort answer for application screening questions."""
    q = question.lower().strip()
    if not q:
        return None

    # Strip (options: ...) from the question for matching purposes
    q_clean = re.sub(r'\s*\(options:.*?\)', '', q).strip()

    custom = profile.get("custom_answers", {}) or {}
    for key in sorted(custom.keys(), key=lambda k: len(k), reverse=True):
        kl = key.lower().strip()
        kl_clean = re.sub(r'\s*\(options:.*?\)', '', kl).strip()
        
        # Exact match (with or without options)
        if kl == q or kl_clean == q_clean:
            return str(custom[key])
            
        # Substring match (ensure at least 12 chars to avoid false positives)
        if len(kl_clean) >= 12 and kl_clean in q_clean:
            return str(custom[key])
        if len(q_clean) >= 12 and q_clean in kl_clean:
            return str(custom[key])

    years = str(profile.get("years_experience", 7))
    current_ctc = str(profile.get("current_ctc_lpa", ""))
    expected_ctc = str(profile.get("expected_ctc_lpa", ""))
    notice = str(profile.get("notice_period_days", "0"))
    location = profile.get("current_location", "Mumbai")

    if any(k in q for k in ["years of experience", "years do you have", "how many years", "total experience"]):
        return years
    if "experience do you have in" in q or "years of experience do you have in" in q:
        skill_years = profile.get("skill_years", {}) or {}
        for skill, yrs in skill_years.items():
            if skill.lower() in q:
                return str(yrs)
        if "python" in q:
            return years
        if "sql" in q:
            return years
        if any(s in q for s in ["spark", "pyspark", "hadoop", "kafka", "etl", "airflow", "aws", "azure"]):
            return years
    if re.search(r"\bexperience\b", q) and any(k in q for k in ["year", "how long", "how many"]):
        return years
    if any(k in q for k in ["sql", "python", "spark", "pyspark", "etl", "data engineer"]) and "year" in q:
        return years

    if "residing in" in q and "or willing to relocate" in q:
        return profile.get("willing_to_relocate", "Yes")

    ctc_markers = ["ctc", "salary", "compensation", "package", "lpa", "lacs", "lac", "per annum"]
    if ("current" in q or "present" in q) and any(k in q for k in ctc_markers):
        return current_ctc
    if any(k in q for k in ["expected", "expecting", "desired", "target"]) and any(k in q for k in ctc_markers):
        return expected_ctc
    if any(k in q for k in ctc_markers) and "notice" not in q:
        if "current" in q or "present" in q:
            return current_ctc
        if "expected" in q or "desired" in q:
            return expected_ctc
        return current_ctc or expected_ctc

    if "notice" in q:
        return notice

    if any(k in q for k in ["willing to relocate", "open to relocate", "ready to relocate", "relocate"]):
        return profile.get("willing_to_relocate", "Yes")

    city = _city_in_question(q)
    if city and any(k in q for k in ["living in", "located in", "currently in", "based in", "residing in", "work in"]):
        current = location.lower()
        return "Yes" if city in current or (city == "mumbai" and "mumbai" in current) else "No"

    if any(k in q for k in ["current location", "where do you live", "your location", "city are you", "location city"]):
        return location

    if any(k in q for k in ["authorized", "authorised", "legally eligible", "work permit", "right to work"]):
        return profile.get("work_authorization", "Yes")
    if any(k in q for k in ["sponsorship", "visa sponsor", "require immigration"]):
        return profile.get("visa_sponsorship_required", "No")

    if any(k in q for k in ["hybrid", "onsite", "on-site", "office", "in-person", "work from office"]):
        return profile.get("comfortable_onsite", "Yes")
    if "remote" in q and any(k in q for k in ["comfortable", "willing", "open", "prefer"]):
        return profile.get("comfortable_remote", "Yes")

    if any(k in q for k in ["start date", "join", "availability", "when can you"]):
        return profile.get("earliest_start", "Immediately")

    if any(k in q for k in ["email", "e-mail"]):
        return profile.get("email", "")
    if any(k in q for k in ["phone", "mobile", "contact number", "whatsapp"]):
        return profile.get("phone", "")
    if any(k in q for k in ["full name", "first name", "last name", "your name"]) or q in {"name"}:
        return profile.get("full_name", "")
    if "linkedin" in q and "url" in q:
        return profile.get("linkedin_url", "") or "N/A"
    if any(k in q for k in ["portfolio", "github", "website"]):
        return profile.get("portfolio_url", "") or "N/A"

    if any(k in q for k in ["english", "communication skill", "fluent"]):
        return profile.get("english_proficiency", "Yes")

    if any(k in q for k in ["why", "fit", "about yourself", "cover", "summary", "describe", "motivat", "interest"]):
        return pitch_for_role(role, company, profile, resume_text)

    if resume_text and any(k in q for k in ["skill", "technology", "tool", "stack", "proficien"]):
        return resume_text[:1200]

    if is_experience_question(q):
        return years

    if "?" in q and any(k in q for k in ["why", "fit", "describe", "explain", "tell us"]):
        return pitch_for_role(role, company, profile, resume_text)

    return None


def answer_from_context(question: str, profile: dict, resume_text: str, role: str, company: str) -> str | None:
    return screening_answer(question, profile, resume_text, role, company)