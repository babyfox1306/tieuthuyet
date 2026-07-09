"""Shared scraper helpers."""

import re
from typing import Any

from bs4 import BeautifulSoup


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d]", "", text.replace(",", ""))
    return int(cleaned) if cleaned else None


def parse_float(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"[\d.]+", text.replace(",", ""))
    return float(m.group()) if m else None


def parse_rating_count(text: str) -> tuple[float | None, int | None]:
    """Parse '4.5 out of 5 stars' and '1,234 ratings'."""
    if not text:
        return None, None
    rating = None
    count = None
    rm = re.search(r"([\d.]+)\s*out of", text, re.I)
    if rm:
        rating = float(rm.group(1))
    cm = re.search(r"([\d,]+)\s*rat", text, re.I)
    if cm:
        count = parse_int(cm.group(1))
    return rating, count


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def extract_links_by_pattern(html: str, pattern: str, base_url: str = "") -> list[str]:
    found: list[str] = []
    for m in re.finditer(pattern, html):
        url = m.group(1) if m.lastindex else m.group(0)
        if url.startswith("/"):
            url = base_url.rstrip("/") + url
        if url not in found:
            found.append(url)
    return found
