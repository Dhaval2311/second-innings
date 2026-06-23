from __future__ import annotations

from playwright.async_api import Page

from ..browser import click_first_visible, detect_captcha, safe_goto, wait_for_human
from ..form_filler import fill_application_form
from ..models import ApplyResult, Job
from .base import BaseApplier

MAX_GENERIC_STEPS = 6


class GenericApplier(BaseApplier):
    """Best-effort applier for Wellfound, Cutshort, and company career pages."""

    source_name = "Other"

    async def apply(self, page: Page, job: Job) -> ApplyResult:
        if self.dry_run():
            return ApplyResult(True, f"dry_run: would apply on {job.source}")

        await safe_goto(page, job.source_url)
        body = await page.locator("body").inner_text()
        if detect_captcha(body):
            await wait_for_human(page, "Solve CAPTCHA/security check.")
            return ApplyResult(True, "Continued after human CAPTCHA solve")

        clicked = await click_first_visible(
            page,
            [
                "button:has-text('Apply')",
                "a:has-text('Apply')",
                "button:has-text('Apply Now')",
                "a:has-text('Apply Now')",
                "input[type='submit'][value*='Apply' i]",
            ],
        )
        if not clicked:
            return ApplyResult(False, "No generic apply button found", needs_human=True)

        await page.wait_for_timeout(2000)
        await self.fill_common_fields(page)

        resume_path = self.profile.get("resume_path", "")
        if resume_path:
            file_input = page.locator("input[type='file']").first
            try:
                if await file_input.count() > 0:
                    await file_input.set_input_files(resume_path)
            except Exception:
                pass

        db = self._get_db()
        wait_timeout = int(self.applier_cfg.get("unknown_question_wait_seconds", 600))
        questions_waited: set[str] = set()
        last_unknown: list[str] = []

        for step in range(MAX_GENERIC_STEPS):
            body_lower = (await page.locator("body").inner_text()).lower()
            if any(
                m in body_lower
                for m in ["application submitted", "successfully applied", "thank you for applying"]
            ):
                return ApplyResult(True, f"Applied on {job.source}", tracker_status="applied")

            unknowns = await fill_application_form(page, self.config, job, db=db)
            if unknowns:
                last_unknown = unknowns
                new_unknowns = [q for q in unknowns if q not in questions_waited]
                if new_unknowns:
                    print(f"  [🤖] {job.source}: {len(new_unknowns)} unknown question(s) — asking UI user…")
                    answers = await self._wait_for_user_answers(
                        page, job, new_unknowns, timeout_seconds=wait_timeout
                    )
                    questions_waited.update(new_unknowns)
                    if answers:
                        if db:
                            for q, a in answers.items():
                                db.save_answer(q, a, source="user")
                        await fill_application_form(page, self.config, job, db=db)

            submitted = await click_first_visible(
                page,
                [
                    "button:has-text('Submit')",
                    "button:has-text('Send')",
                    "button:has-text('Continue')",
                    "button:has-text('Next')",
                    "button:has-text('Apply')",
                    "input[type='submit']",
                ],
            )
            if submitted:
                await page.wait_for_timeout(2000)
                continue

            if self.applier_cfg.get("pause_on_unknown_form", True) and last_unknown:
                break

        if self.applier_cfg.get("pause_on_unknown_form", True):
            await wait_for_human(page, f"Complete application on {job.source_url}")
            return ApplyResult(
                True,
                "Applied with human assistance",
                unknown_questions=last_unknown or None,
            )

        return ApplyResult(
            bool(last_unknown) is False,
            "Generic apply attempted",
            needs_human=bool(last_unknown),
            unknown_questions=last_unknown or None,
        )