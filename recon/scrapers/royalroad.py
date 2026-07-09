"""Royal Road search + fiction detail scraper."""

import json
import re
import urllib.parse

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext

from recon.config import TOP_N
from recon.core.browser import fetch_page
from recon.core.html_cache import load_html, save_html
from recon.scrapers.base import clean_text, parse_int, soup


BASE = "https://www.royalroad.com"


def search_url(keyword: str, tags: list[str] | None = None) -> str:
    params: list[tuple[str, str]] = [("title", keyword)]
    if tags:
        for t in tags[:2]:
            params.append(("tagsAdd", t.replace(" ", "_")))
    params.append(("orderBy", "popularity"))
    return f"{BASE}/fictions/search?{urllib.parse.urlencode(params)}"


def parse_search(html: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    for m in re.finditer(r'/fiction/(\d+)/', html):
        fid = m.group(1)
        if fid in seen:
            continue
        seen.add(fid)
        results.append(
            {
                "platform": "royalroad",
                "external_id": fid,
                "story_url": f"{BASE}/fiction/{fid}",
            }
        )
        if len(results) >= TOP_N:
            break

    if len(results) < TOP_N:
        s = soup(html)
        for a in s.select("a[href*='/fiction/']"):
            href = a.get("href", "")
            m = re.search(r"/fiction/(\d+)", href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                results.append(
                    {
                        "platform": "royalroad",
                        "external_id": m.group(1),
                        "story_url": f"{BASE}/fiction/{m.group(1)}",
                    }
                )
                if len(results) >= TOP_N:
                    break
    return results[:TOP_N]


def _parse_json_ld(s: BeautifulSoup) -> dict | None:
    for script in s.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw or '"@type":"Book"' not in raw and '"@type": "Book"' not in raw:
            continue
        try:
            data = json.loads(raw)
            if data.get("@type") == "Book":
                return data
        except json.JSONDecodeError:
            continue
    return None


def _parse_fiction_stats(s) -> dict:
    """Parse label/value pairs from .fiction-stats (e.g. 'Followers :' -> '5,384')."""
    out: dict = {}
    key_map = {
        "total views": "view_count",
        "followers": "follower_count",
        "ratings": "review_count",
        "pages": "page_count",
        "favorites": "follower_count",  # fallback only if followers missing
    }
    for ul in s.select(".fiction-stats ul.list-unstyled"):
        items = ul.select("li")
        i = 0
        while i < len(items) - 1:
            label = clean_text(items[i].get_text())
            value = clean_text(items[i + 1].get_text())
            if label and value:
                norm = re.sub(r"[^a-z ]+", "", label.lower()).strip()
                for prefix, field in key_map.items():
                    if norm.startswith(prefix):
                        if field == "page_count":
                            out["page_count"] = parse_int(value)
                            out.setdefault("chapter_count", parse_int(value))
                        elif field == "follower_count" and "follower_count" not in out:
                            out["follower_count"] = parse_int(value)
                        else:
                            out.setdefault(field, parse_int(value) if field != "rating_avg" else value)
                        break
                # Overall score row: value is a star span, not plain text
                if "overall score" in (label or "").lower():
                    star = items[i + 1].select_one("[data-content], [aria-label]")
                    if star:
                        dc = star.get("data-content") or star.get("aria-label") or ""
                        m = re.search(r"([\d.]+)", dc)
                        if m:
                            out["rating_avg"] = float(m.group(1))
            i += 2
    return out


def parse_story(html: str, fiction_id: str) -> dict:
    s = soup(html)
    data: dict = {
        "platform": "royalroad",
        "external_id": fiction_id,
        "story_url": f"{BASE}/fiction/{fiction_id}",
    }

    title_el = s.select_one("h1") or s.select_one(".fiction-title")
    data["title"] = clean_text(title_el.get_text() if title_el else None)

    author_el = s.select_one(".fiction-info a[href*='/profile/']") or s.select_one("a[href*='/profile/']")
    if author_el:
        data["author_name"] = clean_text(author_el.get_text())
        href = author_el.get("href", "")
        data["author_url"] = href if href.startswith("http") else f"{BASE}{href}"

    # JSON-LD is the most reliable source for rating + views + pages
    ld = _parse_json_ld(s)
    if ld:
        rating = ld.get("aggregateRating") or {}
        if rating.get("ratingValue"):
            data["rating_avg"] = float(rating["ratingValue"])
        if rating.get("ratingCount"):
            data["review_count"] = int(rating["ratingCount"])
        stats = ld.get("interactionStatistic") or {}
        if stats.get("userInteractionCount"):
            data["view_count"] = int(stats["userInteractionCount"])
        if ld.get("numberOfPages"):
            data["page_count"] = int(ld["numberOfPages"])
        if ld.get("dateModified"):
            data["last_update"] = ld["dateModified"][:10]

    # HTML stats block (backup / extra fields)
    data.update({k: v for k, v in _parse_fiction_stats(s).items() if k not in data or data[k] is None})

    # Meta og rating fallback
    if not data.get("rating_avg"):
        meta = s.select_one('meta[property="books:rating:value"]')
        if meta and meta.get("content"):
            data["rating_avg"] = float(meta["content"])

    # Chapter count from TOC header
    ch = s.find(string=re.compile(r"(\d+)\s+Chapters", re.I))
    if ch:
        m = re.search(r"(\d+)\s+Chapters", ch, re.I)
        if m:
            data["chapter_count"] = int(m.group(1))

    # Status badges near fiction-info
    info = s.select_one(".fiction-info")
    if info:
        badges = clean_text(info.get_text()) or ""
        for st in ("ongoing", "completed", "hiatus", "stub"):
            if re.search(rf"\b{st}\b", badges, re.I):
                data["status"] = st if st != "stub" else "stubbed"
                break

    tags = []
    for a in s.select("a.fiction-tag, a[href*='/fictions/search?tagsAdd=']"):
        t = clean_text(a.get_text())
        if t and t.upper() not in ("STUB", "ORIGINAL"):
            tags.append(t)
    if tags:
        data["tags"] = json.dumps(tags[:8])

    return data


def parse_reviews(html: str) -> list[dict]:
    s = soup(html)
    reviews: list[dict] = []
    for block in s.select(".review, .review-inner, [class*='review']")[:20]:
        body = clean_text(block.get_text())
        if not body or len(body) < 20:
            continue
        rating = None
        stars = block.select("[class*='star'], .rating")
        if stars:
            m = re.search(r"([\d.]+)", stars[0].get_text())
            if m:
                rating = int(float(m.group(1)))
        reviews.append({"body": body[:2000], "rating": rating})
        if len(reviews) >= 20:
            break
    return reviews


def search(
    context: BrowserContext, keyword: str, subniche_id: int, tags: list[str] | None = None
) -> list[dict]:
    url = search_url(keyword, tags)
    _, html = fetch_page(context, url, platform="royalroad", wait_selector="body")
    save_html("royalroad", f"search_{subniche_id}", "search", html)
    items = parse_search(html)
    for i, item in enumerate(items,  1):
        item["rank_in_search"] = i
        item["search_keyword"] = keyword
        item["subniche_id"] = subniche_id
    return items


def scrape_detail(context: BrowserContext, fiction_id: str) -> dict:
    url = f"{BASE}/fiction/{fiction_id}"
    _, html = fetch_page(context, url, platform="royalroad", wait_selector=".fiction-stats")
    save_html("royalroad", fiction_id, "story", html)
    return parse_story(html, fiction_id)


def reparse_cached(fiction_id: str) -> dict | None:
    """Re-parse a cached story HTML without hitting the network."""
    html = load_html("royalroad", fiction_id, "story")
    if not html:
        return None
    return parse_story(html, fiction_id)


def scrape_reviews(context: BrowserContext, fiction_id: str) -> list[dict]:
    url = f"{BASE}/fiction/{fiction_id}/reviews"
    try:
        _, html = fetch_page(context, url, platform="royalroad", wait_selector="body")
        save_html("royalroad", fiction_id, "reviews", html)
        return parse_reviews(html)
    except Exception:
        return []
