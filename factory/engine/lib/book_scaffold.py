"""Scaffold workspace + catalog for book 2, 3, … within an existing series workspace."""

from __future__ import annotations

import json
from typing import Any

import yaml

from factory.engine.lib.book_config import get_total_chapters, set_total_chapters
from factory.engine.lib.narrative_schema import load_concept, save_concept_yaml
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import (
    book_catalog_dir,
    book_workspace_dir,
    catalog_series_dir,
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
    ws = workspace_dir(workspace_id)
    seen: dict[int, dict[str, Any]] = {}

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
                    title = str(
                        (yaml.safe_load(by.read_text(encoding="utf-8")) or {}).get("title") or ""
                    )
                row["title"] = title
                if not title:
                    c = load_concept(ws, num)
                    if c.get("title"):
                        row["title"] = str(c["title"])
                seen[num] = row

    for p in sorted((ws / "books").glob("[0-9][0-9]")):
        if not p.is_dir():
            continue
        num = int(p.name)
        row = seen.get(num, {"book": num, "source": "workspace"})
        if (p / "master_plan.json").exists():
            row["has_plan"] = True
        if not row.get("title"):
            c = load_concept(ws, num)
            if c.get("title"):
                row["title"] = str(c["title"])
        if (p / "concept.yaml").exists() or (num == 1 and (ws / "concept.yaml").exists()):
            row["has_concept"] = True
        seen[num] = row

    return [seen[k] for k in sorted(seen)]


def book_title_from_series(workspace_id: str, book: int) -> str:
    ws = workspace_dir(workspace_id)
    existing = load_concept(ws, book)
    if existing.get("title"):
        return str(existing["title"]).strip()
    bible = ws / "bible" / "series.json"
    if bible.exists():
        data = json.loads(bible.read_text(encoding="utf-8"))
        if book == 1 and data.get("title"):
            return str(data["title"])
    concept = load_concept(ws, 1)
    if book == 1:
        return str(concept.get("title") or "Book 1")
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
    concept_seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create workspace books/NN, catalog entry, pipeline buckets. Idempotent."""
    if book < 1:
        raise ValueError("book must be >= 1")
    ws = workspace_dir(workspace_id)
    if not ws.exists():
        raise FileNotFoundError(f"workspace not found: {workspace_id}")

    direction = load_direction(ws)
    concept_b1 = load_concept(ws, 1)
    total = total_chapters or get_total_chapters(workspace_id, book)
    title = (title or book_title_from_series(workspace_id, book) or f"Book {book}").strip()
    slug = slug or default_book_slug(workspace_id, book, title)

    book_ws = book_workspace_dir(ws, book)
    book_ws.mkdir(parents=True, exist_ok=True)
    for bucket in _PIPELINE_BUCKETS:
        (book_ws / "pipeline" / bucket).mkdir(parents=True, exist_ok=True)

    plan_path = book_ws / "master_plan.json"

    book_dir = book_catalog_dir(workspace_id, slug)
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    (book_dir / "exports").mkdir(parents=True, exist_ok=True)

    by_path = book_dir / "book.yaml"
    if not by_path.exists():
        by_path.write_text(
            yaml.dump(
                {
                    "book": book,
                    "slug": slug,
                    "title": title,
                    "series": workspace_id,
                    "language": direction.get("target_language")
                    or concept_b1.get("target_language")
                    or "en",
                    "total_chapters": total,
                },
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    else:
        meta = yaml.safe_load(by_path.read_text(encoding="utf-8")) or {}
        meta["title"] = title
        meta["slug"] = slug
        meta["book"] = book
        if total_chapters is not None:
            meta["total_chapters"] = total
        by_path.write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    existing_concept = load_concept(ws, book)
    concept_created = False
    if not existing_concept:
        seed: dict[str, Any] = {
            "concept_status": "draft",
            "concept_schema_version": 2,
            "target_language": direction.get("target_language")
            or concept_b1.get("target_language")
            or "en",
            "chapter_count": total,
            "title": title,
            "logline": "",
            "author_directive": "",
            "surface_plot": "",
            "true_plot": "",
            "must_include": [],
            "must_avoid": [],
            "ending_book1": "",
            "hook_book2": "",
            "notes": f"Book {book} of series {workspace_id}",
        }
        if concept_seed:
            seed.update(concept_seed)
            seed["title"] = title
            seed["chapter_count"] = total
            seed.setdefault("concept_status", "draft")
        save_concept_yaml(ws, seed, book)
        concept_created = True

    if book >= 2:
        manifest_path = ws / "manifest.yaml"
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        manifest["active_book"] = book
        manifest["book_slug"] = slug
        if total_chapters is not None:
            manifest["total_chapters"] = total
        manifest_path.write_text(
            yaml.dump(manifest, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        direction["book"] = book
        direction["book_slug"] = slug
        direction["canon_through"] = int(direction.get("canon_through") or 0)
        if total_chapters is not None:
            direction["total_chapters"] = total
        (ws / "direction.yaml").write_text(
            yaml.dump(direction, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    if update_config and total_chapters is not None:
        set_total_chapters(workspace_id, book, total)

    return {
        "workspace_id": workspace_id,
        "book": book,
        "title": title,
        "slug": slug,
        "workspace_dir": str(book_ws),
        "catalog_dir": str(book_dir),
        "plan_path": str(plan_path),
        "concept_created": concept_created,
        "total_chapters": total,
    }
