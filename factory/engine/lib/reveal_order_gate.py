"""Reveal-order by role — tier-4 named as adversary/mastermind before reveal_chapter.

Phrase gates miss role-language ("named her adversary", org-chart apex).
This module detects when the binding antagonist is identified as the top/enemy
before ``binding_condition.reveal_chapter``.
"""

from __future__ import annotations

import re
from typing import Any

# Role / apex language near the antagonist name (pre-reveal BLOCK).
_ROLE_APEX_RE = re.compile(
    r"(?:"
    r"adversary|antagonist|mastermind|architect(?:ed|ure)?|"
    r"real\s+enemy|true\s+enemy|the\s+one\s+behind|"
    r"at\s+the\s+top|behind\s+(?:it|everything|this)|"
    r"named\s+her\s+(?:adversary|enemy|opponent)|"
    r"named\s+his\s+(?:adversary|enemy)|"
    r"director\s+of\s+policy|"
    r"ultimate\s+(?:sponsor|enemy|target)|"
    r"capture\s+instrument|"
    r"designed\s+the\s+directorate"
    r")",
    re.IGNORECASE,
)

# Window: name and role cue within N chars (either order).
_WINDOW = 160


def _name_variants(canonical: str, aliases: list[str] | None = None) -> list[str]:
    names = [canonical]
    for a in aliases or []:
        if a and a not in names:
            names.append(a)
    # Prefer longer names first for matching
    return sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)


def _name_pattern(names: list[str]) -> re.Pattern[str] | None:
    if not names:
        return None
    parts = [re.escape(n) for n in names]
    return re.compile(r"(?:%s)" % "|".join(parts), re.IGNORECASE)


def find_early_tier4_identity_hits(
    text: str,
    *,
    antagonist_canonical: str,
    antagonist_aliases: list[str] | None = None,
    reveal_chapter: int,
    chapter: int,
) -> list[dict[str, Any]]:
    """If chapter < reveal_chapter, flag name↔apex-role co-occurrence."""
    if chapter <= 0 or reveal_chapter <= 0 or chapter >= reveal_chapter:
        return []
    if not (text or "").strip() or not antagonist_canonical:
        return []

    names = _name_variants(antagonist_canonical, antagonist_aliases)
    name_re = _name_pattern(names)
    if not name_re:
        return []

    hits: list[dict[str, Any]] = []
    # Slide over role matches; require antagonist name nearby
    for role_m in _ROLE_APEX_RE.finditer(text):
        left = max(0, role_m.start() - _WINDOW)
        right = min(len(text), role_m.end() + _WINDOW)
        window = text[left:right]
        name_m = name_re.search(window)
        if not name_m:
            continue
        snippet = window.replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        hits.append(
            {
                "chapter": chapter,
                "reveal_chapter": reveal_chapter,
                "name": name_m.group(0),
                "role_cue": role_m.group(0),
                "snippet": snippet,
            }
        )
    # Dedupe by (name, role_cue, approx position)
    uniq: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for h in hits:
        key = (h["name"].lower(), h["role_cue"].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq


def antagonist_from_concept(concept: dict[str, Any]) -> tuple[str, list[str]]:
    """Best-effort antagonist name from concept binding / author_directive."""
    binding = concept.get("binding_condition") or {}
    canonical = str(binding.get("canonical_text") or "")
    # "Stellan Marsh architected..." → leading Proper Name pair
    m = re.match(
        r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+",
        canonical.strip(),
    )
    if m:
        full = m.group(1).strip()
        parts = full.split()
        aliases = [parts[-1]] if len(parts) > 1 else []
        return full, aliases
    # Fallback male lead fields if present
    for key in ("male_lead", "antagonist", "architect"):
        block = concept.get(key)
        if isinstance(block, dict) and block.get("name"):
            name = str(block["name"]).strip()
            return name, [name.split()[-1]] if " " in name else []
        if isinstance(block, str) and block.strip():
            name = block.strip()
            return name, [name.split()[-1]] if " " in name else []
    return "", []


def reveal_chapter_from_concept(concept: dict[str, Any]) -> int:
    binding = concept.get("binding_condition") or {}
    try:
        return int(binding.get("reveal_chapter") or 0)
    except (TypeError, ValueError):
        return 0
