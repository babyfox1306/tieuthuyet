"""Amazon author page → portfolio stats."""

import re
from datetime import datetime, timedelta

from playwright.sync_api import BrowserContext

from recon.core.browser import fetch_page
from recon.core.html_cache import save_html
from recon.scrapers.base import clean_text, soup


def parse_author_id(url: str) -> str:
    m = re.search(r"/e/([A-Z0-9]+)", url) or re.search(r"author=([A-Z0-9]+)", url)
    return m.group(1) if m else url


def parse_author(html: str, author_url: str) -> dict:
    s = soup(html)
    author_id = parse_author_id(author_url)
    data: dict = {
        "platform": "amazon",
        "external_id": author_id,
        "profile_url": author_url,
    }

    name_el = s.select_one("h1") or s.select_one("#ap-author-name")
    data["name"] = clean_text(name_el.get_text() if name_el else None)

    books = s.select('a[href*="/dp/"]')
    asins = set()
    for a in books:
        m = re.search(r"/dp/([A-Z0-9]{10})", a.get("href", ""))
        if m:
            asins.add(m.group(1))
    data["total_books"] = len(asins)

    # Vella mention
    vella = s.find(string=re.compile(r"Vella|Kindle Vella", re.I))
    data["has_vella"] = 1 if vella else 0

    # Recent publish heuristic from page text
    dates = re.findall(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
        html,
    )
    latest = None
    for d in dates:
        try:
            dt = datetime.strptime(d, "%B %d, %Y")
            if latest is None or dt > latest:
                latest = dt
        except ValueError:
            pass
    if latest:
        data["latest_publish_date"] = latest.strftime("%Y-%m-%d")
        cutoff = datetime.now() - timedelta(days=180)
        data["active_6mo"] = 1 if latest >= cutoff else 0

    return data


def scrape(context: BrowserContext, author_url: str) -> dict:
    if not author_url.startswith("http"):
        author_url = f"https://www.amazon.com{author_url}"
    _, html = fetch_page(context, author_url, platform="amazon")
    save_html("amazon", parse_author_id(author_url), "author", html)
    return parse_author(html, author_url)
