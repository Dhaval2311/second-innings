from __future__ import annotations

from urllib.parse import urlparse

from playwright.async_api import Page

from ..browser import click_first_visible, detect_captcha, wait_for_human
from ..form_filler import fill_application_form
from ..models import ApplyResult, Job
from .base import BaseApplier

NAUKRI_HOST = "naukri.com"


class NaukriApplier(BaseApplier):
    source_name = "Naukri"

    async def _button_counts(self, page: Page) -> tuple[int, int]:
        naukri = await page.locator("#apply-button").count()
        company = await page.locator("#company-site-button").count()
        return naukri, company

    async def _return_to_listing(self, page: Page, job_url: str) -> None:
        if NAUKRI_HOST not in urlparse(page.url).netloc:
            await page.goto(job_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

    async def _handle_apply_flow(self, page: Page, job: Job) -> ApplyResult:
        wait_timeout = int(self.applier_cfg.get("unknown_question_wait_seconds", 600))
        questions_waited: set[str] = set()
        steps = 0
        while steps < 8:
            steps += 1
            body = (await page.locator("body").inner_text()).lower()
            if any(m in body for m in ["application sent", "successfully applied", "you have applied"]):
                return ApplyResult(True, "Applied on Naukri", tracker_status="applied")
                
            # Naukri often changes the apply button text to 'Applied' upon instant success
            try:
                apply_btn = page.locator("#apply-button, .already-applied").first
                if await apply_btn.count():
                    btn_text = (await apply_btn.inner_text()).lower()
                    if "applied" in btn_text and "already" not in btn_text:
                        return ApplyResult(True, "Applied on Naukri (button updated)", tracker_status="applied")
                        
                # If this is the first step (just clicked apply) and there are no visible form fields,
                # it was a 1-click instant apply that succeeded silently.
                form_fields = page.locator("input:not([type='hidden']), select, textarea")
                visible_fields = 0
                for i in range(await form_fields.count()):
                    if await form_fields.nth(i).is_visible():
                        visible_fields += 1
                if steps == 1 and visible_fields == 0:
                    return ApplyResult(True, "Applied on Naukri (1-click instant)", tracker_status="applied")
            except Exception:
                pass

            unknowns = await fill_application_form(page, self.config, job, db=self._get_db())
            if unknowns:
                new_unknowns = [q for q in unknowns if q not in questions_waited]
                if new_unknowns:
                    print(f"  [🤖] Naukri: {len(new_unknowns)} unknown question(s) — asking UI user…")
                    answers = await self._wait_for_user_answers(
                        page, job, new_unknowns, timeout_seconds=wait_timeout
                    )
                    questions_waited.update(new_unknowns)
                    if answers:
                        db = self._get_db()
                        if db:
                            for q, a in answers.items():
                                db.save_answer(q, a, source="user")
                        # Re-fill with new answers
                        unknowns = await fill_application_form(page, self.config, job, db=self._get_db())

            submitted = await click_first_visible(
                page,
                [
                    "button:has-text('Submit')",
                    "button:has-text('Apply anyway')",
                    "button:has-text('Save and apply')",
                    "button:has-text('Apply now')",
                    "button:has-text('Next')",
                    "button:has-text('Continue')",
                ],
            )
            if submitted:
                await page.wait_for_timeout(2000)
                continue

            if self.applier_cfg.get("pause_on_unknown_form", True):
                ok = await wait_for_human(page, f"Complete remaining Naukri form for {job.company} - {job.role}")
                if ok:
                    return ApplyResult(True, "Applied with human assistance", tracker_status="applied")
                return ApplyResult(
                    False,
                    "Apply form opened — complete manually in browser",
                    needs_human=True,
                    tracker_status="needs_human",
                )

            return ApplyResult(False, "Could not complete Naukri apply form", needs_human=True)

        return ApplyResult(False, "Too many apply steps", needs_human=True)


    async def apply(self, page: Page, job: Job) -> ApplyResult:
        if self.dry_run():
            return ApplyResult(True, "dry_run: would apply on Naukri", tracker_status="ready_to_apply")

        job_url = job.source_url

        # Always start by going to the specific job URL. Do not assume a reused tab 
        # that happens to be on /myapply/ is meant for this job.
        await page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)

        body = await page.locator("body").inner_text()
        if detect_captcha(body):
            if self.applier_cfg.get("pause_on_captcha", True):
                await wait_for_human(page, "Solve CAPTCHA on Naukri, then continue.")
            else:
                return ApplyResult(False, "CAPTCHA detected", needs_human=True)

        body_lower = body.lower()
        if any(m in body_lower for m in ["you have already applied", "already applied"]):
            return ApplyResult(True, "Already applied", already_applied=True, tracker_status="applied")

        naukri_btns, company_btns = await self._button_counts(page)

        if naukri_btns == 0 and company_btns > 0:
            return ApplyResult(
                False,
                "Naukri quick apply not available — company site only",
                pending_external=True,
                tracker_status="pending_external",
            )

        if naukri_btns == 0 and company_btns == 0:
            return ApplyResult(False, "No apply button found on listing", needs_human=True)

        pages_before = {id(p) for p in page.context.pages}
        apply_btn = page.locator("#apply-button").first
        try:
            await apply_btn.click(timeout=8000)
        except Exception:
            return ApplyResult(False, "Could not click Naukri apply button", needs_human=True)

        await page.wait_for_timeout(2000)

        new_pages = [p for p in page.context.pages if id(p) not in pages_before and p != page]
        for extra in new_pages:
            ext_url = extra.url
            if NAUKRI_HOST not in urlparse(ext_url).netloc:
                await extra.close()
                await self._return_to_listing(page, job_url)
                return ApplyResult(
                    False,
                    f"Company site opened in new tab ({ext_url}) — deferred",
                    pending_external=True,
                    tracker_status="pending_external",
                )

        if NAUKRI_HOST not in urlparse(page.url).netloc:
            external = page.url
            await page.goto(job_url, wait_until="domcontentloaded")
            return ApplyResult(
                False,
                f"Redirected to company site ({external}) — deferred",
                pending_external=True,
                tracker_status="pending_external",
            )

        return await self._handle_apply_flow(page, job)