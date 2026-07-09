"""Sync direction.yaml + manifest.yaml from concept.yaml — no template bleed."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.prompt_builder import load_direction

# Defaults copied from glass-meridian / ceo-contract workspace_init — detect & replace.
_TEMPLATE_SETTING_HUB = "Singapore"
_TEMPLATE_SETTING_NODES = ["Hong Kong", "Zurich", "New York"]
_TEMPLATE_SPICE_EXPLICIT = [3, 12, 18, 25, 32, 40, 48]
_TEMPLATE_SPICE_STEAMY = [8, 15, 22, 28, 36, 44]
_SPICE_BADGES = {1: "sweet", 2: "steamy", 3: "16+"}


def _load_concept(ws: Path) -> dict[str, Any]:
    path = ws / "concept.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def is_template_setting(direction: dict) -> bool:
    return (
        direction.get("setting_hub") == _TEMPLATE_SETTING_HUB
        and list(direction.get("setting_nodes") or []) == _TEMPLATE_SETTING_NODES
    )


def is_template_spice_schedule(direction: dict) -> bool:
    return (
        int(direction.get("spice_level") or 0) == 3
        and list(direction.get("spice_explicit_chapters") or []) == _TEMPLATE_SPICE_EXPLICIT
        and list(direction.get("spice_steamy_chapters") or []) == _TEMPLATE_SPICE_STEAMY
    )


def infer_spice_level(concept: dict) -> int:
    """Read spice 1–3 from author_directive / must_avoid / notes."""
    blob = "\n".join(
        str(concept.get(k) or "")
        for k in ("author_directive", "must_avoid", "notes", "surface_plot")
    )
    blob_lower = blob.lower()
    for pat in (
        r"spice\s*level\s*(\d)",
        r"keep\s+spice\s*(\d)",
        r"spice\s*(\d)\s*\(",
        r"mức\s*(\d)\s*\(sweet",
    ):
        m = re.search(pat, blob_lower, re.IGNORECASE)
        if m:
            return max(1, min(3, int(m.group(1))))
    if "no explicit" in blob_lower or "spice 1" in blob_lower or "atmospheric" in blob_lower:
        return 1
    if "explicit 18" in blob_lower or "spice 3" in blob_lower:
        return 3
    if "steamy" in blob_lower or "spice 2" in blob_lower:
        return 2
    return 1


def parse_chapter_count_from_concept(concept: dict) -> int | None:
    notes = str(concept.get("notes") or "")
    m = re.search(r"(\d{1,3})\s+chapters?\b", notes, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,3})\s+chương", notes, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def infer_setting_from_concept(concept: dict) -> tuple[str, list[str]]:
    text = " ".join(
        str(concept.get(k) or "")
        for k in ("logline", "author_directive", "surface_plot", "true_plot", "title")
    ).lower()
    if "house" in text and any(w in text for w in ("inherit", "inherited", "aunt", "estate")):
        return "Ilse's inherited house", []
    if "singapore" in text or "hong kong" in text:
        nodes = [n for n in ("Hong Kong", "Zurich", "New York") if n.lower().split()[0] in text]
        return "Singapore", nodes or list(_TEMPLATE_SETTING_NODES)
    title = (concept.get("title") or "Story").strip()
    return f"{title} — primary setting", []


def scale_act_arc(total: int) -> dict[str, list[int]]:
    """Four-act ranges scaled to book length."""
    total = max(3, int(total))
    if total <= 4:
        return {
            "act1_setup": [1, 1],
            "act2_complications": [2, max(2, total - 2)],
            "act3_crisis": [max(2, total - 1), max(2, total - 1)],
            "act4_resolution": [total, total],
        }
    a1 = max(1, round(total * 0.25))
    a2 = max(a1 + 1, round(total * 0.55))
    a3 = max(a2 + 1, round(total * 0.85))
    if a3 >= total:
        a3 = total - 1
    return {
        "act1_setup": [1, a1],
        "act2_complications": [a1 + 1, a2],
        "act3_crisis": [a2 + 1, a3],
        "act4_resolution": [a3 + 1, total],
    }


def spice_chapter_lists(total: int, spice_level: int) -> tuple[list[int], list[int]]:
    """Explicit/steamy chapter slots within 1..total (empty when sweet)."""
    if spice_level <= 1:
        return [], []
    explicit = [c for c in _TEMPLATE_SPICE_EXPLICIT if 1 <= c <= total]
    steamy = [c for c in _TEMPLATE_SPICE_STEAMY if 1 <= c <= total]
    if spice_level == 2:
        return [], steamy
    return explicit, steamy


def sync_direction_from_concept(
    ws: Path,
    *,
    preserve_gate_status: bool = True,
    force_setting: bool = False,
) -> dict[str, Any]:
    """Align direction.yaml with concept + scaled arc/spice."""
    concept = _load_concept(ws)
    direction = load_direction(ws)
    if not direction:
        direction = {"id": ws.name, "book": 1}

    changed: list[str] = []
    logline = (concept.get("logline") or "").strip()
    ending = (concept.get("ending_book1") or "").strip()
    lang = concept.get("target_language") or direction.get("target_language") or "en"

    if logline and direction.get("blurb") != logline:
        direction["blurb"] = logline
        changed.append("blurb")
    if ending and direction.get("book1_ending") != ending:
        direction["book1_ending"] = ending
        changed.append("book1_ending")
    if lang and direction.get("target_language") != lang:
        direction["target_language"] = lang
        changed.append("target_language")

    spice = infer_spice_level(concept)
    if int(direction.get("spice_level") or 0) != spice or is_template_spice_schedule(direction):
        direction["spice_level"] = spice
        direction["spice_default"] = spice
        direction["spice_badge"] = _SPICE_BADGES.get(spice, "sweet")
        changed.append("spice_level")

    total = int(direction.get("total_chapters") or 0)
    from_notes = parse_chapter_count_from_concept(concept)
    if from_notes and from_notes != total:
        total = from_notes
        direction["total_chapters"] = total
        changed.append("total_chapters")

    if total < 3:
        total = 30
        direction["total_chapters"] = total

    explicit, steamy = spice_chapter_lists(total, spice)
    if list(direction.get("spice_explicit_chapters") or []) != explicit:
        direction["spice_explicit_chapters"] = explicit
        changed.append("spice_explicit_chapters")
    if list(direction.get("spice_steamy_chapters") or []) != steamy:
        direction["spice_steamy_chapters"] = steamy
        changed.append("spice_steamy_chapters")

    arc = scale_act_arc(total)
    if direction.get("arc") != arc:
        direction["arc"] = arc
        changed.append("arc")

    if force_setting or is_template_setting(direction) or not direction.get("setting_hub"):
        hub, nodes = infer_setting_from_concept(concept)
        if direction.get("setting_hub") != hub:
            direction["setting_hub"] = hub
            changed.append("setting_hub")
        if list(direction.get("setting_nodes") or []) != nodes:
            direction["setting_nodes"] = nodes
            changed.append("setting_nodes")

    if not preserve_gate_status:
        for key in ("plan_status", "bible_status", "narrative_status"):
            if key in direction:
                direction[key] = "draft"

    _save_yaml(ws / "direction.yaml", direction)
    sync_manifest_from_direction(ws)
    return {"ok": True, "changed": changed, "total_chapters": total, "spice_level": spice}


def sync_manifest_from_direction(ws: Path) -> dict[str, Any]:
    """Mirror publish metadata from direction → manifest.yaml."""
    direction = load_direction(ws)
    manifest_path = ws / "manifest.yaml"
    manifest = (
        yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    ) or {}

    keys = (
        "id",
        "target_language",
        "spice_level",
        "publish_strategy",
        "book_slug",
        "blurb",
        "canon_through",
        "plan_status",
        "bible_status",
        "total_chapters",
    )
    for key in keys:
        if key == "id":
            manifest["id"] = direction.get("id") or ws.name
        elif key in direction:
            manifest[key] = direction[key]

    _save_yaml(manifest_path, manifest)
    return manifest


def rescale_direction_arc(ws: Path, total: int) -> None:
    """Update act + spice chapter lists when total_chapters changes."""
    direction = load_direction(ws)
    total = max(3, int(total))
    direction["total_chapters"] = total
    direction["arc"] = scale_act_arc(total)
    spice = int(direction.get("spice_level") or infer_spice_level(_load_concept(ws)))
    explicit, steamy = spice_chapter_lists(total, spice)
    direction["spice_explicit_chapters"] = explicit
    direction["spice_steamy_chapters"] = steamy
    _save_yaml(ws / "direction.yaml", direction)
    sync_manifest_from_direction(ws)
