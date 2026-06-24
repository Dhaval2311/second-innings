from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import Locator, Page

from .models import Job
from .screening import format_question_for_ui, load_screening_profile, resolve_screening_answer


async def _field_label(field: Locator) -> str:
    """Prefer human-readable labels over technical field attributes."""
    try:
        fid = await field.get_attribute("id")
        if fid:
            label = field.page.locator(f"label[for='{fid}']").first
            if await label.count() > 0:
                text = (await label.inner_text()).strip()
                if text:
                    return format_question_for_ui(text)
    except Exception:
        pass

    for attr in ("aria-label", "placeholder"):
        try:
            val = await field.get_attribute(attr)
            if val and len(val.strip()) > 2:
                return format_question_for_ui(val.strip())
        except Exception:
            pass

    parts: list[str] = []
    for attr in ("aria-label", "placeholder", "name", "id"):
        try:
            val = await field.get_attribute(attr)
            if val:
                parts.append(val)
        except Exception:
            pass
    return format_question_for_ui(" | ".join(parts).strip())


SKIP_FIELD_HINTS = (
    "keyword",
    "designation",
    "companies",
    "enter location",
    "search",
    "naukri 360",
)


def _should_skip_field(label: str) -> bool:
    lower = label.lower()
    return any(h in lower for h in SKIP_FIELD_HINTS)


async def prompt_user(question: str, answers_path: Path) -> str:
    print(f"\n[INPUT NEEDED] {question}")
    try:
        answer = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("Your answer: ").strip()
        )
    except EOFError:
        print("[warn] No interactive terminal — skipping prompt.")
        return ""
    saved: dict[str, Any] = {}
    if answers_path.exists():
        saved = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {}
    saved[question] = answer
    answers_path.write_text(yaml.safe_dump(saved, allow_unicode=True), encoding="utf-8")
    print(f"[saved] Answer stored in {answers_path}")
    return answer


def _get_db():
    try:
        from .ui.server import _db
        return _db
    except Exception:
        return None


async def fill_application_form(
    page: Page,
    config: dict[str, Any],
    job: Job,
    db=None,
) -> list[str]:
    """Read visible form fields, fill known answers, return formatted unknown questions."""
    if db is None:
        db = _get_db()

    await page.evaluate("window.scrollBy(0, 2000)")
    await page.wait_for_timeout(500)

    profile = load_screening_profile(config, db=db)
    answers_path = Path(config.get("applier", {}).get("answers_file", "user_answers.yaml"))

    fields = page.locator(
        "form input:visible, form textarea:visible, form select:visible, "
        ".myapply input:visible, .myapply textarea:visible, .myapply select:visible, "
        "[class*='apply'] input:visible, [class*='apply'] textarea:visible, "
        "[class*='apply'] select:visible"
    )
    if await fields.count() == 0:
        fields = page.locator("input:visible, textarea:visible, select:visible")

    count = await fields.count()

    # --- Pass 1: resolve rule-based answers, collect fields that need AI ---
    # field_data[i] = (field_locator, label, tag)
    field_data: list[tuple] = []
    answers: dict[int, str] = {}   # index → resolved answer
    ai_needed: list[int] = []      # indices where rule-based failed

    for i in range(count):
        field = fields.nth(i)
        try:
            ftype = (await field.get_attribute("type") or "").lower()
            if ftype in {"hidden", "submit", "button", "checkbox", "radio", "file"}:
                continue
            if not await field.is_editable():
                continue
            label = await _field_label(field)
            if not label or _should_skip_field(label):
                continue
            tag = await field.evaluate("el => el.tagName.toLowerCase()")
            field_data.append((field, label, tag))
            idx = len(field_data) - 1

            ans = await resolve_screening_answer(label, job, config, db=db)
            if ans:
                answers[idx] = ans
            else:
                ai_needed.append(idx)
        except Exception:
            continue

    # --- Pass 2: batch all unknown questions into one AI call ---
    if ai_needed:
        from .content.ai_client import AIClient
        from .resume_context import load_resume_text
        ai_client = AIClient(config)
        if ai_client.is_enabled():
            resume_text = load_resume_text(profile.get("resume_path", ""))
            questions = [field_data[i][1] for i in ai_needed]
            batch = await ai_client.answer_screening_questions_batch(
                questions, job, profile, resume_text
            )
            for idx, q in zip(ai_needed, questions):
                if q in batch:
                    ans = batch[q]
                    answers[idx] = ans
                    if db is not None:
                        try:
                            db.save_answer(q, ans, source="ai")
                        except Exception:
                            pass

    # --- Pass 3: fill fields; prompt user for anything still unknown ---
    unknown_prompts: list[str] = []
    for idx, (field, label, tag) in enumerate(field_data):
        answer = answers.get(idx)
        if not answer:
            if config.get("applier", {}).get("prompt_on_unknown", True):
                answer = await prompt_user(
                    f"{job.company} — {job.role}: {label}", answers_path
                )
                if not answer:
                    unknown_prompts.append(label)
                    continue
            else:
                unknown_prompts.append(label)
                continue
        try:
            if tag == "select":
                try:
                    await field.select_option(label=answer)
                except Exception:
                    try:
                        await field.select_option(value=answer)
                    except Exception:
                        pass
            else:
                await field.fill(answer)
        except Exception:
            continue

    return list(dict.fromkeys(unknown_prompts))