"""Narrative OS — profile requirements + lightweight validation."""

from __future__ import annotations

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
            plant = int(c.get("plant_chapter") or 0)
            payoff = int(c.get("payoff_chapter") or 0)
            if plant and payoff and payoff < plant:
                errors.append(f"mystery_ledger:payoff_before_plant:{cid}")

        reveal_ids: set[str] = set()
        for rev in ledger.get("major_reveals") or []:
            if not isinstance(rev, dict):
                continue
            rid = str(rev.get("id") or "").strip()
            if rid:
                reveal_ids.add(rid)

        for rev in ledger.get("major_reveals") or []:
            if not isinstance(rev, dict):
                continue
            rid = str(rev.get("id") or "").strip() or "?"
            required = [str(x).strip() for x in (rev.get("required_clues") or []) if str(x).strip()]
            for cid in required:
                if cid in reveal_ids:
                    errors.append(f"mystery_ledger:required_clue_is_reveal:{rid}:{cid}")
                elif cid not in clue_ids:
                    errors.append(f"mystery_ledger:required_clue_unknown:{rid}:{cid}")

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
    for key in ("surface_plot", "true_plot", "ending_book1", "hook_book2", "logline"):
        val = concept.get(key)
        if val and str(val).strip() and str(val).strip() not in ('""', "''"):
            parts.append(str(val).strip())
    return "\n".join(parts)


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
