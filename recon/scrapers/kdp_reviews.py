"""Amazon reviews → 20 newest + velocity signal."""

import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import BrowserContext

from recon.core.browser import fetch_page
from recon.core.html_cache import save_html
from recon.scrapers.base import clean_text, soup


def reviews_url(asin: str) -> str:
    return f"https://www.amazon.com/product-reviews/{asin}/ref=cm_cr_dp_d_show_all_btm?sortBy=recent"


def _parse_review_date(text: str) -> str | None:
    if not text:
        return None
    text = text.replace("Reviewed in the United States on ", "").strip()
    for fmt in ("%B %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def parse_reviews(html: str) -> tuple[list[dict], int]:
    s = soup(html)
    reviews: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    for block in s.select("[data-hook='review']")[:20]:
        rating_el = block.select_one("[data-hook='review-star-rating']") or block.select_one(
            "i.review-rating"
        )
        rating = None
        if rating_el:
            m = re.search(r"([\d.]+)", rating_el.get_text())
            if m:
                rating = int(float(m.group(1)))

        title_el = block.select_one("[data-hook='review-title']")
        body_el = block.select_one("[data-hook='review-body']")
        date_el = block.select_one("[data-hook='review-date']")
        reviewer_el = block.select_one(".a-profile-name")

        review_date = _parse_review_date(date_el.get_text(strip=True) if date_el else "")
        reviews.append(
            {
                "rating": rating,
                "title": clean_text(title_el.get_text() if title_el else None),
                "body": clean_text(body_el.get_text() if body_el else None),
                "review_date": review_date,
                "reviewer": clean_text(reviewer_el.get_text() if reviewer_el else None),
            }
        )

    velocity = 0
    for r in reviews:
        if r.get("review_date"):
            try:
                dt = datetime.strptime(r["review_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    velocity += 1
            except ValueError:
                pass
    return reviews, velocity


def scrape(context: BrowserContext, asin: str) -> tuple[list[dict], int]:
    url = reviews_url(asin)
    _, html = fetch_page(context, url, platform="amazon", wait_selector="[data-hook='review']")
    save_html("amazon", asin, "reviews", html)
    return parse_reviews(html)
