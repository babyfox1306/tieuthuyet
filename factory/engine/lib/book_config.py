"""Per-book chapter count — single source synced across factory files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.master_plan import load_master_plan, master_plan_path, save_master_plan
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import (
    book_catalog_dir,
    book_workspace_dir,
    load_config,
    resolve_book_slug,
    workspace_dir,
)

MIN_CHAPTERS = 3
MAX_CHAPTERS = 200
DEFAULT_CHAPTERS = 30


def _clamp_total(n: int) -> int:
    return max(MIN_CHAPTERS, min(MAX_CHAPTERS, int(n)))


def get_total_chapters(workspace_id: str, book: int) -> int:
    """Read total chapter target for a book (plan → catalog → direction)."""
    ws = workspace_dir(workspace_id)
    plan_path = master_plan_path(ws, book)
    if plan_path.exists():
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        if data.get("total_chapters"):
            return _clamp_total(int(data["total_chapters"]))

    cfg = load_config()
    try:
        slug = resolve_book_slug(workspace_id, book, cfg=cfg)
        by = book_catalog_dir(workspace_id, slug) / "book.yaml"
        if by.exists():
            meta = yaml.safe_load(by.read_text(encoding="utf-8")) or {}
            if meta.get("total_chapters"):
                return _clamp_total(int(meta["total_chapters"]))
    except ValueError:
        pass

    direction = load_direction(ws)
    active = int(direction.get("book") or 1)
    if book == active and direction.get("total_chapters"):
        return _clamp_total(int(direction["total_chapters"]))

    return DEFAULT_CHAPTERS


def sync_book_arc_total_chapters(ws: Path, book: int, total: int) -> bool:
    """Patch bible/narrative/book_arc.json to match canonical chapter count."""
    arc_path = ws / "bible" / "narrative" / "book_arc.json"
    if not arc_path.exists():
        return False
    try:
        arc = json.loads(arc_path.read_text(encoding="utf-8"))
        changed = int(arc.get("total_chapters") or 0) != total or int(arc.get("book_number") or 0) != book
        if not changed:
            return False
        arc["total_chapters"] = total
        arc["book_number"] = book
        arc_path.write_text(json.dumps(arc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return False


def set_total_chapters(workspace_id: str, book: int, total: int) -> dict[str, Any]:
    """Persist chapter count to plan, catalog, direction (if active book), narrative arc."""
    total = _clamp_total(total)
    ws = workspace_dir(workspace_id)
    direction = load_direction(ws)
    cfg = load_config()
    updated: list[str] = []

    plan = load_master_plan(ws, book)
    existing_plans = len(plan.get("chapter_plans") or [])
    plan["book"] = book
    plan["total_chapters"] = total
    save_master_plan(ws, book, plan)
    updated.append(f"master_plan.json (book {book:02d})")

    try:
        slug = resolve_book_slug(workspace_id, book, cfg=cfg)
        by_path = book_catalog_dir(workspace_id, slug) / "book.yaml"
        if by_path.exists():
            meta = yaml.safe_load(by_path.read_text(encoding="utf-8")) or {}
        else:
            meta = {"book": book, "slug": slug}
        meta["total_chapters"] = total
        by_path.parent.mkdir(parents=True, exist_ok=True)
        by_path.write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        updated.append(f"catalog/{slug}/book.yaml")
    except ValueError:
        pass

    active = int(direction.get("book") or cfg.get("active_book") or 1)
    if book == active:
        from factory.engine.lib.workspace_metadata import rescale_direction_arc

        direction["total_chapters"] = total
        direction["book"] = book
        rescale_direction_arc(ws, total)
        updated.append("direction.yaml (arc + spice schedule)")

        manifest_path = ws / "manifest.yaml"
        if manifest_path.exists():
            updated.append("manifest.yaml")

    if sync_book_arc_total_chapters(ws, book, total):
        updated.append("bible/narrative/book_arc.json")

    warn: str | None = None
    if existing_plans > total:
        warn = (
            f"Plan hiện có {existing_plans} chương — lớn hơn mục tiêu {total}. "
            "Chạy plan lại hoặc normalize-plan nếu cần thu gọn."
        )

    return {
        "ok": True,
        "workspace_id": workspace_id,
        "book": book,
        "total_chapters": total,
        "updated": updated,
        "warning": warn,
        "planned_chapters": existing_plans,
    }


def book_config_summary(workspace_id: str, book: int) -> dict[str, Any]:
    ws = workspace_dir(workspace_id)
    plan = load_master_plan(ws, book)
    return {
        "book": book,
        "total_chapters": get_total_chapters(workspace_id, book),
        "planned_chapters": len(plan.get("chapter_plans") or []),
        "min_chapters": MIN_CHAPTERS,
        "max_chapters": MAX_CHAPTERS,
        "default_chapters": DEFAULT_CHAPTERS,
    }
