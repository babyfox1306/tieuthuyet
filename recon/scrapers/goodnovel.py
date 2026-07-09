"""GoodNovel.com search + story detail scraper."""

import json
import re
import urllib.parse

from playwright.sync_api import BrowserContext

from recon.config import TOP_N
from recon.core.browser import fetch_page
from recon.core.html_cache import save_html
from recon.scrapers.base import clean_text, parse_int, soup


BASE = "https://www.goodnovel.com"


def search_url(keyword: str) -> str:
    q = urllib.parse.quote_plus(keyword)
    return f"{BASE}/search?searchKey={q}"


def parse_search(html: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    for m in re.finditer(r'/book/([a-zA-Z0-9_-]+)', html):
        bid = m.group(1)
        if bid in seen:
            continue
        seen.add(bid)
        results.append(
            {
                "platform": "goodnovel",
                "external_id": bid,
                "story_url": f"{BASE}/book/{bid}",
            }
        )
        if len(results) >= TOP_N:
            break

    if len(results) < TOP_N:
        s = soup(html)
        for a in s.select("a[href*='/book/']"):
            href = a.get("href", "")
            m = re.search(r"/book/([a-zA-Z0-9_-]+)", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                results.append(
                    {
                        "platform": "goodnovel",
                        "external_id": m.group(1),
                        "story_url": f"{BASE}/book/{m.group(1)}",
                    }
                )
                if len(results) >= TOP_N:
                    break
    return results[:TOP_N]


def parse_story(html: str, book_id: str) -> dict:
    s = soup(html)
    data: dict = {
        "platform": "goodnovel",
        "external_id": book_id,
        "story_url": f"{BASE}/book/{book_id}",
    }

    title_el = s.select_one("h1") or s.select_one(".book-title")
    data["title"] = clean_text(title_el.get_text() if title_el else None)

    author_el = s.select_one("a[href*='/author/']") or s.select_one(".author-name")
    if author_el:
        data["author_name"] = clean_text(author_el.get_text())
        href = author_el.get("href", "")
        data["author_url"] = href if href.startswith("http") else f"{BASE}{href}"

    text_blob = s.get_text(" ", strip=True)

    vm = re.search(r"([\d,.]+[KkMm]?)\s*(?:reads|views|Views)", text_blob, re.I)
    if vm:
        raw = vm.group(1).replace(",", "")
        mult = 1
        if raw[-1].lower() == "k":
            mult = 1000
            raw = raw[:-1]
        elif raw[-1].lower() == "m":
            mult = 1_000_000
            raw = raw[:-1]
        try:
            data["view_count"] = int(float(raw) * mult)
        except ValueError:
            pass

    cm = re.search(r"(\d+)\s*(?:chapters|Chapters)", text_blob)
    if cm:
        data["chapter_count"] = int(cm.group(1))

    rm = re.search(r"([\d.]+)\s*(?:rating|score)", text_blob, re.I)
    if rm:
        data["rating_avg"] = float(rm.group(1))

    if re.search(r"\bcompleted\b", text_blob, re.I):
        data["status"] = "completed"
    elif re.search(r"\bongoing\b", text_blob, re.I):
        data["status"] = "ongoing"

    tags = []
    for a in s.select("a[href*='/tag/'], a[href*='/category/']"):
        t = clean_text(a.get_text())
        if t:
            tags.append(t)
    if tags:
        data["tags"] = json.dumps(tags[:5])

    return data


def search(context: BrowserContext, keyword: str, subniche_id: int) -> list[dict]:
    url = search_url(keyword)
    _, html = fetch_page(context, url, platform="goodnovel", wait_selector="body")
    save_html("goodnovel", f"search_{subniche_id}", "search", html)
    items = parse_search(html)
    for i, item in enumerate(items, 1):
        item["rank_in_search"] = i
        item["search_keyword"] = keyword
        item["subniche_id"] = subniche_id
    return items


def scrape_detail(context: BrowserContext, book_id: str) -> dict:
    url = f"{BASE}/book/{book_id}"
    _, html = fetch_page(context, url, platform="goodnovel", wait_selector="body")
    save_html("goodnovel", book_id, "story", html)
    return parse_story(html, book_id)
