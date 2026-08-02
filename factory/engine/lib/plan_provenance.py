"""Plan provenance gate — Outliner proposals cannot become canon without sources."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from factory.engine.lib.canonical_ir import (
    allowed_claim_blob,
    entity_names,
    load_canonical_ir,
    sha256_obj,
)
from factory.engine.lib.canon_artifacts import (
    artifact_path,
    is_sealed,
    make_seal,
    write_json,
)
from factory.engine.lib.plan_hard_gates import hard_gate_plan_against_ir

PLAN_TEXT_FIELDS = (
    "title",
    "one_line_summary",
    "beat_summary",
    "opens_with",
    "cliffhanger",
    "chapter_task",
    "signature_detail_hint",
    "carries_to_next",
    "spice_note",
)

# Specificity that must be generalized when not in IR.
_SPECIFICITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(?:EDTA|K2EDTA|K3EDTA)\b|"
            r"\b\d+(?:\.\d+)?\s*(?:µg|ug|micrograms?)\s*/\s*ml\b|"
            r"\b\d+(?:\.\d+)?\s*ml\s+K?2?EDTA\b",
            re.I,
        ),
        "anticoagulant treatment",
    ),
    (
        re.compile(r"\bDr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"),
        "a clinician",
    ),
    (
        re.compile(r"\bSuite\s+\d+\b", re.I),
        "an office suite",
    ),
]

_MOTIVE_SWAP_RE = re.compile(
    r"\b(?:worthy\s+partner|test(?:ing)?\s+whether\s+.+\s+partner|"
    r"partnership\s+he\s+had\s+already\s+decided|"
    r"orchestrated\s+the\s+entire\s+confrontation\s+to\s+test)\b",
    re.I,
)

_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def extract_plan_claims(plan: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    ch = int(plan.get("chapter") or 0)

    def _add(field: str, text: str, index: int | None = None) -> None:
        text = str(text or "").strip()
        if not text:
            return
        claims.append(
            {
                "claim_id": f"CH{ch}-{field}"
                + (f"-{index}" if index is not None else ""),
                "field": field,
                "claim": text,
                "chapter": ch,
            }
        )

    for field in PLAN_TEXT_FIELDS:
        _add(field, str(plan.get(field) or ""))

    for i, item in enumerate(plan.get("must_happen") or []):
        _add("must_happen", str(item), i)
    for i, item in enumerate(plan.get("must_not") or []):
        _add("must_not", str(item), i)

    return claims


def _claim_supported(claim: str, allow_blob: str, allowed_entities: set[str]) -> bool:
    text = claim.casefold()
    # Direct substring overlap with IR corpus (conservative but practical).
    words = [w for w in re.findall(r"[a-z0-9']{4,}", text) if w not in _STOP]
    if not words:
        return True  # pure texture / short
    hits = sum(1 for w in words if w in allow_blob)
    if hits / max(1, len(words)) >= 0.45:
        return True
    # Entity-only mentions of allowed cast are fine.
    for match in _PROPER_NOUN_RE.finditer(claim):
        name = match.group(1)
        if name not in allowed_entities and name.split()[0] not in {
            e.split()[0] for e in allowed_entities
        }:
            # Check if full name appears in allow blob
            if name.casefold() not in allow_blob:
                return False
    return hits >= 3


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
        "must",
        "does",
        "not",
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
        "into",
        "over",
        "under",
    }
)


def generalize_claim(text: str) -> tuple[str, list[str]]:
    """Replace unsourced specificity with safer wording. Returns (text, notes)."""
    notes: list[str] = []
    out = text
    for pattern, replacement in _SPECIFICITY_PATTERNS:
        if pattern.search(out):
            out = pattern.sub(replacement, out)
            notes.append(f"generalized->{replacement}")
    return out, notes


def validate_plan_against_ir(
    plan: dict[str, Any],
    ir: dict[str, Any],
) -> dict[str, Any]:
    """Return gate result with repaired plan text and unverified claims."""
    chapter = int(plan.get("chapter") or 0)
    allow_blob = allowed_claim_blob(ir, max(chapter, 1))
    # Include future-locked true_plot only for STOP motive checks, not writer allow.
    true_plot = str((ir.get("plots") or {}).get("true_plot") or "")
    allowed_entities = entity_names(ir)

    repaired = deepcopy(plan)
    unverified: list[dict[str, Any]] = []
    warnings: list[str] = []
    generalizations = 0

    def _check_text(field: str, text: str) -> str:
        nonlocal generalizations
        original = str(text or "")

        # Proper-noun / address checks run on the ORIGINAL text so generalization
        # cannot launder unsourced named doctors into a sealed plan.
        for match in _PROPER_NOUN_RE.finditer(original):
            name = match.group(1)
            if name in allowed_entities:
                continue
            if name.casefold() in allow_blob:
                continue
            if first_token_ok(name):
                continue
            if name.startswith("Chapter ") or name in {"Zero Day", "Zero-Day Server"}:
                continue
            unverified.append(
                {
                    "field": field,
                    "claim": name,
                    "reason": "unsourced_proper_noun",
                    "authority": "LLM_PROPOSAL",
                }
            )

        generalized, notes = generalize_claim(original)
        if notes:
            generalizations += 1
            warnings.extend(f"{field}: {n}" for n in notes)
            # Named clinician specificity that was generalized still blocks —
            # CE did not lock a doctor identity.
            if any("clinician" in n for n in notes):
                unverified.append(
                    {
                        "field": field,
                        "claim": original[:240],
                        "reason": "unsourced_proper_noun",
                        "authority": "LLM_PROPOSAL",
                    }
                )

        # Motive swap vs true plot goals
        if _MOTIVE_SWAP_RE.search(generalized):
            if "partner" in generalized.casefold() and "zero-day" in true_plot.casefold():
                # If IR true goal is server access, partner-test is STOP
                if "server" in true_plot.casefold() or "archive" in true_plot.casefold():
                    unverified.append(
                        {
                            "field": field,
                            "claim": generalized,
                            "reason": "motive_swap_vs_true_plot",
                            "authority": "LLM_PROPOSAL",
                        }
                    )
                    return generalized

        if not _claim_supported(generalized, allow_blob, allowed_entities):
            # High-impact markers only — don't block every creative sentence
            if re.search(
                r"\b(?:server|archive|murder|alibi|backdoor|anticoagulant|"
                r"hired|commissioned|password|biometric|smartwatch)\b",
                generalized,
                re.I,
            ):
                # If still unsupported after generalize, flag but allow if mostly IR words
                words = re.findall(r"[a-z0-9']{4,}", generalized.casefold())
                hits = sum(1 for w in words if w in allow_blob)
                if words and hits / len(words) < 0.30:
                    unverified.append(
                        {
                            "field": field,
                            "claim": generalized[:240],
                            "reason": "unsourced_canon_claim",
                            "authority": "LLM_PROPOSAL",
                        }
                    )
        return generalized

    def first_token_ok(name: str) -> bool:
        first = name.split()[0]
        if first in {"The", "Chapter", "Day", "Zero", "Crisis", "Mutual"}:
            return True
        if any(first == e.split()[0] and len(e.split()) == 1 for e in allowed_entities):
            return True
        return False

    for field in PLAN_TEXT_FIELDS:
        if field in repaired:
            repaired[field] = _check_text(field, str(repaired.get(field) or ""))

    if isinstance(repaired.get("must_happen"), list):
        repaired["must_happen"] = [
            _check_text(f"must_happen[{i}]", str(item))
            for i, item in enumerate(repaired["must_happen"])
        ]
    if isinstance(repaired.get("must_not"), list):
        repaired["must_not"] = [
            _check_text(f"must_not[{i}]", str(item))
            for i, item in enumerate(repaired["must_not"])
        ]

    # Deduplicate unverified by claim
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for row in unverified:
        key = f"{row.get('reason')}:{row.get('claim')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)

    blockers = [
        u
        for u in uniq
        if u.get("reason")
        in {
            "motive_swap_vs_true_plot",
            "unsourced_proper_noun",
            "unsourced_canon_claim",
        }
    ]

    # Hard structural gates — unmapped claims are UNRESOLVED and never seal.
    hard = hard_gate_plan_against_ir(repaired, ir)
    for row in hard:
        key = f"{row.get('reason')}:{row.get('claim')}"
        if key in seen:
            continue
        seen.add(key)
        blockers.append(row)

    status = "sealed" if not blockers else "blocked"
    return {
        "status": status,
        "repaired_plan": repaired,
        "unverified_claims": blockers,
        "warnings": warnings,
        "generalizations": generalizations,
        "claims_extracted": extract_plan_claims(plan),
    }


def seal_chapter_plan(
    ws,
    book: int,
    plan: dict[str, Any],
    *,
    ir: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate proposal, write artifacts, return approval payload."""
    from pathlib import Path

    ws = Path(ws)
    ir = ir or load_canonical_ir(ws)
    if not ir:
        raise RuntimeError("canonical IR missing — run ingest first")

    chapter = int(plan.get("chapter") or 0)
    proposal_path = artifact_path(ws, book, chapter, "plan_proposal.json")
    approval_path = artifact_path(ws, book, chapter, "plan.approval.json")

    write_json(proposal_path, plan)
    result = validate_plan_against_ir(plan, ir)
    repaired = result["repaired_plan"]
    write_json(artifact_path(ws, book, chapter, "plan.repaired.json"), repaired)

    approval = make_seal(
        status=result["status"],
        source_ir_hash=str(ir.get("ir_digest") or ""),
        artifact_hash=sha256_obj(repaired),
        validators={
            "provenance_gate": "pass" if result["status"] == "sealed" else "fail",
            "specificity_generalize": "pass",
        },
        unverified_claims=result["unverified_claims"],
        warnings=result["warnings"],
        extra={
            "chapter": chapter,
            "generalizations": result["generalizations"],
        },
    )
    write_json(approval_path, approval)
    return {
        "approval": approval,
        "repaired_plan": repaired,
        "sealed": is_sealed(approval),
        "result": result,
    }
