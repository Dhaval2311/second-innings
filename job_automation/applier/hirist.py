from __future__ import annotations

import re

from playwright.async_api import Page

from ..browser import click_first_visible, detect_captcha, wait_for_human
from ..models import ApplyResult, Job
from ..screening import format_question_for_ui, resolve_screening_answer
from ..screening_fields import is_choice_question
from .base import BaseApplier

HIRIST_HOST = "hirist.tech"


class HiristApplier(BaseApplier):
    source_name = "Hirist"

    async def _answer_for_question(self, question: str, job: Job) -> str:
        db = self._get_db()
        ans = await resolve_screening_answer(
            question, job, self.config, db=db
        )
        return ans or ""

    async def _get_questions(self, page: Page) -> list[str]:
        body = await page.locator("body").inner_text()
        questions = []
        for line in body.split("\n"):
            l = line.strip()
            if not l:
                continue
            if "?" in l or re.search(r"\b(ctc|lpa|notice period|years of experience)\b", l, re.I):
                formatted = format_question_for_ui(l)
                if formatted and len(formatted) < 200 and formatted not in questions:
                    questions.append(formatted)
        return questions

    async def _click_choice(self, page: Page, answer: str) -> bool:
        answer = answer.strip()
        if not answer:
            return False
        # Yes / No
        if answer.lower() in {"yes", "no"}:
            loc = page.get_by_text(answer, exact=True)
            if await loc.count():
                try:
                    await loc.first.click(timeout=3000)
                    return True
                except Exception:
                    pass
        # Notice period chips
        notice_map = {
            "0": ["15 Days or less", "Immediate", "Serving Notice Period", "15 days or less"],
            "15": ["15 Days or less", "15 Days"],
            "30": ["1 Month", "30 Days"],
            "60": ["2 Months"],
            "90": ["3 Months"],
        }
        try:
            nd = int(answer)
            for label in notice_map.get(str(nd), notice_map.get("0", [])):
                loc = page.get_by_text(label, exact=False)
                if await loc.count():
                    await loc.first.click(timeout=3000)
                    return True
        except ValueError:
            pass

        loc = page.get_by_text(answer, exact=False)
        if await loc.count():
            try:
                await loc.first.click(timeout=3000)
                return True
            except Exception:
                pass
        return False

    async def _input_context(self, field) -> str:
        try:
            return await field.evaluate(
                """el => {
                    let node = el;
                    for (let depth = 0; depth < 8 && node; depth++) {
                        const text = (node.innerText || '').trim();
                        if (text && text.length < 500) return text;
                        node = node.parentElement;
                    }
                    const id = el.id;
                    if (id) {
                        const lbl = document.querySelector(`label[for='${id}']`);
                        if (lbl) return lbl.innerText.trim();
                    }
                    return el.getAttribute('aria-label') || el.placeholder || el.name || '';
                }"""
            )
        except Exception:
            return ""

    async def _fill_screening_step(self, page: Page, job: Job) -> list[str]:
        unknown: list[str] = []
        questions = await self._get_questions(page)

        for q in questions:
            answer = await self._answer_for_question(q, job)
            if not answer:
                unknown.append(q)
                continue
            if is_choice_question(q):
                await self._click_choice(page, answer)

        text_inputs = page.locator(
            "input[type='number']:visible, input[type='text']:visible:not([type='checkbox']):not([type='radio'])"
        )
        for i in range(await text_inputs.count()):
            field = text_inputs.nth(i)
            try:
                current = (await field.input_value()).strip()
                if current:
                    continue
                context = format_question_for_ui(await self._input_context(field))
                answer = await self._answer_for_question(context, job)
                if not answer and context:
                    first_line = format_question_for_ui(context.split("\n")[0])
                    if first_line != context:
                        answer = await self._answer_for_question(first_line, job)
                if not answer:
                    unknown.append(context or f"input#{i}")
                    continue
                await field.fill(str(answer))
            except Exception:
                continue

        for ta in await page.locator("textarea:visible").all():
            try:
                if (await ta.input_value()).strip():
                    continue
                context = format_question_for_ui(await self._input_context(ta))
                answer = await self._answer_for_question(context, job)
                if answer:
                    await ta.fill(str(answer))
                elif context:
                    unknown.append(context)
            except Exception:
                continue

        return list(dict.fromkeys(unknown))

    async def _click_apply(self, page: Page) -> bool:
        try:
            btn = page.locator("button.MuiButton-containedPrimary").filter(has_text="Apply").first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=8000)
                return True
        except Exception:
            pass
        try:
            btn = page.get_by_role("button", name="Apply").first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=8000)
                return True
        except Exception:
            pass
        return False

    async def _click_screening_next(self, page: Page) -> bool:
        for sel in [
            "button.MuiButton-containedPrimary:has-text('Submit')",
            "button.MuiButton-containedPrimary:has-text('Next')",
            "button:has-text('Submit')",
            "button:has-text('Next')",
            "button:has-text('Apply')",
        ]:
            btn = page.locator(sel).first
            try:
                if await btn.count() and await btn.is_visible():
                    await btn.click(timeout=8000)
                    return True
            except Exception:
                continue
        return await click_first_visible(
            page,
            ["button:has-text('Submit')", "button:has-text('Next')", "button:has-text('Apply')"],
        )

    async def _submit_screening(self, page: Page, job: Job) -> ApplyResult:
        wait_timeout = int(self.applier_cfg.get("unknown_question_wait_seconds", 600))
        questions_waited: set[str] = set()
        last_unknown: list[str] = []

        for step in range(10):
            if "/job/applied" in page.url:
                return ApplyResult(True, "Applied on Hirist", tracker_status="applied")

            body = (await page.locator("body").inner_text()).lower()
            if any(m in body for m in ["application submitted", "successfully applied", "you have applied"]):
                return ApplyResult(True, "Applied on Hirist", tracker_status="applied")

            await page.wait_for_timeout(1200)
            unknown = await self._fill_screening_step(page, job)
            if unknown:
                last_unknown = unknown
                new_unknowns = [q for q in unknown if q not in questions_waited]
                if new_unknowns:
                    print(f"  [🤖] Hirist: {len(new_unknowns)} unknown question(s) — asking UI user…")
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
                        unknown = await self._fill_screening_step(page, job)
                        if unknown:
                            last_unknown = unknown

            clicked = await self._click_screening_next(page)
            if clicked:
                await page.wait_for_timeout(3000)
                if "/job/applied" in page.url:
                    return ApplyResult(True, "Applied on Hirist", tracker_status="applied")
                continue

            if "/job/applied" in page.url:
                return ApplyResult(True, "Applied on Hirist", tracker_status="applied")

            break

        if "/job/applied" in page.url:
            return ApplyResult(True, "Applied on Hirist", tracker_status="applied")

        msg = f"Hirist screening incomplete at {page.url}"
        if last_unknown:
            msg += f" — needs: {last_unknown[0][:80]}"
        return ApplyResult(False, msg, needs_human=True, unknown_questions=last_unknown)


    async def apply(self, page: Page, job: Job) -> ApplyResult:
        if self.dry_run():
            return ApplyResult(True, "dry_run: would apply on Hirist", tracker_status="ready_to_apply")

        await page.goto(job.source_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)

        body = await page.locator("body").inner_text()
        if detect_captcha(body):
            ok = await wait_for_human(page, "Solve CAPTCHA on Hirist.")
            if not ok:
                return ApplyResult(False, "CAPTCHA on Hirist", needs_human=True)

        if any(m in body.lower() for m in ["already applied", "you have applied", "you've applied"]):
            return ApplyResult(True, "Already applied", already_applied=True, tracker_status="applied")

        applied_btn = page.get_by_role("button", name="Applied")
        if await applied_btn.count():
            return ApplyResult(True, "Already applied", already_applied=True, tracker_status="applied")

        pages_before = {id(p) for p in page.context.pages}
        if not await self._click_apply(page):
            if await applied_btn.count():
                return ApplyResult(True, "Already applied", already_applied=True, tracker_status="applied")
            return ApplyResult(False, "Hirist Apply button not found", needs_human=True)

        try:
            await page.wait_for_url(re.compile(r".*hirist\.tech.*(screening|applied).*"), timeout=15000)
        except Exception:
            await page.wait_for_timeout(3000)

        if "/job/applied" in page.url:
            return ApplyResult(True, "Applied on Hirist", tracker_status="applied")

        new_pages = [p for p in page.context.pages if id(p) not in pages_before and p != page]
        for extra in new_pages:
            if HIRIST_HOST not in extra.url:
                await extra.close()
                return ApplyResult(
                    False,
                    f"External site opened ({extra.url}) — deferred",
                    pending_external=True,
                    tracker_status="pending_external",
                )

        if "screening" in page.url:
            return await self._submit_screening(page, job)

        if "/j/" in page.url:
            await self._click_apply(page)
            await page.wait_for_timeout(3000)
            if "screening" in page.url or "/job/applied" in page.url:
                return await self._submit_screening(page, job)

        return ApplyResult(False, f"Hirist apply stuck at {page.url}", needs_human=True)