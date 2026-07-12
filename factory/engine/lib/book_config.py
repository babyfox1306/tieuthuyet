"""Per-book chapter count — operator (UI) is canonical via direction.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.engine.lib.master_plan import load_master_plan
from factory.engine.lib.operator_sync import (
    DEFAULT_CHAPTERS,
    MAX_CHAPTERS,
    MIN_CHAPTERS,
    clamp_chapters,
    get_canonical_total_chapters,
    write_chapter_count_everywhere,
)
from factory.engine.paths import workspace_dir

# Re-export for callers
__all__ = [
    "DEFAULT_CHAPTERS",
    "MAX_CHAPTERS",
    "MIN_CHAPTERS",
    "book_config_summary",
    "get_total_chapters",
    "set_total_chapters",
    "sync_book_arc_total_chapters",
    "sync_chapter_count_from_concept",
]


def _clamp_total(n: int) -> int:
    return clamp_chapters(n)


def get_total_chapters(workspace_id: str, book: int) -> int:
    """Read canonical chapter target — direction.yaml (UI last wrote)."""
    return get_canonical_total_chapters(workspace_id, book)


def sync_chapter_count_from_concept(ws: Path, book: int = 1) -> dict[str, Any] | None:
    """Legacy hook — only runs when direction has no operator value yet."""
    from factory.engine.lib.operator_sync import parse_chapter_count_from_concept
    from factory.engine.lib.prompt_builder import load_direction
    from factory.engine.lib.narrative_schema import load_concept

    direction = load_direction(ws)
    if direction.get("total_chapters"):
        return None
    n = parse_chapter_count_from_concept(load_concept(ws))
    if not n:
        return None
    return set_total_chapters(ws.name, book, n)


def sync_book_arc_total_chapters(ws: Path, book: int, total: int) -> bool:
    """Patch bible/narrative/book_arc.json to match canonical chapter count."""
    import json

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
    """UI save — authoritative writeback to all derived files."""
    return write_chapter_count_everywhere(workspace_id, book, total)


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
