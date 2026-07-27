"""Hard-off romance policy for anti-romance books.

Three layers, all deterministic (no LLM goodwill required):

1. ``strip_romance_section`` removes the opt-in ROMANCE block from a role prompt
   and replaces it with an explicit prohibition, so the model never sees the
   micro-beat template it likes to copy.
2. ``scrub_plan_romance`` deletes ``[ROMANCE]`` beats and romance sentences the
   model emitted anyway.
3. ``romance_violations`` reports attraction semantics that survived the scrub —
   the caller re-generates the chunk instead of shipping it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROMANCE_SECTION_START = "<!-- ROMANCE_SECTION_START -->"
ROMANCE_SECTION_END = "<!-- ROMANCE_SECTION_END -->"

ROMANCE_OFF_BLOCK = """## ROMANCE — TẮT CỨNG (concept cấm romance)
- Cuốn này **KHÔNG** có romance, love interest, attraction, hay micro-beat tình cảm.
- **CẤM TUYỆT ĐỐI** marker `[ROMANCE]` trong `must_happen` hay bất kỳ field nào.
- **CẤM** từ/ý: attraction, attracted, chemistry, desire, longing, intimacy,
  "dark intimacy", romantic, love interest, lust, "pull toward", "rung động",
  "thân mật", "hấp dẫn".
- `emotional_beat` chỉ mô tả cảm xúc plot (fear, rage, grief, control, paranoia).
- `spice_note` ghi đúng: "No romance; tension is plot-driven."
- Nếu cần khoảnh khắc đơn độc, dùng `[ISOLATION]` — thuần cô lập, không hàm ý tình cảm.
- Nam chính/phản diện chỉ là target/antagonist — **không** phải love interest.
"""

_ROMANCE_MARKER_RE = re.compile(r"\[\s*ROMANCE\s*\]", re.IGNORECASE)

# Attraction semantics — used both to scrub and to reject.
_ROMANCE_TOKEN_RE = re.compile(
    r"\[\s*ROMANCE\s*\]|"
    r"\battract(?:ion|ed|ive)\b|"
    r"\bchemistry\b|"
    r"\bdark intimac\w*\b|"
    r"\bintimac\w*\b|"
    r"\bromanc\w*\b|"
    r"\bromantic\w*\b|"
    r"\blove interest\b|"
    r"\bdesire for (?:him|her)\b|"
    r"\blonging for (?:him|her)\b|"
    r"\blust\b|"
    r"\bseduc\w*\b|"
    r"\bflirt\w*\b|"
    r"\brung động\b|"
    r"\bthân mật\b|"
    r"\bhấp dẫn giới tính\b",
    re.IGNORECASE,
)

# Prohibition fields legitimately name romance ("must_not: no romantic subplot").
_NEGATIVE_FIELDS = frozenset({"must_not", "must_avoid", "forbidden", "must_not_reveal"})

# Fields scrubbed sentence-by-sentence; fallback used when nothing survives.
_SENTENCE_FIELDS: dict[str, str] = {
    "beat_summary": "",
    "chapter_task": "",
    "one_line_summary": "",
    "emotional_beat": "Plot-driven tension: control, paranoia, and cost.",
    "carries_to_next": "Unresolved plot pressure carries into the next chapter.",
    "cliffhanger": "The threat escalates without resolution.",
    "opens_with": "",
}

# Short, formulaic fields: rewrite wholesale instead of salvaging sentences.
_REPLACED_FIELDS: dict[str, str] = {
    "spice_note": "Spice 0 — tension is plot-driven only.",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")

# Last-resort beats so a scrubbed chapter still meets the 3-beat plan minimum.
_FILLER_BEATS = (
    "[ISOLATION] The scene ends with no comfort offered — only the case.",
    "[ISOLATION] She works alone; the pressure of the investigation tightens.",
    "[ISOLATION] The threat advances while no one stands beside her.",
)


def strip_romance_section(role_text: str) -> str:
    """Replace the opt-in ROMANCE block with an explicit prohibition."""
    start = role_text.find(ROMANCE_SECTION_START)
    end = role_text.find(ROMANCE_SECTION_END)
    if start == -1 or end == -1 or end < start:
        return role_text.rstrip() + "\n\n" + ROMANCE_OFF_BLOCK
    return (
        role_text[:start]
        + ROMANCE_OFF_BLOCK
        + role_text[end + len(ROMANCE_SECTION_END):]
    )


def romance_is_forbidden(direction: dict, ws: Path | None = None) -> bool:
    from factory.engine.lib.plan_qc import romance_forbidden

    return romance_forbidden(direction, ws=ws)


def outliner_system_prompt(direction: dict, ws: Path | None = None) -> str | None:
    """Role text with romance cut out; None when romance stays opt-in."""
    from factory.engine.lib.call_9router import load_role

    if not romance_is_forbidden(direction, ws):
        return None
    return strip_romance_section(load_role("outliner", direction=direction))


def _strip_tokens(text: str) -> str:
    out = _ROMANCE_TOKEN_RE.sub("", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;:-—")


def _scrub_sentences(text: str, fallback: str) -> tuple[str, bool]:
    if not text or not _ROMANCE_TOKEN_RE.search(text):
        return text, False
    kept = [
        s for s in _SENTENCE_SPLIT_RE.split(text) if not _ROMANCE_TOKEN_RE.search(s)
    ]
    cleaned = " ".join(x.strip() for x in kept if x.strip()).strip()
    if not cleaned:
        # Whole value was romance: use the field fallback, else token-strip so no
        # attraction semantics survive even when we cannot rewrite the beat.
        cleaned = fallback or _strip_tokens(text)
    return cleaned, True


def scrub_plan_romance(plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove [ROMANCE] beats and romance sentences.

    Notes are tagged ``material:`` when the repair cost real content (a dropped
    beat or a field rewritten to boilerplate) — the caller re-generates on those
    instead of shipping a hollowed-out plan.
    """
    out = dict(plan)
    notes: list[str] = []
    ch = out.get("chapter")

    must_happen = out.get("must_happen")
    if isinstance(must_happen, list):
        kept: list[Any] = []
        changed = False
        for item in must_happen:
            text = str(item)
            body = _ROMANCE_MARKER_RE.sub("", text).strip()
            if _ROMANCE_TOKEN_RE.search(body):
                # The beat itself is romantic — no salvage.
                notes.append(f"material:ch{ch}:dropped romance must_happen beat")
                changed = True
                continue
            if body != text:
                # Marker only: the action survives, the romance framing does not.
                notes.append(f"material:ch{ch}:unmarked [ROMANCE] beat")
                kept.append(body)
                changed = True
                continue
            kept.append(item)
        # Never let scrubbing starve a valid chapter below the 3-beat minimum.
        while len(must_happen) >= 3 and len(kept) < 3:
            kept.append(_FILLER_BEATS[len(kept) % len(_FILLER_BEATS)])
            notes.append(f"material:ch{ch}:filler beat after romance scrub")
        if changed:
            out["must_happen"] = kept

    for field, replacement in _REPLACED_FIELDS.items():
        val = out.get(field)
        if isinstance(val, str) and _ROMANCE_TOKEN_RE.search(val):
            out[field] = replacement
            notes.append(f"material:ch{ch}:replaced {field}")

    for field, fallback in _SENTENCE_FIELDS.items():
        val = out.get(field)
        if not isinstance(val, str):
            continue
        cleaned, changed = _scrub_sentences(val, fallback)
        if not changed:
            continue
        out[field] = cleaned
        material = not cleaned or cleaned == fallback
        tag = "material" if material else "light"
        notes.append(f"{tag}:ch{ch}:scrubbed {field}")

    return out, notes


def romance_violations(plan: dict[str, Any]) -> list[str]:
    """Attraction semantics still present after scrub — caller should re-generate."""
    hits: list[str] = []
    ch = plan.get("chapter")
    for key, val in plan.items():
        if key == "narrative" or key in _NEGATIVE_FIELDS:
            continue
        blob = val if isinstance(val, str) else None
        if blob is None and isinstance(val, list):
            blob = " ".join(str(x) for x in val)
        if not blob:
            continue
        for m in _ROMANCE_TOKEN_RE.finditer(blob):
            hits.append(f"ch{ch}:{key}:{m.group(0).strip()}")
            break
    return hits


def enforce_romance_off(plans: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    """Scrub every plan, then report what warrants a re-generation.

    Returns ``(plans, notes, violations)``. Violations = attraction semantics the
    scrub could not remove, plus repairs that cost real content.
    """
    out: list[dict] = []
    notes: list[str] = []
    violations: list[str] = []
    for plan in plans:
        scrubbed, plan_notes = scrub_plan_romance(plan)
        notes.extend(plan_notes)
        violations.extend(n for n in plan_notes if n.startswith("material:"))
        violations.extend(romance_violations(scrubbed))
        out.append(scrubbed)
    return out, notes, violations
