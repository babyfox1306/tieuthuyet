"""Hard phrase-gate for chapter_plans at generation/merge time (not LLM plan QC).

Uses the same compile_chapter_canon_rules as the writer. Dramatized plan fields
must not contain forbidden_facts for that chapter. must_not is excluded because
it often names banned phrases as prohibitions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.engine.lib.concept_canon import compile_chapter_canon_rules

# Fields that instruct the writer what HAPPENS — god-truth bleed here poisons prose.
PLAN_DRAMATIZED_FIELDS = (
    "one_line_summary",
    "beat_summary",
    "opens_with",
    "cliffhanger",
    "chapter_task",
    "carries_to_next",
    "emotional_beat",
    "signature_detail_hint",
)


def _field_text(plan: dict, key: str) -> str:
    val = plan.get(key)
    if val is None:
        return ""
    if isinstance(val, list):
        return "\n".join(str(x) for x in val)
    return str(val)


def plan_prose_blob(plan: dict) -> str:
    parts = [_field_text(plan, k) for k in PLAN_DRAMATIZED_FIELDS]
    mh = plan.get("must_happen")
    if isinstance(mh, list):
        parts.append("\n".join(str(x) for x in mh))
    elif mh:
        parts.append(str(mh))
    return "\n".join(parts)


def plan_forbidden_phrase_hits(
    plan: dict,
    concept: dict | None,
) -> list[dict[str, Any]]:
    """Return hits: [{phrase, field, chapter}, ...] for dramatized fields + must_happen."""
    if not concept:
        return []
    try:
        ch = int(plan.get("chapter") or 0)
    except (TypeError, ValueError):
        return []
    if ch < 1:
        return []
    rules = compile_chapter_canon_rules(concept, ch)
    phrases = [str(p).strip() for p in (rules.forbidden_facts or []) if str(p).strip()]
    if not phrases:
        return []

    hits: list[dict[str, Any]] = []
    # Per-field so logs are actionable
    field_map: list[tuple[str, str]] = []
    for key in PLAN_DRAMATIZED_FIELDS:
        text = _field_text(plan, key)
        if text.strip():
            field_map.append((key, text))
    mh = plan.get("must_happen")
    if isinstance(mh, list) and mh:
        field_map.append(("must_happen", "\n".join(str(x) for x in mh)))
    elif mh:
        field_map.append(("must_happen", str(mh)))

    for phrase in phrases:
        pl = phrase.lower()
        for field, text in field_map:
            if pl in text.lower():
                hits.append({"chapter": ch, "field": field, "phrase": phrase})
                break  # one hit per phrase is enough
    return hits


def filter_plans_by_phrase_gate(
    plans: list[dict],
    concept: dict | None,
) -> tuple[list[dict], list[dict[str, Any]]]:
    """Keep plans with no forbidden-phrase hits. Returns (clean, all_hits)."""
    clean: list[dict] = []
    all_hits: list[dict[str, Any]] = []
    for plan in plans:
        hits = plan_forbidden_phrase_hits(plan, concept)
        if hits:
            all_hits.extend(hits)
            continue
        clean.append(plan)
    return clean, all_hits


def format_phrase_gate_violations(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    lines = []
    for h in hits[:12]:
        lines.append(
            f"ch{h.get('chapter')}.{h.get('field')}: forbidden phrase "
            f"{h.get('phrase')!r}"
        )
    extra = len(hits) - 12
    if extra > 0:
        lines.append(f"... and {extra} more")
    return "; ".join(lines)


def chapter_canon_rules_for_act(
    concept: dict | None,
    act_from: int,
    act_to: int,
) -> dict[str, dict[str, Any]]:
    """Map str(ch) -> ChapterCanonRules.to_dict() for outliner payload."""
    if not concept:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ch in range(int(act_from), int(act_to) + 1):
        out[str(ch)] = compile_chapter_canon_rules(concept, ch).to_dict()
    return out
