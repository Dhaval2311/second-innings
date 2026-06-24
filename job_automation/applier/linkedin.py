from __future__ import annotations

from playwright.async_api import Page

from ..browser import detect_captcha, wait_for_human
from ..linkedin_form import (
    MODAL_SELECTOR,
    application_submitted,
    click_modal_footer,
    fill_linkedin_modal,
    has_validation_errors,
)
from ..models import ApplyResult, Job
from ..site_login import normalize_linkedin_job_url
from .base import BaseApplier

LINKEDIN_HOST = "linkedin.com"
MAX_STEPS = 18


class LinkedInApplier(BaseApplier):
    source_name = "LinkedIn"

    async def _apply_control_text(self, loc) -> str:
        try:
            text = (await loc.inner_text()).strip().lower()
            aria = (await loc.get_attribute("aria-label") or "").strip().lower()
            return f"{text} {aria}".strip()
        except Exception:
            return ""

    async def _has_easy_apply(self, page: Page) -> bool:
        selectors = [
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            "a:has-text('Easy Apply')",
            "button[aria-label*='Easy Apply']",
            "a[aria-label*='Easy Apply']",
            ".jobs-s-apply button",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    blob = await self._apply_control_text(loc)
                    if "easy apply" in blob:
                        return True
            except Exception:
                continue
        return False

    async def _has_company_apply_only(self, page: Page) -> bool:
        if await self._has_easy_apply(page):
            return False
        body = (await page.locator("body").inner_text()).lower()
        if "apply on company website" in body or "on company website" in body:
            return True
        for sel in ["button:has-text('Apply')", "a:has-text('Apply')"]:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    blob = await self._apply_control_text(loc)
                    if "easy apply" in blob:
                        continue
                    if "apply" in blob:
                        return True
            except Exception:
                continue
        return False

    async def _click_company_apply(self, page: Page) -> bool:
        for sel in ["button:has-text('Apply')", "a:has-text('Apply')"]:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    blob = await self._apply_control_text(loc)
                    if "easy apply" in blob:
                        continue
                    await loc.click(timeout=8000)
                    return True
            except Exception:
                continue
        return False

    async def _resolve_company_apply_url(self, page: Page) -> str:
        """Click the (non-Easy-Apply) Apply control and capture the resulting
        external URL, without leaving the job page in a navigated-away state."""
        pages_before = {id(p) for p in page.context.pages}
        if not await self._click_company_apply(page):
            return ""
        await page.wait_for_timeout(2000)

        new_pages = [p for p in page.context.pages if id(p) not in pages_before and p != page]
        for extra in new_pages:
            if LINKEDIN_HOST not in extra.url:
                url = extra.url
                try:
                    await extra.close()
                except Exception:
                    pass
                return url

        if LINKEDIN_HOST not in page.url:
            external = page.url
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass
            return external

        return ""

    async def _click_easy_apply(self, page: Page) -> bool:
        selectors = [
            "button.jobs-apply-button:has-text('Easy Apply')",
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            "a:has-text('Easy Apply')",
            "button[aria-label*='Easy Apply']",
            "a[aria-label*='Easy Apply']",
            ".jobs-s-apply button",
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=8000)
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_modal(self, page: Page) -> bool:
        try:
            await page.wait_for_selector(MODAL_SELECTOR, timeout=10000)
            await page.wait_for_timeout(1000)
            return True
        except Exception:
            return False

    async def _dismiss_post_apply(self, page: Page):
        for btn_text in ["Done", "Not now"]:
            try:
                btn = page.locator(f"button:has-text('{btn_text}')").first
                if await btn.count() and await btn.is_visible():
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(1000)
                    return
            except Exception:
                pass
        try:
            dismiss = page.locator("button[aria-label='Dismiss']").first
            if await dismiss.count() and await dismiss.is_visible():
                await dismiss.click(timeout=2000)
        except Exception:
            pass

    async def _step_through_easy_apply(self, page: Page, job: Job) -> ApplyResult:
        import asyncio

        last_unknown: list[str] = []
        # Track questions we're actively waiting on so we don't re-queue them
        questions_being_waited_on: set[str] = set()
        wait_timeout = int(self.applier_cfg.get("unknown_question_wait_seconds", 600))

        for step in range(MAX_STEPS):
            if await application_submitted(page):
                await self._dismiss_post_apply(page)
                return ApplyResult(True, "LinkedIn Easy Apply submitted", tracker_status="applied")

            # ── Fill current step ─────────────────────────────────────
            unknown = await fill_linkedin_modal(page, self.config, job, db=self._get_db())
            if unknown:
                last_unknown = unknown
                # Only queue questions we haven't already waited on
                new_unknowns = [q for q in unknown if q not in questions_being_waited_on]
                if new_unknowns:
                    print(f"  [🤖] Gemini couldn't answer {len(new_unknowns)} question(s) — asking UI user…")
                    answers = await self._wait_for_user_answers(
                        page, job, new_unknowns, timeout_seconds=wait_timeout
                    )
                    questions_being_waited_on.update(new_unknowns)

                    if answers:
                        # Save answered questions to screening_answers so Gemini
                        # and the form filler can reuse them immediately
                        db = self._get_db()
                        if db:
                            for q, a in answers.items():
                                db.save_answer(q, a, source="user")
                        # Re-fill the form now that we have answers
                        unknown = await fill_linkedin_modal(page, self.config, job, db=self._get_db())
                        if unknown:
                            last_unknown = unknown

            # ── Try to advance to next step ───────────────────────────
            clicked = await click_modal_footer(
                page,
                [
                    "Submit application",
                    "Review your application",
                    "Review",
                    "Next",
                    "Continue",
                ],
            )
            if clicked:
                await page.wait_for_timeout(2000)
                if await application_submitted(page):
                    await self._dismiss_post_apply(page)
                    return ApplyResult(True, "LinkedIn Easy Apply submitted", tracker_status="applied")
                continue

            if await has_validation_errors(page):
                await fill_linkedin_modal(page, self.config, job)
                clicked = await click_modal_footer(
                    page,
                    ["Next", "Review", "Submit application", "Continue"],
                )
                if clicked:
                    await page.wait_for_timeout(2000)
                    continue

            # Contact/resume steps may have no editable fields — try advancing once more
            if step < 3:
                clicked = await click_modal_footer(page, ["Next", "Continue", "Review"])
                if clicked:
                    await page.wait_for_timeout(1500)
                    continue

            break

        if await application_submitted(page):
            await self._dismiss_post_apply(page)
            return ApplyResult(True, "LinkedIn Easy Apply submitted", tracker_status="applied")

        if self.applier_cfg.get("pause_on_unknown_form", False):
            ok = await wait_for_human(page, f"Finish LinkedIn Easy Apply for {job.company}")
            if ok:
                return ApplyResult(True, "Applied with human assistance", tracker_status="applied")

        detail = f" ({len(last_unknown)} unanswered)" if last_unknown else ""
        return ApplyResult(
            False,
            f"Could not complete LinkedIn Easy Apply{detail}",
            needs_human=True,
            tracker_status="needs_human",

        )

    async def apply(self, page: Page, job: Job) -> ApplyResult:
        if self.dry_run():
            return ApplyResult(True, "dry_run: would apply on LinkedIn", tracker_status="ready_to_apply")

        job_url = normalize_linkedin_job_url(job.source_url)
        await page.goto(job_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)

        body = await page.locator("body").inner_text()
        if detect_captcha(body):
            ok = await wait_for_human(page, "Solve LinkedIn security check.")
            if not ok:
                return ApplyResult(False, "CAPTCHA/security check", needs_human=True)

        body_lower = body.lower()
        if "applied" in body_lower and "easy apply" not in body_lower:
            return ApplyResult(True, "Already applied", already_applied=True, tracker_status="applied")

        if await self._has_company_apply_only(page):
            external_url = await self._resolve_company_apply_url(page)
            if external_url:
                db = self._get_db()
                if db:
                    db.set_external_url(job.source_url, external_url)
            return ApplyResult(
                False,
                f"Company site apply only ({external_url or 'url unresolved'}) — deferred for manual apply",
                pending_external=True,
                tracker_status="pending_external",
            )

        if not await self._has_easy_apply(page):
            return ApplyResult(False, "Easy Apply not available", needs_human=True, tracker_status="needs_human")

        pages_before = {id(p) for p in page.context.pages}
        if not await self._click_easy_apply(page):
            return ApplyResult(False, "Could not click Easy Apply", needs_human=True)

        if not await self._wait_for_modal(page):
            return ApplyResult(False, "Easy Apply modal did not open", needs_human=True)

        new_pages = [p for p in page.context.pages if id(p) not in pages_before and p != page]
        for extra in new_pages:
            if LINKEDIN_HOST not in extra.url:
                external_url = extra.url
                try:
                    await extra.close()
                except Exception:
                    pass
                db = self._get_db()
                if db:
                    db.set_external_url(job.source_url, external_url)
                return ApplyResult(
                    False,
                    f"Company site opened ({external_url}) — deferred",
                    pending_external=True,
                    tracker_status="pending_external",
                )

        if LINKEDIN_HOST not in page.url:
            external_url = page.url
            db = self._get_db()
            if db:
                db.set_external_url(job.source_url, external_url)
            return ApplyResult(
                False,
                f"Redirected off LinkedIn ({external_url}) — deferred",
                pending_external=True,
                tracker_status="pending_external",
            )

        return await self._step_through_easy_apply(page, job)