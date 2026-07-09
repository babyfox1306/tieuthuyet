"""Shared path helpers for factory + catalog."""

from __future__ import annotations

import json
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
FACTORY = ENGINE.parent
ROOT = FACTORY.parent
CATALOG = ROOT / "catalog"
WORKSPACES = FACTORY / "workspaces"


def load_config() -> dict:
    return json.loads((ENGINE / "config.json").read_text(encoding="utf-8"))


def bible_path(ws: Path) -> Path:
    return ws / "bible" / "series.json"


def workspace_dir(name: str | None = None) -> Path:
    cfg = load_config()
    wid = name or cfg.get("default_workspace", "ceo-contract")
    return WORKSPACES / wid


def catalog_series_dir(workspace_id: str | None = None) -> Path:
    cfg = load_config()
    wid = workspace_id or cfg.get("default_workspace", "ceo-contract")
    return CATALOG / wid


def book_workspace_dir(ws: Path, book: int) -> Path:
    return ws / "books" / f"{book:02d}"


def pipeline_dir(ws: Path, book: int, bucket: str) -> Path:
    p = book_workspace_dir(ws, book) / "pipeline" / bucket
    p.mkdir(parents=True, exist_ok=True)
    return p


def chapter_pipeline_path(ws: Path, book: int, bucket: str, ch: int) -> Path:
    return pipeline_dir(ws, book, bucket) / f"ch_{ch:03d}.txt"


def promoted_marker(ws: Path, book: int, ch: int) -> Path:
    return pipeline_dir(ws, book, "ready") / f"ch_{ch:03d}.promoted"


def book_catalog_dir(series_id: str, book_slug: str) -> Path:
    return catalog_series_dir(series_id) / "books" / book_slug


def catalog_archive_dir(workspace_id: str, book_slug: str) -> Path:
    """Single rolling backup per book — new backup replaces the previous folder."""
    return CATALOG.parent / "archive" / f"catalog_{workspace_id}_{book_slug}"


def resolve_book_slug(
    workspace_id: str,
    book: int | None = None,
    *,
    cfg: dict | None = None,
) -> str:
    """Map book number → catalog slug (config.book_slugs, catalog scan, fallback)."""
    cfg = cfg or load_config()
    book = int(book or cfg.get("active_book") or 1)
    slugs = cfg.get("book_slugs") or {}
    if str(book) in slugs:
        return str(slugs[str(book)])
    books_dir = catalog_series_dir(workspace_id) / "books"
    if books_dir.exists():
        prefix = f"{book:02d}-"
        for p in sorted(books_dir.iterdir()):
            if p.is_dir() and p.name.startswith(prefix):
                return p.name
    if book == 1:
        return str(cfg.get("book_slug", "01-hop-dong-co-gia"))
    raise ValueError(f"No catalog slug for workspace={workspace_id} book={book}")


def resolve_book_number(book_slug: str) -> int:
    prefix = book_slug.split("-", 1)[0]
    if prefix.isdigit():
        return int(prefix)
    return 1
