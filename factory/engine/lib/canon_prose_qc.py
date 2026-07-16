"""Deterministic canon prose checks — shared by machine_qc and canon_guard."""

from __future__ import annotations

import re
from typing import Any

from factory.engine.lib.canon_registry import CanonRegistry, LEAD_ROLES

POV_FIRST_PERSON_THRESHOLD = 3

_FIRST_PERSON_OUTSIDE_RE = re.compile(
    r"\b(I|I'm|I've|I'll|I'd|my|me|myself)\b",
    re.IGNORECASE,
)

# Typographic / guillemet / low-9 quotes → ASCII before any quote-span regex.
_TYPOGRAPHIC_DOUBLE = str.maketrans(
    {
        "\u201c": '"',  # “ LEFT DOUBLE
        "\u201d": '"',  # ” RIGHT DOUBLE
        "\u201e": '"',  # „ DOUBLE LOW-9
        "\u201f": '"',  # ‟ DOUBLE HIGH-REVERSED-9
        "\u00ab": '"',  # « LEFT GUILLEMET
        "\u00bb": '"',  # » RIGHT GUILLEMET
        "\u2039": "'",  # ‹ SINGLE LEFT GUILLEMET (rare)
        "\u203a": "'",  # › SINGLE RIGHT GUILLEMET
        "\u2018": "'",  # ‘ LEFT SINGLE
        "\u2019": "'",  # ’ RIGHT SINGLE / apostrophe
        "\u201a": "'",  # ‚ SINGLE LOW-9
        "\u201b": "'",  # ‛ SINGLE HIGH-REVERSED-9
    }
)


def normalize_typographic_quotes(text: str) -> str:
    """Map curly/guillemet quotes to straight ASCII so quote regexes match once."""
    if not text:
        return text
    return text.translate(_TYPOGRAPHIC_DOUBLE)


def strip_dialogue_for_pov(text: str) -> str:
    """Remove quoted dialogue spans before scanning for first-person narration."""
    body = normalize_typographic_quotes(text)
    body = re.sub(r"^#.*$", "", body, flags=re.M)
    body = re.sub(r'"[^"\n]*"', " ", body)
    body = re.sub(r"'[^'\n]*'", " ", body)
    return body


def count_first_person_outside_dialogue(text: str) -> int:
    prose = strip_dialogue_for_pov(text)
    return len(_FIRST_PERSON_OUTSIDE_RE.findall(prose))


def is_third_person_limited(registry: CanonRegistry) -> bool:
    mode = str(registry.pov_mode or "").strip().lower().replace("-", "_")
    return mode in ("third_person_limited", "third_person", "3rd_person_limited")


def find_name_drift_hits(text: str, registry: CanonRegistry) -> list[dict[str, str]]:
    """Forbidden lead alias occurrences in prose."""
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    lower = text.lower()
    for role in LEAD_ROLES:
        char = registry.characters[role]
        canonical = char.canonical
        for alias in sorted(char.forbidden_aliases, key=len, reverse=True):
            a = alias.strip()
            if not a or char.is_allowed(a):
                continue
            if " " in a:
                pat = re.compile(re.escape(a), re.IGNORECASE)
            else:
                pat = re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
            if pat.search(lower):
                key = (role, a.lower())
                if key not in seen:
                    seen.add(key)
                    hits.append(
                        {
                            "role": role,
                            "found": a,
                            "canonical": canonical,
                        }
                    )
    return hits


def canon_prose_issues(text: str, registry: CanonRegistry) -> dict[str, Any]:
    """Aggregate canon prose violations for machine_qc.

    Spice/content boundaries are NOT keyword-scanned here — they are enforced
    by injecting concept must_avoid / spice_max into the writer LOCKED CANON
    block at generation time. Keyword lists cannot tell "floorboards groaned"
    from an intimate scene.
    """
    issues: dict[str, Any] = {}
    drift = find_name_drift_hits(text, registry)
    if drift:
        issues["name_drift"] = drift
    if is_third_person_limited(registry):
        fp_count = count_first_person_outside_dialogue(text)
        if fp_count >= POV_FIRST_PERSON_THRESHOLD:
            issues["pov_violation"] = {
                "count": fp_count,
                "threshold": POV_FIRST_PERSON_THRESHOLD,
            }
    return issues
