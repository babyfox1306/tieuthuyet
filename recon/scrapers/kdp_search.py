"""Amazon Kindle search → top N ASINs per keyword."""

import re
import urllib.parse

from playwright.sync_api import BrowserContext

from recon.config import TOP_N
from recon.core.browser import fetch_page
from recon.core.html_cache import save_html
from recon.scrapers.base import extract_links_by_pattern, soup


def search_url(keyword: str) -> str:
    q = urllib.parse.quote_plus(keyword)
    return (
        f"https://www.amazon.com/s?k={q}"
        "&i=digital-text&rh=n%3A133140011"
        "&s=exact-aware-popularity-rank"
    )


def parse_search_results(html: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    # data-asin on search result cards
    for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', html):
        asin = m.group(1)
        if asin in seen or asin == "0000000000":
            continue
        seen.add(asin)
        results.append({"external_id": asin, "platform": "amazon"})
        if len(results) >= TOP_N:
            break

    if len(results) < TOP_N:
        s = soup(html)
        for a in s.select('a[href*="/dp/"]'):
            href = a.get("href", "")
            m = re.search(r"/dp/([A-Z0-9]{10})", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                results.append({"external_id": m.group(1), "platform": "amazon"})
                if len(results) >= TOP_N:
                    break
    return results[:TOP_N]


def search(context: BrowserContext, keyword: str, subniche_id: int) -> list[dict]:
    url = search_url(keyword)
    _, html = fetch_page(context, url, platform="amazon", wait_selector="[data-component-type='s-search-result']")
    save_html("amazon", f"search_{subniche_id}", "search", html)
    items = parse_search_results(html)
    for i, item in enumerate(items, 1):
        item["rank_in_search"] = i
        item["search_keyword"] = keyword
        item["subniche_id"] = subniche_id
        item["story_url"] = f"https://www.amazon.com/dp/{item['external_id']}"
    return items
