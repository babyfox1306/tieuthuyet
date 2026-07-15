"""Operator (UI) is source of truth — authoritative writeback to all derived files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.master_plan import load_master_plan, save_master_plan
from factory.engine.lib.narrative_schema import load_concept
from factory.engine.lib.prompt_builder import load_direction
from factory.engine.paths import book_catalog_dir, load_config, resolve_book_slug, workspace_dir

MIN_CHAPTERS = 3
MAX_CHAPTERS = 200
DEFAULT_CHAPTERS = 30


def clamp_chapters(n: int) -> int:
    return max(MIN_CHAPTERS, min(MAX_CHAPTERS, int(n)))


def _save_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def patch_concept_chapter_count(concept: dict, total: int) -> dict:
    """Update explicit field + notes line so concept never disagrees with UI."""
    concept = dict(concept)
    concept["chapter_count"] = total
    notes = str(concept.get("notes") or "")
    if re.search(r"\d{1,3}\s+chapters?\b", notes, re.IGNORECASE):
        notes = re.sub(
            r"\d{1,3}\s+chapters?\b",
            f"{total} chapters",
            notes,
            count=1,
            flags=re.IGNORECASE,
        )
    elif re.search(r"\d{1,3}\s+chương", notes, re.IGNORECASE):
        notes = re.sub(
            r"\d{1,3}\s+chương",
            f"{total} chương",
            notes,
            count=1,
            flags=re.IGNORECASE,
        )
    elif notes.strip():
        notes = f"{total} chapters. {notes}"
    else:
        notes = f"{total} chapters"
    concept["notes"] = notes
    return concept


def parse_chapter_count_from_concept(concept: dict) -> int | None:
    """Read chapter target from concept — explicit field first, then notes."""
    raw = concept.get("chapter_count")
    if raw is not None and str(raw).strip().isdigit():
        return int(raw)
    notes = str(concept.get("notes") or "")
    m = re.search(r"(\d{1,3})\s+chapters?\b", notes, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\s+chương", notes, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def get_canonical_total_chapters(workspace_id: str, book: int) -> int:
    """Single read path: direction.yaml (UI last wrote) → plan → catalog → default."""
    ws = workspace_dir(workspace_id)
    direction = load_direction(ws)
    active = int(direction.get("book") or 1)

    if book == active and direction.get("total_chapters"):
        return clamp_chapters(int(direction["total_chapters"]))

    plan = load_master_plan(ws, book)
    if plan.get("total_chapters"):
        return clamp_chapters(int(plan["total_chapters"]))

    cfg = load_config()
    try:
        slug = resolve_book_slug(workspace_id, book, cfg=cfg)
        by = book_catalog_dir(workspace_id, slug) / "book.yaml"
        if by.exists():
            meta = yaml.safe_load(by.read_text(encoding="utf-8")) or {}
            if meta.get("total_chapters"):
                return clamp_chapters(int(meta["total_chapters"]))
    except ValueError:
        pass

    return DEFAULT_CHAPTERS


def _arc_max_chapter(arc: dict) -> int:
    max_ch = 0
    for act in arc.get("act_structure") or []:
        chapters = act.get("chapters") or []
        if chapters:
            max_ch = max(max_ch, max(int(c) for c in chapters))
    return max_ch


def _narrative_needs_develop(ws: Path, new_total: int, prior_arc_total: int | None) -> bool:
    arc_path = ws / "bible" / "narrative" / "book_arc.json"
    if not arc_path.exists():
        return False
    try:
        arc = json.loads(arc_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    old = prior_arc_total if prior_arc_total is not None else int(arc.get("total_chapters") or 0)
    if old and old != new_total:
        return True
    max_ch = _arc_max_chapter(arc)
    return bool(max_ch and max_ch != new_total)


def write_chapter_count_everywhere(
    workspace_id: str,
    book: int,
    total: int,
) -> dict[str, Any]:
    """UI save: overwrite chapter count in plan/narrative/config only.

    Never rewrites chapter prose (``pipeline/*/ch_*.txt``, catalog ``chapters/*.md``,
    spot_check). Those files are publishable bodies — rescale must not touch them.
    """
    from factory.engine.lib.workspace_metadata import rescale_direction_arc, sync_manifest_from_direction

    total = clamp_chapters(total)
    ws = workspace_dir(workspace_id)
    direction = load_direction(ws)
    concept = load_concept(ws)
    cfg = load_config()
    updated: list[str] = []
    warnings: list[str] = []

    arc_path = ws / "bible" / "narrative" / "book_arc.json"
    prior_arc_total: int | None = None
    if arc_path.exists():
        try:
            prior_arc_total = int(
                json.loads(arc_path.read_text(encoding="utf-8")).get("total_chapters") or 0
            ) or None
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            prior_arc_total = None

    prior_total = int(direction.get("total_chapters") or 0) or prior_arc_total or 0
    from factory.engine.lib.chapter_derivation import (
        infer_narrative_extent,
        orphans_above_total,
        rescale_narrative_dir,
    )

    narrative_extent = infer_narrative_extent(ws)
    rescale_from = max(prior_total, narrative_extent) or narrative_extent or prior_total or total
    if rescale_from < total:
        rescale_from = total

    needs_develop = _narrative_needs_develop(ws, total, prior_arc_total)

    # concept.yaml
    concept_path = ws / "concept.yaml"
    if concept_path.exists():
        patched = patch_concept_chapter_count(concept, total)
        _save_yaml(concept_path, patched)
        updated.append("concept.yaml")

    # master_plan.json
    plan = load_master_plan(ws, book)
    existing_plans = len(plan.get("chapter_plans") or [])
    plan["book"] = book
    plan["total_chapters"] = total
    if not plan.get("title"):
        plan["title"] = str(concept.get("title") or f"Book {book}")
    if not plan.get("status"):
        plan["status"] = "draft"
    if not plan.get("created_at"):
        plan["created_at"] = datetime.now(timezone.utc).isoformat()
    save_master_plan(ws, book, plan)
    updated.append(f"books/{book:02d}/master_plan.json")

    # catalog book.yaml
    try:
        slug = resolve_book_slug(workspace_id, book, cfg=cfg)
        book_dir = book_catalog_dir(workspace_id, slug)
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
        (book_dir / "exports").mkdir(parents=True, exist_ok=True)
        by_path = book_dir / "book.yaml"
        if by_path.exists():
            meta = yaml.safe_load(by_path.read_text(encoding="utf-8")) or {}
        else:
            meta = {
                "book": book,
                "slug": slug,
                "title": str(concept.get("title") or f"Book {book}"),
                "series": workspace_id,
                "language": concept.get("target_language")
                or direction.get("target_language")
                or "en",
            }
        meta["total_chapters"] = total
        _save_yaml(by_path, meta)
        updated.append(f"catalog/{slug}/book.yaml")
    except ValueError:
        pass

    # direction.yaml + manifest.yaml (active book)
    active = int(direction.get("book") or cfg.get("active_book") or 1)
    if book == active:
        direction["total_chapters"] = total
        direction["book"] = book
        rescale_direction_arc(ws, total)
        updated.append("direction.yaml")
        sync_manifest_from_direction(ws)
        updated.append("manifest.yaml")

    # book_arc + other narrative JSON — derive chapter refs from N
    narrative_updated = rescale_narrative_dir(
        ws, total, from_total=rescale_from if rescale_from != total else None, book=book
    )
    updated.extend(narrative_updated)

    orphan_refs = orphans_above_total(ws, total)
    if orphan_refs:
        needs_develop = True
        warnings.append(
            f"Còn {len(orphan_refs)} tham chiếu chương > {total} trong narrative "
            "(chạy develop-narrative lại để làm sạch nội dung)."
        )

    if existing_plans > total:
        warnings.append(
            f"Plan có {existing_plans} chương — lớn hơn mục tiêu {total}. Chạy plan lại nếu cần."
        )
    if needs_develop:
        warnings.append(
            "Narrative sinh cho số chương khác — chạy develop-narrative lại "
            "để cập nhật act_structure / milestones / reveals."
        )

    return {
        "ok": True,
        "workspace_id": workspace_id,
        "book": book,
        "total_chapters": total,
        "updated": updated,
        "warning": " ".join(warnings) if warnings else None,
        "warnings": warnings,
        "needs_develop_narrative": needs_develop,
        "planned_chapters": existing_plans,
    }


def write_language_everywhere(ws: Path, lang: str) -> list[str]:
    """UI concept language save → all copies."""
    from factory.engine.paths import bible_path

    lang = (lang or "en").strip().lower()
    if lang not in ("vi", "en"):
        lang = "en"
    updated: list[str] = []

    concept_path = ws / "concept.yaml"
    if concept_path.exists():
        concept = yaml.safe_load(concept_path.read_text(encoding="utf-8")) or {}
        if concept.get("target_language") != lang:
            concept["target_language"] = lang
            _save_yaml(concept_path, concept)
            updated.append("concept.yaml")

    direction = load_direction(ws)
    if direction:
        if direction.get("target_language") != lang:
            direction["target_language"] = lang
            _save_yaml(ws / "direction.yaml", direction)
            updated.append("direction.yaml")

    bible = bible_path(ws)
    if bible.exists():
        data = json.loads(bible.read_text(encoding="utf-8"))
        meta = data.setdefault("meta", {})
        if meta.get("target_language") != lang:
            meta["target_language"] = lang
            bible.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            updated.append("bible/series.json")

    manifest_path = ws / "manifest.yaml"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if manifest.get("target_language") != lang:
            manifest["target_language"] = lang
            _save_yaml(manifest_path, manifest)
            updated.append("manifest.yaml")

    cfg = load_config()
    book = int(direction.get("book") or 1)
    try:
        slug = resolve_book_slug(ws.name, book, cfg=cfg)
        by_path = book_catalog_dir(ws.name, slug) / "book.yaml"
        if by_path.exists():
            meta = yaml.safe_load(by_path.read_text(encoding="utf-8")) or {}
            if meta.get("language") != lang:
                meta["language"] = lang
                _save_yaml(by_path, meta)
                updated.append(f"catalog/{slug}/book.yaml")
    except ValueError:
        pass

    arc_path = ws / "bible" / "narrative" / "book_arc.json"
    if arc_path.exists():
        try:
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
            if arc.get("target_language") != lang:
                arc["target_language"] = lang
                arc_path.write_text(json.dumps(arc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                updated.append("bible/narrative/book_arc.json")
        except (json.JSONDecodeError, OSError):
            pass

    return updated


def write_title_everywhere(ws: Path, title: str, *, book: int = 1) -> list[str]:
    """UI concept title save → plan + catalog."""
    title = (title or "").strip()
    if not title:
        return []
    updated: list[str] = []
    cfg = load_config()

    plan = load_master_plan(ws, book)
    if plan.get("title") != title:
        plan["title"] = title
        save_master_plan(ws, book, plan)
        updated.append(f"books/{book:02d}/master_plan.json")

    try:
        slug = resolve_book_slug(ws.name, book, cfg=cfg)
        by_path = book_catalog_dir(ws.name, slug) / "book.yaml"
        if by_path.exists():
            meta = yaml.safe_load(by_path.read_text(encoding="utf-8")) or {}
            if meta.get("title") != title:
                meta["title"] = title
                _save_yaml(by_path, meta)
                updated.append(f"catalog/{slug}/book.yaml")
        else:
            book_dir = by_path.parent
            book_dir.mkdir(parents=True, exist_ok=True)
            _save_yaml(
                by_path,
                {
                    "book": book,
                    "slug": slug,
                    "title": title,
                    "series": ws.name,
                    "language": load_direction(ws).get("target_language") or "en",
                },
            )
            updated.append(f"catalog/{slug}/book.yaml")
    except ValueError:
        pass

    return updated
