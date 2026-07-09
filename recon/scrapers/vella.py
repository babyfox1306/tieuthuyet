"""Kindle Vella search + story detail scraper."""

import json
import re
import urllib.parse

from playwright.sync_api import BrowserContext

from recon.config import TOP_N
from recon.core.browser import fetch_page
from recon.core.html_cache import save_html
from recon.scrapers.base import clean_text, parse_float, parse_int, soup


BASE = "https://www.amazon.com"


def search_url(keyword: str) -> str:
    q = urllib.parse.quote_plus(keyword)
    return f"{BASE}/s?k={q}&i=digital-text&rh=n%3A19419896011"


def parse_search(html: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'/story/([a-zA-Z0-9_-]+)', html):
        sid = m.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        results.append(
            {
                "platform": "vella",
                "external_id": sid,
                "story_url": f"{BASE}/kindle-vella/story/{sid}",
            }
        )
        if len(results) >= TOP_N:
            break
    if len(results) < TOP_N:
        for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', html):
            asin = m.group(1)
            if asin in seen:
                continue
            seen.add(asin)
            results.append(
                {
                    "platform": "vella",
                    "external_id": asin,
                    "story_url": f"{BASE}/dp/{asin}",
                }
            )
            if len(results) >= TOP_N:
                break
    return results[:TOP_N]


def parse_story(html: str, external_id: str, story_url: str) -> dict:
    s = soup(html)
    data: dict = {
        "platform": "vella",
        "external_id": external_id,
        "story_url": story_url,
        "ku_enrolled": 1,
    }
    title_el = s.select_one("h1") or s.select_one("#productTitle")
    data["title"] = clean_text(title_el.get_text() if title_el else None)

    author_el = s.select_one("a[href*='author']") or s.select_one(".author")
    if author_el:
        data["author_name"] = clean_text(author_el.get_text())
        href = author_el.get("href", "")
        data["author_url"] = href if href.startswith("http") else f"{BASE}{href}"

    # Episodes / chapters
    for text in s.stripped_strings:
        if "episode" in text.lower():
            m = re.search(r"(\d+)\s*episode", text, re.I)
            if m:
                data["episodes_count"] = int(m.group(1))
                data["chapter_count"] = int(m.group(1))
                break

    rating_el = s.select_one("[data-hook='rating-out-of-text']")
    if rating_el:
        rm = re.search(r"([\d.]+)", rating_el.get_text())
        if rm:
            data["rating_avg"] = float(rm.group(1))
    count_el = s.select_one("#acrCustomerReviewText")
    if count_el:
        cm = re.search(r"([\d,]+)", count_el.get_text())
        if cm:
            data["review_count"] = parse_int(cm.group(1))

    tags = []
    for a in s.select("a[href*='kindle-vella']"):
        t = clean_text(a.get_text())
        if t and len(t) < 40:
            tags.append(t)
    if tags:
        data["tags"] = json.dumps(tags[:5])

    return data


def search(context: BrowserContext, keyword: str, subniche_id: int) -> list[dict]:
    url = search_url(keyword)
    _, html = fetch_page(context, url, platform="vella", wait_selector="body")
    save_html("vella", f"search_{subniche_id}", "search", html)
    items = parse_search(html)
    for i, item in enumerate(items, 1):
        item["rank_in_search"] = i
        item["search_keyword"] = keyword
        item["subniche_id"] = subniche_id
    return items


def scrape_detail(context: BrowserContext, external_id: str, story_url: str) -> dict:
    _, html = fetch_page(context, story_url, platform="vella", wait_selector="body")
    save_html("vella", external_id, "story", html)
    return parse_story(html, external_id, story_url)
