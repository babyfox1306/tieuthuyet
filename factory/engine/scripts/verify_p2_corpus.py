"""P2.3 — Corpus: Zero-Day infection regressions + synthetic mini-concepts.

Workspace disposable: factory/workspaces/_canon_p2_corpus_*
Does not mutate the golden Zero-Day CE source.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.canonical_ir import (  # noqa: E402
    build_ingest_report,
    compile_canonical_ir,
    ingest_concept_to_workspace,
)
from factory.engine.lib.p2_fixtures import MYSTERY_LITE_CONCEPT, ROMANCE_GATE_CONCEPT  # noqa: E402
from factory.engine.lib.p2_harness import concept_to_workspace, seal_minimal_chapter  # noqa: E402
from factory.engine.lib.plan_provenance import validate_plan_against_ir  # noqa: E402
from factory.engine.lib.prose_claim_gate import validate_prose_against_ir  # noqa: E402
from factory.engine.lib.prose_settlement import build_settlement  # noqa: E402

CE = Path(r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml")
CE_FALLBACK = ROOT / "factory" / "workspaces" / "the-zero-day-alibi" / "concept.yaml"
WS_ROOT = ROOT / "factory" / "workspaces" / "_canon_p2_corpus_verify"
FIXTURES = ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_corpus"


INFECTION_CASES = {
    "B_invented_name_in_dialogue": {
        "expect": "fail",
        "prose": (
            "I kept my voice flat. "
            '"Call Dr. Patricia Holloway immediately." '
            "The line stayed dead."
        ),
    },
    "C_future_fact_no_new_name": {
        "expect": "fail",
        "prose": (
            "I already knew the truth: I secretly hired him to kill Claire Thorne "
            "and planned the frame from the start."
        ),
    },
    "D_generic_texture": {
        "expect": "pass_no_state_texture",
        "prose": (
            "The fluorescent light hummed above the desk while steam rose from the coffee."
        ),
    },
    "A_canon_name_in_dialogue": {
        "expect": "pass",
        "prose": (
            "I kept my voice flat. "
            '"Adrian Thorne, put the phone on the desk." '
            "He did not smile."
        ),
    },
}


def _ce_path() -> Path:
    if CE.exists():
        return CE
    if CE_FALLBACK.exists():
        return CE_FALLBACK
    raise FileNotFoundError("Zero-Day concept.yaml not found")


def main() -> int:
    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT, ignore_errors=True)
    WS_ROOT.mkdir(parents=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)

    results: dict[str, object] = {}

    # --- Infection corpus on Zero-Day (failing→fixed regressions) ---
    zd_ws = WS_ROOT / "zero_day_infection"
    zd_ws.mkdir()
    (zd_ws / "concept.yaml").write_bytes(_ce_path().read_bytes())
    ingest_concept_to_workspace(zd_ws)
    from factory.engine.lib.canonical_ir import load_canonical_ir

    ir = load_canonical_ir(zd_ws)
    assert ir
    infection: dict[str, bool] = {}
    for case_id, spec in INFECTION_CASES.items():
        qc = validate_prose_against_ir(spec["prose"], ir, chapter=2)
        if spec["expect"] == "fail":
            infection[case_id] = qc.get("status") == "fail"
        elif spec["expect"] == "pass":
            infection[case_id] = qc.get("status") == "pass"
        elif spec["expect"] == "pass_no_state_texture":
            settle = build_settlement(
                chapter=2, canon_qc=qc, prose_len=len(spec["prose"]), ir=ir
            )
            infection[case_id] = (
                qc.get("status") == "pass"
                and int(settle.get("texture_excluded_from_state") or 0) > 0
            )
        else:
            infection[case_id] = False
    results["zero_day_infection"] = infection

    # --- Romance-only synthetic (quiet omit of mystery pressure) ---
    romance_ws = WS_ROOT / "romance_gate"
    romance_ir = concept_to_workspace(romance_ws, ROMANCE_GATE_CONCEPT)
    romance_report = build_ingest_report(ROMANCE_GATE_CONCEPT)
    romance_seal = seal_minimal_chapter(
        romance_ws,
        romance_ir,
        1,
        {
            "chapter": 1,
            "title": "latch inventory",
            "must_happen": ["Lina Reed inventories the latch without forcing it."],
            "beat_summary": "Lina Reed inventories the latch without forcing it.",
            "must_not": ["Invent unsupported medical diagnosis."],
        },
    )
    results["romance_gate"] = {
        "ingest_ok": romance_report.get("ok"),
        "ir_digest": romance_ir.get("ir_digest"),
        "contract_digest": romance_seal.get("contract_digest"),
        "has_reveal_schedule": bool(romance_ir.get("reveal_schedule")),
        "pass": bool(romance_report.get("ok") and romance_seal.get("contract_digest")),
    }
    (FIXTURES / "romance_gate_concept.yaml").write_text(
        yaml.safe_dump(ROMANCE_GATE_CONCEPT, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # --- Mystery-lite synthetic (enough clocks for Memory/Strategy) ---
    mystery_ws = WS_ROOT / "mystery_lite"
    mystery_ir = concept_to_workspace(mystery_ws, MYSTERY_LITE_CONCEPT)
    mystery_report = build_ingest_report(MYSTERY_LITE_CONCEPT)
    # Memory clock check: ML2 hidden at ch2
    from factory.engine.lib.prose_settlement import evaluate_knowledge_full_audit

    ml2 = next(
        (
            r
            for r in (mystery_ir.get("reveal_schedule") or [])
            if str(r.get("id")) == "ML2"
        ),
        {},
    )
    kept, audit = evaluate_knowledge_full_audit(
        [str(ml2.get("fact") or "")], mystery_ir, 2, source="corpus"
    )
    mem_clamp = any(
        a.get("reason") == "pov_clock_not_reached" for a in audit
    ) and not kept
    plan2 = {
        "chapter": 2,
        "title": "envelope gap",
        "must_happen": ["Nora Quill weighs the envelope against the log."],
        "beat_summary": "Nora Quill weighs the envelope against the log.",
        "must_not": ["Invent unsupported medical diagnosis."],
    }
    sealed = validate_plan_against_ir(plan2, mystery_ir)
    results["mystery_lite"] = {
        "ingest_ok": mystery_report.get("ok"),
        "ir_digest": mystery_ir.get("ir_digest"),
        "reveal_count": len(mystery_ir.get("reveal_schedule") or []),
        "ml2_clamped_at_ch2": mem_clamp,
        "plan2_status": sealed.get("status"),
        "pass": bool(
            mystery_report.get("ok")
            and len(mystery_ir.get("reveal_schedule") or []) >= 2
            and mem_clamp
        ),
    }
    (FIXTURES / "mystery_lite_concept.yaml").write_text(
        yaml.safe_dump(MYSTERY_LITE_CONCEPT, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    infection_pass = all(infection.values())
    gate = {
        "zero_day_infection_pass": infection_pass,
        "romance_gate_pass": bool((results["romance_gate"] or {}).get("pass")),  # type: ignore
        "mystery_lite_pass": bool((results["mystery_lite"] or {}).get("pass")),  # type: ignore
        "results": results,
        "p2_corpus_complete": False,
        "llm_used": False,
    }
    gate["p2_corpus_complete"] = (
        gate["zero_day_infection_pass"]
        and gate["romance_gate_pass"]
        and gate["mystery_lite_pass"]
    )

    (WS_ROOT / "CORPUS_GATE.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (FIXTURES / "CORPUS_GATE.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(gate, indent=2, ensure_ascii=False))
    return 0 if gate["p2_corpus_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
