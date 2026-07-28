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
_CHAPTER_NUMBER_WORDS = {
    word: number
    for number, word in enumerate(
        (
            "zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen",
            "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen", "twenty",
        )
    )
}


_TEMPLATE_GOAL_THRILLER_EN = (
    "end-of-chapter hooks — procedural thriller pace, no romance engine"
)
_TEMPLATE_GOAL_THRILLER_VI = (
    "móc cuối chương — nhịp thriller thủ tục, không engine romance"
)


_ROMANCE_MODE_ON = frozenset(
    {"on", "true", "yes", "enabled", "romance", "primary", "required"}
)
_ROMANCE_MODE_OFF = frozenset(
    {"off", "false", "no", "disabled", "none", "forbidden", "non_romance"}
)


def _normalize_romance_mode(value: object) -> str | None:
    if isinstance(value, bool):
        return "on" if value else "off"
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in _ROMANCE_MODE_ON:
        return "on"
    if text in _ROMANCE_MODE_OFF:
        return "off"
    return None


def resolve_romance_mode(
    concept: dict, direction: dict | None = None
) -> str | None:
    """Return explicit romance intent: ``on``, ``off``, or unknown.

    Hard-off is a story classification, not a prose keyword. Safety constraints
    such as "no assault presented as romance" must never disable the romance
    engine. Prefer ``concept.romance_mode``; structured genre is the fallback.
    """
    for source in (concept, direction or {}):
        if "romance_mode" in source:
            mode = _normalize_romance_mode(source.get("romance_mode"))
            if mode:
                return mode

    genre = concept.get("genre")
    if isinstance(genre, dict):
        if "romance" in genre:
            mode = _normalize_romance_mode(genre.get("romance"))
            if mode:
                return mode
        genre_values = [
            genre.get("primary"),
            genre.get("secondary"),
            genre.get("subgenre"),
            genre.get("tags"),
        ]
    else:
        genre_values = [genre, concept.get("genre_profile")]

    def _genre_text(value: object) -> str:
        if isinstance(value, (list, tuple, set)):
            return " ".join(str(item) for item in value)
        return str(value or "")

    genre_blob = " ".join(_genre_text(value) for value in genre_values).lower()
    if re.search(r"\b(?:dark[\s-]?)?romance\b|\bromantic suspense\b", genre_blob):
        return "on"
    return None


def concept_forbids_romance(concept: dict) -> bool:
    """True only when structured concept metadata explicitly opts out."""
    return resolve_romance_mode(concept) == "off"


def concept_wants_romance(concept: dict) -> bool:
    """True only when structured concept metadata explicitly opts in."""
    return resolve_romance_mode(concept) == "on"


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
    """Derive profile while taking romance intent only from structured metadata."""
    blob = "\n".join(
        [
            str(concept.get(k) or "")
            for k in (
                "author_directive",
                "notes",
                "surface_plot",
                "true_plot",
                "title",
                "logline",
                "genre",
                "genre_profile",
            )
        ]
        + [str(x) for x in (concept.get("must_include") or [])]
    ).lower()
    if not blob.strip():
        return None

    forbids = concept_forbids_romance(concept)
    wants_thriller = bool(
        re.search(
            r"\bthriller\b|"
            r"\brevenge\b|"
            r"\bprocedural\b|"
            r"\btwo-way hunt\b|"
            r"\bcold case\b|"
            r"\banti-hero\b|"
            r"\bgood for her\b",
            blob,
        )
    )
    wants_gothic = bool(
        re.search(r"\bgothic\b|\bpsychological horror\b|\bhorror\b", blob)
    )
    wants_conspiracy = "conspiracy" in blob and "thriller" in blob
    wants_romance = concept_wants_romance(concept)

    if forbids:
        if wants_gothic and not wants_thriller:
            return "gothic_psychological_horror"
        if wants_conspiracy:
            return "conspiracy_thriller"
        if wants_thriller or wants_gothic:
            return "thriller"
        return "thriller" if "thriller" in blob else None

    if wants_gothic and not wants_romance:
        return "gothic_psychological_horror"
    if wants_romance and "thriller" in blob:
        return "romance_thriller"
    if wants_conspiracy:
        return "conspiracy_thriller"
    if wants_thriller and not wants_romance:
        return "thriller"
    if wants_gothic:
        return "gothic_psychological_horror"
    return None


def resolve_narrative_profile(ws: Path, concept: dict | None = None) -> str | None:
    """Explicit concept romance mode beats stale kernel/profile inference."""
    concept = concept if concept is not None else _load_concept(ws)
    inferred = infer_narrative_profile_from_concept(concept)
    kernel = load_kernel_narrative_profile(ws)
    mode = resolve_romance_mode(concept)
    if mode == "off":
        if inferred:
            return inferred
        if kernel and "romance" in kernel.lower():
            return "thriller"
    if mode == "on":
        if inferred and "romance" in inferred.lower():
            return inferred
        if kernel and "romance" in kernel.lower():
            return kernel
        return "romance_thriller"
    if kernel:
        return kernel
    return inferred


def is_template_goal(direction: dict) -> bool:
    goal = str(direction.get("goal") or "").strip()
    return goal in (
        _TEMPLATE_GOAL_ROMANCE_EN,
        _TEMPLATE_GOAL_ROMANCE_VI,
        _TEMPLATE_GOAL_THRILLER_EN,
        _TEMPLATE_GOAL_THRILLER_VI,
        _TEMPLATE_GOAL_GOTHIC_EN,
    )


def default_goal_for_profile(profile: str | None, lang: str) -> str | None:
    if profile == "gothic_psychological_horror":
        return _TEMPLATE_GOAL_GOTHIC_EN
    if profile == "thriller":
        return _TEMPLATE_GOAL_THRILLER_EN if lang == "en" else _TEMPLATE_GOAL_THRILLER_VI
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
    """Infer the book-wide spice ceiling from positive concept declarations.

    ``must_avoid`` is deliberately excluded: a prohibition such as "no sexual
    assault presented as romance" describes a boundary, not the absence of
    consensual explicit scenes.
    """
    for key in ("spice_max", "spice_level"):
        value = concept.get(key)
        if value is not None:
            try:
                return max(0, min(3, int(value)))
            except (TypeError, ValueError):
                pass

    positive_blob = "\n".join(
        str(concept.get(k) or "")
        for k in (
            "author_directive",
            "true_plot",
            "must_include",
            "chapter_map",
            "notes",
            "surface_plot",
        )
    )
    blob_lower = positive_blob.lower()
    for pat in (
        r"spice\s*level\s*(\d)",
        r"keep\s+spice\s*(\d)",
        r"spice\s*(\d)\s*\(",
        r"mức\s*(\d)\s*\(sweet",
    ):
        m = re.search(pat, blob_lower, re.IGNORECASE)
        if m:
            return max(1, min(3, int(m.group(1))))
    if (
        "explicit 18" in blob_lower
        or "spice 3" in blob_lower
        or re.search(
            r"(?<!no )(?<!not )(?<!without )\bexplicit\s+"
            r"(?:sexual|sex|scene|encounter|content)",
            blob_lower,
        )
    ):
        return 3
    if "steamy" in blob_lower or "spice 2" in blob_lower:
        return 2

    boundary_blob = "\n".join(
        str(concept.get(k) or "") for k in ("author_directive", "notes")
    ).lower()
    if (
        "no explicit" in boundary_blob
        or "spice 1" in boundary_blob
        or "atmospheric" in boundary_blob
    ):
        return 1
    return 1


def infer_spice_default(concept: dict, ceiling: int) -> int:
    raw = concept.get("spice_default")
    if raw is None:
        return min(1, ceiling)
    if isinstance(raw, bool):
        raise ValueError("spice_default must be integer 0..3")
    try:
        level = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("spice_default must be integer 0..3") from exc
    if level < 0 or level > 3 or level > ceiling:
        raise ValueError(
            f"spice_default {level} exceeds valid book ceiling {ceiling}"
        )
    return level


def spice_schedule_errors(
    concept: dict,
    total: int,
    ceiling: int,
) -> list[str]:
    raw = concept.get("spice_schedule")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["spice_schedule: must be a chapter-to-level map"]
    errors: list[str] = []
    scheduled: set[int] = set()
    for raw_chapter, raw_level in raw.items():
        try:
            chapter = int(str(raw_chapter).lstrip("chCH"))
        except (TypeError, ValueError):
            errors.append(f"spice_schedule.{raw_chapter}: chapter must be a positive integer")
            continue
        if chapter <= 0 or (total > 0 and chapter > total):
            errors.append(
                f"spice_schedule.{raw_chapter}: chapter outside 1..{total}"
            )
        if isinstance(raw_level, bool) or not isinstance(raw_level, int):
            errors.append(f"spice_schedule.{raw_chapter}: level must be integer 0..3")
            continue
        level = raw_level
        if level < 0 or level > 3:
            errors.append(f"spice_schedule.{raw_chapter}: level must be within 0..3")
        elif level > ceiling:
            errors.append(
                f"spice_schedule.{raw_chapter}: level {level} exceeds ceiling {ceiling}"
            )
        scheduled.add(chapter)
    explicit = concept.get("spice_explicit_chapters")
    if explicit is not None:
        if not isinstance(explicit, list):
            errors.append("spice_explicit_chapters: must be a list")
        else:
            for raw_chapter in explicit:
                try:
                    chapter = int(raw_chapter)
                except (TypeError, ValueError):
                    errors.append(
                        f"spice_explicit_chapters: invalid chapter {raw_chapter!r}"
                    )
                    continue
                if chapter not in scheduled:
                    errors.append(
                        "spice_schedule:"
                        f" chapter {chapter} is explicit but has no per-chapter level"
                    )
    return errors


def normalize_spice_schedule(
    concept: dict,
    total: int,
    ceiling: int,
) -> dict[int, int]:
    errors = spice_schedule_errors(concept, total, ceiling)
    if errors:
        raise ValueError("; ".join(errors))
    raw = concept.get("spice_schedule")
    if not isinstance(raw, dict):
        return {}
    return {
        int(str(chapter).lstrip("chCH")): int(level)
        for chapter, level in raw.items()
    }


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


def infer_spice_chapter_lists(
    concept: dict, total: int, spice_level: int
) -> tuple[list[int], list[int]]:
    """Prefer chapter locks declared by the concept over the generic template."""
    schedule = normalize_spice_schedule(concept, total, spice_level)
    if schedule:
        explicit_raw = concept.get("spice_explicit_chapters")
        if isinstance(explicit_raw, list):
            return sorted({int(ch) for ch in explicit_raw}), []
        return (
            sorted(ch for ch, level in schedule.items() if level >= 3),
            sorted(ch for ch, level in schedule.items() if level == 2),
        )
    explicit_raw = concept.get("spice_explicit_chapters")
    if isinstance(explicit_raw, list) and explicit_raw:
        explicit = sorted(
            {
                int(ch)
                for ch in explicit_raw
                if str(ch).strip().lstrip("-").isdigit()
                and 1 <= int(ch) <= total
            }
        )
        return explicit, []
    text = "\n".join(
        str(concept.get(key) or "")
        for key in ("author_directive", "true_plot", "must_include", "chapter_map", "notes")
    ).lower()
    explicit: set[int] = set()
    for match in re.finditer(r"\bchapters?\s+([^.;\n]{1,100})", text):
        context = text[max(0, match.start() - 100):match.end()]
        if not re.search(
            r"\bexplicit\s+(?:sexual|sex|content|encounter|scene)\b"
            r"|\bsexual\s+(?:content|encounter|scene)\b",
            context,
        ):
            continue
        tail = match.group(1)
        for token in re.findall(r"\d+|[a-z]+", tail):
            chapter = int(token) if token.isdigit() else _CHAPTER_NUMBER_WORDS.get(token)
            if chapter and 1 <= chapter <= total:
                explicit.add(chapter)
    if explicit:
        return sorted(explicit), []
    return spice_chapter_lists(total, spice_level)


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
    spice_default = infer_spice_default(concept, spice)
    if int(direction.get("spice_level") or 0) != spice or is_template_spice_schedule(direction):
        direction["spice_level"] = spice
        direction["spice_badge"] = _SPICE_BADGES.get(spice, "sweet")
        changed.append("spice_level")
    if int(direction.get("spice_default") if direction.get("spice_default") is not None else -1) != spice_default:
        direction["spice_default"] = spice_default
        changed.append("spice_default")

    # Chapter count: operator sets via UI (direction.yaml). Concept save must not override.
    total = int(direction.get("total_chapters") or 0)

    if total >= 3:
        schedule = normalize_spice_schedule(concept, total, spice)
        if direction.get("spice_schedule") != schedule:
            direction["spice_schedule"] = schedule
            changed.append("spice_schedule")
        explicit, steamy = infer_spice_chapter_lists(concept, total, spice)
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
        direction["spice_schedule"] = {}
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

    # A saved/imported concept invalidates every derived storytelling layer.
    # Preserve statuses only while the approved intent digest still matches.
    try:
        from factory.engine.lib.intent_manifest import concept_digest, intent_manifest_path

        book = int(direction.get("book") or 1)
        intent_path = intent_manifest_path(ws, book)
        if intent_path.exists():
            intent = json.loads(intent_path.read_text(encoding="utf-8")) or {}
            if intent.get("concept_digest") != concept_digest(concept):
                intent["status"] = "draft"
                intent.pop("approved_at", None)
                intent_path.write_text(
                    json.dumps(intent, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                direction["intent_status"] = "draft"
                for key in ("narrative_status", "bible_status", "plan_status"):
                    direction[key] = "draft"
                changed.append("derived_gates_invalidated")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass

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

    _save_yaml(manifest_path, manifest)
    return manifest


def rescale_direction_arc(ws: Path, total: int) -> None:
    """Update act + spice chapter lists when total_chapters changes."""
    direction = load_direction(ws)
    total = max(3, int(total))
    direction["total_chapters"] = total
    direction["arc"] = scale_act_arc(total)
    concept = _load_concept(ws)
    spice = int(direction.get("spice_level") or infer_spice_level(concept))
    schedule = normalize_spice_schedule(concept, total, spice)
    explicit, steamy = infer_spice_chapter_lists(concept, total, spice)
    direction["spice_schedule"] = schedule
    direction["spice_explicit_chapters"] = explicit
    direction["spice_steamy_chapters"] = steamy
    _save_yaml(ws / "direction.yaml", direction)
    sync_manifest_from_direction(ws)
