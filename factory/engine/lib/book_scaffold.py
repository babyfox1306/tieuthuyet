"""Scaffold workspace + catalog for book 2, 3, … within an existing series workspace."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.book_config import get_total_chapters
from factory.engine.lib.narrative_schema import load_concept
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import (
    book_catalog_dir,
    book_workspace_dir,
    catalog_series_dir,
    load_config,
    workspace_dir,
)

_PIPELINE_BUCKETS = ("draft", "needs_fix", "needs_review", "ready")


def _slugify(title: str) -> str:
    import re

    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")[:48]


def list_series_books(workspace_id: str) -> list[dict[str, Any]]:
    """Books known from config, catalog folders, and workspace books/."""
    cfg = load_config()
    ws = workspace_dir(workspace_id)
    seen: dict[int, dict[str, Any]] = {}

    for key, slug in (cfg.get("book_slugs") or {}).items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        seen[num] = {"book": num, "slug": slug, "source": "config"}

    books_cat = catalog_series_dir(workspace_id) / "books"
    if books_cat.exists():
        for p in sorted(books_cat.iterdir()):
            if not p.is_dir():
                continue
            parts = p.name.split("-", 1)
            if parts and parts[0].isdigit():
                num = int(parts[0])
                row = seen.get(num, {"book": num, "source": "catalog"})
                row["slug"] = p.name
                title = ""
                by = p / "book.yaml"
                if by.exists():
                    title = str((yaml.safe_load(by.read_text(encoding="utf-8")) or {}).get("title") or "")
                row["title"] = title
                seen[num] = row

    for p in sorted((ws / "books").glob("[0-9][0-9]")):
        if not p.is_dir():
            continue
        num = int(p.name)
        row = seen.get(num, {"book": num, "source": "workspace"})
        if (p / "master_plan.json").exists():
            row["has_plan"] = True
        seen[num] = row

    return [seen[k] for k in sorted(seen)]


def book_title_from_series(workspace_id: str, book: int) -> str:
    ws = workspace_dir(workspace_id)
    bible = ws / "bible" / "series.json"
    if bible.exists():
        data = json.loads(bible.read_text(encoding="utf-8"))
        for arc in data.get("series_arc") or []:
            if int(arc.get("book") or 0) == book:
                thesis = str(arc.get("thesis") or "").strip()
                if thesis:
                    return f"The Glass Meridian — Book {book}"
    concept = load_concept(ws)
    if book == 1:
        return str(concept.get("title") or "Book 1")
    if book == 2:
        return "The Altered Name"
    return f"Book {book}"


def default_book_slug(workspace_id: str, book: int, title: str | None = None) -> str:
    title = title or book_title_from_series(workspace_id, book)
    return f"{book:02d}-{_slugify(title)}"


def init_book(
    workspace_id: str,
    book: int,
    *,
    title: str | None = None,
    slug: str | None = None,
    total_chapters: int | None = None,
    update_config: bool = True,
) -> dict[str, Any]:
    """Create workspace books/NN, catalog entry, pipeline buckets. Idempotent."""
    if book < 1:
        raise ValueError("book must be >= 1")
    ws = workspace_dir(workspace_id)
    if not ws.exists():
        raise FileNotFoundError(f"workspace not found: {workspace_id}")

    direction = load_direction(ws)
    concept = load_concept(ws)
    total = total_chapters or get_total_chapters(workspace_id, book)
    title = title or book_title_from_series(workspace_id, book)
    slug = slug or default_book_slug(workspace_id, book, title)

    # Workspace tree
    book_ws = book_workspace_dir(ws, book)
    book_ws.mkdir(parents=True, exist_ok=True)
    for bucket in _PIPELINE_BUCKETS:
        (book_ws / "pipeline" / bucket).mkdir(parents=True, exist_ok=True)

    plan_path = book_ws / "master_plan.json"
    if not plan_path.exists():
        hook = ""
        if book == 2:
            hook = str(concept.get("hook_book2") or "")
        plan = {
            "book": book,
            "title": title,
            "total_chapters": total,
            "status": "draft",
            "book2_hook": hook,
            "chapter_plans": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Catalog
    book_dir = book_catalog_dir(workspace_id, slug)
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    (book_dir / "exports").mkdir(parents=True, exist_ok=True)
    by_path = book_dir / "book.yaml"
    if not by_path.exists():
        lang = direction.get("target_language", "en")
        book_yaml = {
            "book": book,
            "slug": slug,
            "title": title,
            "series": workspace_id,
            "language": lang,
            "total_chapters": total,
            "keywords_kdp": ["romance thriller", "marriage of convenience", "conspiracy"],
            "categories_kdp": ["Fiction > Romance > Suspense"],
            "kindle_unlimited": True,
        }
        if book == 2 and concept.get("hook_book2"):
            book_yaml["hook"] = concept["hook_book2"]
        by_path.write_text(
            yaml.dump(book_yaml, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    # Carry series canon pointer into direction when starting book 2+
    if book >= 2:
        manifest_path = ws / "manifest.yaml"
        manifest = {}
        if manifest_path.exists():
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        manifest["active_book"] = book
        manifest["book_slug"] = slug
        manifest_path.write_text(
            yaml.dump(manifest, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        direction["book"] = book
        direction["book_slug"] = slug
        direction["canon_through"] = int(direction.get("canon_through") or 0)
        (ws / "direction.yaml").write_text(
            yaml.dump(direction, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    if update_config:
        cfg_path = Path(__file__).resolve().parents[1] / "config.json"
        cfg = load_config()
        slugs = dict(cfg.get("book_slugs") or {})
        slugs[str(book)] = slug
        cfg["book_slugs"] = slugs
        cfg["active_book"] = book
        cfg["book_slug"] = slug
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "workspace_id": workspace_id,
        "book": book,
        "title": title,
        "slug": slug,
        "workspace_dir": str(book_ws),
        "catalog_dir": str(book_dir),
        "plan_path": str(plan_path),
    }
