"""develop-narrative — sinh bible/narrative/* từ concept.yaml + 9router."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from factory.engine.lib.call_9router import call_9router, parse_json_response
from factory.engine.lib.narrative_schema import (
    concept_is_ready,
    load_concept,
    narrative_dir,
    normalize_mystery_ledger_schedule,
)
from factory.engine.lib.book_config import get_total_chapters, sync_book_arc_total_chapters
from factory.engine.lib.prompt_builder import load_direction, load_series_bible
from factory.engine.paths import workspace_dir

PASSES = ("kernel", "book_arc", "threads", "mystery_ledger", "knowledge_matrix")
PASS_TO_FILE = {
    "kernel": "kernel.json",
    "book_arc": "book_arc.json",
    "threads": "threads.json",
    "mystery_ledger": "mystery_ledger.json",
    "knowledge_matrix": "knowledge_matrix.json",
}
PASS_DEPS = {
    "kernel": [],
    "book_arc": ["kernel"],
    "threads": ["kernel"],
    "mystery_ledger": ["kernel", "threads"],
    "knowledge_matrix": ["kernel", "mystery_ledger", "threads"],
}

MAX_TOKENS = {
    "kernel": 4096,
    "book_arc": 4096,
    "threads": 6144,
    "mystery_ledger": 12288,
    "knowledge_matrix": 8192,
}

OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "kernel": {
        "required_fields": [
            "narrative_profile",
            "target_language",
            "title_working",
            "surface_case",
            "true_case",
            "core_question",
            "emotional_question",
            "book1_promise",
            "case_closed",
            "series_door_opened",
            "book2_hook",
            "book1_ending_type",
            "reader_payoff_book1",
        ]
    },
    "book_arc": {
        "required_fields": [
            "book_number",
            "total_chapters",
            "target_language",
            "case_closed",
            "case_open",
            "lead_internal_arc",
            "act_structure",
        ]
    },
    "threads": {
        "required_fields": ["description", "threads"],
        "thread_fields": [
            "id",
            "name",
            "opened_chapter",
            "status",
            "book1_resolution",
            "book2_promise",
        ],
    },
    "mystery_ledger": {
        "required_fields": [
            "main_mystery",
            "truth",
            "canonical_reveal_chapter",
            "red_herrings",
            "major_reveals",
            "clues",
        ],
        "clue": {
            "id": "C-prefix only, e.g. C001",
            "fields": [
                "id",
                "plant_chapter",
                "payoff_chapter",
                "description",
                "type",
                "noticed_by",
            ],
        },
        "major_reveal": {
            "id": "MR-prefix only, e.g. MR01",
            "fields": [
                "id",
                "chapter",
                "description",
                "required_clues",
                "prerequisite_reveals",
                "schedule_refs",
            ],
            "required_clues": "List of clue IDs only (C-prefix). Never put MR IDs here.",
            "prerequisite_reveals": (
                "List of earlier major-reveal IDs only (MR-prefix). Use this when "
                "a later reveal depends on earlier reveals having occurred."
            ),
            "schedule_refs": (
                "List of required_reveal_schedule refs covered by this reveal. "
                "Every ref must be covered at exactly its locked chapter."
            ),
        },
    },
    "knowledge_matrix": {
        "required_fields": [
            "description",
            "target_language",
            "milestones",
            "characters",
        ]
    },
}


def _author_directive(concept: dict) -> str:
    parts: list[str] = []
    if concept.get("title"):
        parts.append(f"Tiêu đề: {concept['title']}")
    if concept.get("logline"):
        parts.append(f"Logline: {concept['logline']}")
    if concept.get("author_directive"):
        parts.append(str(concept["author_directive"]).strip())
    for key in ("surface_plot", "true_plot", "must_include", "must_avoid", "ending_book1", "hook_book2"):
        val = concept.get(key)
        if val:
            if isinstance(val, list):
                parts.append(f"{key}:\n- " + "\n- ".join(str(x) for x in val))
            else:
                parts.append(f"{key}: {val}")
    return "\n\n".join(parts) if parts else "(chưa có chỉ đạo — điền concept.yaml)"


def _load_prior(nd: Path, deps: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dep in deps:
        fname = PASS_TO_FILE.get(dep)
        if not fname:
            continue
        p = nd / fname
        if p.exists():
            out[dep] = json.loads(p.read_text(encoding="utf-8"))
    return out


def _set_narrative_draft(ws: Path) -> None:
    dir_path = ws / "direction.yaml"
    if not dir_path.exists():
        return
    data = yaml.safe_load(dir_path.read_text(encoding="utf-8")) or {}
    data["narrative_status"] = "draft"
    dir_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def develop_pass(ws: Path, pass_name: str) -> Path:
    if pass_name not in PASS_TO_FILE:
        raise ValueError(f"Unknown pass: {pass_name}")

    direction = load_direction(ws)
    concept = load_concept(ws)
    nd = narrative_dir(ws)
    nd.mkdir(parents=True, exist_ok=True)

    bible: dict = {}
    try:
        bible = load_series_bible(ws)
    except FileNotFoundError:
        pass

    prior = _load_prior(nd, PASS_DEPS.get(pass_name, []))
    from factory.engine.lib.intent_manifest import (
        infer_canonical_reveal_chapter,
        load_intent_manifest,
    )

    intent = load_intent_manifest(ws, int(direction.get("book") or 1))
    canonical_reveal = intent.get("canonical_reveal_chapter")
    if canonical_reveal is None:
        canonical_reveal = infer_canonical_reveal_chapter(concept)
    book = int(direction.get("book") or 1)
    total_chapters = get_total_chapters(ws.name, book)
    payload = {
        "pass": pass_name,
        "author_directive": _author_directive(concept),
        "direction": direction,
        "book": book,
        "total_chapters": total_chapters,
        "prior_narrative": prior,
        "series_bible": bible if bible else None,
        "output_schema": OUTPUT_SCHEMAS[pass_name],
        "output_file": PASS_TO_FILE[pass_name],
        "intent_reveal_policy": {
            "canonical_reveal_chapter": canonical_reveal,
            "authority": "concept/approved intent; derived narrative must match",
        },
    }
    if pass_name == "mystery_ledger":
        payload["required_reveal_schedule"] = list(
            intent.get("required_reveal_schedule") or []
        )

    raw, log = call_9router(
        "narrative_developer",
        json.dumps(payload, ensure_ascii=False),
        max_tokens=MAX_TOKENS.get(pass_name, 8192),
        direction=direction,
    )
    data = parse_json_response(raw)
    if isinstance(data, dict):
        from factory.engine.lib.chapter_derivation import normalize_narrative_pass

        if pass_name == "mystery_ledger":
            data = normalize_mystery_ledger_schedule(data)
            from factory.engine.lib.narrative_schema import (
                project_required_reveal_semantics,
                reveal_schedule_fidelity_errors,
            )

            required_schedule = list(intent.get("required_reveal_schedule") or [])
            fidelity_errors = reveal_schedule_fidelity_errors(
                data,
                required_schedule,
            )
            if fidelity_errors:
                raise ValueError("; ".join(fidelity_errors))
            data = project_required_reveal_semantics(data, required_schedule)
        data = normalize_narrative_pass(pass_name, data, total_chapters, book)
        if pass_name == "mystery_ledger" and canonical_reveal is not None:
            data["canonical_reveal_chapter"] = int(canonical_reveal)
    if pass_name == "book_arc" and isinstance(data, dict):
        data["total_chapters"] = total_chapters
        data["book_number"] = book
    out = nd / PASS_TO_FILE[pass_name]
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sync_book_arc_total_chapters(ws, book, total_chapters)
    if pass_name == "kernel":
        from factory.engine.lib.workspace_metadata import sync_narrative_profile_to_direction

        sync_narrative_profile_to_direction(ws)
    # Catch invented doctors before they poison plan/state.
    from factory.engine.lib.canon_registry import find_invented_doctors, collect_allowed_cast_names
    from factory.engine.lib.catalog import safe_print

    invented = find_invented_doctors(
        json.dumps(data, ensure_ascii=False),
        collect_allowed_cast_names(ws, book),
    )
    if invented:
        safe_print(
            f"  narrative/{PASS_TO_FILE[pass_name]} CANON WARN — invented doctors: "
            + ", ".join(invented)
            + " (must match concept/bible cast; do not propagate)"
        )
    _set_narrative_draft(ws)
    return out


def develop_narrative(workspace_id: str, *, pass_name: str = "all") -> list[Path]:
    ws = workspace_dir(workspace_id)
    concept_path = ws / "concept.yaml"
    if not concept_path.exists():
        raise FileNotFoundError(
            f"Thiếu {concept_path} — chạy: concept --init hoặc concept --interview"
        )
    concept = load_concept(ws)
    if not concept_is_ready(concept):
        from factory.engine.lib.narrative_schema import concept_validation_errors

        errs = concept_validation_errors(concept)
        msg = "\n".join(f"  - {e}" for e in errs)
        raise RuntimeError(
            "Chưa có chỉ đạo câu chuyện từ bạn.\n"
            "Chạy: concept (xem câu hỏi) → điền concept.yaml → concept --ready\n"
            f"{msg}"
        )

    direction = load_direction(ws)
    book = int(direction.get("book") or 1)
    total_chapters = get_total_chapters(workspace_id, book)

    written: list[Path] = []
    if pass_name == "all":
        for p in PASSES:
            written.append(develop_pass(ws, p))
    else:
        written.append(develop_pass(ws, pass_name))

    sync_book_arc_total_chapters(ws, book, total_chapters)
    from factory.engine.lib.workspace_metadata import sync_narrative_profile_to_direction

    sync_narrative_profile_to_direction(ws)
    return written
