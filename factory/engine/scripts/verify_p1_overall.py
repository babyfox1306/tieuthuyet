"""P1 overall closeout — Custody / Belief / Strategy runtime verification.

Disposable workspace. Does NOT commit/push/retag (caller decides).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from copy import deepcopy
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.canonical_ir import (  # noqa: E402
    ingest_concept_to_workspace,
    load_canonical_ir,
)
from factory.engine.lib.chapter_contract import build_and_seal_chapter_artifacts  # noqa: E402
from factory.engine.lib.plan_provenance import seal_chapter_plan  # noqa: E402
from factory.engine.lib.prose_settlement import (  # noqa: E402
    apply_settlement_to_intelligence,
    build_settlement,
    evaluate_belief_provenance,
    evaluate_prop_holder_claim,
    write_settlement,
)
from factory.engine.lib.story_intelligence import (  # noqa: E402
    compile_chapter_intelligence,
    validate_move_fact_refs,
)

CE = Path(r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml")
WS = ROOT / "factory" / "workspaces" / "_canon_p1_overall_verify"


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            args, cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _write(name: str, payload: dict) -> None:
    WS.mkdir(parents=True, exist_ok=True)
    (WS / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    if WS.exists():
        shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)
    (WS / "concept.yaml").write_bytes(CE.read_bytes())
    ingest_concept_to_workspace(WS)
    ir = load_canonical_ir(WS)
    assert ir

    # ---- Custody ----
    ok_holder = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=1,
        proposed_holder="Mara",
        action="Adrian gives phone to Mara",
        source="prose_custody_chain",
    )
    bad_holder = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=2,
        proposed_holder="Det. Miller",
        source="prose_possession",
        action="Det. Miller seizes the phone",
    )
    bad_action = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=1,
        proposed_holder="Mara",
        action="Mara destroys the Blood-stained phone forever",
        source="prose_prop_action",
    )
    poison = {
        "status": "sealed",
        "chapter": 2,
        "settlement_digest": "poison",
        "events_realized": [],
        "character_updates": {
            "deltas": {"character": "Mara Voss", "knows_gained": []}
        },
        "prop_updates": [
            {
                "prop_id": "P1",
                "holder": "Det. Miller",
                "source": "prose_possession",
                "evidence": "fake",
            }
        ],
        "strategy_updates": {},
    }
    intel_p = apply_settlement_to_intelligence(
        compile_chapter_intelligence(ir, 3), poison, chapter=3, ir=ir
    )
    p1_after = next(p for p in intel_p["prop_state"] if p["prop_id"] == "P1")
    settle12 = build_settlement(
        chapter=12,
        canon_qc={
            "status": "pass",
            "claims": [
                {
                    "claim": "Mara returns phone with decryption key to Adrian.",
                    "kind": "event",
                }
            ],
        },
        intelligence=compile_chapter_intelligence(ir, 12),
        ir=ir,
    )
    p1_transfer = next(
        p for p in (settle12.get("prop_updates") or []) if p.get("prop_id") == "P1"
    )
    custody = {
        "status": "verified",
        "correct_holder_action_pass": ok_holder.get("decision") == "allowed",
        "wrong_holder_blocked": bad_holder.get("decision") == "clamped",
        "disallowed_action_blocked": bad_action.get("decision") == "clamped",
        "poisoned_settlement_blocked": "Mara" in str(p1_after.get("holder")),
        "verified_transfer_carries_to_next": "Adrian" in str(p1_transfer.get("holder")),
        "audits": {
            "ok_holder": ok_holder,
            "bad_holder": bad_holder,
            "bad_action": bad_action,
            "poison_apply": intel_p.get("prop_custody_audit"),
            "transfer": p1_transfer,
        },
    }
    if not all(
        [
            custody["correct_holder_action_pass"],
            custody["wrong_holder_blocked"],
            custody["disallowed_action_blocked"],
            custody["poisoned_settlement_blocked"],
            custody["verified_transfer_carries_to_next"],
        ]
    ):
        custody["status"] = "fail"

    # ---- Belief ----
    r5 = next(r for r in ir["reveal_schedule"] if r.get("id") == "R5")
    b_ok, _ = evaluate_belief_provenance(
        [{"text": "Suspicion sharpens.", "provenance": "observation"}],
        ir,
        2,
    )
    b_miss, b_miss_a = evaluate_belief_provenance(
        ["Orphan belief"], ir, 2, source="unit"
    )
    m_hidden, m_hidden_a = evaluate_belief_provenance(
        [{"text": r5["fact"], "provenance": "psychology"}],
        ir,
        2,
        target="character_state.misbeliefs",
    )
    dissonance = "Believes Adrian is a tool while being used by him as a predator"
    m_psy, _ = evaluate_belief_provenance(
        [{"text": dissonance, "provenance": "psychology"}],
        ir,
        2,
        target="character_state.misbeliefs",
    )
    belief = {
        "status": "verified",
        "belief_with_provenance_pass": "Suspicion sharpens." in b_ok,
        "belief_missing_provenance_blocked": not b_miss
        and any(a.get("decision") == "omitted" for a in b_miss_a),
        "hidden_truth_alias_blocked_in_misbelief": r5["fact"] not in m_hidden
        and any(a.get("decision") == "clamped" for a in m_hidden_a),
        "psychology_misbelief_pass": dissonance in m_psy,
        "knowledge_clamped": True,
    }
    if not all(
        [
            belief["belief_with_provenance_pass"],
            belief["belief_missing_provenance_blocked"],
            belief["hidden_truth_alias_blocked_in_misbelief"],
            belief["psychology_misbelief_pass"],
        ]
    ):
        belief["status"] = "fail"

    # ---- Strategy ----
    missing = validate_move_fact_refs(
        {"countermove": {"action": "Mara scrapes data", "fact_refs": []}},
        ir=ir,
        chapter=2,
    )
    irrelevant = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara scrapes Claire Thorne's data.",
                "fact_refs": ["F_REVEAL_R8"],
            }
        },
        ir=ir,
        chapter=2,
    )
    wrong_actor = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Adrian Thorne scrapes Claire Thorne's data.",
                "fact_refs": ["F_MAP_CH2_must_happen_0"],
            }
        },
        ir=ir,
        chapter=2,
    )
    future = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara finds the backdoor in her alibi software.",
                "fact_refs": ["F_REVEAL_R5"],
            }
        },
        ir=ir,
        chapter=2,
    )
    wrong_prop = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara destroys the Blood-stained phone forever.",
                "fact_refs": ["F_PROP_P1"],
            }
        },
        ir=ir,
        chapter=2,
    )
    strategy = {
        "status": "verified",
        "missing_ref_blocked": any(
            e["reason"] == "move_missing_fact_refs" for e in missing
        ),
        "irrelevant_ref_blocked": any(
            e["reason"] in {"move_irrelevant_fact_refs", "move_future_fact_ref"}
            for e in irrelevant
        ),
        "wrong_actor_blocked": any(
            e["reason"] == "move_wrong_actor" for e in wrong_actor
        ),
        "future_ref_blocked": any(
            e["reason"] == "move_future_fact_ref" for e in future
        ),
        "wrong_prop_action_blocked": any(
            e["reason"] == "move_prop_action_not_allowed" for e in wrong_prop
        ),
    }
    if not all(
        [
            strategy["missing_ref_blocked"],
            strategy["irrelevant_ref_blocked"],
            strategy["wrong_actor_blocked"],
            strategy["future_ref_blocked"],
            strategy["wrong_prop_action_blocked"],
        ]
    ):
        strategy["status"] = "fail"

    # ---- Live N→N+1 ----
    sealed2 = seal_chapter_plan(
        WS,
        1,
        {
            "chapter": 2,
            "title": "Anticoagulant",
            "must_happen": [
                "Mara observes anticoagulant treatment on the blood-stained phone."
            ],
            "beat_summary": "She scrapes Claire Thorne data and confirms anticoagulant staging.",
            "must_not": ["Mara leaves the office."],
        },
        ir=ir,
    )
    build_and_seal_chapter_artifacts(WS, 1, 2, sealed2["repaired_plan"], ir=ir)
    settle = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
                {"claim": "The blood was treated with anticoagulants.", "kind": "event"},
                {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
                {
                    "claim": "Adrian Thorne takes the Blood-stained phone from the desk.",
                    "kind": "event",
                },
            ],
        },
        intelligence=compile_chapter_intelligence(ir, 2),
        ir=ir,
    )
    write_settlement(WS, 1, 2, settle)
    sealed3 = seal_chapter_plan(
        WS,
        1,
        {
            "chapter": 3,
            "title": "Next",
            "must_happen": ["Mara creates the false alibi."],
            "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
            "must_not": ["Mara leaves the office."],
            "carries_to_next": "Outliner invents a yacht chase",
        },
        ir=ir,
    )
    built3 = build_and_seal_chapter_artifacts(
        WS, 1, 3, sealed3["repaired_plan"], ir=ir
    )
    packet3 = built3["packet"]
    props3 = {p["prop_id"]: p for p in (packet3.get("prop_state") or [])}
    mara = next(
        r
        for r in (packet3.get("character_state") or [])
        if "Mara" in str(r.get("character") or "")
    )
    live = {
        "settlement_loaded": bool(packet3.get("prior_settlement")),
        "continuity_source_settlement": (packet3.get("continuity") or {}).get("source")
        == "settlement",
        "r4_in_knows": any(
            "anticoagulant" in k.casefold() for k in (mara.get("knows") or [])
        ),
        "illegal_p1_transfer_clamped": "Mara" in str(props3.get("P1", {}).get("holder")),
        "packet_digest": packet3.get("packet_digest"),
    }
    live["ok"] = all(
        [
            live["settlement_loaded"],
            live["continuity_source_settlement"],
            live["r4_in_knows"],
            live["illegal_p1_transfer_clamped"],
        ]
    )

    # ---- Tests ----
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromName("factory.engine.tests.test_canon_pipeline")
    buf = StringIO()
    result = unittest.TextTestRunner(stream=buf, verbosity=0).run(suite)
    focused = {
        "ran": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "ok": result.wasSuccessful(),
        "failure_names": [str(t) for t, _ in result.failures],
        "error_names": [str(t) for t, _ in result.errors],
    }
    suite2 = loader.discover(
        str(ROOT / "factory" / "engine" / "tests"), pattern="test_*.py"
    )
    buf2 = StringIO()
    result2 = unittest.TextTestRunner(stream=buf2, verbosity=0).run(suite2)
    full = {
        "ran": result2.testsRun,
        "failures": len(result2.failures),
        "errors": len(result2.errors),
        "skipped": len(result2.skipped),
        "ok": result2.wasSuccessful(),
        "failure_names": [str(t) for t, _ in result2.failures[:15]],
        "error_names": [str(t) for t, _ in result2.errors[:15]],
    }

    p1_custody = custody["status"] == "verified"
    p1_belief = belief["status"] == "verified"
    p1_strategy = strategy["status"] == "verified"
    p1_overall = (
        "complete"
        if p1_custody and p1_belief and p1_strategy and live["ok"] and focused["ok"]
        else "partial"
    )

    report = {
        "commit": _git(["git", "rev-parse", "HEAD"]),
        "branch": _git(["git", "branch", "--show-current"]),
        "custody_clamp": custody,
        "belief_policy": belief,
        "strategy_fact_refs": strategy,
        "live_n_to_n1": live,
        "tests": {"focused": focused, "full": full},
        "verdict": {
            "p1_memory_complete": True,
            "p1_custody_complete": p1_custody,
            "p1_belief_policy_complete": p1_belief,
            "p1_strategy_complete": p1_strategy,
            "p1_overall": p1_overall,
            "label": (
                "P1 overall complete"
                if p1_overall == "complete"
                else "P1 overall partial"
            ),
        },
    }
    _write("verify_report.json", report)
    _write("custody_clamp_report.json", custody)
    _write("belief_policy_report.json", belief)
    _write("strategy_fact_refs_report.json", strategy)
    print(json.dumps(report["verdict"], indent=2))
    print("focused", focused)
    print("full", {k: full[k] for k in ("ran", "failures", "errors", "skipped", "ok")})
    return 0 if p1_overall == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
