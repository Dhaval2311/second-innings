from __future__ import annotations

import re
from typing import Any, Optional

from playwright.async_api import Locator, Page


from .resume_context import load_resume_text
from .models import Job
from .screening import (
    format_question_for_ui,
    load_screening_profile,
    resolve_screening_answer,
)

MODAL_SELECTOR = (
    ".jobs-easy-apply-modal, "
    "[data-test-modal], "
    "[role='dialog'].artdeco-modal, "
    ".artdeco-modal.artdeco-modal--layer-confirmation, "
    ".artdeco-modal"
)
FORM_GROUP_SELECTOR = (
    "[data-test-form-element], "
    ".jobs-easy-apply-form-section__group, "
    ".fb-dash-form-element, "
    "fieldset"
)
FOOTER_SELECTOR = (
    ".jobs-easy-apply-footer, "
    ".artdeco-modal__actionbar, "
    ".ph5.pv4, "
    "footer"
)

SUCCESS_MARKERS = (
    "application sent",
    "your application was sent",
    "submitted successfully",
    "application submitted",
)

SKIP_QUESTION_HINTS = (
    "gender",
    "race",
    "ethnicity",
    "veteran",
    "disability",
    "lgbt",
    "pronoun",
    "optional",
    "eeo",
    "diversity self",
)


async def _group_label(group: Locator) -> str:
    label_text = ""
    for sel in (
        "label",
        "legend",
        "span[data-test-form-element-label]",
        ".fb-dash-form-element__label",
        ".jobs-easy-apply-form-element__label",
    ):
        loc = group.locator(sel).first
        try:
            if await loc.count():
                text = (await loc.inner_text()).strip()
                if text:
                    label_text = text
                    break
        except Exception:
            continue
            
    if label_text:
        label_text = format_question_for_ui(label_text)

    if not label_text:
        return ""

    # If it's a select dropdown, append options to help the AI
    try:
        select = group.locator("select").first
        if await select.count():
            options = select.locator("option")
            opt_count = await options.count()
            if opt_count > 0:
                opt_texts = []
                for i in range(opt_count):
                    opt = await options.nth(i).inner_text()
                    opt = opt.strip()
                    if opt and opt.lower() != "select an option":
                        opt_texts.append(opt)
                if opt_texts:
                    label_text += f" (Options: {', '.join(opt_texts)})"
    except Exception:
        pass
        
    return label_text


async def _should_skip_question(label: str) -> bool:
    lower = label.lower()
    return any(h in lower for h in SKIP_QUESTION_HINTS)

async def _is_group_filled(group: Locator) -> bool:
    """Check if the form group already has a valid user-provided answer."""
    try:
        # 1. Text/number/email inputs
        text_inputs = group.locator("input[type='text'], input[type='number'], input[type='email'], input[type='tel'], textarea")
        for i in range(await text_inputs.count()):
            val = await text_inputs.nth(i).input_value()
            if val and val.strip():
                return True
                
        # 2. Select dropdowns
        selects = group.locator("select")
        for i in range(await selects.count()):
            sel = selects.nth(i)
            val = await sel.input_value()
            text = await sel.evaluate("el => el.options[el.selectedIndex]?.text || ''")
            if val and text and "select an option" not in text.lower() and "choose" not in text.lower():
                return True
                
        # 3. Radio buttons
        radios = group.locator("input[type='radio']")
        for i in range(await radios.count()):
            if await radios.nth(i).evaluate("el => el.checked"):
                return True
                
        # 4. Checkboxes
        checkboxes = group.locator("input[type='checkbox']")
        for i in range(await checkboxes.count()):
            if await checkboxes.nth(i).evaluate("el => el.checked"):
                return True
    except Exception:
        pass
    return False


async def _click_choice_in_group(group: Locator, answer: str) -> bool:
    if not answer:
        return False
    answer = answer.strip()
    lower = answer.lower()

    if lower in {"yes", "no"}:
        for text in (answer, answer.capitalize(), lower):
            loc = group.get_by_text(text, exact=True)
            try:
                if await loc.count():
                    await loc.first.click(timeout=2000)
                    return True
            except Exception:
                pass

    notice_labels = {
        "0": ["Immediately", "Immediate", "15 days or less", "2 weeks", "None", "Serving notice period"],
        "15": ["15 days or less", "2 weeks", "15 Days"],
        "30": ["1 month", "30 days", "1 Month"],
        "60": ["2 months", "2 Months"],
        "90": ["3 months", "3 Months"],
    }
    try:
        days = int(re.sub(r"\D", "", answer) or "-1")
        for label in notice_labels.get(str(days), notice_labels["0"]):
            loc = group.get_by_text(label, exact=False)
            try:
                if await loc.count():
                    await loc.first.click(timeout=2000)
                    return True
            except Exception:
                continue
    except ValueError:
        pass

    for text in (answer, answer.title()):
        loc = group.get_by_text(text, exact=False)
        try:
            if await loc.count():
                await loc.first.click(timeout=2000)
                return True
        except Exception:
            continue

    radios = group.locator("input[type='radio']")
    count = await radios.count()
    for i in range(count):
        radio = radios.nth(i)
        try:
            aria = (await radio.get_attribute("aria-label") or "").lower()
            val = (await radio.get_attribute("value") or "").lower()
            if lower in aria or lower in val or answer.lower() in aria:
                await radio.click(timeout=2000)
                return True
        except Exception:
            continue
    return False


async def _fill_select(group: Locator, answer: str) -> bool:
    select = group.locator("select").first
    if await select.count() == 0:
        return False
    try:
        # First try exact standard methods
        for strategy in (
            lambda: select.select_option(label=answer),
            lambda: select.select_option(value=answer),
            lambda: select.select_option(label=re.sub(r"\D", "", answer) or answer),
        ):
            try:
                await strategy()
                return True
            except Exception:
                continue
                
        # If standard methods fail, use JavaScript fuzzy matching
        js = """
        (select, answerText) => {
            if (!answerText) return false;
            answerText = answerText.toLowerCase().trim();
            let numAnswer = answerText.replace(/\\D/g, '');
            for (let i = 0; i < select.options.length; i++) {
                let optText = select.options[i].text.toLowerCase().trim();
                if (optText === 'select an option' || optText === 'choose') continue;
                if (optText === answerText || optText.includes(answerText) || (answerText.length > 2 && answerText.includes(optText))) {
                    select.selectedIndex = i;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                if (numAnswer && optText.includes(numAnswer)) {
                    select.selectedIndex = i;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
            }
            return false;
        }
        """
        success = await select.evaluate(js, str(answer))
        return success
    except Exception:
        return False


async def _fill_text_field(field: Locator, answer: str) -> bool:
    try:
        if not await field.is_visible() or not await field.is_editable():
            return False
        ftype = (await field.get_attribute("type") or "").lower()
        if ftype in {"hidden", "submit", "button", "file"}:
            return False
        current = await field.input_value()
        if current:
            return True
        await field.fill(str(answer))
        return True
    except Exception:
        return False


async def _fill_typeahead(group: Locator, answer: str) -> bool:
    field = group.locator(
        "input[role='combobox'], input[type='text'], input[type='search']"
    ).first
    if await field.count() == 0:
        return False
    try:
        await field.click(timeout=2000)
        await field.fill(answer)
        await field.page.wait_for_timeout(800)
        option = group.page.locator(
            "[role='option'], .basic-typeahead__selectable"
        ).filter(has_text=answer).first
        if await option.count():
            await option.click(timeout=2000)
        else:
            await field.press("Enter")
        return True
    except Exception:
        return False


async def fill_linkedin_modal(
    page: Page,
    config: dict[str, Any],
    job: Job,
    db=None,
) -> list[str]:
    """Fill all fields in the LinkedIn Easy Apply modal. Returns unfilled question labels."""
    profile = load_screening_profile(config, db=db)
    resume = load_resume_text(profile.get("resume_path", ""))
    modal = page.locator(MODAL_SELECTOR).first
    scope = modal if await modal.count() else page

    # Scroll the modal content down to reveal lazy-loaded questions
    try:
        for sel in [".jobs-easy-apply-modal__content", ".artdeco-modal__content", ".ph5.pb4"]:
            content = page.locator(sel).first
            if await content.count() > 0:
                await content.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                await page.wait_for_timeout(800)
                break
        
        # Fallback keyboard scroll
        await scope.click(timeout=1000)
        await page.keyboard.press("PageDown")
        await page.keyboard.press("PageDown")
        await page.wait_for_timeout(500)
    except Exception:
        pass

    resume_path = profile.get("resume_path", "")
    if resume_path:
        file_input = scope.locator("input[type='file']").first
        try:
            if await file_input.count():
                await file_input.set_input_files(resume_path)
        except Exception:
            pass

    unknown: list[str] = []
    groups = scope.locator(FORM_GROUP_SELECTOR)
    group_count = await groups.count()

    for i in range(group_count):
        group = groups.nth(i)
        try:
            label = await _group_label(group)
            if not label or await _should_skip_question(label):
                continue
                
            if await _is_group_filled(group):
                continue

            answer = await resolve_screening_answer(label, job, config, db=db)

            if not answer:
                unknown.append(label)
                continue

            filled = False
            ql = label.lower()
            is_choice = any(
                k in ql
                for k in [
                    "notice",
                    "relocate",
                    "authorized",
                    "sponsorship",
                    "visa",
                    "living in",
                    "located in",
                    "based in",
                    "comfortable",
                    "willing",
                    "hybrid",
                    "onsite",
                    "remote",
                    "yes or no",
                ]
            ) or answer.lower() in {"yes", "no"}

            if is_choice:
                filled = await _click_choice_in_group(group, answer)
            if not filled:
                filled = await _fill_select(group, answer)
            if not filled:
                filled = await _fill_typeahead(group, answer)
            if not filled:
                for sel in ("textarea", "input[type='number']", "input[type='text']", "input[type='email']", "input[type='tel']"):
                    field = group.locator(sel).first
                    if await field.count():
                        filled = await _fill_text_field(field, answer)
                        if filled:
                            break

            if not filled and answer.lower() in {"yes", "no"}:
                filled = await _click_choice_in_group(group, answer)

            if not filled:
                unknown.append(label)
        except Exception:
            continue

    # Fallback: unfilled visible inputs in modal
    fields = scope.locator(
        "input:not([type='hidden']):not([type='checkbox']):not([type='radio']):visible, "
        "textarea:visible, select:visible"
    )
    for i in range(await fields.count()):
        field = fields.nth(i)
        try:
            current = await field.input_value()
            if current:
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
            if not label:
                continue
            answer = await resolve_screening_answer(label, job, config, db=db)
            if answer:
                tag = await field.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    await _fill_select(field.locator("xpath=.."), answer)
                else:
                    await _fill_text_field(field, answer)
        except Exception:
            continue

    return unknown


async def click_modal_footer(page: Page, actions: list[str]) -> bool:
    modal = page.locator(MODAL_SELECTOR).first
    modal_found = await modal.count() > 0

    # Build list of scopes to search: footer → modal → full page fallback
    scopes = []
    if modal_found:
        footer = modal.locator(FOOTER_SELECTOR).first
        if await footer.count():
            scopes.append(footer)
        scopes.append(modal)
    scopes.append(page)  # always fall back to full page

    for action in actions:
        # aria-label may contain partial text (LinkedIn uses e.g. "Continue to next step")
        aria_variants = [
            action,
            action.lower(),
            action.title(),
        ]
        for scope in scopes:
            for aria_val in aria_variants:
                for sel in (
                    f"button[aria-label='{aria_val}']",
                    f"button[aria-label*='{aria_val}']",
                    f"button:has-text('{aria_val}')",
                ):
                    try:
                        btn = scope.locator(sel).first
                        if not await btn.count():
                            continue
                        if not await btn.is_visible():
                            continue
                        disabled = await btn.get_attribute("disabled")
                        aria_disabled = await btn.get_attribute("aria-disabled")
                        if disabled is not None or aria_disabled == "true":
                            continue
                        await btn.scroll_into_view_if_needed(timeout=2000)
                        await btn.click(timeout=5000)
                        return True
                    except Exception:
                        continue
    return False


async def has_validation_errors(page: Page) -> bool:
    modal = page.locator(MODAL_SELECTOR).first
    scope = modal if await modal.count() else page
    return await scope.locator(
        ".artdeco-inline-feedback--error, [data-test-form-element-error], .fb-dash-form-element__error-text"
    ).count() > 0


async def application_submitted(page: Page) -> bool:
    body = (await page.locator("body").inner_text()).lower()
    return any(m in body for m in SUCCESS_MARKERS)