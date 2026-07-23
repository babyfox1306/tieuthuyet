"""Deterministic concept satisfiability — coded errors, no LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConceptValidationError:
    code: str
    path: str
    message: str

    def format(self) -> str:
        return f"{self.code}: {self.message}"


_TOUCH_PATTERNS = (
    re.compile(r"every\s+chapter\s+that\s+touches\s+the\s+clause", re.I),
    re.compile(r"stated\s+identically\s+in\s+every\s+chapter\s+that\s+touches", re.I),
    re.compile(r"touches\s+the\s+clause", re.I),
)


def _as_dict(val: Any) -> dict[str, Any] | None:
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    return None


def _has_pair_side(concept: dict, key: str) -> bool:
    d = _as_dict(concept.get(key))
    if not d:
        return False
    # empty dict counts as absent
    return any(str(v).strip() for v in d.values() if v is not None)


def _norm_phrase(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _creative_blobs(concept: dict) -> list[tuple[str, str]]:
    """Story blobs scanned for flat forbidden_phrases.

    ``author_directive`` is excluded (same rationale as ``must_avoid``): operators
    routinely list bans there (\"NO Vance / NO Rook\"). Those tokens belong in
    ``forbidden_phrases`` for chapter locks — mentioning them as instructions must
    not block develop-narrative.
    """
    out: list[tuple[str, str]] = []
    for key in ("logline", "surface_plot", "true_plot"):
        val = concept.get(key)
        if val and str(val).strip():
            out.append((key, str(val)))
    return out


def _must_include_blob(concept: dict) -> str:
    items = concept.get("must_include") or []
    if isinstance(items, list):
        return "\n".join(str(x) for x in items)
    return str(items or "")


def concept_satisfiability_errors(concept: dict) -> list[ConceptValidationError]:
    """Return coded satisfiability failures. Empty = OK."""
    if not concept:
        return []

    errors: list[ConceptValidationError] = []
    has_surface = _has_pair_side(concept, "surface_order")
    has_binding = _has_pair_side(concept, "binding_condition")

    if has_surface ^ has_binding:
        missing = "binding_condition" if has_surface else "surface_order"
        present = "surface_order" if has_surface else "binding_condition"
        errors.append(
            ConceptValidationError(
                code="SAT_PAIR_INCOMPLETE",
                path=missing,
                message=f"{present} exists without {missing}",
            )
        )
        return errors  # further pair checks need both sides

    if not (has_surface and has_binding):
        # optional schema unused — still scan forbidden_phrases if present
        errors.extend(_forbidden_phrase_errors(concept))
        return errors

    surface = _as_dict(concept.get("surface_order")) or {}
    binding = _as_dict(concept.get("binding_condition")) or {}

    s_eid = str(surface.get("event_id") or "").strip()
    b_eid = str(binding.get("event_id") or "").strip()
    if not s_eid or not b_eid:
        errors.append(
            ConceptValidationError(
                code="SAT_EVENT_ID_MISMATCH",
                path="surface_order.event_id" if not s_eid else "binding_condition.event_id",
                message="both surface_order and binding_condition require non-empty event_id",
            )
        )
    elif s_eid != b_eid:
        errors.append(
            ConceptValidationError(
                code="SAT_EVENT_ID_MISMATCH",
                path="binding_condition.event_id",
                message=f"event_id mismatch: surface={s_eid!r} binding={b_eid!r}",
            )
        )

    try:
        visible = int(surface.get("visible_from_chapter") or 0)
    except (TypeError, ValueError):
        visible = 0
    try:
        reveal = int(binding.get("reveal_chapter") or 0)
    except (TypeError, ValueError):
        reveal = 0

    if visible < 1:
        errors.append(
            ConceptValidationError(
                code="SAT_INVALID_REVEAL_WINDOW",
                path="surface_order.visible_from_chapter",
                message="visible_from_chapter must be >= 1",
            )
        )
    if reveal < 1:
        errors.append(
            ConceptValidationError(
                code="SAT_INVALID_REVEAL_WINDOW",
                path="binding_condition.reveal_chapter",
                message="reveal_chapter must be >= 1",
            )
        )
    elif visible >= 1 and reveal < visible:
        errors.append(
            ConceptValidationError(
                code="SAT_INVALID_REVEAL_WINDOW",
                path="binding_condition.reveal_chapter",
                message=f"reveal_chapter ({reveal}) must be >= visible_from_chapter ({visible})",
            )
        )

    if not str(surface.get("exact_text") or "").strip():
        errors.append(
            ConceptValidationError(
                code="SAT_PAIR_INCOMPLETE",
                path="surface_order.exact_text",
                message="surface_order.exact_text is required",
            )
        )
    if not str(binding.get("canonical_text") or "").strip():
        errors.append(
            ConceptValidationError(
                code="SAT_PAIR_INCOMPLETE",
                path="binding_condition.canonical_text",
                message="binding_condition.canonical_text is required",
            )
        )

    # Ambiguous touch rules forbidden when pair exists
    touch_blobs = [
        ("author_directive", str(concept.get("author_directive") or "")),
        ("must_include", _must_include_blob(concept)),
    ]
    for path, blob in touch_blobs:
        for pat in _TOUCH_PATTERNS:
            if pat.search(blob):
                errors.append(
                    ConceptValidationError(
                        code="SAT_AMBIGUOUS_TOUCH_RULE",
                        path=path,
                        message=f"{path} contains forbidden ambiguous wording matching {pat.pattern!r}",
                    )
                )
                break

    errors.extend(_forbidden_phrase_errors(concept))
    return errors


def _all_flat_forbidden_phrases(concept: dict) -> list[str]:
    """Forever-banned phrases only (forbidden_phrases).

    Staged gate phrases live in forbidden_phrase_gates and are allowed in concept
    creative blobs — they become chapter locks via compile_chapter_canon_rules.
    """
    phrases = concept.get("forbidden_phrases") or []
    if not isinstance(phrases, list):
        return []
    return [str(p).strip() for p in phrases if str(p).strip()]


def _forbidden_phrase_gate_errors(concept: dict) -> list[ConceptValidationError]:
    gates = concept.get("forbidden_phrase_gates")
    if gates is None:
        return []
    errors: list[ConceptValidationError] = []
    if not isinstance(gates, list):
        errors.append(
            ConceptValidationError(
                code="SAT_GATE_INVALID",
                path="forbidden_phrase_gates",
                message="forbidden_phrase_gates must be a list",
            )
        )
        return errors
    for i, gate in enumerate(gates):
        path = f"forbidden_phrase_gates[{i}]"
        if not isinstance(gate, dict):
            errors.append(
                ConceptValidationError(
                    code="SAT_GATE_INVALID",
                    path=path,
                    message="each gate must be a mapping",
                )
            )
            continue
        try:
            unlock = int(gate.get("unlock_chapter") or 0)
        except (TypeError, ValueError):
            unlock = 0
        if unlock < 1:
            errors.append(
                ConceptValidationError(
                    code="SAT_GATE_INVALID",
                    path=f"{path}.unlock_chapter",
                    message="unlock_chapter must be >= 1",
                )
            )
        phrases = gate.get("phrases")
        if not isinstance(phrases, list) or not any(str(p).strip() for p in phrases):
            errors.append(
                ConceptValidationError(
                    code="SAT_GATE_INVALID",
                    path=f"{path}.phrases",
                    message="phrases must be a non-empty list",
                )
            )
    return errors


def _forbidden_phrase_errors(concept: dict) -> list[ConceptValidationError]:
    errors = _forbidden_phrase_gate_errors(concept)
    phrases = _all_flat_forbidden_phrases(concept)
    if not phrases:
        return errors
    norms = [(str(p), _norm_phrase(str(p))) for p in phrases]
    code_by_key = {
        "logline": "SAT_FORBIDDEN_PHRASE_IN_LOGLINE",
        "surface_plot": "SAT_FORBIDDEN_PHRASE_IN_SURFACE_PLOT",
        "true_plot": "SAT_FORBIDDEN_PHRASE_IN_TRUE_PLOT",
    }
    for key, text in _creative_blobs(concept):
        hay = _norm_phrase(text)
        for raw, needle in norms:
            if needle and needle in hay:
                errors.append(
                    ConceptValidationError(
                        code=code_by_key[key],
                        path=key,
                        message=f"{raw!r} appears in {key}",
                    )
                )
    return errors


def format_satisfiability_errors(errors: list[ConceptValidationError]) -> list[str]:
    return [e.format() for e in errors]
