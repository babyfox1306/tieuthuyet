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


def save_config_patch(updates: dict) -> dict:
    """Merge keys into config.json (preserves unrelated settings / secrets)."""
    path = ENGINE / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(updates)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cfg


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
    """Map book number → catalog slug from workspace direction.yaml, then catalog scan."""
    from factory.engine.lib.prompt_builder import load_direction

    cfg = cfg or load_config()
    book = int(book or cfg.get("active_book") or 1)
    ws = workspace_dir(workspace_id)
    direction = load_direction(ws)
    active_book = int(direction.get("book") or 1)
    dir_slug = str(direction.get("book_slug") or "").strip()
    if book == active_book and dir_slug:
        return dir_slug

    books_dir = catalog_series_dir(workspace_id) / "books"
    prefix = f"{book:02d}-"
    if books_dir.exists():
        for p in sorted(books_dir.iterdir()):
            if p.is_dir() and p.name.startswith(prefix):
                return p.name
    return f"{book:02d}-{workspace_id}"


def resolve_book_number(book_slug: str) -> int:
    prefix = book_slug.split("-", 1)[0]
    if prefix.isdigit():
        return int(prefix)
    return 1
