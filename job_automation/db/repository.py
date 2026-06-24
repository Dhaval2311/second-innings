"""SQLite repository — all DB read/write operations for Second Innings."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Optional

from ..models import Job, now_str
from ..screening import format_question_for_ui
from .schema import SCHEMA_SQL


class JobRepository:
    """Thread-safe SQLite repository. All public methods are synchronous."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    # Columns added after the original schema shipped — applied via ALTER TABLE
    # to existing DBs, since CREATE TABLE IF NOT EXISTS won't add them.
    _JOBS_NEW_COLUMNS = {
        "external_url": "TEXT DEFAULT ''",
        "contact_name": "TEXT DEFAULT ''",
        "contact_email": "TEXT DEFAULT ''",
        "contact_profile_url": "TEXT DEFAULT ''",
    }

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for col, decl in self._JOBS_NEW_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def upsert_job(self, job: Job) -> bool:
        """Insert or update a job by source_url. Returns True if new."""
        row = job.to_row()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, status, applied_date FROM jobs WHERE source_url = ?",
                (job.source_url,),
            ).fetchone()

            if existing:
                # Preserve terminal statuses across re-scrapes
                preserved = {"applied", "pending_external", "needs_human",
                             "needs_user_input", "company_site_pending", "failed"}
                new_status = job.status
                if existing["status"] in preserved:
                    new_status = existing["status"]
                new_applied = existing["applied_date"] or job.applied_date

                conn.execute(
                    """UPDATE jobs SET
                        company=?, role=?, location=?, experience=?, posted=?,
                        work_mode=?, apply_type=?, status=?, score=?, ai_score=?,
                        jd_text=CASE WHEN ?='' THEN jd_text ELSE ? END,
                        core_match=?, bonus_match=?, notes=?, next_action=?,
                        applied_date=?, search_label=?, duplicate_of=?,
                        updated_at=?
                    WHERE source_url=?""",
                    (
                        job.company, job.role, job.location, job.experience,
                        job.posted, job.work_mode, job.apply_type, new_status,
                        job.score, job.ai_score,
                        job.jd_text, job.jd_text,
                        job.core_match, job.bonus_match, job.notes,
                        job.next_action, new_applied, job.search_label,
                        job.duplicate_of, now_str(), job.source_url,
                    ),
                )
                return False
            else:
                conn.execute(
                    """INSERT INTO jobs
                        (source, company, role, source_url, location, experience,
                         posted, openings, applicants, work_mode, apply_type, status,
                         score, ai_score, jd_text, core_match, bonus_match, notes,
                         next_action, applied_date, search_label, duplicate_of,
                         scraped_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        job.source, job.company, job.role, job.source_url,
                        job.location, job.experience, job.posted, job.openings,
                        job.applicants, job.work_mode, job.apply_type, job.status,
                        job.score, job.ai_score, job.jd_text, job.core_match,
                        job.bonus_match, job.notes, job.next_action,
                        job.applied_date, job.search_label, job.duplicate_of,
                        now_str(), now_str(),
                    ),
                )
                return True

    def get_jobs(
        self,
        status: Optional[str | list[str]] = None,
        apply_type: Optional[str] = None,
        source: Optional[str] = None,
        exclude_duplicate: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Job]:
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            if isinstance(status, list):
                placeholders = ",".join("?" * len(status))
                conditions.append(f"status IN ({placeholders})")
                params.extend(status)
            else:
                conditions.append("status = ?")
                params.append(status)

        if apply_type:
            conditions.append("apply_type = ?")
            params.append(apply_type)

        if source:
            conditions.append("source = ?")
            params.append(source)

        if exclude_duplicate:
            conditions.append("(duplicate_of = '' OR duplicate_of IS NULL)")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY score DESC, scraped_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def get_job_by_url(self, url: str) -> Optional[Job]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE source_url = ?", (url,)).fetchone()
        return self._row_to_job(row) if row else None

    def update_job_status(
        self,
        url: str,
        status: str,
        applied_date: str = "",
        note: str = "",
        next_action: str = "",
    ) -> None:
        with self._conn() as conn:
            current = conn.execute(
                "SELECT notes FROM jobs WHERE source_url = ?", (url,)
            ).fetchone()
            existing_notes = current["notes"] if current else ""
            new_notes = f"{existing_notes}; {note}".strip("; ") if note else existing_notes
            conn.execute(
                """UPDATE jobs SET status=?, applied_date=CASE WHEN ?!='' THEN ? ELSE applied_date END,
                   notes=?, next_action=CASE WHEN ?!='' THEN ? ELSE next_action END, updated_at=?
                   WHERE source_url=?""",
                (status, applied_date, applied_date, new_notes,
                 next_action, next_action, now_str(), url),
            )

    def set_external_url(self, url: str, external_url: str) -> None:
        """Persist the resolved external (company-site/ATS) apply URL for a job."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET external_url=?, updated_at=? WHERE source_url=?",
                (external_url, now_str(), url),
            )

    def set_contact(
        self, url: str, name: str = "", email: str = "", profile_url: str = ""
    ) -> None:
        """Persist a discovered hiring-manager/recruiter contact for a job."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE jobs SET contact_name=?, contact_email=?, contact_profile_url=?,
                   updated_at=? WHERE source_url=?""",
                (name, email, profile_url, now_str(), url),
            )

    def get_job_id(self, url: str) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE source_url = ?", (url,)).fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------
    # Pipeline stats (for dashboard)
    # ------------------------------------------------------------------

    def get_pipeline_stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            easy_total = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE apply_type='easy_apply'"
            ).fetchone()[0]
            easy_applied = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE apply_type='easy_apply' AND status='applied'"
            ).fetchone()[0]
            company_total = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE apply_type='company_site'"
            ).fetchone()[0]
            company_applied = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE apply_type='company_site' AND status='applied'"
            ).fetchone()[0]
            company_pending = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE apply_type='company_site' AND status='company_site_pending'"
            ).fetchone()[0]
            needs_human = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='needs_human'"
            ).fetchone()[0]
            needs_input = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='needs_user_input'"
            ).fetchone()[0]
            pending_answers = conn.execute(
                "SELECT COUNT(*) FROM pending_inputs WHERE status='waiting'"
            ).fetchone()[0]
        return {
            "total_scraped": total,
            "easy_apply_total": easy_total,
            "easy_apply_done": easy_applied,
            "company_site_total": company_total,
            "company_site_applied": company_applied,
            "company_site_pending": company_pending,
            "needs_human": needs_human,
            "needs_user_input": needs_input,
            "pending_answers": pending_answers,
        }

    def get_source_breakdown(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT source,
                       COUNT(*) as total,
                       SUM(CASE WHEN apply_type='easy_apply' THEN 1 ELSE 0 END) as easy_apply,
                       SUM(CASE WHEN apply_type='company_site' THEN 1 ELSE 0 END) as company_site,
                       SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) as applied,
                       SUM(CASE WHEN status IN ('priority','shortlist') THEN 1 ELSE 0 END) as high_priority
                   FROM jobs GROUP BY source ORDER BY total DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Screening answers
    # ------------------------------------------------------------------

    def get_answer(self, question: str) -> Optional[str]:
        """Exact match lookup for screening answer."""
        q_norm = _normalize_question(question)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT answer FROM screening_answers WHERE question = ?", (q_norm,)
            ).fetchone()
        return row["answer"] if row else None

    def fuzzy_get_answer(self, question: str) -> Optional[str]:
        """Fuzzy lookup — returns answer if question contains a stored key or vice versa."""
        q_norm = _normalize_question(question)
        with self._conn() as conn:
            rows = conn.execute("SELECT question, answer FROM screening_answers").fetchall()
        for row in rows:
            stored = row["question"]
            if stored in q_norm or q_norm in stored:
                return row["answer"]
        return None

    def save_answer(self, question: str, answer: str, source: str = "user") -> None:
        q_norm = _normalize_question(question)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO screening_answers (question, answer, source, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(question) DO UPDATE SET answer=excluded.answer,
                   source=excluded.source, updated_at=excluded.updated_at""",
                (q_norm, answer, source, now_str()),
            )

    def get_all_answers(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT question, answer FROM screening_answers").fetchall()
        return {r["question"]: r["answer"] for r in rows}

    def import_yaml_answers(self, yaml_path: Path) -> int:
        """One-time migration of user_answers.yaml → screening_answers table."""
        if not yaml_path.exists():
            return 0
        import yaml
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        count = 0
        for q, a in data.items():
            if q and a:
                existing = self.get_answer(str(q))
                if not existing:
                    self.save_answer(str(q), str(a), source="learned")
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Pending inputs (unknown questions during apply)
    # ------------------------------------------------------------------

    def log_pending_input(self, job_url: str, question: str, context: str = "") -> None:
        question = format_question_for_ui(question)
        if not question:
            return
        job_id = self.get_job_id(job_url)
        if not job_id:
            return
        with self._conn() as conn:
            # Avoid duplicate entries for same job+question
            existing = conn.execute(
                "SELECT id FROM pending_inputs WHERE job_id=? AND question=? AND status='waiting'",
                (job_id, question),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO pending_inputs (job_id, question, context) VALUES (?,?,?)",
                    (job_id, question, context),
                )

    def get_pending_inputs(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT pi.id, pi.question, pi.context, pi.status,
                          j.company, j.role, j.source_url, pi.created_at
                   FROM pending_inputs pi
                   JOIN jobs j ON j.id = pi.job_id
                   WHERE pi.status = 'waiting'
                   ORDER BY pi.created_at DESC""",
            ).fetchall()
        return [dict(r) for r in rows]

    def answer_pending_input(self, pending_id: int, answer: str) -> str | None:
        """Answer a pending input. Returns the question text if found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT question FROM pending_inputs WHERE id=?", (pending_id,)
            ).fetchone()
            if not row:
                return None
            question = row["question"]
            conn.execute(
                "UPDATE pending_inputs SET status='answered', answer=?, answered_at=? WHERE id=?",
                (answer, now_str(), pending_id),
            )
        # Auto-save to screening_answers so future applies use it
        self.save_answer(question, answer, source="user")
        return question

    def count_pending_inputs(self) -> int:
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM pending_inputs WHERE status='waiting'"
            ).fetchone()[0]

    def get_answered_input(self, pending_id: int) -> str | None:
        """Return the answer for a pending_input if it has been answered, else None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status, answer FROM pending_inputs WHERE id=?", (pending_id,)
            ).fetchone()
        if row and row["status"] == "answered":
            return row["answer"]
        return None

    def log_pending_input_returning_id(self, job_url: str, question: str, context: str = "") -> int | None:
        """Like log_pending_input but returns the new row id (or existing waiting id)."""
        question = format_question_for_ui(question)
        if not question:
            return None
        job_id = self.get_job_id(job_url)
        if not job_id:
            return None
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM pending_inputs WHERE job_id=? AND question=? AND status='waiting'",
                (job_id, question),
            ).fetchone()
            if existing:
                return existing["id"]
            cur = conn.execute(
                "INSERT INTO pending_inputs (job_id, question, context) VALUES (?,?,?)",
                (job_id, question, context),
            )
            return cur.lastrowid


    # ------------------------------------------------------------------
    # Content drafts
    # ------------------------------------------------------------------

    def save_content_draft(self, job_url: str, draft_type: str, content: str) -> None:
        job_id = self.get_job_id(job_url)
        if not job_id:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO content_drafts (job_id, type, content) VALUES (?,?,?)",
                (job_id, draft_type, content),
            )

    def get_content_drafts(self, job_url: str, draft_type: str | None = None) -> list[dict]:
        job_id = self.get_job_id(job_url)
        if not job_id:
            return []
        with self._conn() as conn:
            if draft_type:
                rows = conn.execute(
                    "SELECT * FROM content_drafts WHERE job_id=? AND type=? ORDER BY created_at DESC",
                    (job_id, draft_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM content_drafts WHERE job_id=? ORDER BY created_at DESC",
                    (job_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Scrape runs log
    # ------------------------------------------------------------------

    def log_scrape_run(
        self, source: str, label: str, found: int, new: int,
        duplicate: int, duration: float
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO scrape_runs
                   (source, label, jobs_found, jobs_new, jobs_duplicate, duration_seconds)
                   VALUES (?,?,?,?,?,?)""",
                (source, label, found, new, duplicate, round(duration, 2)),
            )

    def get_scrape_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scrape_runs ORDER BY run_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        d = dict(row)
        return Job(
            source=d.get("source", ""),
            company=d.get("company", ""),
            role=d.get("role", ""),
            source_url=d.get("source_url", ""),
            location=d.get("location", ""),
            experience=d.get("experience", ""),
            posted=d.get("posted", ""),
            openings=d.get("openings", ""),
            applicants=d.get("applicants", ""),
            work_mode=d.get("work_mode", ""),
            skills=[s.strip() for s in (d.get("core_match") or "").split(",") if s.strip()],
            score=d.get("score") or 0,
            ai_score=d.get("ai_score"),
            apply_type=d.get("apply_type", "unknown"),  # type: ignore[arg-type]
            status=d.get("status", "new"),
            core_match=d.get("core_match", ""),
            bonus_match=d.get("bonus_match", ""),
            notes=d.get("notes", ""),
            next_action=d.get("next_action", ""),
            applied_date=d.get("applied_date", ""),
            search_label=d.get("search_label", ""),
            jd_text=d.get("jd_text", ""),
            duplicate_of=d.get("duplicate_of", ""),
            cover_letter=d.get("cover_letter", ""),
            external_url=d.get("external_url", ""),
            contact_name=d.get("contact_name", ""),
            contact_email=d.get("contact_email", ""),
            contact_profile_url=d.get("contact_profile_url", ""),
        )


# ------------------------------------------------------------------
# Module-level singleton factory
# ------------------------------------------------------------------

_repo_instance: dict[str, JobRepository] = {}


def get_repo(db_path: Path) -> JobRepository:
    key = str(db_path)
    if key not in _repo_instance:
        _repo_instance[key] = JobRepository(db_path)
    return _repo_instance[key]


def _normalize_question(q: str) -> str:
    return " ".join(q.lower().strip().split())
