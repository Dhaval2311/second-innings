from __future__ import annotations

from playwright.async_api import Page

from ..browser import click_first_visible, detect_captcha, safe_goto, wait_for_human
from ..form_filler import fill_application_form
from ..models import ApplyResult, Job
from .base import BaseApplier

MAX_INDEED_STEPS = 6


class IndeedApplier(BaseApplier):
    source_name = "Indeed"

    async def apply(self, page: Page, job: Job) -> ApplyResult:
        if self.dry_run():
            return ApplyResult(True, "dry_run: would apply on Indeed")

        await safe_goto(page, job.source_url)
        body = await page.locator("body").inner_text()
        if detect_captcha(body):
            if self.applier_cfg.get("pause_on_captcha", True):
                await wait_for_human(page, "Solve Indeed CAPTCHA, then continue.")
            else:
                return ApplyResult(False, "CAPTCHA detected", needs_human=True)

        if "applied" in body.lower():
            return ApplyResult(True, "Already applied", already_applied=True)

        clicked = await click_first_visible(
            page,
            [
                "button:has-text('Apply now')",
                "button:has-text('Apply')",
                "a:has-text('Apply now')",
                "#indeedApplyButton",
            ],
        )
        if not clicked:
            return ApplyResult(False, "Apply button not found", needs_human=True)

        await page.wait_for_timeout(2000)
        await self.fill_common_fields(page)

        wait_timeout = int(self.applier_cfg.get("unknown_question_wait_seconds", 600))
        questions_waited: set[str] = set()

        for step in range(MAX_INDEED_STEPS):
            body = (await page.locator("body").inner_text()).lower()
            if any(m in body for m in ["application submitted", "your application was sent", "successfully applied"]):
                return ApplyResult(True, "Applied on Indeed", tracker_status="applied")

            # Try to fill any visible form fields
            unknowns = await fill_application_form(page, self.config, job, db=self._get_db())
            if unknowns:
                new_unknowns = [q for q in unknowns if q not in questions_waited]
                if new_unknowns:
                    print(f"  [🤖] Indeed: {len(new_unknowns)} unknown question(s) — asking UI user…")
                    answers = await self._wait_for_user_answers(
                        page, job, new_unknowns, timeout_seconds=wait_timeout
                    )
                    questions_waited.update(new_unknowns)
                    if answers:
                        db = self._get_db()
                        if db:
                            for q, a in answers.items():
                                db.save_answer(q, a, source="user")
                        await fill_application_form(page, self.config, job, db=self._get_db())

            submitted = await click_first_visible(
                page,
                [
                    "button:has-text('Submit your application')",
                    "button:has-text('Continue')",
                    "button:has-text('Next')",
                    "button:has-text('Submit')",
                ],
            )
            if submitted:
                await page.wait_for_timeout(2000)
                continue

            # Nothing more to click — done or stuck
            break

        body = (await page.locator("body").inner_text()).lower()
        if any(m in body for m in ["application submitted", "your application was sent", "successfully applied"]):
            return ApplyResult(True, "Applied on Indeed", tracker_status="applied")

        if self.applier_cfg.get("pause_on_unknown_form", True):
            await wait_for_human(page, f"Complete Indeed apply for {job.company} - {job.role}")
            return ApplyResult(True, "Applied with human assistance")
        return ApplyResult(False, "Could not submit Indeed form", needs_human=True)