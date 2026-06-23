from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page

from .question_log import learn_answers


async def extract_screening_qa(page: Page) -> dict[str, str]:
    """Read filled values from a visible screening/application form."""
    learned: dict[str, str] = {}
    body = await page.locator("body").inner_text()
    lines = [l.strip() for l in body.split("\n") if l.strip()]

    questions: list[str] = []
    for line in lines:
        if "?" in line or re.search(r"\b(ctc|lpa|notice period|years of experience|salary)\b", line, re.I):
            if len(line) < 250:
                questions.append(line)

    inputs = page.locator(
        "input[type='number']:visible, input[type='text']:visible, textarea:visible"
    )
    count = await inputs.count()
    for i in range(count):
        field = inputs.nth(i)
        try:
            val = (await field.input_value()).strip()
            if not val:
                continue
            label = await field.evaluate(
                """el => {
                    const id = el.id;
                    if (id) {
                        const lbl = document.querySelector(`label[for='${id}']`);
                        if (lbl) return lbl.innerText.trim();
                    }
                    return el.getAttribute('aria-label') || el.placeholder || el.name || '';
                }"""
            )
            if label:
                learned[label] = val
            elif i < len(questions):
                learned[questions[i]] = val
        except Exception:
            continue

    # Hirist chip selections (notice period, yes/no)
    for q in questions:
        ql = q.lower()
        if "notice" in ql:
            for chip in ["15 Days or less", "Immediate", "Serving Notice Period", "1 Month", "2 Months", "3 Months"]:
                loc = page.get_by_text(chip, exact=False)
                try:
                    if await loc.count():
                        parent = loc.first.locator("xpath=ancestor::*[contains(@class,'selected') or contains(@class,'active') or contains(@class,'Mui-selected')][1]")
                        if await parent.count():
                            learned[q] = chip
                            break
                except Exception:
                    continue

    return learned


async def learn_from_open_tab(page: Page, base_dir, config: dict[str, Any]) -> int:
    qa = await extract_screening_qa(page)
    if not qa:
        return 0
    return learn_answers(base_dir, config, qa)