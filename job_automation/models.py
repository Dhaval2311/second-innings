from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


TRACKER_COLUMNS = [
    "status",
    "source",
    "company",
    "role",
    "location",
    "experience",
    "posted",
    "openings",
    "applicants",
    "score",
    "ai_score",
    "apply_type",
    "work_mode",
    "source_url",
    "core_match",
    "bonus_match",
    "notes",
    "next_action",
    "applied_date",
    "duplicate_of",
]

ApplyType = Literal["easy_apply", "company_site", "unknown"]


@dataclass
class Job:
    source: str
    company: str
    role: str
    source_url: str
    location: str = ""
    experience: str = ""
    posted: str = ""
    openings: str = ""
    applicants: str = ""
    work_mode: str = ""
    skills: list[str] = field(default_factory=list)
    score: int = 0
    ai_score: Optional[int] = None
    apply_type: ApplyType = "unknown"
    status: str = "new"
    core_match: str = ""
    bonus_match: str = ""
    notes: str = ""
    next_action: str = ""
    applied_date: str = ""
    search_label: str = ""
    jd_text: str = ""           # full job description text (from enrich step)
    duplicate_of: str = ""      # source_url of canonical job if cross-source dup
    cover_letter: str = ""      # generated cover letter

    def to_row(self) -> dict[str, str]:
        return {
            "status": self.status,
            "source": self.source,
            "company": self.company,
            "role": self.role,
            "location": self.location,
            "experience": self.experience,
            "posted": self.posted,
            "openings": self.openings,
            "applicants": self.applicants,
            "score": str(self.score),
            "ai_score": str(self.ai_score) if self.ai_score is not None else "",
            "apply_type": self.apply_type,
            "work_mode": self.work_mode,
            "source_url": self.source_url,
            "core_match": self.core_match,
            "bonus_match": self.bonus_match,
            "notes": self.notes,
            "next_action": self.next_action,
            "applied_date": self.applied_date,
            "duplicate_of": self.duplicate_of,
        }

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Job":
        core = row.get("core_match", "")
        skills = [s.strip() for s in core.split(",") if s.strip()]
        ai_score_raw = row.get("ai_score", "")
        return cls(
            source=row.get("source", ""),
            company=row.get("company", ""),
            role=row.get("role", ""),
            source_url=row.get("source_url", ""),
            location=row.get("location", ""),
            experience=row.get("experience", ""),
            posted=row.get("posted", ""),
            openings=row.get("openings", ""),
            applicants=row.get("applicants", ""),
            work_mode=row.get("work_mode", ""),
            skills=skills,
            score=int(row.get("score") or 0),
            ai_score=int(ai_score_raw) if ai_score_raw.strip().isdigit() else None,
            apply_type=row.get("apply_type", "unknown"),  # type: ignore[arg-type]
            status=row.get("status", "new"),
            core_match=core,
            bonus_match=row.get("bonus_match", ""),
            notes=row.get("notes", ""),
            next_action=row.get("next_action", ""),
            applied_date=row.get("applied_date", ""),
            duplicate_of=row.get("duplicate_of", ""),
        )


@dataclass
class ApplyResult:
    success: bool
    message: str
    needs_human: bool = False
    already_applied: bool = False
    pending_external: bool = False
    needs_user_input: bool = False
    tracker_status: str = ""
    unknown_questions: list[str] = field(default_factory=list)


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")