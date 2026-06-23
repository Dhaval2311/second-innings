from __future__ import annotations

import re


def question_context(text: str) -> str:
    return " ".join(text.lower().split())


def is_experience_question(q: str) -> bool:
    ql = question_context(q)
    if "notice" in ql:
        return False
    if "ctc" in ql or "salary" in ql or "compensation" in ql or "lacs" in ql or "lac" in ql:
        return False
    return bool(
        re.search(r"\b(years?|experience)\b", ql)
        and re.search(r"\b(how many|years?|experience|yoe)\b", ql)
    )


def is_current_ctc_question(q: str) -> bool:
    ql = question_context(q)
    if not any(k in ql for k in ["ctc", "salary", "compensation", "package", "lacs", "lac", "per annum"]):
        return False
    return "current" in ql or "present" in ql or ("ctc" in ql and "expected" not in ql and "desired" not in ql)


def is_expected_ctc_question(q: str) -> bool:
    ql = question_context(q)
    if not any(k in ql for k in ["ctc", "salary", "compensation", "package", "lacs", "lac", "per annum"]):
        return False
    return any(k in ql for k in ["expected", "expecting", "desired", "target"])


def is_notice_question(q: str) -> bool:
    return "notice" in question_context(q)


def is_choice_question(q: str) -> bool:
    ql = question_context(q)
    return any(
        k in ql
        for k in [
            "notice",
            "living",
            "located",
            "relocate",
            "residing",
            "authorized",
            "visa",
            "sponsorship",
            "bangalore",
            "bengaluru",
            "hyderabad",
            "pune",
            "chennai",
            "delhi",
            "gurugram",
            "noida",
            "mumbai",
            "yes or no",
        ]
    )


def profile_value_for_question(q: str, profile: dict) -> str | None:
    """Map a question/context string to the correct profile value — never mix CTC with years."""
    ql = question_context(q)
    if is_current_ctc_question(q):
        return str(profile.get("current_ctc_lpa", ""))
    if is_expected_ctc_question(q):
        return str(profile.get("expected_ctc_lpa", ""))
    if is_notice_question(q):
        return str(profile.get("notice_period_days", "0"))
    if is_experience_question(q):
        skill_years = profile.get("skill_years", {}) or {}
        for skill, yrs in skill_years.items():
            if skill.lower() in ql:
                return str(yrs)
        return str(profile.get("years_experience", 7))
    return None