from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from playwright.async_api import Page

from ..models import ApplyResult, Job
from ..screening import format_question_for_ui


class BaseApplier(ABC):
    source_name: str = "Generic"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.profile = config.get("profile", {})
        self.applier_cfg = config.get("applier", {})

    @abstractmethod
    async def apply(self, page: Page, job: Job) -> ApplyResult:
        raise NotImplementedError

    def dry_run(self) -> bool:
        return bool(self.applier_cfg.get("dry_run", True))

    # ------------------------------------------------------------------
    # Shared: DB access + wait-for-user-answers
    # ------------------------------------------------------------------

    def _get_db(self):
        """Return the DB repo — injected via self.db or server singleton."""
        if hasattr(self, "db") and self.db:
            return self.db
        try:
            from ..ui.server import _db
            return _db
        except Exception:
            return None

    async def _wait_for_user_answers(
        self,
        page: Page,
        job: Job,
        unknown_questions: list[str],
        timeout_seconds: int = 600,
    ) -> dict[str, str]:
        """
        Save each unknown question to the DB as a pending_input, then poll
        every 5 s until ALL are answered or timeout expires.
        Keeps the page alive during the wait.
        Returns {question: answer}.
        """
        db = self._get_db()
        if not db:
            print("  [⚠] No DB — cannot wait for user answers")
            return {}

        pending_ids: dict[int, str] = {}
        context = f"{self.source_name} Apply — {job.company} | {job.role}"

        for q in unknown_questions:
            formatted = format_question_for_ui(q)
            pid = db.log_pending_input_returning_id(job.source_url, formatted, context=context)
            if pid:
                pending_ids[pid] = formatted
                print(f"  [🔔] Pending question (id={pid}): {formatted!r}")

        if not pending_ids:
            return {}

        print(
            f"  [⏳] Waiting for user to answer {len(pending_ids)} question(s)"
            f" in UI (timeout {timeout_seconds}s)…"
        )

        collected: dict[str, str] = {}
        elapsed = 0
        poll_interval = 5

        while elapsed < timeout_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            for pid, q in list(pending_ids.items()):
                if q in collected:
                    continue
                answer = db.get_answered_input(pid)
                if answer:
                    collected[q] = answer
                    print(f"  [✅] Got answer for {q!r}: {answer!r}")

            if len(collected) == len(pending_ids):
                break

            # Keep page alive
            try:
                await page.mouse.move(600, 400)
            except Exception:
                pass

        unanswered = [q for pid, q in pending_ids.items() if q not in collected]
        if unanswered:
            print(f"  [⚠] Timed out — {len(unanswered)} question(s) still unanswered")

        return collected

    # ------------------------------------------------------------------
    # Common field fill
    # ------------------------------------------------------------------

    async def fill_common_fields(self, page: Page) -> None:
        """Best-effort fill for common application fields."""
        field_map = {
            "input[name*='email' i], input[type='email']": self.profile.get("email", ""),
            "input[name*='phone' i], input[type='tel']": self.profile.get("phone", ""),
            "input[name*='name' i]": self.profile.get("full_name", ""),
            "input[name*='ctc' i], input[name*='salary' i]": self.profile.get("expected_ctc_lpa", ""),
            "input[name*='notice' i]": self.profile.get("notice_period_days", ""),
            "input[name*='experience' i]": str(self.profile.get("years_experience", "")),
        }
        for selector, value in field_map.items():
            if not value:
                continue
            loc = page.locator(selector).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.fill(str(value))
            except Exception:
                continue