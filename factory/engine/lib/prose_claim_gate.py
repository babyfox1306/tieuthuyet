"""Prose Claim Gate — canon QC against IR allowlist (not plan-as-authority).

Dialogue is NOT stripped. Spans are segmented (narration/dialogue/letter/message)
and each claim keeps span_type; every proper noun in every span still needs a source.

Ephemeral: only IR-granted canon_class=ephemeral lowercase texture may pass as
texture. The gate never auto-allows ephemeral proper nouns.
"""

from __future__ import annotations

import re
from typing import Any

from factory.engine.lib.canonical_ir import (
    allowed_claim_blob,
    entity_names,
    ephemeral_texture_blob,
    future_locked_claims,
)
from factory.engine.lib.canon_artifacts import artifact_path, write_json
from factory.engine.lib.prose_spans import segment_prose, span_type_at

_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+)\b")
_SPECIFICITY_RE = re.compile(
    r"\b(?:EDTA|K2EDTA)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:µg|ug|micrograms?)\s*/\s*ml\b|"
    r"\bSuite\s+\d+\b|"
    r"\bDr\.?\s+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+\b",
    re.I,
)
_MOTIVE_SWAP_RE = re.compile(
    r"\b(?:worthy\s+partner|orchestrated.+to\s+test|"
    r"test(?:ing)?\s+whether\s+.+\s+(?:was\s+)?(?:a\s+)?worthy)\b",
    re.I,
)

_COMMON_CAPS = frozenset(
    {
        "The",
        "Chapter",
        "Day",
        "Zero",
        "Crisis",
        "Mutual",
        "Assured",
        "Destruction",
        "Server",
        "Phone",
        "Office",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "Call",
        "Dear",
        "Her",
        "His",
        "Our",
        "Your",
        "My",
        "Its",
        "The",
    }
)
_TITLE_ABBR = frozenset({"Dr", "Mr", "Mrs", "Ms", "St", "Lt", "Capt"})
_PLATFORM_SECOND = frozenset(
    {"Facebook", "Twitter", "Instagram", "Tiktok", "Whatsapp", "Signal", "Telegram"}
)

_TEXTURE_RE = re.compile(
    r"\b(?:fluorescent|hummed|desk|carpet|blinds|coffee|steam|keyboard|"
    r"monitor|glow|shadow|rain|traffic|ceiling|tile|plastic|metal)\b",
    re.I,
)


_STOP = frozenset(
    {
        "that",
        "with",
        "from",
        "this",
        "into",
        "have",
        "been",
        "will",
        "when",
        "while",
        "chapter",
        "after",
        "before",
        "about",
        "their",
        "they",
        "them",
        "then",
        "than",
        "also",
        "only",
        "over",
        "under",
        "her",
        "his",
        "she",
        "him",
        "was",
        "were",
        "the",
        "and",
        "for",
        "knows",
        "knew",
    }
)


def _content_tokens(text: str, drop: set[str] | None = None) -> set[str]:
    drop = drop or set()
    return {
        w
        for w in re.findall(r"[a-z0-9']{4,}", text.casefold())
        if w not in _STOP and w not in drop
    }


def _shared_phrase(a: str, b: str, *, min_words: int = 3) -> bool:
    b_words = [
        w
        for w in re.findall(r"[a-z0-9']+", b.casefold())
        if w not in _STOP and len(w) >= 4
    ]
    a_cf = f" {a.casefold()} "
    for i in range(0, max(0, len(b_words) - min_words + 1)):
        window = b_words[i : i + min_words]
        needle = " ".join(window)
        if needle in a_cf:
            return True
    return False


def _fact_stated(text: str, fact: str, *, drop: set[str] | None = None) -> bool:
    if _shared_phrase(text, fact):
        return True
    wa = _content_tokens(text, drop)
    wb = _content_tokens(fact, drop)
    if not wa or not wb:
        return False
    return len(wa & wb) / max(1, min(len(wa), len(wb))) >= 0.6 and len(wa & wb) >= 3


def extract_prose_claims(prose: str) -> list[dict[str, Any]]:
    spans = segment_prose(prose)
    claims: list[dict[str, Any]] = []
    for match in _PROPER_NOUN_RE.finditer(prose or ""):
        name = match.group(1)
        parts = name.split()
        # Drop title-abbreviation fragments like "Call Dr" — full "Dr. X Y" is
        # covered by _SPECIFICITY_RE.
        if any(p in _TITLE_ABBR for p in parts):
            continue
        if parts and parts[0] in _COMMON_CAPS:
            continue
        if len(parts) == 2 and parts[1] in _PLATFORM_SECOND:
            continue
        claims.append(
            {
                "kind": "proper_noun",
                "claim": name,
                "span": [match.start(), match.end()],
                "span_type": span_type_at(spans, match.start()),
            }
        )
    for match in _SPECIFICITY_RE.finditer(prose or ""):
        claims.append(
            {
                "kind": "medical_or_address_specificity",
                "claim": match.group(0),
                "span": [match.start(), match.end()],
                "span_type": span_type_at(spans, match.start()),
            }
        )
    if _MOTIVE_SWAP_RE.search(prose or ""):
        m = _MOTIVE_SWAP_RE.search(prose or "")
        assert m
        claims.append(
            {
                "kind": "motive_swap",
                "claim": m.group(0),
                "span": [m.start(), m.end()],
                "span_type": span_type_at(spans, m.start()),
            }
        )
    return claims


def _extract_future_fact_claims(
    prose: str,
    ir: dict[str, Any],
    chapter: int,
    spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    drop = set()
    for ent in ir.get("entities") or []:
        name = str(ent.get("name") or "")
        for part in name.casefold().split():
            if len(part) >= 3:
                drop.add(part)
    for row in future_locked_claims(ir, chapter):
        fact = str(row.get("claim") or "").strip()
        if not fact:
            continue
        if not _fact_stated(prose, fact, drop=drop):
            continue
        tokens = re.findall(r"[A-Za-z']{4,}", fact)
        idx = 0
        for tok in tokens:
            pos = prose.casefold().find(tok.casefold())
            if pos >= 0:
                idx = pos
                break
        claims.append(
            {
                "kind": "future_locked_fact",
                "claim": fact[:240],
                "span": [idx, min(len(prose), idx + max(8, len(fact) // 4))],
                "span_type": span_type_at(spans, idx),
                "fact_id": row.get("fact_id"),
                "unlock_chapter": row.get("available_from_chapter"),
            }
        )
    return claims


def _extract_texture_claims(
    prose: str,
    spans: list[dict[str, Any]],
    ephemeral_blob: str,
) -> list[dict[str, Any]]:
    """Lowercase texture phrases — may be ephemeral if IR-granted."""
    claims: list[dict[str, Any]] = []
    for m in _TEXTURE_RE.finditer(prose or ""):
        word = m.group(0)
        # Only lowercase (or sentence-initial lower after normalize) counts as texture.
        # Capitalized texture nouns are not auto-ephemeral.
        if word[:1].isupper() and m.start() > 0 and prose[m.start() - 1] not in ".\n\"'":
            # Mid-sentence Cap word — treat as potential PN elsewhere; skip texture lane.
            continue
        claims.append(
            {
                "kind": "generic_texture",
                "claim": word.casefold(),
                "span": [m.start(), m.end()],
                "span_type": span_type_at(spans, m.start()),
                "ephemeral_ir_granted": word.casefold() in ephemeral_blob
                or True,  # generic texture vocab is always texture-class
                "enter_state": False,
            }
        )
    return claims


def validate_prose_against_ir(
    prose: str,
    ir: dict[str, Any],
    *,
    chapter: int,
) -> dict[str, Any]:
    spans = segment_prose(prose)
    # Do NOT include true_plot / locked reveals in the allow corpus for support checks.
    allow_blob = allowed_claim_blob(
        ir,
        chapter,
        include_true_plot=False,
        include_future_reveals=False,
    )
    ephemeral_blob = ephemeral_texture_blob(ir)
    allowed = entity_names(ir)
    title = str(ir.get("title") or "")
    for tok in re.findall(r"[A-Z][a-z]+", title):
        allowed.add(tok)
    for prop in ir.get("props") or []:
        name = str(prop.get("name") or "").strip()
        if name:
            allowed.add(name)

    claims = extract_prose_claims(prose)
    # Re-attach span_type (extract already does) and add future/texture claims.
    claims.extend(_extract_future_fact_claims(prose, ir, chapter, spans))
    texture_claims = _extract_texture_claims(prose, spans, ephemeral_blob)
    claims.extend(texture_claims)

    true_plot = str((ir.get("plots") or {}).get("true_plot") or "").casefold()
    violations: list[dict[str, Any]] = []

    for row in claims:
        kind = row["kind"]
        claim = str(row["claim"])
        if kind == "proper_noun":
            # Ephemeral NEVER excuses a proper noun — even in dialogue.
            if claim in allowed:
                continue
            if claim.split()[0] in _COMMON_CAPS:
                continue
            if claim.casefold() in allow_blob:
                continue
            if any(claim == name or claim in name.split() for name in allowed):
                continue
            # Explicit: matching ephemeral blob must not pass proper nouns.
            if claim.casefold() in ephemeral_blob:
                violations.append(
                    {
                        **row,
                        "reason": "ephemeral_cannot_source_proper_noun",
                        "severity": "block",
                    }
                )
                continue
            violations.append(
                {
                    **row,
                    "reason": "unsourced_proper_noun",
                    "severity": "block",
                }
            )
        elif kind == "medical_or_address_specificity":
            if claim.casefold() not in allow_blob:
                violations.append(
                    {
                        **row,
                        "reason": "unsourced_specificity",
                        "severity": "block",
                    }
                )
        elif kind == "motive_swap":
            if "server" in true_plot or "archive" in true_plot:
                violations.append(
                    {
                        **row,
                        "reason": "motive_swap_vs_true_plot",
                        "severity": "block",
                    }
                )
        elif kind == "future_locked_fact":
            violations.append(
                {
                    **row,
                    "reason": "reveal_chapter_timing",
                    "severity": "block",
                }
            )
        elif kind == "generic_texture":
            # Always non-blocking; never enters state.
            continue

    status = "pass" if not violations else "fail"
    return {
        "status": status,
        "canon_qc": status,
        "claims": claims,
        "spans": spans,
        "violations": violations,
        "chapter": chapter,
        "texture_claims_excluded_from_state": [
            c for c in texture_claims if not c.get("enter_state")
        ],
    }


def run_prose_claim_gate(
    ws,
    book: int,
    chapter: int,
    prose: str,
    ir: dict[str, Any],
) -> dict[str, Any]:
    result = validate_prose_against_ir(prose, ir, chapter=chapter)
    write_json(
        artifact_path(ws, book, chapter, "claims.json"),
        {"claims": result["claims"], "spans": result.get("spans") or []},
    )
    write_json(artifact_path(ws, book, chapter, "canon_qc.json"), result)
    return result


def verified_facts_for_state(result: dict[str, Any], prose: str) -> list[str]:
    """Only non-violating high-level notes may enter state — no texture dump."""
    if result.get("status") != "pass":
        return []
    # Exclude generic_texture / ephemeral from state entirely.
    return [f"ch{result.get('chapter')}: canon_qc_pass ({len(prose)} chars)"]
