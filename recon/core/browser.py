"""Playwright browser session with user-agent rotation."""

import random
import re
from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from recon.config import USER_AGENTS
from recon.core.delays import random_delay


class CaptchaDetected(Exception):
    """Raised when Amazon (or similar) serves a CAPTCHA page."""

    def __init__(self, url: str, platform: str = "amazon"):
        self.url = url
        self.platform = platform
        super().__init__(f"CAPTCHA detected on {platform}: {url}")


CAPTCHA_PATTERNS = re.compile(
    r"captcha|robot check|type the characters|sorry, we just need to make sure",
    re.I,
)


@contextmanager
def browser_session(headless: bool = True) -> Generator[tuple[Browser, BrowserContext], None, None]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="en-US",
            viewport={"width": 1366, "height": 768},
        )
        try:
            yield browser, context
        finally:
            context.close()
            browser.close()


def fetch_page(
    context: BrowserContext,
    url: str,
    *,
    platform: str = "default",
    wait_selector: str | None = None,
    timeout_ms: int = 45000,
) -> tuple[Page, str]:
    """Navigate, detect CAPTCHA, return page + HTML."""
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
            except Exception:
                pass
        random_delay(platform)
        html = page.content()
        if platform in ("amazon", "vella") and CAPTCHA_PATTERNS.search(html):
            raise CaptchaDetected(url, platform)
        return page, html
    except CaptchaDetected:
        page.close()
        raise
    except Exception:
        page.close()
        raise
