"""Narrative OS — profile requirements + lightweight validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PROFILE_REQUIRED: dict[str, list[str]] = {
    "sweet_romance": ["kernel.json", "book_arc.json"],
    "romance_thriller": [
        "kernel.json",
        "book_arc.json",
        "threads.json",
        "mystery_ledger.json",
        "knowledge_matrix.json",
    ],
    "thriller": [
        "kernel.json",
        "book_arc.json",
        "threads.json",
        "mystery_ledger.json",
        "knowledge_matrix.json",
    ],
    "conspiracy_thriller": [
        "kernel.json",
        "book_arc.json",
        "threads.json",
        "mystery_ledger.json",
        "knowledge_matrix.json",
        "conspiracy.json",
    ],
    "gothic_psychological_horror": [
        "kernel.json",
        "book_arc.json",
        "threads.json",
        "mystery_ledger.json",
        "knowledge_matrix.json",
    ],
    "progression_fantasy": ["kernel.json", "book_arc.json", "power_system.json"],
    "dark_romance": ["kernel.json", "book_arc.json", "threads.json"],
}


def narrative_dir(ws: Path) -> Path:
    return ws / "bible" / "narrative"


def clue_plant_chapter(clue: dict[str, Any]) -> int:
    """Canonical clue plant chapter with legacy generator-alias support."""
    return int(
        clue.get("plant_chapter")
        or clue.get("chapter_planted")
        or clue.get("planted_chapter")
        or 0
    )


def clue_payoff_chapter(clue: dict[str, Any]) -> int:
    """Canonical clue payoff chapter with legacy generator-alias support."""
    return int(
        clue.get("payoff_chapter")
        or clue.get("chapter_payoff")
        or 0
    )


def normalize_mystery_ledger_schedule(ledger: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM clue schedule aliases at the generation boundary."""
    clues = ledger.get("clues")
    if not isinstance(clues, list):
        return ledger
    for clue in clues:
        if not isinstance(clue, dict):
            continue
        plant = clue_plant_chapter(clue)
        payoff = clue_payoff_chapter(clue)
        if plant:
            clue["plant_chapter"] = plant
        if payoff:
            clue["payoff_chapter"] = payoff
        clue.pop("chapter_planted", None)
        clue.pop("planted_chapter", None)
        clue.pop("chapter_payoff", None)
    return ledger


def reveal_schedule_fidelity_errors(
    ledger: dict[str, Any],
    required_schedule: list[dict[str, Any]],
) -> list[str]:
    """Require semantic schedule refs without depending on generated MR IDs."""
    required: dict[str, int] = {}
    for item in required_schedule:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "").strip()
        try:
            chapter = int(item.get("chapter") or 0)
        except (TypeError, ValueError):
            chapter = 0
        if ref and chapter > 0:
            required[ref] = chapter
    if not required:
        return []

    covered: dict[str, list[tuple[str, int]]] = {}
    errors: list[str] = []
    for reveal in ledger.get("major_reveals") or []:
        if not isinstance(reveal, dict):
            continue
        rid = str(reveal.get("id") or "?").strip()
        try:
            chapter = int(reveal.get("chapter") or 0)
        except (TypeError, ValueError):
            chapter = 0
        refs = reveal.get("schedule_refs") or []
        if not isinstance(refs, list):
            errors.append(f"mystery_ledger:schedule_refs_not_list:{rid}")
            continue
        for raw_ref in refs:
            ref = str(raw_ref).strip()
            if not ref:
                continue
            if ref not in required:
                errors.append(f"mystery_ledger:unknown_schedule_ref:{rid}:{ref}")
                continue
            covered.setdefault(ref, []).append((rid, chapter))
            expected = required[ref]
            if chapter != expected:
                errors.append(
                    "mystery_ledger:reveal_schedule_chapter_mismatch:"
                    f"{ref}:expected_ch{expected}:{rid}:ch{chapter}"
                )
    for ref, chapter in required.items():
        if ref not in covered:
            errors.append(
                f"mystery_ledger:required_reveal_missing:{ref}:ch{chapter}"
            )
    return errors


def project_required_reveal_semantics(
    ledger: dict[str, Any],
    required_schedule: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach canonical intent text to generated reveals by stable schedule ref."""
    requirements = {
        str(item.get("ref") or "").strip(): dict(item)
        for item in required_schedule
        if isinstance(item, dict) and str(item.get("ref") or "").strip()
    }
    for reveal in ledger.get("major_reveals") or []:
        if not isinstance(reveal, dict):
            continue
        refs = reveal.get("schedule_refs") or []
        if not isinstance(refs, list):
            continue
        reveal["required_semantics"] = [
            requirements[str(ref).strip()]
            for ref in refs
            if str(ref).strip() in requirements
        ]
    return ledger


def required_files(profile: str) -> list[str]:
    return list(PROFILE_REQUIRED.get(profile, PROFILE_REQUIRED["romance_thriller"]))


def narrative_is_approved(direction: dict | None) -> bool:
    if not direction:
        return False
    profile = (direction.get("narrative_profile") or "").strip()
    if not profile:
        return True
    return (direction.get("narrative_status") or "draft") == "approved"


def validate_narrative_assets(ws: Path, direction: dict) -> list[str]:
    errors: list[str] = []
    profile = (direction.get("narrative_profile") or "romance_thriller").strip()
    nd = narrative_dir(ws)
    for fname in required_files(profile):
        if not (nd / fname).exists():
            errors.append(f"missing:{fname}")

    book_arc_path = nd / "book_arc.json"
    if book_arc_path.exists():
        import json

        from factory.engine.lib.book_config import get_total_chapters

        arc = json.loads(book_arc_path.read_text(encoding="utf-8"))
        book = int(direction.get("book") or 1)
        expected = get_total_chapters(ws.name, book)
        actual = int(arc.get("total_chapters") or 0)
        if actual != expected:
            errors.append(
                f"book_arc:total_chapters_mismatch (có {actual}, cần {expected} — Lưu số chương hoặc chạy develop-narrative lại)"
            )

    kernel_path = nd / "kernel.json"
    if kernel_path.exists():
        import json

        k = json.loads(kernel_path.read_text(encoding="utf-8"))
        for key in ("surface_case", "true_case", "core_question", "book1_promise"):
            if not str(k.get(key, "")).strip():
                errors.append(f"kernel:empty:{key}")

    ledger_path = nd / "mystery_ledger.json"
    if ledger_path.exists():
        import json

        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        intent_path = ws / "books" / str(int(direction.get("book") or 1)).zfill(2) / "intent_manifest.json"
        if intent_path.exists():
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            errors.extend(
                reveal_schedule_fidelity_errors(
                    ledger,
                    list(intent.get("required_reveal_schedule") or []),
                )
            )
        clues = ledger.get("clues") or []
        seen: set[str] = set()
        clue_ids: set[str] = set()
        for c in clues:
            cid = c.get("id")
            if not cid:
                errors.append("mystery_ledger:clue_missing_id")
                continue
            cid = str(cid)
            if cid in seen:
                errors.append(f"mystery_ledger:duplicate_clue:{cid}")
            seen.add(cid)
            clue_ids.add(cid)
            plant = clue_plant_chapter(c)
            payoff = clue_payoff_chapter(c)
            if not plant:
                errors.append(
                    f"mystery_ledger:clue_missing_plant_chapter:{cid}"
                )
            if not payoff:
                errors.append(
                    f"mystery_ledger:clue_missing_payoff_chapter:{cid}"
                )
            if plant and payoff and payoff < plant:
                errors.append(f"mystery_ledger:payoff_before_plant:{cid}")

        reveal_ids: set[str] = set()
        reveal_chapters: dict[str, int] = {}
        for rev in ledger.get("major_reveals") or []:
            if not isinstance(rev, dict):
                continue
            rid = str(rev.get("id") or "").strip()
            if rid:
                reveal_ids.add(rid)
                reveal_chapters[rid] = int(rev.get("chapter") or 0)

        for rev in ledger.get("major_reveals") or []:
            if not isinstance(rev, dict):
                continue
            rid = str(rev.get("id") or "").strip() or "?"
            required = [str(x).strip() for x in (rev.get("required_clues") or []) if str(x).strip()]
            for cid in required:
                if cid in reveal_ids:
                    errors.append(
                        "mystery_ledger:required_clue_is_reveal:"
                        f"{rid}:{cid}:move_to_prerequisite_reveals"
                    )
                elif cid not in clue_ids:
                    errors.append(f"mystery_ledger:required_clue_unknown:{rid}:{cid}")
            prerequisites = [
                str(x).strip()
                for x in (rev.get("prerequisite_reveals") or [])
                if str(x).strip()
            ]
            current_chapter = reveal_chapters.get(rid, 0)
            for prerequisite_id in prerequisites:
                if prerequisite_id == rid:
                    errors.append(
                        f"mystery_ledger:prerequisite_reveal_self:{rid}:{prerequisite_id}"
                    )
                elif prerequisite_id not in reveal_ids:
                    errors.append(
                        "mystery_ledger:prerequisite_reveal_unknown:"
                        f"{rid}:{prerequisite_id}"
                    )
                else:
                    prerequisite_chapter = reveal_chapters.get(prerequisite_id, 0)
                    if (
                        current_chapter
                        and prerequisite_chapter
                        and prerequisite_chapter >= current_chapter
                    ):
                        errors.append(
                            "mystery_ledger:prerequisite_reveal_not_earlier:"
                            f"{rid}:ch{current_chapter}:{prerequisite_id}:"
                            f"ch{prerequisite_chapter}"
                        )

    threads_path = nd / "threads.json"
    if threads_path.exists():
        import json

        data = json.loads(threads_path.read_text(encoding="utf-8"))
        tids: set[str] = set()
        for t in data.get("threads") or []:
            tid = t.get("id")
            if not tid:
                errors.append("threads:missing_id")
            elif tid in tids:
                errors.append(f"threads:duplicate:{tid}")
            else:
                tids.add(tid)

    return errors


def load_concept(ws: Path) -> dict[str, Any]:
    import yaml

    path = ws / "concept.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


# Top-level concept keys the UI form owns. Anything not listed must survive a
# load → save round-trip untouched (hand-edited YAML is authoritative).
CONCEPT_TEXT_FIELDS = (
    "title",
    "logline",
    "author_directive",
    "surface_plot",
    "true_plot",
    "ending_book1",
    "hook_book2",
    "notes",
)
CONCEPT_LIST_FIELDS = ("must_include", "must_avoid")
CONCEPT_BOOL_FIELDS = ("intentional_early_reveal",)


def normalize_concept_characters(raw: Any) -> list[dict[str, str]]:
    """Normalize concept.characters to ``[{name, role}]`` (empty name dropped)."""
    out: list[dict[str, str]] = []
    if raw is None:
        return out
    if isinstance(raw, str):
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        raw = lines
    if not isinstance(raw, list):
        return out
    for item in raw:
        name = ""
        role = ""
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            role = str(item.get("role") or item.get("relation_type") or "").strip()
        elif item is not None:
            line = str(item).strip().lstrip("-•* ").strip()
            if not line:
                continue
            if "—" in line:
                name, role = [p.strip() for p in line.split("—", 1)]
            elif " - " in line:
                name, role = [p.strip() for p in line.split(" - ", 1)]
            elif ":" in line:
                # Prefer ``Name: role`` when left side looks like a person name.
                left, right = [p.strip() for p in line.split(":", 1)]
                if re.match(r"^[A-ZÀ-ÖØ-Þ]", left) and " " in left:
                    name, role = left, right
                else:
                    # ``role: Name — desc`` (LOCKED CAST style)
                    m = re.match(
                        r"^([^:]+):\s*([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
                        r"(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){0,2})",
                        line,
                    )
                    if m:
                        role, name = m.group(1).strip(), m.group(2).strip()
                    else:
                        name = line
            else:
                name = line
        if not name:
            continue
        out.append({"name": name, "role": role})
    # Dedupe by normalized name, keep first role.
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in out:
        key = re.sub(r"\s+", " ", row["name"]).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


_ANON_PLOT_ROLE_PATTERNS: tuple[tuple[re.Pattern[str], str, tuple[str, ...]], ...] = (
    (
        re.compile(
            r"\b(?:a|an)\s+(?:young\s+)?(?:woman|girl)\b|"
            r"\bcold[-\s]?case\s+(?:murder|victim)\s+of\s+(?:a|an)\s+",
            re.I,
        ),
        "victim/cold-case",
        ("victim", "cold-case", "cold case", "woman", "girl", "murder"),
    ),
    (
        re.compile(
            r"\b(?:a|an|the)\s+(?:killer|murderer)\b(?!\s+walked)|"
            r"\bher\s+killer\b|"
            r"\borigin\s+killer\b",
            re.I,
        ),
        "killer/origin-killer",
        ("killer", "murderer", "origin", "first kill"),
    ),
)


def concept_unnamed_plot_role_errors(concept: dict) -> list[str]:
    """Hard errors only: structured cast rows with role but empty name.

    Anonymous prose roles (``a young woman``) are surfaced as WARN via
    ``warn_unnamed_plot_roles`` — too many legacy books use ``the victim``
    after already naming them in LOCKED CAST.
    """
    errors: list[str] = []
    raw = concept.get("characters")
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            name = str(item.get("name") or "").strip()
            if role and not name:
                errors.append(
                    f"concept:characters[{i}]:role_without_name:{role} — "
                    "điền name hoặc xóa hàng; vai trống buộc Outliner bịa."
                )
    return errors


def warn_unnamed_plot_roles(concept: dict) -> list[str]:
    """WARN when plot text uses anonymous people and cast has no covering name."""
    from factory.engine.lib.catalog import safe_print

    cast = normalize_concept_characters(concept.get("characters"))
    directive = str(concept.get("author_directive") or "")
    for m in re.finditer(
        r"^\s*[-*]\s+([^:\n]{1,80}):\s*"
        r"([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
        r"(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){1,2})",
        directive,
        re.M,
    ):
        cast.append({"role": m.group(1).strip(), "name": m.group(2).strip()})

    blob = "\n".join(
        [
            str(concept.get("surface_plot") or ""),
            str(concept.get("true_plot") or ""),
            str(concept.get("logline") or ""),
        ]
    )
    chapter_map = concept.get("chapter_map")
    if isinstance(chapter_map, dict):
        for entry in chapter_map.values():
            if isinstance(entry, dict):
                blob += "\n" + str(entry.get("beat") or "")
            else:
                blob += "\n" + str(entry or "")
    elif isinstance(chapter_map, str):
        blob += "\n" + chapter_map

    warnings: list[str] = []
    for pat, label, role_keys in _ANON_PLOT_ROLE_PATTERNS:
        if not pat.search(blob):
            continue
        covered = False
        for row in cast:
            hay = f"{row.get('name', '')} {row.get('role', '')}".lower()
            if any(k in hay for k in role_keys) and str(row.get("name") or "").strip():
                if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", row["name"]):
                    covered = True
                    break
        if not covered:
            msg = (
                f"concept:unnamed_plot_role:{label} — "
                "khai tên FIXED trong Cast (UI) hoặc LOCKED CAST "
                "(vd. COLD-CASE VICTIM: Elise Marchetti). "
                "Để trống vai = Outliner bịa tên."
            )
            warnings.append(msg)
            safe_print(f"  [cast WARN] {msg}")
    return warnings


def coerce_concept_bool(value: Any) -> bool:
    """YAML/JSON/form truthiness for boolean concept flags."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def intentional_early_reveal(
    ws: Path | None = None,
    concept: dict[str, Any] | None = None,
) -> bool:
    """True when concept opts into intentional early reader-knowledge (anti-hero).

    Softens only reader-facing reveal cadence at approve-plan (BLOCK → WARN).
    It never relaxes writer-prompt confidentiality. Default / absent = False.
    """
    if concept is None:
        if ws is None:
            return False
        concept = load_concept(ws)
    return coerce_concept_bool(concept.get("intentional_early_reveal"))


PLACEHOLDER_MARKERS = (
    "ĐIỀN CHỈ ĐẠO",
    "điền chỉ đạo",
    "YOUR STORY",
    "(điền",
    "TODO:",
    "FIXME",
)

MIN_DIRECTIVE_CHARS = 120


def concept_directive_text(concept: dict) -> str:
    parts: list[str] = []
    if concept.get("author_directive"):
        parts.append(str(concept["author_directive"]).strip())
    for key in (
        "surface_plot",
        "surface_mystery",
        "true_plot",
        "ending_book1",
        "hook_book2",
        "logline",
        "final_supernatural_residue",
    ):
        val = concept.get(key)
        if val and str(val).strip() and str(val).strip() not in ('""', "''"):
            parts.append(str(val).strip())
    return "\n".join(parts)


def concept_intent_lock_errors(concept: dict) -> list[str]:
    """Fields compile-intent requires — also enforced at concept ready so UI/CLI match."""
    from factory.engine.lib.intent_manifest import (
        _infer_pov,
        _normalize_structured_chapter_map,
        _parse_chapter_map_from_directive,
    )

    errors: list[str] = []
    directive = str(concept.get("author_directive") or "")
    chapter_map = _normalize_structured_chapter_map(concept.get("chapter_map"))
    if not chapter_map:
        chapter_map = _parse_chapter_map_from_directive(directive)
    if not chapter_map:
        errors.append(
            "concept:chapter_map_missing — điền Chapter map (Ch1:/Ch2:…) trên form Concept"
        )
    if not _infer_pov(concept, directive):
        errors.append(
            "concept:pov_missing — chọn POV trên form Concept (nhân vật + ngôi) hoặc ghi POV: trong chỉ đạo"
        )
    return errors


# --- G0b: concept map ↔ directive/plot fidelity (deterministic, no LLM) --------

_MAPFID_WORD_RE = re.compile(r"[a-zA-Zà-ỹÀ-Ỹ0-9']{4,}")
_MAPFID_STOP = {
    "that", "this", "with", "from", "into", "about", "when", "what", "their", "them",
    "than", "only", "just", "more", "some", "very", "also", "does", "have", "been",
    "will", "they", "then", "over", "before", "after", "again", "each", "both",
    "which", "where", "while", "would", "could", "should", "these", "those", "there",
    "here", "must", "make", "made", "finds", "find", "first", "last",
    "chapter", "reader", "story",
}
# A/B hard motif patterns: strong signal a whole plot family diverged from the lock.
_MAPFID_HARD = (
    re.compile(r"subject\s*\d+", re.I),
    re.compile(r"\bexperiment", re.I),
    re.compile(r"\bcollection\b", re.I),
)
_MAPFID_SUBJECT = re.compile(r"subject\s*\d+", re.I)
_MAPFID_TIER = re.compile(
    r"TIER\s*\d+\s*\(ch\s*(\d+)\s*[-–]\s*(\d+)\)\s*[:—-]?\s*(.+?)(?=TIER\s*\d|\Z)",
    re.I | re.S,
)
# Role placeholders / non-name capitalized words that are never proper-noun drift.
_MAPFID_ROLE_STOP = {
    "the", "she", "her", "his", "him", "they", "wife", "husband", "housekeeper",
    "narrator", "reader", "chapter", "tier", "subject", "book", "act", "part",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # common sentence-starter / function words that get capitalized mid-text
    "at", "it", "no", "on", "that", "then", "than", "this", "these", "those",
    "while", "when", "where", "what", "you", "your", "and", "but", "for", "nor",
    "afterward", "afterwards", "ending", "before", "after", "as", "if", "in",
    "of", "to", "by", "an", "a", "or", "so", "yet", "now", "here", "there",
    "meanwhile", "later", "finally", "inside", "outside", "above", "below",
}
_MAPFID_E_THR = 0.12          # E: both-way coverage floor
_MAPFID_F_THR = 0.10          # F: per-TIER-band coverage floor
_MAPFID_F_MIN_BANDS = 2       # F: how many bands must fail to BLOCK


def _mapfid_tokens(text: str) -> set[str]:
    return {
        w.lower()
        for w in _MAPFID_WORD_RE.findall(text or "")
        if w.lower() not in _MAPFID_STOP
    }


def _mapfid_token_list(text: str) -> list[str]:
    return [
        w.lower()
        for w in _MAPFID_WORD_RE.findall(text or "")
        if w.lower() not in _MAPFID_STOP
    ]


def _mapfid_coverage(required: str, haystack: str) -> float:
    req = _mapfid_tokens(required)
    if not req:
        return 1.0
    have = _mapfid_tokens(haystack)
    if not have:
        return 0.0
    return len(req & have) / max(1, len(req))


def _mapfid_lock_text(concept: dict) -> str:
    parts: list[str] = []
    for k in ("author_directive", "surface_plot", "true_plot", "ending_book1", "logline"):
        v = concept.get(k)
        if v:
            parts.append(str(v))
    for k in ("must_include", "must_avoid"):
        v = concept.get(k)
        if isinstance(v, list):
            parts.append(" ".join(str(x) for x in v))
        elif v:
            parts.append(str(v))
    return "\n".join(parts)


def _mapfid_map_text(chapter_map: dict) -> str:
    parts: list[str] = []
    for ch in sorted(chapter_map):
        entry = chapter_map[ch]
        parts.append(str(entry.get("beat") or ""))
        mh = entry.get("must_happen") or []
        if isinstance(mh, list):
            parts.append(" ".join(str(x) for x in mh))
    return "\n".join(parts)


def _mapfid_signals(concept: dict) -> dict:
    """Compute deterministic divergence signals for chapter_map vs directive/plot."""
    from factory.engine.lib.intent_manifest import (
        _infer_cast,
        _normalize_structured_chapter_map,
        _parse_chapter_map_from_directive,
    )

    directive = str(concept.get("author_directive") or "")
    chapter_map = _normalize_structured_chapter_map(concept.get("chapter_map"))
    if not chapter_map:
        chapter_map = _parse_chapter_map_from_directive(directive)
    if not chapter_map:
        return {"skip": True}

    lock = _mapfid_lock_text(concept)
    mapt = _mapfid_map_text(chapter_map)
    lock_tokens = _mapfid_tokens(lock)

    # A — hard motif patterns repeated in MAP but absent from LOCK.
    a_hits: list[str] = []
    for pat in _MAPFID_HARD:
        if len(pat.findall(mapt)) >= 2 and not pat.findall(lock):
            a_hits.append(pat.pattern)

    # B — Subject N appears in MAP, not in LOCK, not declared in cast.
    subj_map = sorted({s.strip() for s in _MAPFID_SUBJECT.findall(mapt)})
    subj_lock = _MAPFID_SUBJECT.findall(lock)
    cast_lower = {n.lower() for n in _infer_cast(concept, directive)}
    subj_in_cast = any(s.lower() in cast_lower for s in subj_map)
    b_flag = bool(subj_map) and not subj_lock and not subj_in_cast

    # E — two-way rare-token coverage between MAP and LOCK.
    lock_list = _mapfid_token_list(lock)
    map_list = _mapfid_token_list(mapt)
    lock_rare = " ".join({t for t in lock_list if lock_list.count(t) >= 2})
    map_rare = " ".join({t for t in map_list if map_list.count(t) >= 2})
    r1 = _mapfid_coverage(lock_rare, mapt)  # lock motifs found in map
    r2 = _mapfid_coverage(map_rare, lock)   # map motifs found in lock
    e_flag = bool(lock_rare) and bool(map_rare) and r1 < _MAPFID_E_THR and r2 < _MAPFID_E_THR

    # F — per-TIER-band coverage (only when directive declares TIER (ch a-b) bands).
    bands: list[tuple[str, float]] = []
    for lo_s, hi_s, desc in _MAPFID_TIER.findall(directive):
        lo, hi = int(lo_s), int(hi_s)
        band_map = "\n".join(
            str(chapter_map[c].get("beat") or "") for c in chapter_map if lo <= c <= hi
        )
        bands.append((f"ch{lo}-{hi}", round(_mapfid_coverage(desc, band_map), 3)))
    band_fail = [b for b in bands if b[1] < _MAPFID_F_THR]
    f_flag = len(band_fail) >= _MAPFID_F_MIN_BANDS

    # WARN-only: proper nouns in MAP absent from cast and lock.
    # Keep it low-noise: strip function words, then keep either multi-word names
    # (Clara Higgins) or single names that recur (>=2 occurrences).
    proper_counts: dict[str, int] = {}
    for m in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", mapt):
        toks = [t for t in m.split() if t.lower() not in _MAPFID_ROLE_STOP]
        if not toks:
            continue
        cand = " ".join(toks)
        cl = cand.lower()
        if cl in cast_lower or cl in lock_tokens:
            continue
        if all(t.lower() in lock_tokens for t in toks):
            continue
        proper_counts[cand] = proper_counts.get(cand, 0) + 1
    proper = sorted(
        {
            c
            for c, n in proper_counts.items()
            if " " in c or n >= 2
        }
    )[:12]

    # WARN-only: rare divergent map tokens (>=3 occurrences, absent from lock).
    map_counts: dict[str, int] = {}
    for t in map_list:
        map_counts[t] = map_counts.get(t, 0) + 1
    rare_divergent = sorted(
        [t for t, c in map_counts.items() if c >= 3 and t not in lock_tokens],
        key=lambda x: -map_counts[x],
    )[:12]

    cast_sparse = len(cast_lower) == 0 and len(proper) >= 2

    return {
        "skip": False,
        "A": a_hits,
        "B": subj_map if b_flag else [],
        "E": (round(r1, 3), round(r2, 3)) if e_flag else None,
        "E_raw": (round(r1, 3), round(r2, 3)),
        "F": band_fail if f_flag else [],
        "F_raw": bands,
        "warn_proper": proper,
        "warn_rare": rare_divergent,
        "warn_cast_sparse": cast_sparse,
    }


def concept_map_fidelity_errors(concept: dict) -> list[str]:
    """G0b — BLOCK when chapter_map plot family contradicts author_directive/true_plot.

    Deterministic (no LLM). BLOCK signals: A (hard motif ≥2 ∉ lock), B (Subject N ∉
    cast), E (two-way rare-token coverage below floor), F (≥2 TIER bands below floor).
    Everything else is WARN (printed, non-fatal). Escape hatch:
    ``concept.gate_overrides: [map_fidelity]`` downgrades BLOCK→WARN with a loud line.
    """
    from factory.engine.lib.catalog import safe_print

    sig = _mapfid_signals(concept)
    if sig.get("skip"):
        return []

    block: list[str] = []
    if sig["A"]:
        block.append("concept:map_fidelity:A_hard_motif:" + ",".join(sig["A"]))
    if sig["B"]:
        block.append("concept:map_fidelity:B_subject_not_in_cast:" + ",".join(sig["B"]))
    if sig["E"]:
        block.append(
            f"concept:map_fidelity:E_two_way_divergence:r1={sig['E'][0]},r2={sig['E'][1]}"
        )
    if sig["F"]:
        bands = ",".join(f"{name}={cov}" for name, cov in sig["F"])
        block.append(f"concept:map_fidelity:F_tier_band_mismatch:{bands}")

    # WARN — always surfaced, never fatal.
    if sig["warn_proper"]:
        safe_print(
            "  [map_fidelity WARN] proper nouns in chapter_map not in cast/directive: "
            + ", ".join(sig["warn_proper"])
        )
    if not sig["A"] and sig["warn_rare"]:
        safe_print(
            "  [map_fidelity WARN] motif tokens in map absent from directive/plot: "
            + ", ".join(sig["warn_rare"])
        )
    if sig["warn_cast_sparse"]:
        safe_print(
            "  [map_fidelity WARN] cast not declared — proper nouns appear only in map; "
            "consider filling concept.characters"
        )

    if not block:
        return []

    overrides = concept.get("gate_overrides") or []
    if isinstance(overrides, str):
        overrides = [overrides]
    if "map_fidelity" in {str(o).strip() for o in overrides}:
        safe_print("⚠ GATE BYPASSED: map_fidelity divergence allowed by operator")
        for b in block:
            safe_print(f"  [map_fidelity WARN-bypassed] {b}")
        return []
    return block


def concept_content_errors(concept: dict) -> list[str]:
    errors: list[str] = []
    if not concept:
        errors.append("concept:missing_file")
        return errors

    directive = concept_directive_text(concept)
    if not directive:
        errors.append("concept:author_directive_trống — điền concept.yaml hoặc chạy concept --interview")
        return errors

    for marker in PLACEHOLDER_MARKERS:
        if marker in directive:
            errors.append(f"concept:author_directive_còn_placeholder ({marker})")
            break

    if len(directive) < MIN_DIRECTIVE_CHARS:
        errors.append(
            f"concept:author_directive_quá_ngắn ({len(directive)} ký tự, cần ≥{MIN_DIRECTIVE_CHARS})"
        )

    errors.extend(concept_intent_lock_errors(concept))
    errors.extend(concept_unnamed_plot_role_errors(concept))
    warn_unnamed_plot_roles(concept)
    errors.extend(concept_map_fidelity_errors(concept))
    return errors


def concept_validation_errors(concept: dict) -> list[str]:
    errors = concept_content_errors(concept)
    if errors:
        return errors
    status = (concept.get("concept_status") or "draft").strip().lower()
    if status != "ready":
        errors.append(
            'concept:concept_status chưa "ready" — sau khi điền xong chạy: concept --ready'
        )
    return errors


def concept_is_ready(concept: dict) -> bool:
    return len(concept_validation_errors(concept)) == 0
