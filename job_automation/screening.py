"""Unified screening — profile loading, question formatting, answer resolution."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

from .content.ai_client import AIClient
from .models import Job
from .resume_context import load_resume_text, screening_answer
from .screening_fields import profile_value_for_question

_TECHNICAL_ID = re.compile(r"^[a-z][a-z0-9_-]{0,24}$", re.I)
_SCREENING_HINT = re.compile(
    r"\b(years?|experience|ctc|salary|notice|relocate|authorized|visa|location|lpa)\b",
    re.I,
)


def format_question_for_ui(raw: str) -> str:
    """Turn a raw DOM label/context into a readable screening question."""
    if not raw:
        return ""

    text = raw.strip()
    if "\n" in text:
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]
        for line in lines:
            if "?" in line or _SCREENING_HINT.search(line):
                text = line
                break
        else:
            text = lines[0] if lines else text

    text = re.sub(r"\s+", " ", text).strip()

    if " | " in text:
        parts = [p.strip() for p in text.split(" | ") if p.strip()]
        with_question = [p for p in parts if "?" in p]
        if with_question:
            text = max(with_question, key=len)
        else:
            natural = [
                p for p in parts
                if len(p) > 12 and not _TECHNICAL_ID.match(p) and _SCREENING_HINT.search(p)
            ]
            if natural:
                text = natural[0]
            else:
                readable = [p for p in parts if not _TECHNICAL_ID.match(p) and len(p) > 3]
                text = readable[0] if readable else parts[0]

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 320:
        cut = text[:320]
        q_idx = cut.rfind("?")
        text = cut[: q_idx + 1] if q_idx > 40 else cut.rstrip() + "…"
    return text


def load_screening_profile(config: dict[str, Any], db=None) -> dict[str, Any]:
    """Merge config profile with DB + YAML screening answers."""
    profile = dict(config.get("profile", {}))
    custom: dict[str, str] = {}

    answers_path = Path(config.get("applier", {}).get("answers_file", "user_answers.yaml"))
    if answers_path.exists():
        try:
            custom.update(yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {})
        except Exception:
            pass

    if db is not None:
        try:
            custom.update(db.get_all_answers())
        except Exception:
            pass

    profile["custom_answers"] = custom
    return profile


async def resolve_screening_answer(
    question: str,
    job: Job,
    config: dict[str, Any],
    *,
    db=None,
    ai_client: Optional[AIClient] = None,
) -> Optional[str]:
    """
    Resolve a screening answer: rules → profile fields → DB → AI.
    Returns None when the bot should wait for the user.
    """
    if not question or not question.strip():
        return None

    profile = load_screening_profile(config, db=db)
    resume_text = load_resume_text(profile.get("resume_path", ""))
    formatted = format_question_for_ui(question)

    for q in dict.fromkeys([formatted, question.strip()]):
        if not q:
            continue

        ans = screening_answer(q, profile, resume_text, job.role, job.company)
        if ans:
            return ans

        profile_val = profile_value_for_question(q, profile)
        if profile_val:
            return profile_val

        if db is not None:
            try:
                stored = db.get_answer(q) or db.fuzzy_get_answer(q)
                if stored:
                    return stored
            except Exception:
                pass

    if ai_client is None:
        ai_client = AIClient(config)
    if ai_client.is_enabled():
        prompt_q = formatted or question.strip()
        ans = await ai_client.answer_screening_question(
            prompt_q, job, profile, resume_text
        )
        if ans:
            if db is not None:
                try:
                    db.save_answer(prompt_q, ans, source="ai")
                except Exception:
                    pass
            return ans

    return None