"""Compile per-chapter narrative constraints from mystery_ledger + knowledge_matrix.

Source of truth for (a) plan merge and (b) prompt injection — both read from here,
never from each other. See architecture: compiler is the spine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.narrative_schema import (
    PROFILE_REQUIRED,
    clue_payoff_chapter,
    clue_plant_chapter,
    narrative_dir,
)
from factory.engine.paths import workspace_dir

# Profiles whose required_files include mystery ledger + knowledge matrix.
# Enablement itself is asset-driven (narrative_compiler_enabled) — not this set.
NARRATIVE_COMPILER_PROFILES = frozenset(
    name
    for name, files in PROFILE_REQUIRED.items()
    if "mystery_ledger.json" in files and "knowledge_matrix.json" in files
)

# Archived workspaces — prefer direction.yaml ``workspace_mode: archive``.
ARCHIVE_WORKSPACES = frozenset()

REVEAL_WEIGHT_MAJOR = "major"
REVEAL_WEIGHT_MINOR = "minor"
MIN_CLUES_BY_REVEAL_WEIGHT = {
    REVEAL_WEIGHT_MAJOR: 2,
    REVEAL_WEIGHT_MINOR: 1,
}


def min_clues_for_reveal(reveal_weight: str) -> int:
    return MIN_CLUES_BY_REVEAL_WEIGHT.get(reveal_weight, MIN_CLUES_BY_REVEAL_WEIGHT[REVEAL_WEIGHT_MAJOR])


def _first_text(obj: dict[str, Any], *keys: str) -> str:
    """Return first non-empty string field (ledger schemas vary: content vs description)."""
    for key in keys:
        val = obj.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def clue_semantic_text(clue: dict[str, Any]) -> str:
    """Canonical clue prose for Outliner/Writer — content preferred, description fallback."""
    return _first_text(clue, "content", "description")


def reveal_semantic_text(rev: dict[str, Any]) -> str:
    """Canonical reveal prose — reveal preferred, description fallback."""
    return _first_text(rev, "reveal", "description")


def red_herring_semantic_text(rh: dict[str, Any]) -> str:
    return _first_text(rh, "false_lead", "description")


def narrative_compiler_enabled(ws: Path, direction: dict | None = None) -> bool:
    """True when mystery narrative assets exist and narrative is approved.

    Driven by workspace data from the user's concept pipeline — NOT by hardcoding
    a genre (gothic/thriller/…). If concept → profile produced ledger+matrix and
    the operator approved narrative, the compiler runs. Kill switches:
    ``narrative_compiler: false`` or ``workspace_mode: archive``.
    """
    if direction is None:
        direction = _load_direction(ws)
    if direction.get("narrative_compiler") is False:
        return False
    if direction.get("workspace_mode") == "archive":
        return False
    if ws.name in ARCHIVE_WORKSPACES:
        return False
    if (direction.get("narrative_status") or "draft") != "approved":
        return False
    nd = narrative_dir(ws)
    return (nd / "mystery_ledger.json").exists() and (nd / "knowledge_matrix.json").exists()


def _load_direction(ws: Path) -> dict:
    path = ws / "direction.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_ledger(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "mystery_ledger.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_knowledge_matrix(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "knowledge_matrix.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return normalize_knowledge_matrix(raw)


def _coerce_chapter_number(val: Any) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            return int(s)
        m = re.match(r"^ch(\d+)$", s, re.I)
        if m:
            return int(m.group(1))
    return None


def normalize_knowledge_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    """Canonical shape: ``milestones: [int]``, ``characters: {name: {...}}``.

    Accepts legacy / LLM variants:
    - milestones as ``[1, 10, 25]``
    - milestones as ``[{chapter: 1, characters: {...}}, ...]`` (develop-narrative output)
    """
    if not matrix:
        return {"milestones": [], "characters": {}}

    out = dict(matrix)
    raw_ms = matrix.get("milestones") or []
    milestones: list[int] = []
    characters: dict[str, Any] = dict(matrix.get("characters") or {})

    for item in raw_ms:
        if isinstance(item, dict):
            ch = _coerce_chapter_number(item.get("chapter"))
            if ch is not None:
                milestones.append(ch)
            block_chars = item.get("characters")
            if isinstance(block_chars, dict):
                for name, data in block_chars.items():
                    if isinstance(data, dict):
                        characters[str(name)] = dict(data)
        else:
            ch = _coerce_chapter_number(item)
            if ch is not None:
                milestones.append(ch)

    out["milestones"] = sorted(set(milestones))
    out["characters"] = characters
    return out


def load_threads(ws: Path) -> dict[str, Any]:
    path = narrative_dir(ws) / "threads.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def effective_milestone(chapter: int, milestones: list[int]) -> int:
    """Largest milestone <= chapter; 0 if none."""
    eligible = [m for m in milestones if m <= chapter]
    return max(eligible) if eligible else 0


def _split_knows(text: str) -> tuple[list[str], list[str]]:
    """Parse milestone prose into knows / does-not-know bullet lists."""
    if not text:
        return [], []
    lower = text.lower()
    for sep in ("does not know yet:", "does not know:", "doesn't know:"):
        idx = lower.find(sep)
        if idx >= 0:
            knows_part = text[:idx]
            not_part = text[idx + len(sep) :]
            knows = _split_list_items(knows_part.replace("Knows:", "").replace("knows:", ""))
            not_knows = _split_list_items(not_part)
            return knows, not_knows
    knows = _split_list_items(text.replace("Knows:", "").replace("knows:", ""))
    return knows, []


def _split_list_items(blob: str) -> list[str]:
    blob = blob.strip()
    if not blob:
        return []
    parts = re.split(r"[.;]\s+|\n+", blob)
    out: list[str] = []
    for p in parts:
        p = p.strip().strip("-").strip()
        if len(p) > 3:
            out.append(p)
    return out


def _active_thread_ids(threads_data: dict[str, Any], chapter: int) -> list[str]:
    out: list[str] = []
    for t in threads_data.get("threads") or []:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        opened = int(t.get("opened_chapter") or 0)
        close_by = int(t.get("must_close_by") or 9999)
        if tid and opened <= chapter <= close_by:
            out.append(str(tid))
    return sorted(out)


def _clues_for_chapter(ledger: dict[str, Any], chapter: int) -> tuple[list[str], list[str], dict[str, dict]]:
    plant: list[str] = []
    payoff: list[str] = []
    details: dict[str, dict] = {}
    for clue in ledger.get("clues") or []:
        if not isinstance(clue, dict):
            continue
        cid = clue.get("id")
        if not cid:
            continue
        pc = clue_plant_chapter(clue)
        pay = clue_payoff_chapter(clue)
        semantic = clue_semantic_text(clue)
        entry = {
            "id": cid,
            "content": semantic,
            "description": semantic,
            "type": clue.get("type", ""),
            "misdirection": clue.get("misdirection", ""),
            "true_meaning": _first_text(clue, "true_meaning", "note"),
            "note": str(clue.get("note") or "").strip(),
            "plant_chapter": pc,
            "payoff_chapter": pay,
        }
        if pc == chapter:
            plant.append(cid)
            details[cid] = entry
        if pay == chapter:
            payoff.append(cid)
            details.setdefault(cid, entry)
    return plant, payoff, details


def _reveals_for_chapter(ledger: dict[str, Any], chapter: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rev in ledger.get("major_reveals") or []:
        if not isinstance(rev, dict):
            continue
        ch = int(rev.get("chapter") or 0)
        if ch != chapter:
            continue
        weight = str(rev.get("reveal_weight") or REVEAL_WEIGHT_MAJOR).lower()
        if weight not in MIN_CLUES_BY_REVEAL_WEIGHT:
            weight = REVEAL_WEIGHT_MAJOR
        semantic = reveal_semantic_text(rev)
        out.append(
            {
                "id": rev.get("id", ""),
                "reveal": semantic,
                "description": semantic,
                "impact": _first_text(rev, "impact", "note"),
                "note": str(rev.get("note") or "").strip(),
                "reveal_weight": weight,
                "required_clues": list(rev.get("required_clues") or []),
                "prerequisite_reveals": list(
                    rev.get("prerequisite_reveals") or []
                ),
                "min_clues_required": min_clues_for_reveal(weight),
            }
        )
    return out


def _red_herring_plant_chapters(rh: dict[str, Any]) -> list[int]:
    raw = rh.get("plant_chapters")
    if isinstance(raw, list) and raw:
        out: list[int] = []
        for x in raw:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out
    try:
        single = int(rh.get("plant_chapter") or 0)
    except (TypeError, ValueError):
        single = 0
    return [single] if single else []


def _red_herring_dispel_chapter(rh: dict[str, Any]) -> int:
    for key in ("dispelled_chapter", "payoff_chapter", "dispel_chapter"):
        try:
            val = int(rh.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if val:
            return val
    return 0


def _red_herrings_for_chapter(ledger: dict[str, Any], chapter: int) -> tuple[list[str], list[str]]:
    plant: list[str] = []
    dispel: list[str] = []
    for rh in ledger.get("red_herrings") or []:
        if not isinstance(rh, dict):
            continue
        rid = rh.get("id")
        if not rid:
            continue
        if chapter in _red_herring_plant_chapters(rh):
            plant.append(rid)
        if _red_herring_dispel_chapter(rh) == chapter:
            dispel.append(rid)
    return plant, dispel


def _parse_must_not_know_entry(key: str, val: Any) -> tuple[str, int] | None:
    """Support fact→chapter int OR chN→fact string (legacy matrix layouts)."""
    key_s = str(key).strip()
    if re.match(r"^ch\d+$", key_s, re.I):
        try:
            threshold = int(key_s[2:])
        except ValueError:
            return None
        return str(val).strip(), threshold
    try:
        threshold = int(val)
    except (TypeError, ValueError):
        return None
    return key_s, threshold


def iter_must_not_know_before(char_data: dict[str, Any]) -> list[tuple[str, int]]:
    """Normalize must_not_know_before — dict, scalar int + hidden_truth, or empty."""
    raw = char_data.get("must_not_know_before")
    if raw is None:
        return []
    if isinstance(raw, int):
        hidden = str(char_data.get("hidden_truth") or "").strip()
        return [(hidden, raw)] if hidden else []
    if isinstance(raw, dict):
        out: list[tuple[str, int]] = []
        for fact_key, before_ch in raw.items():
            parsed = _parse_must_not_know_entry(fact_key, before_ch)
            if parsed:
                out.append(parsed)
        return out
    return []


def _milestone_knowledge_lists(block: Any) -> tuple[list[str], list[str]]:
    """Extract knows / does-not-know from a milestone block.

    Structured develop-narrative output uses ``known_items`` lists. Legacy prose
    uses ``Knows: … Does not know yet: …``. Never ``str(dict)`` — that splits on
    ``. `` inside JSON and truncates mid-sentence in prompts.
    """
    if block is None:
        return [], []
    if isinstance(block, dict):
        known_raw = (
            block.get("known_items")
            or block.get("knows")
            or block.get("known")
            or block.get("may_know")
            or []
        )
        not_raw = (
            block.get("does_not_know_yet")
            or block.get("does_not_know")
            or block.get("must_not_know")
            or block.get("unknown")
            or []
        )
        if isinstance(known_raw, str):
            knows = _split_list_items(known_raw)
        elif isinstance(known_raw, list):
            knows = [str(x).strip() for x in known_raw if str(x).strip()]
        else:
            knows = []
        if isinstance(not_raw, str):
            not_knows = _split_list_items(not_raw)
        elif isinstance(not_raw, list):
            # Milestone-local lists are facts, not fact→chapter maps.
            not_knows = [
                str(x).strip()
                for x in not_raw
                if not isinstance(x, dict) and str(x).strip()
            ]
        else:
            not_knows = []
        hidden = str(block.get("hidden_truth") or "").strip()
        if hidden and hidden not in not_knows and hidden not in knows:
            # Keep as soft context under may_know only when not a future ban.
            pass
        return knows, not_knows
    return _split_knows(str(block))


def _knowledge_for_chapter(
    matrix: dict[str, Any],
    chapter: int,
    *,
    milestones: list[int] | None = None,
) -> dict[str, Any]:
    matrix = normalize_knowledge_matrix(matrix)
    ms = milestones if milestones is not None else list(matrix.get("milestones") or [])
    ms = sorted(ms)
    eff = effective_milestone(chapter, ms)
    pov: list[str] = []
    may_know: list[str] = []
    must_not_know: list[str] = []
    prompt_restricted_characters: list[str] = []

    for char_name, data in (matrix.get("characters") or {}).items():
        if not isinstance(data, dict):
            continue
        pov.append(str(char_name))
        key = f"ch{eff}" if eff else None
        if key and data.get(key) is not None:
            knows, not_knows = _milestone_knowledge_lists(data.get(key))
            for k in knows:
                may_know.append(f"{char_name}: {k}")
            for nk in not_knows:
                must_not_know.append(f"{char_name}: {nk}")
                if str(char_name) not in prompt_restricted_characters:
                    prompt_restricted_characters.append(str(char_name))
        for fact, threshold in iter_must_not_know_before(data):
            if threshold > chapter:
                must_not_know.append(f"{char_name}: {fact}")
                if str(char_name) not in prompt_restricted_characters:
                    prompt_restricted_characters.append(str(char_name))
            else:
                may_know.append(f"{char_name}: {fact}")

    return {
        "pov_characters": pov,
        "may_know": may_know,
        "must_not_know": must_not_know,
        # Writer-facing prohibition is intentionally opaque. The semantic facts
        # above remain available to deterministic plan/QC checks only.
        "prompt_restricted_characters": prompt_restricted_characters,
        "effective_milestone": eff,
    }


def compile_chapter_narrative(
    ledger: dict[str, Any],
    matrix: dict[str, Any],
    threads_data: dict[str, Any],
    chapter: int,
) -> dict[str, Any]:
    """Deterministic narrative constraint for one chapter — no LLM."""
    clues_plant, clues_payoff, clue_details = _clues_for_chapter(ledger, chapter)
    rh_plant, rh_dispel = _red_herrings_for_chapter(ledger, chapter)
    return {
        "chapter": chapter,
        "clues_plant": clues_plant,
        "clues_payoff": clues_payoff,
        "reveals": _reveals_for_chapter(ledger, chapter),
        "red_herrings_plant": rh_plant,
        "red_herrings_dispel": rh_dispel,
        "threads_touch": _active_thread_ids(threads_data, chapter),
        "knowledge": _knowledge_for_chapter(matrix, chapter),
        "clue_details": clue_details,
    }


def build_clue_catalog(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for clue in ledger.get("clues") or []:
        if not isinstance(clue, dict) or not clue.get("id"):
            continue
        cid = str(clue["id"])
        semantic = clue_semantic_text(clue)
        catalog[cid] = {
            "content": semantic,
            "description": semantic,
            "type": clue.get("type", ""),
            "plant_chapter": clue_plant_chapter(clue),
            "payoff_chapter": clue_payoff_chapter(clue),
            "misdirection": clue.get("misdirection", ""),
            "true_meaning": _first_text(clue, "true_meaning", "note"),
            "note": str(clue.get("note") or "").strip(),
        }
    return catalog


def build_reveal_catalog(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for rev in ledger.get("major_reveals") or []:
        if not isinstance(rev, dict) or not rev.get("id"):
            continue
        rid = str(rev["id"])
        semantic = reveal_semantic_text(rev)
        catalog[rid] = {
            "reveal": semantic,
            "description": semantic,
            "chapter": int(rev.get("chapter") or 0),
            "impact": _first_text(rev, "impact", "note"),
            "note": str(rev.get("note") or "").strip(),
            "required_clues": list(rev.get("required_clues") or []),
            "prerequisite_reveals": list(
                rev.get("prerequisite_reveals") or []
            ),
            "reveal_weight": str(rev.get("reveal_weight") or REVEAL_WEIGHT_MAJOR).lower(),
        }
    return catalog


def build_red_herring_catalog(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for rh in ledger.get("red_herrings") or []:
        if not isinstance(rh, dict) or not rh.get("id"):
            continue
        rid = str(rh["id"])
        semantic = red_herring_semantic_text(rh)
        catalog[rid] = {
            "description": semantic,
            "false_lead": semantic,
            "plant_chapters": _red_herring_plant_chapters(rh),
            "dispelled_chapter": _red_herring_dispel_chapter(rh),
            "note": str(rh.get("note") or "").strip(),
        }
    return catalog


def _network_cast_candidates(ws: Path) -> list[str]:
    """Supporting network names for deferred leak choice (exclude leads / victims)."""
    from factory.engine.lib.narrative_schema import load_concept, normalize_concept_characters

    names: list[str] = []
    try:
        concept = load_concept(ws)
    except Exception:
        return names
    for row in normalize_concept_characters(concept.get("characters")):
        role = str(row.get("role") or "").lower()
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if any(tok in role for tok in ("network", "lawyer", "coroner", "hacker", "ally")):
            names.append(name)
    return names


def deferred_choice_defs(ws: Path, ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Plan-time choices that must be resolved BEFORE the Outliner runs."""
    from factory.engine.lib.narrative_schema import load_concept

    choices: list[dict[str, Any]] = []
    try:
        concept = load_concept(ws)
    except Exception:
        concept = {}

    blob = "\n".join(
        [
            str(concept.get("author_directive") or ""),
            "\n".join(str(x) for x in (concept.get("must_include") or [])),
            str(ledger.get("truth") or ""),
            json.dumps(ledger.get("major_reveals") or [], ensure_ascii=False),
        ]
    ).lower()

    leakish = bool(
        re.search(r"decide\s+(which|at\s+plan)|decide-at-plan|kept\s+consistent", blob)
        or re.search(r"\bthe leak\b|\bnetwork betrayal\b|\bone of the three\b", blob)
    )
    if leakish:
        candidates = _network_cast_candidates(ws) or [
            "Sasha Okafor",
            "Priya Anand",
            "Wren Delgado",
        ]
        choices.append(
            {
                "id": "network_leak",
                "label": "network leak / betrayer",
                "candidates": candidates,
                "cardinality": 1,
            }
        )
    return choices


def _extract_deferred_global_choices(
    ws: Path,
    ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolved plan-time choices for the Outliner payload.

    The Outliner never picks: ``plan_choices.yaml`` holds the decision and the
    payload states both the chosen name and the explicit non-candidates, so a
    'second leak' has no room to appear.
    """
    from factory.engine.lib.plan_choices import load_plan_choices

    defs = deferred_choice_defs(ws, ledger)
    if not defs:
        return []
    resolved = load_plan_choices(ws)
    out: list[dict[str, Any]] = []
    for spec in defs:
        cid = str(spec.get("id"))
        candidates = list(spec.get("candidates") or [])
        entry = resolved.get(cid) if isinstance(resolved, dict) else None
        value = str((entry or {}).get("value") or "").strip()
        if value:
            others = [c for c in candidates if c.strip().lower() != value.lower()]
            out.append(
                {
                    "id": cid,
                    "status": "resolved",
                    "value": value,
                    "non_leaks": others,
                    "cardinality": 1,
                    "resolved_by": (entry or {}).get("resolved_by", "auto"),
                    "constraint": (
                        f"{value} IS the one and only leak/betrayer for the whole "
                        "book. "
                        + (
                            f"{', '.join(others)} are NOT leaks and never betray "
                            "the protagonist. "
                            if others
                            else "No other character betrays the protagonist. "
                        )
                        + "FORBIDDEN: a 'second leak', another mole, a deeper leak, "
                        "an infrastructure leak, or re-assigning the betrayal to "
                        "anyone else. Before the reveal chapter, refer to the "
                        "unknown betrayer as 'the leak' without naming a different "
                        "person."
                    ),
                }
            )
            continue
        out.append(
            {
                "id": cid,
                "status": "unresolved_at_plan",
                "candidates": candidates,
                "cardinality": 1,
                "constraint": (
                    "Choose exactly ONE candidate as the leak/betrayer and lock that "
                    "name for the rest of the book. NEVER invent a second leak, "
                    "alternate mole, or 'also betrayed' character."
                ),
            }
        )
    return out


def _plot_boundary_payload(ws: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    """Hard true_plot fence so Outliner cannot invent parallel conspiracies."""
    true_plot = ""
    surface_plot = ""
    try:
        from factory.engine.lib.intent_manifest import load_intent_manifest

        man = load_intent_manifest(ws, 1)
        true_plot = str(man.get("true_plot") or "").strip()
        surface_plot = str(man.get("surface_plot") or "").strip()
    except Exception:
        pass
    if not true_plot:
        try:
            from factory.engine.lib.narrative_schema import load_concept

            concept = load_concept(ws)
            true_plot = str(concept.get("true_plot") or "").strip()
            surface_plot = str(
                concept.get("surface_plot") or concept.get("surface_mystery") or ""
            ).strip()
        except Exception:
            pass
    return {
        "main_mystery": str(ledger.get("main_mystery") or "").strip(),
        "truth": str(ledger.get("truth") or "").strip(),
        "true_plot": true_plot,
        "surface_plot": surface_plot,
        "forbidden_expansions": [
            "Do NOT invent serial-killer patterns, multi-decade murder sprees, camps, "
            "or missing-person side cases unless they already appear in true_plot / "
            "locked cast / ledger descriptions.",
            "Do NOT rename or replace ledger clue/reveal semantics — plant/payoff the "
            "exact content from clue_catalog / reveal_catalog.",
            "Do NOT expand the conspiracy beyond true_plot + ledger truth.",
        ],
    }


def compile_book_narrative(ws: Path, *, total_chapters: int | None = None) -> dict[int, dict[str, Any]]:
    direction = _load_direction(ws)
    if total_chapters is None:
        from factory.engine.lib.book_config import get_total_chapters

        book = int(direction.get("book") or 1)
        total = get_total_chapters(ws.name, book)
    else:
        total = total_chapters
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    return {
        ch: compile_chapter_narrative(ledger, matrix, threads_data, ch)
        for ch in range(1, total + 1)
    }


def compile_act_constraints(ws: Path, act_from: int, act_to: int) -> dict[str, Any]:
    """Payload slice for Outliner: constraints + full semantic catalogs for an act range."""
    direction = _load_direction(ws)
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    chapters = {
        str(ch): compile_chapter_narrative(ledger, matrix, threads_data, ch)
        for ch in range(act_from, act_to + 1)
    }
    return {
        "act_range": [act_from, act_to],
        "target_language": direction.get("target_language", "en"),
        "chapters": chapters,
        "clue_catalog": build_clue_catalog(ledger),
        "reveal_catalog": build_reveal_catalog(ledger),
        "red_herring_catalog": build_red_herring_catalog(ledger),
        "canonical_reveal_chapter": ledger.get("canonical_reveal_chapter"),
        "plot_boundary": _plot_boundary_payload(ws, ledger),
        "global_choices": _extract_deferred_global_choices(ws, ledger),
        "semantic_lock": (
            "Clue/reveal IDs in chapters[] are schedules only. "
            "MUST use clue_catalog[id].content and reveal_catalog[id].reveal "
            "verbatim as the planted/paid semantic — do not substitute a different "
            "object, victim, photo, or conspiracy for the same ID."
        ),
    }


def compile_workspace_narrative(workspace_id: str, *, total_chapters: int | None = None) -> dict[int, dict[str, Any]]:
    ws = workspace_dir(workspace_id)
    return compile_book_narrative(ws, total_chapters=total_chapters)


def compile_chapter_for_workspace(ws: Path, chapter: int) -> dict[str, Any] | None:
    """Single-chapter compile; None if compiler disabled for this workspace."""
    direction = _load_direction(ws)
    if not narrative_compiler_enabled(ws, direction):
        return None
    return compile_chapter_narrative(
        load_ledger(ws),
        load_knowledge_matrix(ws),
        load_threads(ws),
        chapter,
    )


def format_narrative_constraints_block(
    compiled: dict[str, Any],
    *,
    lang: str = "en",
    locked_plan: bool = False,
) -> str:
    """Render NARRATIVE CONSTRAINTS for Writer prompt — source is compiler only."""
    ch = compiled.get("chapter", 0)
    vi = lang == "vi"
    heading = (
        f"## RÀNG BUỘC NARRATIVE (Chương {ch})"
        if vi
        else f"## NARRATIVE CONSTRAINTS (Chapter {ch})"
    )
    authority = (
        "Nguồn: mystery_ledger + knowledge_matrix (compiler). "
        "Writer BẮT BUỘC tuân thủ; không mâu thuẫn."
        if vi
        else "Source: mystery_ledger + knowledge_matrix (compiler). "
        "Writer MUST obey; do not contradict."
    )
    lines = [heading, authority]
    if locked_plan:
        lines.append(
            "Beat chương đã khóa — giữ nguyên must_happen/must_not từ plan; "
            "chỉ ràng buộc clue/knowledge bên dưới."
            if vi
            else "Chapter beats are locked — keep plan must_happen/must_not; "
            "obey clue/knowledge rules below."
        )

    def _section(title: str, items: list[str], *, bullet_fmt: str | None = None) -> None:
        if not items:
            return
        lines.append("")
        lines.append(f"### {title}")
        for item in items:
            if bullet_fmt:
                lines.append(f"- {bullet_fmt.format(item=item)}")
            else:
                lines.append(f"- {item}")

    details = compiled.get("clue_details") or {}
    plant_lines = []
    for cid in compiled.get("clues_plant") or []:
        d = details.get(cid, {})
        content = d.get("content") or cid
        plant_lines.append(f"**{cid}**: {content}")
    _section(
        "Clues to PLANT" if not vi else "Manh mối PHẢI GIEO",
        plant_lines,
    )

    payoff_lines = []
    for cid in compiled.get("clues_payoff") or []:
        d = details.get(cid, {})
        content = d.get("content") or cid
        true_meaning = d.get("true_meaning", "")
        line = f"**{cid}**: {content}"
        if true_meaning:
            line += f" → ({true_meaning})"
        payoff_lines.append(line)
    _section(
        "Clues to PAY OFF" if not vi else "Manh mối PHẢI TRẢ",
        payoff_lines,
    )

    reveal_lines = []
    for rev in compiled.get("reveals") or []:
        rid = rev.get("id", "")
        weight = rev.get("reveal_weight", REVEAL_WEIGHT_MAJOR)
        text = rev.get("reveal", "")
        reveal_lines.append(f"**{rid}** [{weight}]: {text}")
    _section(
        "Reveals this chapter" if not vi else "Hé lộ chương này",
        reveal_lines,
    )

    rh_plant = compiled.get("red_herrings_plant") or []
    rh_dispel = compiled.get("red_herrings_dispel") or []
    if rh_plant or rh_dispel:
        lines.append("")
        lines.append("### " + ("Red herrings" if not vi else "Manh gỡ / false lead"))
        if rh_plant:
            lines.append("- " + ("Plant: " if not vi else "Gieo: ") + ", ".join(rh_plant))
        if rh_dispel:
            lines.append("- " + ("Dispel: " if not vi else "Gỡ: ") + ", ".join(rh_dispel))

    threads = compiled.get("threads_touch") or []
    if threads:
        lines.append("")
        lines.append("### " + ("Active threads" if not vi else "Mạch đang mở"))
        lines.append("- " + ", ".join(threads))

    knowledge = compiled.get("knowledge") or {}
    may = knowledge.get("may_know") or []
    must_not = knowledge.get("must_not_know") or []
    restricted = list(knowledge.get("prompt_restricted_characters") or [])
    if must_not and not restricted:
        restricted = list(
            dict.fromkeys(
                str(item).split(":", 1)[0].strip()
                for item in must_not
                if str(item).split(":", 1)[0].strip()
            )
        )
    if may or must_not:
        lines.append("")
        lines.append("### " + ("Knowledge gates" if not vi else "Cổng tri thức"))
        if may:
            lines.append("**" + ("May know" if not vi else "Được biết") + ":**")
            for m in may[:12]:
                lines.append(f"- {m}")
            if len(may) > 12:
                lines.append(f"- … (+{len(may) - 12})")
        if must_not:
            lines.append(
                "**"
                + ("MUST NOT know or reveal yet" if not vi else "TUYỆT ĐỐI chưa được biết/hé")
                + ":**"
            )
            for character in restricted:
                if vi:
                    lines.append(
                        f"- {character}: tri thức đóng — chỉ dùng mục Được biết và "
                        "quan sát trực tiếp trong chương; không suy ra hoặc hé lộ "
                        "nguyên nhân ẩn, kế hoạch bí mật hay phát hiện tương lai."
                    )
                else:
                    lines.append(
                        f"- {character}: closed-world knowledge — use only May know "
                        "facts and direct chapter observations; do not infer or reveal "
                        "hidden causes, secret plans, or future discoveries."
                    )

    if len(lines) <= 2 and not plant_lines and not payoff_lines and not reveal_lines:
        return ""

    return "\n".join(lines)


def narrative_constraints_block_for_prompt(
    ws: Path,
    chapter: int,
    *,
    lang: str = "en",
    locked_plan: bool = False,
) -> str:
    """Prompt block from compiler; empty string if compiler off or no constraints."""
    if not narrative_compiler_enabled(ws):
        return ""
    compiled = compile_chapter_for_workspace(ws, chapter)
    if not compiled:
        return ""
    # Writer sees only the active POV character's knowledge. Other characters'
    # private knowledge is future-story data, not writing context for this scene.
    try:
        from factory.engine.lib.narrative_schema import load_concept

        concept = load_concept(ws)
        pov = concept.get("pov") if isinstance(concept.get("pov"), dict) else {}
        pov_character = str((pov or {}).get("character") or "").strip()
        if pov_character:
            knowledge = dict(compiled.get("knowledge") or {})
            prefix = pov_character.lower() + ":"
            knowledge["pov_characters"] = [pov_character]
            knowledge["may_know"] = [
                item
                for item in (knowledge.get("may_know") or [])
                if str(item).lower().startswith(prefix)
            ]
            knowledge["must_not_know"] = [
                item
                for item in (knowledge.get("must_not_know") or [])
                if str(item).lower().startswith(prefix)
            ]
            knowledge["prompt_restricted_characters"] = (
                [pov_character] if knowledge["must_not_know"] else []
            )
            compiled = {**compiled, "knowledge": knowledge}
    except (OSError, TypeError, ValueError):
        pass
    return format_narrative_constraints_block(
        compiled, lang=lang, locked_plan=locked_plan
    )


def narrative_block_for_plan(compiled: dict[str, Any]) -> dict[str, Any]:
    """Map compiler chapter output → chapter_plan.narrative schema."""
    knowledge = compiled.get("knowledge") or {}
    clue_details = compiled.get("clue_details") or {}
    clue_beats: dict[str, str] = {}
    for cid in compiled.get("clues_plant") or []:
        content = (clue_details.get(cid) or {}).get("content")
        if content:
            clue_beats[str(cid)] = str(content)

    reveals_out: list[dict[str, Any]] = []
    for rev in compiled.get("reveals") or []:
        if not isinstance(rev, dict):
            continue
        reveals_out.append(
            {
                "id": rev.get("id", ""),
                "reveal_weight": rev.get("reveal_weight", REVEAL_WEIGHT_MAJOR),
                "required_clues": list(rev.get("required_clues") or []),
                "prerequisite_reveals": list(
                    rev.get("prerequisite_reveals") or []
                ),
                "min_clues_required": rev.get(
                    "min_clues_required",
                    min_clues_for_reveal(str(rev.get("reveal_weight", REVEAL_WEIGHT_MAJOR))),
                ),
            }
        )

    return {
        "clues_plant": list(compiled.get("clues_plant") or []),
        "clues_payoff": list(compiled.get("clues_payoff") or []),
        "reveals": reveals_out,
        "red_herrings_plant": list(compiled.get("red_herrings_plant") or []),
        "red_herrings_dispel": list(compiled.get("red_herrings_dispel") or []),
        "threads_touch": list(compiled.get("threads_touch") or []),
        "knowledge": {
            "pov_characters": list(knowledge.get("pov_characters") or []),
            "may_know": list(knowledge.get("may_know") or []),
            "must_not_know": list(knowledge.get("must_not_know") or []),
            "effective_milestone": knowledge.get("effective_milestone", 0),
        },
        "clue_beats": clue_beats,
    }


_ID_TOKEN_RE = re.compile(r"\b(?:C\d{3}|MR\d{2,3}|R\d{3})\b")
_ID_MARKER_RE = re.compile(
    r"\[\s*(?:CLUE|PAYOFF|REVEAL)\s+(?:C\d{3}|MR\d{2,3}|R\d{3})\s*\]\s*",
    re.IGNORECASE,
)
_SEMANTIC_STOPWORDS = frozenset(
    {"that", "with", "from", "this", "have", "been", "into", "when", "what", "which", "about"}
)


def _semantic_keywords(content: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-zà-ỹ'\-]{4,}", (content or "").lower())
        if w not in _SEMANTIC_STOPWORDS
    ]


def semantic_present(text: str, content: str) -> bool:
    """True when ``text`` actually carries the canonical ledger meaning."""
    blob = (text or "").lower()
    c = (content or "").lower().strip()
    if not c or not blob:
        return False
    if len(c) >= 12 and c[:36] in blob:
        return True
    words = _semantic_keywords(c)
    if not words:
        return False
    probe = words[:8]
    hits = sum(1 for w in probe if w in blob)
    return hits >= max(2, (len(probe) + 2) // 3)


def _strip_ids(text: str, ids: set[str]) -> str:
    """Remove ID markers/tokens the chapter is not scheduled to fire."""
    if not ids:
        return text

    def _drop_marker(match: re.Match[str]) -> str:
        token = _ID_TOKEN_RE.search(match.group(0))
        return "" if token and token.group(0) in ids else match.group(0)

    def _drop_token(match: re.Match[str]) -> str:
        return "" if match.group(0) in ids else match.group(0)

    out = _ID_MARKER_RE.sub(_drop_marker, text)
    out = _ID_TOKEN_RE.sub(_drop_token, out)
    out = re.sub(r"\b(?:is|are)\s+(?:paid off|planted|revealed)\s*:\s*", "", out)
    out = re.sub(r"\(\s*(?:plants?|pays? off)?\s*\)", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ;:,-—")
    return out


def seal_chapter_semantics(compiled: dict[str, Any], plan: dict) -> tuple[dict, list[str]]:
    """Compiler owns clue/reveal meaning: repair or strip whatever the model wrote.

    * scheduled ID whose prose contradicts the ledger → line replaced by canonical text
    * ID referenced but not scheduled this chapter → token stripped (prose kept)
    """
    notes: list[str] = []
    out = dict(plan)
    details = compiled.get("clue_details") or {}
    plant = [str(c) for c in (compiled.get("clues_plant") or [])]
    payoff = [str(c) for c in (compiled.get("clues_payoff") or [])]
    reveals = {
        str(r.get("id")): r for r in (compiled.get("reveals") or []) if isinstance(r, dict)
    }
    scheduled = set(plant) | set(payoff) | set(reveals)

    canonical: dict[str, str] = {}
    for cid in plant:
        content = str((details.get(cid) or {}).get("content") or "").strip()
        if content:
            canonical[cid] = f"[CLUE {cid}] {content}"
    for cid in payoff:
        content = str((details.get(cid) or {}).get("content") or "").strip()
        if content:
            canonical.setdefault(cid, f"[PAYOFF {cid}] {content}")
    for rid, rev in reveals.items():
        text = str(rev.get("reveal") or "").strip()
        if text:
            canonical[rid] = f"[REVEAL {rid}] {text}"

    def _content_for(_id: str) -> str:
        if _id in details:
            return str((details.get(_id) or {}).get("content") or "")
        return str((reveals.get(_id) or {}).get("reveal") or "")

    ch = plan.get("chapter")
    mh_in = [str(x) for x in (out.get("must_happen") or [])]
    mh_out: list[str] = []
    repaired: set[str] = set()
    for line in mh_in:
        ids = set(_ID_TOKEN_RE.findall(line))
        if not ids:
            mh_out.append(line)
            continue
        sched_here = {i for i in ids if i in scheduled}
        unsched = ids - scheduled
        if sched_here:
            target = sorted(sched_here)[0]
            content = _content_for(target)
            if content and not semantic_present(line, content):
                if target in canonical and target not in repaired:
                    mh_out.append(canonical[target])
                    repaired.add(target)
                    notes.append(f"ch{ch}:{target}:replaced_mismatched_beat")
                else:
                    notes.append(f"ch{ch}:{target}:dropped_duplicate_mismatch")
                continue
            repaired.add(target)
            mh_out.append(line)
            continue
        cleaned = _strip_ids(line, unsched)
        if cleaned:
            notes.append(f"ch{ch}:{','.join(sorted(unsched))}:stripped_unscheduled_id")
            mh_out.append(cleaned)
        else:
            notes.append(f"ch{ch}:{','.join(sorted(unsched))}:dropped_empty_after_strip")
    out["must_happen"] = mh_out

    for field in ("beat_summary", "chapter_task", "one_line_summary", "carries_to_next", "cliffhanger"):
        val = out.get(field)
        if not isinstance(val, str) or not val:
            continue
        unsched = {i for i in _ID_TOKEN_RE.findall(val) if i not in scheduled}
        if unsched:
            out[field] = _strip_ids(val, unsched)
            notes.append(f"ch{ch}:{field}:stripped_unscheduled_id")

    return out, notes


def seal_plan_semantics(ws: Path, plans: list[dict]) -> tuple[list[dict], list[str]]:
    """Apply the semantic seal to a freshly generated chunk (pre-merge)."""
    if not narrative_compiler_enabled(ws):
        return plans, []
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    out: list[dict] = []
    notes: list[str] = []
    for plan in plans:
        ch = int(plan.get("chapter") or 0)
        if plan.get("locked") or ch <= 0:
            out.append(plan)
            continue
        compiled = compile_chapter_narrative(ledger, matrix, threads_data, ch)
        sealed, plan_notes = seal_chapter_semantics(compiled, plan)
        notes.extend(plan_notes)
        out.append(sealed)
    return out, notes


def merge_narrative_into_plans(ws: Path, plans: list[dict]) -> list[dict]:
    """Attach compiler narrative to each plan. Skips locked and archive workspaces.

    The seal runs first, so an ID is never attached to prose that contradicts the
    ledger; only then are missing scheduled beats appended.
    """
    if not narrative_compiler_enabled(ws):
        return plans
    ledger = load_ledger(ws)
    matrix = load_knowledge_matrix(ws)
    threads_data = load_threads(ws)
    out: list[dict] = []
    for plan in plans:
        if plan.get("locked"):
            out.append(plan)
            continue
        ch = int(plan.get("chapter") or 0)
        if ch <= 0:
            out.append(plan)
            continue
        compiled = compile_chapter_narrative(ledger, matrix, threads_data, ch)
        merged, _ = seal_chapter_semantics(compiled, plan)
        merged["narrative"] = narrative_block_for_plan(compiled)
        merged["must_happen"] = _ensure_clue_beats_in_must_happen(
            list(merged.get("must_happen") or []),
            compiled,
            beat_summary=str(merged.get("beat_summary") or ""),
        )
        out.append(merged)
    return out


def _ensure_clue_beats_in_must_happen(
    must_happen: list,
    compiled: dict[str, Any],
    *,
    beat_summary: str = "",
) -> list:
    """Append missing scheduled clue/payoff lines so NC-07 can pass after merge."""
    mh = [str(x) for x in must_happen]
    blob = (" ".join(mh) + " " + beat_summary).lower()
    details = compiled.get("clue_details") or {}

    def _already(cid: str, content: str) -> bool:
        # ID presence alone is NOT proof — the model often stamps the right ID on
        # invented prose. Only canonical meaning counts.
        return semantic_present(blob, content)

    for cid in compiled.get("clues_plant") or []:
        cid_s = str(cid)
        content = str((details.get(cid_s) or {}).get("content") or "").strip()
        if not content:
            # Do not inject bare [CLUE id] — that false-greens NC-07.
            continue
        if _already(cid_s, content):
            continue
        mh.append(f"[CLUE {cid_s}] {content}".strip())
        blob = (" ".join(mh) + " " + beat_summary).lower()

    for cid in compiled.get("clues_payoff") or []:
        cid_s = str(cid)
        content = str((details.get(cid_s) or {}).get("content") or "").strip()
        if not content:
            continue
        if _already(cid_s, content):
            continue
        mh.append(f"[PAYOFF {cid_s}] {content}".strip())
        blob = (" ".join(mh) + " " + beat_summary).lower()

    return mh
