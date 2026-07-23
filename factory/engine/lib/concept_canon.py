"""Single chapter-canon compiler + concept/narrative digests for stale detection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.concept_satisfiability import ConceptValidationError


@dataclass
class ChapterCanonRules:
    allowed_exact_quotes: list[str] = field(default_factory=list)
    forbidden_facts: list[str] = field(default_factory=list)
    required_exact_wording: list[str] = field(default_factory=list)
    reveal_state: str = "none"  # none | surface_only | binding_revealed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DIGEST_FIELDS = (
    "title",
    "logline",
    "author_directive",
    "surface_plot",
    "true_plot",
    "must_include",
    "must_avoid",
    "ending_book1",
    "hook_book2",
    "surface_order",
    "binding_condition",
    "forbidden_phrases",
    "forbidden_phrase_gates",
    "concept_schema_version",
    "target_language",
)

NARRATIVE_DIGEST_FILES = (
    "kernel.json",
    "book_arc.json",
    "threads.json",
    "mystery_ledger.json",
    "knowledge_matrix.json",
    "chapter_canon_gates.json",
    "conspiracy.json",
)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def concept_digest(concept: dict) -> str:
    """Stable hash of story-affecting concept fields (excludes notes/status)."""
    payload = {k: concept.get(k) for k in DIGEST_FIELDS}
    raw = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def narrative_dir(ws: Path) -> Path:
    return ws / "bible" / "narrative"


def narrative_meta_path(ws: Path) -> Path:
    return narrative_dir(ws) / "_meta.json"


def narrative_digest(ws: Path) -> str | None:
    """Hash of narrative JSON assets. None if no narrative files yet."""
    nd = narrative_dir(ws)
    if not nd.exists():
        return None
    parts: dict[str, Any] = {}
    found = False
    for fname in NARRATIVE_DIGEST_FILES:
        p = nd / fname
        if p.exists():
            found = True
            try:
                parts[fname] = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                parts[fname] = p.read_text(encoding="utf-8")
    if not found:
        return None
    return hashlib.sha256(_canonical_json(parts).encode("utf-8")).hexdigest()[:16]


def write_narrative_meta(ws: Path, *, source_concept_digest: str) -> Path:
    path = narrative_meta_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source_concept_digest": source_concept_digest,
        "narrative_digest": narrative_digest(ws),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def sync_chapter_canon_gates(ws: Path, *, concept: dict | None = None) -> Path:
    """Emit machine-readable chapter gates from concept into narrative/.

    Writer prompts already compile live via compile_chapter_canon_rules(concept, ch).
    This file makes the same ladder visible to operators / plan / QC without
    opening concept.yaml — so staged unlocks are a mechanism, not prose notes.
    """
    from factory.engine.lib.narrative_schema import load_concept

    concept = concept if concept is not None else load_concept(ws)
    path = narrative_dir(ws) / "chapter_canon_gates.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    surface = concept.get("surface_order") if isinstance(concept.get("surface_order"), dict) else {}
    binding = concept.get("binding_condition") if isinstance(concept.get("binding_condition"), dict) else {}
    gates_raw = concept.get("forbidden_phrase_gates") or []
    gates_out: list[dict[str, Any]] = []
    if isinstance(gates_raw, list):
        for gate in gates_raw:
            if not isinstance(gate, dict):
                continue
            try:
                unlock = int(gate.get("unlock_chapter") or 0)
            except (TypeError, ValueError):
                unlock = 0
            phrases = [str(p).strip() for p in (gate.get("phrases") or []) if str(p).strip()]
            if unlock < 1 or not phrases:
                continue
            gates_out.append(
                {
                    "id": str(gate.get("id") or "").strip() or f"unlock_{unlock}",
                    "unlock_chapter": unlock,
                    "phrases": phrases,
                }
            )

    payload = {
        "source": "concept.yaml",
        "compiled_by": "sync_chapter_canon_gates",
        "enforcement": (
            "forbidden_phrase_gates.unlock_chapter applies to EVERY chapter number "
            "strictly less than unlock_chapter via compile_chapter_canon_rules(concept, ch) "
            "at write/prompt time. per_chapter_preview is an operator sample only — "
            "missing a preview entry does NOT mean that chapter is ungated."
        ),
        "surface_order": {
            "event_id": str(surface.get("event_id") or "").strip(),
            "exact_text": str(surface.get("exact_text") or "").strip(),
            "visible_from_chapter": int(surface.get("visible_from_chapter") or 0)
            if str(surface.get("visible_from_chapter") or "").strip()
            else 0,
        },
        "binding_condition": {
            "event_id": str(binding.get("event_id") or "").strip(),
            "canonical_text": str(binding.get("canonical_text") or "").strip(),
            "reveal_chapter": int(binding.get("reveal_chapter") or 0)
            if str(binding.get("reveal_chapter") or "").strip()
            else 0,
            "exact_wording_required_when_explicitly_stated": bool(
                binding.get("exact_wording_required_when_explicitly_stated", True)
            ),
        },
        "forbidden_phrases_forever": [
            str(p).strip()
            for p in (concept.get("forbidden_phrases") or [])
            if str(p).strip()
        ],
        "forbidden_phrase_gates": gates_out,
        "per_chapter_preview": {},
    }
    # Sample unlock, unlock-1, binding reveal, and ch1 — never treat as the full set.
    preview_chapters: set[int] = {1}
    for g in gates_out:
        unlock = int(g["unlock_chapter"])
        preview_chapters.add(unlock)
        if unlock > 1:
            preview_chapters.add(unlock - 1)
    reveal = int(binding.get("reveal_chapter") or 0)
    if reveal >= 1:
        preview_chapters.add(reveal)
        if reveal > 1:
            preview_chapters.add(reveal - 1)
    payload["per_chapter_preview"] = {
        str(ch): compile_chapter_canon_rules(concept, ch).to_dict()
        for ch in sorted(preview_chapters)
        if ch >= 1
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_narrative_meta(ws: Path) -> dict[str, Any]:
    path = narrative_meta_path(ws)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _pair_present(concept: dict) -> bool:
    s = concept.get("surface_order")
    b = concept.get("binding_condition")
    return isinstance(s, dict) and isinstance(b, dict) and bool(s) and bool(b)


def _gated_forbidden_phrases(concept: dict, chapter_number: int) -> list[str]:
    """Phrases still locked at this chapter from forbidden_phrase_gates.

    Each gate: {id?, unlock_chapter: int, phrases: [str, ...]}.
    Phrase is forbidden while chapter_number < unlock_chapter.
    Distinct clusters may unlock on different chapters (e.g. Renn+fast-track @19
    vs Renn+override/burial @20) — not a single name switch.
    """
    gates = concept.get("forbidden_phrase_gates") or []
    if not isinstance(gates, list):
        return []
    ch = int(chapter_number)
    out: list[str] = []
    seen: set[str] = set()
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        try:
            unlock = int(gate.get("unlock_chapter") or 0)
        except (TypeError, ValueError):
            unlock = 0
        if unlock < 1 or ch >= unlock:
            continue
        phrases = gate.get("phrases") or []
        if not isinstance(phrases, list):
            continue
        for raw in phrases:
            p = str(raw or "").strip()
            if not p or p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


def compile_chapter_canon_rules(concept: dict, chapter_number: int) -> ChapterCanonRules:
    """Sole chapter-gate compiler — writer prompts and QC must consume this."""
    ch = int(chapter_number)
    gated = _gated_forbidden_phrases(concept, ch)

    if not _pair_present(concept):
        if not gated:
            return ChapterCanonRules()
        return ChapterCanonRules(
            allowed_exact_quotes=[],
            forbidden_facts=gated,
            required_exact_wording=[],
            reveal_state="surface_only",
        )

    surface = concept.get("surface_order") or {}
    binding = concept.get("binding_condition") or {}
    exact = str(surface.get("exact_text") or "").strip()
    canonical = str(binding.get("canonical_text") or "").strip()
    try:
        reveal = int(binding.get("reveal_chapter") or 0)
    except (TypeError, ValueError):
        reveal = 0

    allowed = [exact] if exact else []
    if ch < reveal or reveal < 1:
        forbidden = [canonical] if canonical else []
        # Also ban the distinctive Rook trigger fragment as a fact
        if "restores the" in canonical.lower() or "obedient identity" in canonical.lower():
            forbidden.append("Rook restores the obedient identity")
        for p in gated:
            if p not in forbidden:
                forbidden.append(p)
        return ChapterCanonRules(
            allowed_exact_quotes=allowed,
            forbidden_facts=forbidden,
            required_exact_wording=[],
            reveal_state="surface_only",
        )

    # binding revealed: canonical listed only for when explicitly stating binding
    # — NOT required on every sunrise mention
    required: list[str] = []
    if canonical and binding.get("exact_wording_required_when_explicitly_stated", True):
        required = [canonical]
    return ChapterCanonRules(
        allowed_exact_quotes=allowed,
        forbidden_facts=list(gated),  # residual gates unlocking after binding reveal
        required_exact_wording=required,
        reveal_state="binding_revealed",
    )


def format_chapter_canon_for_prompt(rules: ChapterCanonRules, *, lang: str = "en") -> str:
    if rules.reveal_state == "none":
        return ""
    if lang == "vi":
        lines = ["## Luật clause theo chương (HARD — từ concept compiler)"]
        lines.append(f"Trạng thái reveal: {rules.reveal_state}")
        if rules.allowed_exact_quotes:
            lines.append("Được trích dẫn đúng chữ:")
            for q in rules.allowed_exact_quotes:
                lines.append(f"- {q}")
        if rules.forbidden_facts:
            lines.append("CẤM nêu / diễn giải (chưa tới chương reveal):")
            for f in rules.forbidden_facts:
                lines.append(f"- {f}")
        if rules.required_exact_wording:
            lines.append(
                "Khi (và chỉ khi) nêu RÕ binding condition, phải dùng đúng chữ — "
                "KHÔNG bắt buộc nhắc lại mỗi lần nói tới sunrise:"
            )
            for w in rules.required_exact_wording:
                lines.append(f"- {w}")
        return "\n".join(lines)

    lines = ["## Chapter clause rules (HARD — from concept compiler)"]
    lines.append(f"Reveal state: {rules.reveal_state}")
    if rules.allowed_exact_quotes:
        lines.append("Allowed exact quotes:")
        for q in rules.allowed_exact_quotes:
            lines.append(f"- {q}")
    if rules.forbidden_facts:
        lines.append("FORBIDDEN to state or paraphrase (binding not yet revealed):")
        for f in rules.forbidden_facts:
            lines.append(f"- {f}")
    if rules.required_exact_wording:
        lines.append(
            "When (and only when) explicitly stating the binding condition, use exact wording — "
            "do NOT require restating it on every sunrise mention:"
        )
        for w in rules.required_exact_wording:
            lines.append(f"- {w}")
    return "\n".join(lines)


def artifact_stale_errors(ws: Path, concept: dict | None = None) -> list[ConceptValidationError]:
    """STALE_* errors when narrative/plan digests diverge from current concept.

    Legacy workspaces without surface/binding pair and without schema v2 are not
    forced to regenerate — only mismatch after digests exist, or schema-v2/pair
    workspaces missing digests.
    """
    from factory.engine.lib.narrative_schema import load_concept

    concept = concept if concept is not None else load_concept(ws)
    if not concept:
        return []

    errors: list[ConceptValidationError] = []
    current = concept_digest(concept)
    meta = load_narrative_meta(ws)
    narr_files_exist = any(
        (narrative_dir(ws) / f).exists() for f in NARRATIVE_DIGEST_FILES
    )
    try:
        schema_ver = int(concept.get("concept_schema_version") or 0)
    except (TypeError, ValueError):
        schema_ver = 0
    requires_digest = _pair_present(concept) or schema_ver >= 2

    if narr_files_exist:
        stored = str(meta.get("source_concept_digest") or "").strip()
        if requires_digest and not stored:
            errors.append(
                ConceptValidationError(
                    code="STALE_NARRATIVE_VS_CONCEPT",
                    path="bible/narrative/_meta.json",
                    message="narrative exists but source_concept_digest missing — regenerate develop-narrative",
                )
            )
        elif stored and stored != current:
            errors.append(
                ConceptValidationError(
                    code="STALE_NARRATIVE_VS_CONCEPT",
                    path="bible/narrative/_meta.json",
                    message=f"concept digest {current} != narrative source {stored} — regenerate develop-narrative",
                )
            )

    from factory.engine.lib.prompt_builder import load_direction
    from factory.engine.paths import book_workspace_dir

    direction = load_direction(ws)
    book = int(direction.get("book") or 1)
    plan_path = book_workspace_dir(ws, book) / "master_plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            plan = {}
        if plan.get("chapter_plans"):
            p_concept = str(plan.get("source_concept_digest") or "").strip()
            p_narr = str(plan.get("source_narrative_digest") or "").strip()
            if requires_digest and not p_concept:
                errors.append(
                    ConceptValidationError(
                        code="STALE_PLAN_VS_CONCEPT",
                        path="master_plan.json",
                        message="plan missing source_concept_digest — replan after develop-narrative",
                    )
                )
            elif p_concept and p_concept != current:
                errors.append(
                    ConceptValidationError(
                        code="STALE_PLAN_VS_CONCEPT",
                        path="master_plan.json",
                        message=f"plan concept digest {p_concept} != current {current} — replan",
                    )
                )
            elif p_concept:
                live_narr = narrative_digest(ws)
                if live_narr and p_narr and p_narr != live_narr:
                    errors.append(
                        ConceptValidationError(
                            code="STALE_PLAN_VS_CONCEPT",
                            path="master_plan.json",
                            message=f"plan narrative digest {p_narr} != current {live_narr} — replan",
                        )
                    )
                elif requires_digest and live_narr and not p_narr:
                    errors.append(
                        ConceptValidationError(
                            code="STALE_PLAN_VS_CONCEPT",
                            path="master_plan.json",
                            message="plan missing source_narrative_digest — replan",
                        )
                    )
    return errors


def require_fresh_narrative(ws: Path) -> None:
    errs = [
        e
        for e in artifact_stale_errors(ws)
        if e.code == "STALE_NARRATIVE_VS_CONCEPT"
    ]
    if errs:
        raise RuntimeError("\n".join(e.format() for e in errs))


def require_fresh_plan(ws: Path) -> None:
    errs = artifact_stale_errors(ws)
    if errs:
        raise RuntimeError("\n".join(e.format() for e in errs))


def stamp_plan_digests(ws: Path, plan_data: dict) -> dict:
    from factory.engine.lib.narrative_schema import load_concept

    concept = load_concept(ws)
    plan_data["source_concept_digest"] = concept_digest(concept) if concept else ""
    plan_data["source_narrative_digest"] = narrative_digest(ws) or ""
    return plan_data


def sync_direction_digests(ws: Path) -> None:
    """Mirror digests onto direction.yaml for UI/pipeline_status."""
    from factory.engine.lib.narrative_schema import load_concept

    direction_path = ws / "direction.yaml"
    if not direction_path.exists():
        return
    data = yaml.safe_load(direction_path.read_text(encoding="utf-8")) or {}
    concept = load_concept(ws)
    data["source_concept_digest"] = concept_digest(concept) if concept else ""
    meta = load_narrative_meta(ws)
    data["source_narrative_digest"] = meta.get("narrative_digest") or narrative_digest(ws) or ""
    direction_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
