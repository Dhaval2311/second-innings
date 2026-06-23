from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

# Never use these tabs for automation — not job sites / likely not logged in
BLOCKED_FALLBACK_HOSTS = (
    "youtube.com",
    "google.com",
    "docs.google.com",
    "mail.google.com",
    "github.com",
    "stackoverflow.com",
)


class BrowserSession:
    """Attach to your already-open Brave via CDP. Reuses your logged-in tabs — never opens new ones."""

    def __init__(self, config: dict):
        self.config = config
        browser_cfg = config.get("browser", {})
        self.cdp_url = browser_cfg.get("cdp_url", "http://localhost:9222")
        self.mode = browser_cfg.get("mode", "cdp")
        self.reuse_existing_tabs = browser_cfg.get("reuse_existing_tabs", True)
        self.never_open_new_tabs = browser_cfg.get("never_open_new_tabs", True)
        self.user_data_dir = Path(
            browser_cfg.get("user_data_dir", str(Path.home() / ".job-automation-brave"))
        ).expanduser()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._persistent = False
        self._work_page: Optional[Page] = None
        self._created_work_page = False

    async def connect(self) -> BrowserContext:
        self._playwright = await async_playwright().start()

        if self.mode == "cdp":
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
                pages = await self._all_pages()
                if self._browser.contexts:
                    self._context = self._browser.contexts[0]
                else:
                    self._context = await self._browser.new_context()
                print(f"[browser] Connected via CDP ({self.cdp_url}) — {len(pages)} open tab(s)")
                for i, p in enumerate(pages, 1):
                    print(f"  tab {i}: {p.url}")
                return self._context
            except Exception as exc:
                raise ConnectionError(
                    f"Could not attach to your open Brave browser ({exc}).\n"
                    "Quit Brave completely, then run:\n"
                    "  ./scripts/launch_brave.sh default\n"
                    "Open and log into the job site in that window, then run apply again."
                ) from exc

        browser_cfg = self.config.get("browser", {})
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        launch_args: dict = {
            "user_data_dir": str(self.user_data_dir),
            "headless": False,
            "no_viewport": True,
        }
        executable = browser_cfg.get("executable_path", "")
        if executable:
            launch_args["executable_path"] = executable
        self._context = await self._playwright.chromium.launch_persistent_context(**launch_args)
        self._persistent = True
        print(f"[browser] Launched browser profile: {self.user_data_dir}")
        return self._context

    async def _all_pages(self) -> list[Page]:
        if not self._browser:
            return []
        pages: list[Page] = []
        for ctx in self._browser.contexts:
            pages.extend([p for p in ctx.pages if not p.is_closed()])
        return pages

    def _host_matches(self, url: str, prefer_hosts: list[str]) -> bool:
        host = urlparse(url).netloc.lower()
        return any(h in host for h in prefer_hosts)

    def _is_blocked_fallback(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return any(b in host for b in BLOCKED_FALLBACK_HOSTS)

    async def get_work_page(self, prefer_hosts: list[str] | None = None) -> Page:
        """Reuse your logged-in tab for the target site. Never opens a fresh unlogged tab."""
        if self._work_page and not self._work_page.is_closed():
            return self._work_page

        if not self._browser:
            await self.connect()

        assert self._browser is not None
        pages = await self._all_pages()
        hosts = [h.lower() for h in (prefer_hosts or [])]

        if self.reuse_existing_tabs and pages:
            # 1) Best match: prefer logged-in home pages (feed/jobs) over random deep links
            if "linkedin.com" in hosts:
                priority = []
                other = []
                for page in pages:
                    if not self._host_matches(page.url, hosts):
                        continue
                    url = page.url.lower()
                    if any(p in url for p in ["/feed", "/jobs/search", "/notifications", "/mynetwork"]):
                        priority.append(page)
                    elif "/jobs" in url and "/jobs/view/" not in url:
                        priority.append(page)
                    elif "/login" not in url and "/signup" not in url:
                        other.append(page)
                for page in priority + other:
                    await page.bring_to_front()
                    self._work_page = page
                    page.on("dialog", lambda dialog: asyncio.create_task(self._safe_dismiss_dialog(dialog)))
                    self._context = page.context
                    self._created_work_page = False
                    print(f"[browser] Reusing LinkedIn tab: {page.url}")
                    return page

            for page in pages:
                if hosts and self._host_matches(page.url, hosts):
                    await page.bring_to_front()
                    self._work_page = page
                    page.on("dialog", lambda dialog: asyncio.create_task(self._safe_dismiss_dialog(dialog)))
                    self._context = page.context
                    self._created_work_page = False
                    print(f"[browser] Reusing logged-in tab: {page.url}")
                    return page

            # 2) Required site tab missing — do NOT fall back to random tabs
            if hosts and self.never_open_new_tabs:
                site = prefer_hosts[0] if prefer_hosts else "job site"
                raise ConnectionError(
                    f"No open tab found for {site}.\n"
                    f"Open {site} in your Brave window (logged in), then run apply again.\n"
                    f"Current tabs: {[p.url for p in pages]}"
                )

            # 3) Fallback: any non-blocked tab (only when no specific site required)
            for page in pages:
                if not self._is_blocked_fallback(page.url):
                    await page.bring_to_front()
                    self._work_page = page
                    page.on("dialog", lambda dialog: asyncio.create_task(self._safe_dismiss_dialog(dialog)))
                    self._context = page.context
                    self._created_work_page = False
                    print(f"[browser] Reusing tab: {page.url}")
                    return page

        if self.never_open_new_tabs:
            raise ConnectionError(
                "No usable browser tab found and opening new tabs is disabled.\n"
                "Open the job site (logged in) in Brave, then run apply again."
            )

        assert self._context is not None
        page = await self._context.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(self._safe_dismiss_dialog(dialog)))
        self._work_page = page
        self._created_work_page = True
        print("[browser] Opened a new tab (no reusable tab found)")
        return page

    async def _safe_dismiss_dialog(self, dialog) -> None:
        try:
            await dialog.dismiss()
        except Exception:
            pass

    async def new_page(self) -> Page:
        return await self.get_work_page()

    async def close(self) -> None:
        if self._created_work_page and self._work_page and not self._work_page.is_closed():
            try:
                await self._work_page.close()
            except Exception:
                pass
        if self._persistent and self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        elif self._browser:
            try:
                # Disconnect instead of close to avoid killing the user's browser, 
                # or catch exceptions if the CDP connection drops
                if hasattr(self._browser, "disconnect"):
                    await self._browser.disconnect()
                else:
                    await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    async def __aenter__(self) -> BrowserContext:
        return await self.connect()

    async def __aexit__(self, *args) -> None:
        await self.close()


async def safe_goto(page: Page, url: str, timeout: int = 60000) -> None:
    if page.url.split("?")[0] != url.split("?")[0]:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(1500)
    else:
        await page.wait_for_timeout(500)


async def click_first_visible(page: Page, selectors: list[str], timeout: int = 5000) -> bool:
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


async def text_from_selectors(page: Page, selectors: list[str]) -> str:
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if await loc.count() > 0:
                text = (await loc.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


async def wait_for_human(page: Page, message: str) -> bool:
    print(f"\n[HUMAN REQUIRED] {message}")
    print("Complete the step in the browser, then press Enter here to continue...")
    try:
        await asyncio.get_event_loop().run_in_executor(None, input)
        return True
    except EOFError:
        print("[warn] Non-interactive terminal — mark job for manual completion in browser.")
        return False


def detect_captcha(page_text: str) -> bool:
    markers = ["captcha", "verify you are human", "security check", "unusual traffic"]
    lower = page_text.lower()
    return any(m in lower for m in markers)


async def list_open_tabs(cdp_url: str) -> list[str]:
    session = BrowserSession({"browser": {"cdp_url": cdp_url, "mode": "cdp"}})
    try:
        await session.connect()
        return [p.url for p in await session._all_pages()]
    finally:
        await session.close()