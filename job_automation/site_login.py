from __future__ import annotations

from playwright.async_api import Page


async def is_linkedin_logged_in(page: Page) -> bool:
    body = await page.locator("body").inner_text()
    markers = ["My Network", "Messaging", "Notifications", "Start a post"]
    if any(m in body for m in markers):
        return True
    if "Sign in" in body and "Join now" in body:
        return False
    cookies = await page.context.cookies()
    names = {c["name"] for c in cookies if "linkedin" in c.get("domain", "")}
    return bool(names & {"li_at", "JSESSIONID", "bcookie"})


async def ensure_linkedin_session(page: Page) -> None:
    """Navigate to feed in the user's existing LinkedIn tab to confirm login."""
    if "linkedin.com/feed" not in page.url:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)
    if not await is_linkedin_logged_in(page):
        raise ConnectionError(
            "LinkedIn is not logged in on the browser automation is attached to.\n"
            "Use ONLY the Brave window started with: ./scripts/launch_brave.sh default\n"
            "Log into LinkedIn there, then run apply again."
        )
    await page.bring_to_front()


def normalize_linkedin_job_url(url: str) -> str:
    return url.replace("https://in.linkedin.com", "https://www.linkedin.com").replace("http://in.linkedin.com", "https://www.linkedin.com")