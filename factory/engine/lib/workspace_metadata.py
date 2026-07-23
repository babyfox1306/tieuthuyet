"""Sync direction.yaml + manifest.yaml from concept.yaml — no template bleed."""

from __future__ import annotations

import json
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
_TEMPLATE_GOAL_ROMANCE_EN = "end-of-chapter hooks — international thriller-romance pace"
_TEMPLATE_GOAL_ROMANCE_VI = "unlock chương sau — cliffhanger mỗi ch"
_TEMPLATE_GOAL_GOTHIC_EN = (
    "slow dread — quiet wrongness each chapter, concrete mystery payoff every 2–3 chapters"
)
_TEMPLATE_AUDIENCE_EN = "women 18-35, mobile reading, hook-driven serial fiction"
_TEMPLATE_AUDIENCE_VI = "nữ 18-35, đọc điện thoại, lướt nhanh"
_SPICE_BADGES = {1: "sweet", 2: "steamy", 3: "16+"}


def load_kernel_narrative_profile(ws: Path) -> str | None:
    path = ws / "bible" / "narrative" / "kernel.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = str(data.get("narrative_profile") or "").strip()
        return profile or None
    except (json.JSONDecodeError, OSError):
        return None


def infer_narrative_profile_from_concept(concept: dict) -> str | None:
    """Derive narrative_profile from concept text — no hardcoded romance default."""
    blob = "\n".join(
        str(concept.get(k) or "")
        for k in ("author_directive", "notes", "surface_plot", "true_plot", "title", "logline")
    ).lower()
    if not blob.strip():
        return None
    if "not a romance" in blob or "gothic" in blob or "psychological horror" in blob:
        return "gothic_psychological_horror"
    if "conspiracy" in blob and "thriller" in blob:
        return "conspiracy_thriller"
    if "romance" in blob and "thriller" in blob:
        return "romance_thriller"
    if "horror" in blob:
        return "gothic_psychological_horror"
    return None


def resolve_narrative_profile(ws: Path, concept: dict | None = None) -> str | None:
    """Kernel wins, then concept inference."""
    profile = load_kernel_narrative_profile(ws)
    if profile:
        return profile
    concept = concept if concept is not None else _load_concept(ws)
    return infer_narrative_profile_from_concept(concept)


def is_template_goal(direction: dict) -> bool:
    goal = str(direction.get("goal") or "").strip()
    return goal in (_TEMPLATE_GOAL_ROMANCE_EN, _TEMPLATE_GOAL_ROMANCE_VI)


def default_goal_for_profile(profile: str | None, lang: str) -> str | None:
    if profile == "gothic_psychological_horror":
        return _TEMPLATE_GOAL_GOTHIC_EN
    if profile in ("romance_thriller", "conspiracy_thriller"):
        return _TEMPLATE_GOAL_ROMANCE_EN if lang == "en" else _TEMPLATE_GOAL_ROMANCE_VI
    return None


def sync_narrative_profile_to_direction(ws: Path, *, concept: dict | None = None) -> str | None:
    """Write narrative_profile from kernel/concept → direction (after develop-narrative kernel pass)."""
    concept = concept if concept is not None else _load_concept(ws)
    direction = load_direction(ws)
    profile = resolve_narrative_profile(ws, concept)
    if not profile:
        return None
    lang = str(direction.get("target_language") or concept.get("target_language") or "en")
    changed = False
    if direction.get("narrative_profile") != profile:
        direction["narrative_profile"] = profile
        changed = True
    goal = default_goal_for_profile(profile, lang)
    if goal and (not direction.get("goal") or is_template_goal(direction)):
        direction["goal"] = goal
        changed = True
    if changed:
        _save_yaml(ws / "direction.yaml", direction)
        sync_manifest_from_direction(ws)
    return profile


def _load_concept(ws: Path, book: int | None = None) -> dict[str, Any]:
    from factory.engine.lib.narrative_schema import load_concept

    return load_concept(ws, book)


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
    from factory.engine.lib.operator_sync import parse_chapter_count_from_concept as _parse

    return _parse(concept)


def infer_setting_from_concept(concept: dict) -> tuple[str, list[str]]:
    text = " ".join(
        str(concept.get(k) or "")
        for k in ("logline", "author_directive", "surface_plot", "true_plot", "title")
    ).lower()
    if "lake" in text and "house" in text:
        title = (concept.get("title") or "Story").strip()
        return f"{title} — lake house", []
    if "house" in text and any(w in text for w in ("inherit", "inherited", "aunt", "estate")):
        title = (concept.get("title") or "Story").strip()
        return f"{title} — inherited house", []
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

    # Chapter count: operator sets via UI (direction.yaml). Concept save must not override.
    total = int(direction.get("total_chapters") or 0)

    if total >= 3:
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
    else:
        explicit, steamy = [], []
        if list(direction.get("spice_explicit_chapters") or []) != explicit:
            direction["spice_explicit_chapters"] = explicit
            changed.append("spice_explicit_chapters")
        if list(direction.get("spice_steamy_chapters") or []) != steamy:
            direction["spice_steamy_chapters"] = steamy
            changed.append("spice_steamy_chapters")

    if force_setting or is_template_setting(direction) or not direction.get("setting_hub"):
        hub, nodes = infer_setting_from_concept(concept)
        if direction.get("setting_hub") != hub:
            direction["setting_hub"] = hub
            changed.append("setting_hub")
        if list(direction.get("setting_nodes") or []) != nodes:
            direction["setting_nodes"] = nodes
            changed.append("setting_nodes")

    profile = resolve_narrative_profile(ws, concept)
    if profile and direction.get("narrative_profile") != profile:
        direction["narrative_profile"] = profile
        changed.append("narrative_profile")
        lang = str(direction.get("target_language") or lang)
        goal = default_goal_for_profile(profile, lang)
        if goal and (not direction.get("goal") or is_template_goal(direction)):
            direction["goal"] = goal
            changed.append("goal")

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
        "pen_name",
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

    # Direction is authoritative for author; never leave manifest missing/out of sync.
    manifest["pen_name"] = str(direction.get("pen_name") or "").strip()

    _save_yaml(manifest_path, manifest)
    return manifest


def last_pen_name_default() -> str:
    """Most recently used pen name (factory/engine/config.json), if any."""
    from factory.engine.paths import load_config

    return str(load_config().get("last_pen_name") or "").strip()


def remember_last_pen_name(pen_name: str) -> None:
    name = str(pen_name or "").strip()
    if not name:
        return
    from factory.engine.paths import save_config_patch

    save_config_patch({"last_pen_name": name})


def write_pen_name(ws: Path, pen_name: str, *, remember: bool = True) -> str:
    """Persist pen_name to direction.yaml + manifest.yaml (+ catalog series.yaml).

    direction.yaml is the EPUB exporter's primary source (see catalog.resolve_pen_name).
    """
    name = str(pen_name or "").strip()
    direction = load_direction(ws) or {}
    direction["pen_name"] = name
    if "id" not in direction:
        direction["id"] = ws.name
    _save_yaml(ws / "direction.yaml", direction)
    sync_manifest_from_direction(ws)
    try:
        from factory.engine.lib.catalog import sync_series_yaml

        sync_series_yaml(ws.name)
    except Exception:
        pass
    if remember and name:
        remember_last_pen_name(name)
    return name


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
