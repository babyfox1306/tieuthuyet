"""Amazon product page → book fingerprint."""

import json
import re

from playwright.sync_api import BrowserContext

from recon.core.browser import fetch_page
from recon.core.html_cache import save_html
from recon.scrapers.base import clean_text, parse_float, parse_int, parse_rating_count, soup


def product_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"


def parse_product(html: str, asin: str) -> dict:
    s = soup(html)
    data: dict = {
        "platform": "amazon",
        "external_id": asin,
        "story_url": product_url(asin),
    }

    title_el = s.select_one("#productTitle") or s.select_one("#ebooksProductTitle")
    data["title"] = clean_text(title_el.get_text() if title_el else None)

    author_el = s.select_one("#bylineInfo .author") or s.select_one("a.contributorNameID")
    if author_el:
        data["author_name"] = clean_text(author_el.get_text())
        href = author_el.get("href")
        if href:
            data["author_url"] = href if href.startswith("http") else f"https://www.amazon.com{href}"

    # KU badge
    ku = s.find(string=re.compile(r"Kindle Unlimited", re.I))
    data["ku_enrolled"] = 1 if ku else 0

    # Price
    price_el = s.select_one(".a-price .a-offscreen") or s.select_one("#kindle-price")
    if price_el:
        data["price_usd"] = parse_float(price_el.get_text())

    # Page count
    for li in s.select("#detailBullets_feature_div li, #rpi-attribute-book_details-fiona_pages"):
        text = li.get_text(" ", strip=True)
        if "pages" in text.lower():
            m = re.search(r"(\d[\d,]*)\s*pages", text, re.I)
            if m:
                data["page_count"] = parse_int(m.group(1))
                break

    # BSR
    for el in s.find(string=re.compile(r"Best Sellers Rank", re.I)):
        parent = el.find_parent()
        if parent:
            bsr_text = parent.get_text(" ", strip=True)
            overall = re.search(r"#([\d,]+)\s+in Kindle Store", bsr_text)
            if overall:
                data["bsr_overall"] = parse_int(overall.group(1))
            sub = re.search(r"#([\d,]+)\s+in\s+([^(\n]+)", bsr_text)
            if sub and "Kindle Store" not in sub.group(2):
                data["bsr_sub_rank"] = parse_int(sub.group(1))
                data["bsr_subcategory"] = clean_text(sub.group(2))

    # Rating
    rating_el = s.select_one("#acrPopover") or s.select_one("[data-hook='rating-out-of-text']")
    if rating_el:
        rating, count = parse_rating_count(rating_el.get_text(" ", strip=True))
        data["rating_avg"] = rating
    count_el = s.select_one("#acrCustomerReviewText")
    if count_el:
        _, count = parse_rating_count(count_el.get_text())
        data["review_count"] = count

    # Categories
    cats = []
    for a in s.select("#wayfinding-breadcrumbs_feature_div a"):
        t = clean_text(a.get_text())
        if t:
            cats.append(t)
    if cats:
        data["categories"] = json.dumps(cats[:3])

    # Series info from title/subtitle
    series_text = data.get("title") or ""
    sub_el = s.select_one("#productSubtitle")
    if sub_el:
        series_text += " " + sub_el.get_text()
    sm = re.search(r"(?:Book|Vol\.?|Volume)\s*(\d+)", series_text, re.I)
    if sm:
        data["series_book_num"] = int(sm.group(1))
    series_el = s.find(string=re.compile(r"Book \d+ of \d+", re.I))
    if series_el:
        tm = re.search(r"Book (\d+) of (\d+)", series_el, re.I)
        if tm:
            data["series_book_num"] = int(tm.group(1))
            data["series_total_books"] = int(tm.group(2))

    # Format mix
    formats = []
    if s.find(string=re.compile(r"Kindle", re.I)):
        formats.append("ebook")
    if s.find(string=re.compile(r"Paperback", re.I)):
        formats.append("paperback")
    if s.find(string=re.compile(r"Audiobook", re.I)):
        formats.append("audiobook")
    if formats:
        data["format_mix"] = ",".join(formats)

    # Also bought ASINs
    also = []
    for m in re.finditer(r'/dp/([A-Z0-9]{10})', html):
        aid = m.group(1)
        if aid != asin and aid not in also:
            also.append(aid)
        if len(also) >= 10:
            break
    if also:
        data["also_bought"] = json.dumps(also)

    return data


def scrape(context: BrowserContext, asin: str) -> dict:
    url = product_url(asin)
    _, html = fetch_page(context, url, platform="amazon", wait_selector="#productTitle")
    save_html("amazon", asin, "product", html)
    return parse_product(html, asin)
