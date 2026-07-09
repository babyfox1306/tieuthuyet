"""Save raw HTML for re-parsing without re-scraping."""

import hashlib
from pathlib import Path

from recon.config import RAW_HTML_DIR


def cache_key(platform: str, identifier: str, page_type: str) -> str:
    raw = f"{platform}:{page_type}:{identifier}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def save_html(platform: str, identifier: str, page_type: str, html: str) -> Path:
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(platform, identifier, page_type)
    path = RAW_HTML_DIR / platform / f"{key}_{page_type}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def load_html(platform: str, identifier: str, page_type: str) -> str | None:
    key = cache_key(platform, identifier, page_type)
    path = RAW_HTML_DIR / platform / f"{key}_{page_type}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
