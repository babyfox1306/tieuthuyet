"""Initialize a clean workspace from concept + narrative (no legacy plan/bible)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from factory.engine.lib.workspace_metadata import (
    infer_setting_from_concept,
    infer_spice_level,
    resolve_narrative_profile,
    default_goal_for_profile,
    scale_act_arc,
    spice_chapter_lists,
    sync_manifest_from_direction,
)
from factory.engine.paths import workspace_dir

_WORKSPACE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
_RESERVED_WORKSPACE_IDS = frozenset({".", "..", "con", "prn", "aux", "nul"})


def normalize_workspace_id(raw: str) -> str:
    """Slugify user input → safe folder name (lowercase, a-z0-9-)."""
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:40]


def validate_workspace_id(ws_id: str) -> str | None:
    """Return error message if invalid, else None."""
    if not ws_id:
        return "id workspace trống"
    if ws_id in _RESERVED_WORKSPACE_IDS:
        return f"id '{ws_id}' không hợp lệ"
    if not _WORKSPACE_ID_RE.match(ws_id):
        return "id chỉ gồm chữ thường, số, gạch ngang (3–40 ký tự, bắt đầu bằng chữ)"
    return None


def _blank_concept(*, title: str = "", target_language: str = "en") -> dict:
    return {
        "concept_status": "draft",
        "target_language": target_language,
        "title": title,
        "logline": "",
        "author_directive": "",
        "surface_plot": "",
        "true_plot": "",
        "must_include": [],
        "must_avoid": [],
        "ending_book1": "",
        "hook_book2": "",
        "notes": "",
    }


def init_blank_workspace(
    new_id: str,
    *,
    title: str = "",
    target_language: str = "en",
    total_chapters: int | None = None,
) -> Path:
    """New story — empty concept only. Chapter count comes from concept when ready."""
    err = validate_workspace_id(new_id)
    if err:
        raise ValueError(err)
    dst = workspace_dir(new_id)
    if dst.exists() and any(dst.iterdir()):
        raise FileExistsError(f"Workspace đã tồn tại: {new_id}")

    dst.mkdir(parents=True, exist_ok=True)
    (dst / "bible" / "narrative").mkdir(parents=True, exist_ok=True)
    (dst / "books" / "01").mkdir(parents=True, exist_ok=True)

    concept = _blank_concept(title=title.strip(), target_language=target_language)
    (dst / "concept.yaml").write_text(
        yaml.dump(concept, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    _write_default_direction(dst, new_id, total_chapters=total_chapters)
    _write_default_manifest(dst, new_id)
    return dst


def init_workspace_from_template(
    new_id: str,
    *,
    template_id: str = "ceo-contract",
    copy_narrative: bool = True,
    copy_concept: bool = True,
) -> Path:
    """Create workspace with concept + narrative only. No series.json, plans, or locked canon."""
    err = validate_workspace_id(new_id)
    if err:
        raise ValueError(err)
    src = workspace_dir(template_id)
    dst = workspace_dir(new_id)
    if dst.exists() and any(dst.iterdir()):
        raise FileExistsError(f"Workspace already exists and is not empty: {dst}")

    dst.mkdir(parents=True, exist_ok=True)
    (dst / "bible" / "narrative").mkdir(parents=True, exist_ok=True)

    if copy_concept and (src / "concept.yaml").exists():
        shutil.copy2(src / "concept.yaml", dst / "concept.yaml")

    if copy_narrative:
        narr_src = src / "bible" / "narrative"
        if narr_src.exists():
            for f in narr_src.glob("*.json"):
                shutil.copy2(f, dst / "bible" / "narrative" / f.name)

    _write_default_direction(dst, new_id)
    _write_default_manifest(dst, new_id)
    return dst


def _write_default_direction(ws: Path, ws_id: str, *, total_chapters: int | None = None) -> None:
    concept = {}
    cp = ws / "concept.yaml"
    if cp.exists():
        concept = yaml.safe_load(cp.read_text(encoding="utf-8")) or {}
    lang = concept.get("target_language") or "en"
    from factory.engine.lib.workspace_metadata import parse_chapter_count_from_concept

    from_notes = parse_chapter_count_from_concept(concept)
    total = from_notes or total_chapters
    spice = infer_spice_level(concept)
    hub, nodes = infer_setting_from_concept(concept)
    explicit, steamy = spice_chapter_lists(total, spice) if total else ([], [])
    profile = resolve_narrative_profile(ws, concept)
    goal = default_goal_for_profile(profile, lang)
    data = {
        "id": ws_id,
        "pen_name": "",
        "target_language": lang,
        "publish_strategy": "kdp_ku_exclusive",
        "narrative_status": "draft",
        "book": 1,
        "canon_through": 0,
        "platform": "kdp",
        "audience": "women 18-35, mobile reading, hook-driven serial fiction"
        if lang == "en"
        else "nữ 18-35, đọc điện thoại, lướt nhanh",
        "goal": goal or (
            "end-of-chapter hooks — international thriller-romance pace"
            if lang == "en"
            else "unlock chương sau — cliffhanger mỗi ch"
        ),
        "setting_hub": hub,
        "setting_nodes": nodes,
        "spice_default": spice,
        "spice_explicit_chapters": explicit,
        "spice_steamy_chapters": steamy,
        "book1_ending": concept.get("ending_book1", ""),
        "blurb": concept.get("logline", ""),
        "tropes": [],
        "spice_badge": {1: "sweet", 2: "steamy", 3: "16+"}.get(spice, "sweet"),
        "target_platforms": ["kdp"],
        "spice_level": spice,
        "plan_status": "draft",
        "bible_status": "draft",
        "book_slug": f"01-{ws_id}",
    }
    if profile:
        data["narrative_profile"] = profile
    if total and total >= 3:
        data["total_chapters"] = total
        data["arc"] = scale_act_arc(total)
    (ws / "direction.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _write_default_manifest(ws: Path, ws_id: str) -> None:
    sync_manifest_from_direction(ws)
