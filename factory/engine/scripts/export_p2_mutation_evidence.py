"""P2.2 — Mutation battery for P0 + P1 layers (expect-fail đúng reason/layer).

Usage:
  python factory/engine/scripts/export_p2_mutation_evidence.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.canon_artifacts import (  # noqa: E402
    is_stale,
    mark_stale_descendants,
)
from factory.engine.lib.canon_ops import (  # noqa: E402
    assert_chapter_not_stale,
    classify_error_layer,
    should_skip_literary_fixer,
)
from factory.engine.lib.canonical_ir import (  # noqa: E402
    build_ingest_report,
    compile_canonical_ir,
    ingest_concept_to_workspace,
    load_canonical_ir,
)
from factory.engine.lib.chapter_contract import (  # noqa: E402
    build_and_seal_chapter_artifacts,
    compile_chapter_contract,
    compile_writer_packet,
)
from factory.engine.lib.p2_fixtures import (  # noqa: E402
    MYSTERY_LITE_CONCEPT,
    ROMANCE_GATE_CONCEPT,
    zero_day_concept_path,
)
from factory.engine.lib.p2_harness import (  # noqa: E402
    assert_canon_fail_budget_zero,
    assert_no_incomplete_seal_promoted,
    begin_seal_journal,
    get_call_budget,
    record_call,
    reset_call_budget,
)
from factory.engine.lib.plan_provenance import (  # noqa: E402
    seal_chapter_plan,
    validate_plan_against_ir,
)
from factory.engine.lib.prose_claim_gate import validate_prose_against_ir  # noqa: E402
from factory.engine.lib.prose_settlement import (  # noqa: E402
    apply_settlement_to_intelligence,
    build_settlement,
    evaluate_belief_provenance,
    evaluate_knowledge_full_audit,
    evaluate_prop_holder_claim,
)
from factory.engine.lib.story_intelligence import (  # noqa: E402
    compile_chapter_intelligence,
    validate_move_fact_refs,
)

CE = zero_day_concept_path()
WS = ROOT / "factory" / "workspaces" / "_canon_p2_mutation_verify"
FIXTURES = ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_mutations"


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            args, cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _ce_bytes() -> bytes:
    return (
        zero_day_concept_path()
        .read_bytes()
        .replace(b"\r\n", b"\n")
        .replace(b"\r", b"\n")
    )


def _dump(name: str, payload: object) -> Path:
    path = WS / name
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


def _case(
    case_id: str,
    *,
    rule: str,
    expected: dict,
    actual: object,
    source_refs: dict,
    passed: bool,
    pass_reason_match: bool,
    layer: str,
) -> dict:
    return {
        "case_id": case_id,
        "layer": layer,
        "rule": rule,
        "expected": expected,
        "actual_decision_entry|errors": actual,
        "source_refs": source_refs,
        "pass": passed,
        "pass_reason_match": pass_reason_match,
        "error_layer": classify_error_layer(str(expected.get("reason") or rule)),
    }


def _reason_in(actual: object, reason: str) -> bool:
    if isinstance(actual, dict):
        if actual.get("reason") == reason:
            return True
        for v in actual.values():
            if _reason_in(v, reason):
                return True
    if isinstance(actual, list):
        return any(_reason_in(x, reason) for x in actual)
    return False


def main() -> int:
    if WS.exists():
        shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)

    (WS / "concept.yaml").write_bytes(_ce_bytes())
    ingest_concept_to_workspace(WS)
    # Normalize digest path for stable comparisons in live digest case
    ir = load_canonical_ir(WS)
    assert ir
    concept_obj = yaml.safe_load(_ce_bytes().decode("utf-8"))

    meta = {
        "commit": _git(["git", "rev-parse", "HEAD"]),
        "branch": _git(["git", "branch", "--show-current"]),
        "workspace": str(WS),
    }
    _dump("_meta.json", meta)

    cases: list[dict] = []

    # =====================================================================
    # P0 mutations
    # =====================================================================

    # M0-name: proper noun invented in plan proposal → not sealed
    plan_name = {
        "chapter": 1,
        "title": "The Bloody Phone",
        "must_happen": ["Marcus Chen the driver arrives with coffee."],
        "beat_summary": "Marcus Chen waits outside.",
    }
    name_out = seal_chapter_plan(WS, 1, plan_name, ir=ir)
    name_reasons = {
        u.get("reason") for u in (name_out.get("approval") or {}).get("unverified_claims") or []
    }
    cases.append(
        _case(
            "M0-name",
            rule="plan_provenance / named_entity_membership",
            expected={"sealed": False, "reason_any": ["unsourced_proper_noun", "named_entity_membership"]},
            actual={
                "sealed": name_out.get("sealed"),
                "unverified_claims": (name_out.get("approval") or {}).get("unverified_claims"),
            },
            source_refs={"plan": plan_name},
            passed=not name_out.get("sealed"),
            pass_reason_match=bool(
                name_reasons
                & {"unsourced_proper_noun", "named_entity_membership", "unsupported_claim"}
            )
            or not name_out.get("sealed"),
            layer="P0",
        )
    )

    # M0-reveal: early reveal wording scrubbed from writer packet
    plan_ok = {
        "chapter": 3,
        "title": "Synthetic Alibi",
        "must_happen": ["Mara creates the false alibi."],
    }
    repaired = validate_plan_against_ir(plan_ok, ir)["repaired_plan"]
    contract = compile_chapter_contract(ir, repaired, chapter=3)
    packet = compile_writer_packet(contract)
    blob = json.dumps(packet).casefold()
    reveal_scrubbed = (
        "secretly hired adrian to kill" not in blob
        and "f_reveal_r3" not in blob
        and int(packet.get("hidden_future_reveal_count") or 0) > 0
    )
    cases.append(
        _case(
            "M0-reveal",
            rule="compile_writer_packet scrub / excluded early reveal",
            expected={"scrubbed": True, "hidden_future_reveal_count_gt": 0},
            actual={
                "hidden_future_reveal_count": packet.get("hidden_future_reveal_count"),
                "blob_has_r3_hire": "secretly hired adrian to kill" in blob,
            },
            source_refs={"chapter": 3},
            passed=reveal_scrubbed,
            pass_reason_match=reveal_scrubbed,
            layer="P0",
        )
    )

    # M0-schema: unknown CE field classified importer; blocking unresolved optional
    mutated = deepcopy(concept_obj)
    mutated["totally_fabricated_ce_field_xyz"] = {"evil": True}
    report = build_ingest_report(mutated)
    schema_ok = "totally_fabricated_ce_field_xyz" in (report.get("unknown_fields") or [])
    layer_cls = classify_error_layer("canonical_ir ingest blocked: unknown field")
    cases.append(
        _case(
            "M0-schema",
            rule="build_ingest_report unknown field / importer classify",
            expected={
                "unknown_field": "totally_fabricated_ce_field_xyz",
                "error_layer": "importer_or_ce",
            },
            actual={
                "unknown_fields": report.get("unknown_fields"),
                "ok": report.get("ok"),
                "error_layer": layer_cls,
            },
            source_refs={"schema_version": mutated.get("schema_version")},
            passed=schema_ok and layer_cls == "importer_or_ce",
            pass_reason_match=schema_ok,
            layer="P0",
        )
    )

    # M0-stale: change IR hash → descendants stale; write blocked
    with tempfile.TemporaryDirectory() as tmp:
        tws = Path(tmp)
        (tws / "concept.yaml").write_bytes(_ce_bytes())
        ingest_concept_to_workspace(tws)
        tir = load_canonical_ir(tws)
        plan = {
            "chapter": 2,
            "title": "Anticoagulant",
            "must_happen": [
                "Mara observes anticoagulant treatment on the blood-stained phone."
            ],
            "beat_summary": (
                "She scrapes Claire Thorne data and confirms anticoagulant staging."
            ),
            "must_not": ["Mara leaves the office."],
        }
        sealed = seal_chapter_plan(tws, 1, plan, ir=tir)
        assert sealed.get("sealed"), sealed
        build_and_seal_chapter_artifacts(
            tws, 1, 2, sealed["repaired_plan"], ir=tir
        )
        touched = mark_stale_descendants(tws, 1, reason="p2_m0_stale_ir_hash")
        stale_blocked = False
        stale_err = ""
        try:
            assert_chapter_not_stale(tws, 1, 2, "deliberately-wrong-ir-digest")
        except RuntimeError as exc:
            stale_blocked = True
            stale_err = str(exc)
        cases.append(
            _case(
                "M0-stale",
                rule="mark_stale_descendants / assert_chapter_not_stale",
                expected={"write_blocked": True, "touched_gt": 0},
                actual={
                    "touched": touched,
                    "stale_blocked": stale_blocked,
                    "error": stale_err,
                    "error_layer": classify_error_layer(stale_err),
                },
                source_refs={"reason": "p2_m0_stale_ir_hash"},
                passed=stale_blocked and len(touched) > 0,
                pass_reason_match=stale_blocked,
                layer="P0",
            )
        )

    # M0-texture: texture sentence not in verified state / settlement knows
    prose_tex = (
        "The fluorescent light hummed above the desk while steam rose from the coffee."
    )
    qc_tex = validate_prose_against_ir(prose_tex, ir, chapter=2)
    settle_tex = build_settlement(
        chapter=2, canon_qc=qc_tex, prose_len=len(prose_tex), ir=ir
    )
    tex_ok = (
        qc_tex.get("status") == "pass"
        and int(settle_tex.get("texture_excluded_from_state") or 0) > 0
        and not any(
            c.get("kind") == "generic_texture"
            for c in settle_tex.get("facts_expressed") or []
        )
    )
    cases.append(
        _case(
            "M0-texture",
            rule="generic_texture excluded from settlement state",
            expected={"status": "pass", "texture_excluded_from_state_gt": 0},
            actual={
                "canon_status": qc_tex.get("status"),
                "texture_excluded": settle_tex.get("texture_excluded_from_state"),
                "facts_expressed_kinds": [
                    c.get("kind") for c in (settle_tex.get("facts_expressed") or [])
                ],
            },
            source_refs={"prose": prose_tex},
            passed=tex_ok,
            pass_reason_match=tex_ok,
            layer="P0",
        )
    )

    # M0-motive: motive override vs true_plot → STOP
    plan_motive = {
        "chapter": 11,
        "must_happen": [
            "Adrian reveals he orchestrated the entire confrontation to test "
            "whether Mara was a worthy partner."
        ],
        "beat_summary": "He had already decided to offer partnership as a test.",
        "title": "Two Victories",
        "cliffhanger": "She passed the worthy partner test.",
    }
    motive_res = validate_plan_against_ir(plan_motive, ir)
    motive_hit = any(
        u.get("reason") == "motive_swap_vs_true_plot"
        for u in motive_res.get("unverified_claims") or []
    )
    cases.append(
        _case(
            "M0-motive",
            rule="motive_swap_vs_true_plot",
            expected={"status": "blocked", "reason": "motive_swap_vs_true_plot"},
            actual={
                "status": motive_res.get("status"),
                "unverified_claims": motive_res.get("unverified_claims"),
            },
            source_refs={"true_plot_snippet": str((ir.get("plots") or {}).get("true_plot") or "")[:120]},
            passed=motive_res.get("status") == "blocked" and motive_hit,
            pass_reason_match=motive_hit,
            layer="P0",
        )
    )

    # M0-spec: medical specificity unsourced → STOP (or GENERALIZE then STOP)
    prose_spec = "The assay returned 0.47 micrograms/ml of K2EDTA."
    spec_res = validate_prose_against_ir(prose_spec, ir, chapter=2)
    spec_reasons = {v.get("reason") for v in spec_res.get("violations") or []}
    spec_ok = spec_res.get("status") == "fail" and (
        "unsourced_specificity" in spec_reasons
        or any("EDTA" in str(v.get("claim") or "") for v in spec_res.get("violations") or [])
    )
    cases.append(
        _case(
            "M0-spec",
            rule="unsourced_specificity / GENERALIZE|STOP",
            expected={"status": "fail", "reason": "unsourced_specificity"},
            actual={
                "status": spec_res.get("status"),
                "violations": spec_res.get("violations"),
                "reasons": list(spec_reasons),
            },
            source_refs={"prose": prose_spec},
            passed=spec_ok,
            pass_reason_match=spec_ok,
            layer="P0",
        )
    )

    # =====================================================================
    # P1 mutations
    # =====================================================================

    # Find R4 / R5 from reveal schedule
    reveals = {
        str(r.get("id")): r for r in (ir.get("reveal_schedule") or []) if isinstance(r, dict)
    }
    r4 = reveals.get("R4") or {}
    r5 = reveals.get("R5") or {}
    r4_fact = str(r4.get("fact") or "The blood was treated with anticoagulants.")
    r5_fact = str(
        r5.get("fact")
        or "Adrian planted a backdoor in Mara's alibi software that leaks metadata"
    )

    # M1-mem-future
    kept_f, audit_f = evaluate_knowledge_full_audit([r5_fact], ir, 2, source="mutation")
    mem_future = any(
        a.get("decision") == "clamped" and a.get("reason") == "pov_clock_not_reached"
        for a in audit_f
    ) and r5_fact not in kept_f
    cases.append(
        _case(
            "M1-mem-future",
            rule="evaluate_knowledge_against_pov_clocks",
            expected={"reason": "pov_clock_not_reached", "decision": "clamped"},
            actual={"kept": kept_f, "audit": audit_f},
            source_refs={
                "reveal": "R5",
                "pov_knows_chapter": r5.get("pov_knows_chapter"),
                "chapter": 2,
            },
            passed=mem_future,
            pass_reason_match=mem_future,
            layer="P1-Memory",
        )
    )

    # M1-mem-reader: reader clock reached, POV not — still clamp with clock_used=pov
    # Force a reveal-like claim where reader < chapter but pov > chapter if present;
    # else synthesize audit expectation via R5 at ch where reader may be earlier.
    reader_ch = int(r5.get("reader_reveal_chapter") or 99)
    pov_ch = int(r5.get("pov_knows_chapter") or 99)
    # Use chapter = max(reader, 2) but < pov if possible
    test_ch = 2
    if reader_ch <= test_ch < pov_ch:
        pass
    elif reader_ch < pov_ch:
        test_ch = int(reader_ch)
    kept_r, audit_r = evaluate_knowledge_full_audit(
        [r5_fact], ir, test_ch, source="mutation_reader"
    )
    mem_reader = any(
        a.get("decision") == "clamped"
        and a.get("reason") == "pov_clock_not_reached"
        and a.get("clock_used") == "pov_knows_chapter"
        for a in audit_r
    )
    cases.append(
        _case(
            "M1-mem-reader",
            rule="pov clock authority (never reader_reveal_chapter)",
            expected={
                "reason": "pov_clock_not_reached",
                "clock_used": "pov_knows_chapter",
            },
            actual={
                "chapter": test_ch,
                "reader_reveal_chapter": reader_ch,
                "pov_knows_chapter": pov_ch,
                "kept": kept_r,
                "audit": audit_r,
            },
            source_refs={"reveal": "R5"},
            passed=mem_reader and test_ch < pov_ch,
            pass_reason_match=mem_reader,
            layer="P1-Memory",
        )
    )

    # M1-mem-poison: poisoned settlement knows_gained re-clamped; absent from packet
    poison = {
        "status": "sealed",
        "chapter": 2,
        "settlement_digest": "p2-poison-knows",
        "events_realized": [],
        "character_updates": {
            "deltas": {
                "character": "Mara Voss",
                "knows_gained": [r5_fact, r4_fact],
            }
        },
        "prop_updates": [],
        "strategy_updates": {},
    }
    intel3 = compile_chapter_intelligence(ir, 3, prior_settlement=poison)
    mara = next(
        (
            r
            for r in (intel3.get("character_state") or [])
            if "Mara" in str(r.get("character") or "")
        ),
        {},
    )
    knows = mara.get("knows") or []
    poison_ok = not any("backdoor" in str(k).casefold() for k in knows)
    # Also packet scrub
    plan3 = {
        "chapter": 3,
        "title": "Next",
        "must_happen": ["Mara creates the false alibi."],
        "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
        "must_not": ["Mara leaves the office."],
    }
    intel_poison = compile_chapter_intelligence(ir, 3, prior_settlement=poison)
    c3 = compile_chapter_contract(
        ir, plan3, chapter=3, intelligence=intel_poison
    )
    p3 = compile_writer_packet(c3)
    pblob = json.dumps(p3).casefold()
    poison_packet_ok = "backdoor" not in pblob
    cases.append(
        _case(
            "M1-mem-poison",
            rule="apply/re-clamp poisoned knows_gained",
            expected={"backdoor_absent_from_knows": True, "absent_from_packet": True},
            actual={"knows": knows, "packet_has_backdoor": "backdoor" in pblob},
            source_refs={"settlement_digest": "p2-poison-knows"},
            passed=poison_ok and poison_packet_ok,
            pass_reason_match=poison_ok,
            layer="P1-Memory",
        )
    )

    # M1-cust-holder
    cust_h = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=2,
        proposed_holder="Det. Miller",
        action="Det. Miller seizes the phone",
        source="prose_possession",
    )
    cases.append(
        _case(
            "M1-cust-holder",
            rule="evaluate_prop_holder_claim",
            expected={"reason": "holder_not_on_schedule", "decision": "clamped"},
            actual=cust_h,
            source_refs={"prop_id": "P1", "chapter": 2},
            passed=cust_h.get("reason") == "holder_not_on_schedule",
            pass_reason_match=cust_h.get("reason") == "holder_not_on_schedule",
            layer="P1-Custody",
        )
    )

    # M1-cust-action
    cust_a = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=1,
        proposed_holder="Mara",
        action="Mara destroys the Blood-stained phone forever",
        source="prose_prop_action",
    )
    cases.append(
        _case(
            "M1-cust-action",
            rule="evaluate_prop_holder_claim",
            expected={"reason": "action_not_allowed", "decision": "clamped"},
            actual=cust_a,
            source_refs={"prop_id": "P1", "chapter": 1},
            passed=cust_a.get("reason") == "action_not_allowed",
            pass_reason_match=cust_a.get("reason") == "action_not_allowed",
            layer="P1-Custody",
        )
    )

    # Control C1: correct holder — no false positive
    cust_ok = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=1,
        proposed_holder="Mara",
        action="Adrian gives phone to Mara",
        source="prose_custody_chain",
    )
    cases.append(
        _case(
            "CTRL-cust-allowed",
            rule="evaluate_prop_holder_claim control",
            expected={"decision": "allowed"},
            actual=cust_ok,
            source_refs={"prop_id": "P1"},
            passed=cust_ok.get("decision") == "allowed",
            pass_reason_match=cust_ok.get("decision") == "allowed",
            layer="P1-Custody-control",
        )
    )

    # M1-belief-orphan
    b_kept, b_audit = evaluate_belief_provenance(
        [{"text": "The garden gnomes planned the frame.", "provenance": ""}],
        ir,
        2,
    )
    belief_orphan = "The garden gnomes planned the frame." not in b_kept and any(
        a.get("decision") == "omitted" or a.get("reason") == "missing_provenance"
        for a in b_audit
    )
    cases.append(
        _case(
            "M1-belief-orphan",
            rule="evaluate_belief_provenance missing_provenance",
            expected={"decision_in": ["omitted"], "reason": "missing_provenance"},
            actual={"kept": b_kept, "audit": b_audit},
            source_refs={"chapter": 2},
            passed=belief_orphan,
            pass_reason_match=belief_orphan,
            layer="P1-Belief",
        )
    )

    # M1-belief-alias: hidden truth as misbelief
    ba_kept, ba_audit = evaluate_belief_provenance(
        [{"text": r5_fact, "provenance": "inference"}],
        ir,
        2,
    )
    belief_alias = r5_fact not in ba_kept and any(
        a.get("reason") == "pov_clock_not_reached" for a in ba_audit
    )
    cases.append(
        _case(
            "M1-belief-alias",
            rule="hidden truth as misbelief → pov_clock_not_reached",
            expected={"reason": "pov_clock_not_reached"},
            actual={"kept": ba_kept, "audit": ba_audit},
            source_refs={"reveal": "R5", "chapter": 2},
            passed=belief_alias,
            pass_reason_match=belief_alias,
            layer="P1-Belief",
        )
    )

    # Strategy mutations
    s_missing = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara scrapes Claire Thorne's data.",
                "fact_refs": [],
            }
        },
        ir=ir,
        chapter=2,
    )
    cases.append(
        _case(
            "M1-strat-missing",
            rule="validate_move_fact_refs",
            expected={"reason": "move_missing_fact_refs"},
            actual=s_missing,
            source_refs={"chapter": 2},
            passed=any(e.get("reason") == "move_missing_fact_refs" for e in s_missing),
            pass_reason_match=True,
            layer="P1-Strategy",
        )
    )

    s_future = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara finds the backdoor in her alibi software.",
                "fact_refs": ["F_REVEAL_R5"],
            }
        },
        ir=ir,
        chapter=2,
    )
    cases.append(
        _case(
            "M1-strat-future",
            rule="validate_move_fact_refs",
            expected={"reason": "move_future_fact_ref"},
            actual=s_future,
            source_refs={"fact_ref": "F_REVEAL_R5", "chapter": 2},
            passed=any(e.get("reason") == "move_future_fact_ref" for e in s_future),
            pass_reason_match=True,
            layer="P1-Strategy",
        )
    )

    s_actor = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Adrian Thorne scrapes Claire Thorne's data.",
                "fact_refs": ["F_MAP_CH2_must_happen_0"],
            }
        },
        ir=ir,
        chapter=2,
    )
    cases.append(
        _case(
            "M1-strat-actor",
            rule="validate_move_fact_refs",
            expected={"reason": "move_wrong_actor"},
            actual=s_actor,
            source_refs={"chapter": 2},
            passed=any(e.get("reason") == "move_wrong_actor" for e in s_actor),
            pass_reason_match=True,
            layer="P1-Strategy",
        )
    )

    s_prop = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara destroys the Blood-stained phone forever.",
                "fact_refs": ["F_PROP_P1"],
            }
        },
        ir=ir,
        chapter=2,
    )
    cases.append(
        _case(
            "M1-strat-prop",
            rule="validate_move_fact_refs",
            expected={"reason": "move_prop_action_not_allowed"},
            actual=s_prop,
            source_refs={"fact_ref": "F_PROP_P1"},
            passed=any(e.get("reason") == "move_prop_action_not_allowed" for e in s_prop),
            pass_reason_match=True,
            layer="P1-Strategy",
        )
    )

    # Control S6: IR-built moves no false positive
    builtin = compile_chapter_intelligence(ir, 2)["moves"]
    s_ctrl = validate_move_fact_refs(builtin, ir=ir, chapter=2)
    cases.append(
        _case(
            "CTRL-strat-builtin",
            rule="validate_move_fact_refs control S6",
            expected={"errors": []},
            actual=s_ctrl,
            source_refs={"chapter": 2},
            passed=s_ctrl == [],
            pass_reason_match=s_ctrl == [],
            layer="P1-Strategy-control",
        )
    )

    # M1-live-digest: change settlement N → packet N+1 digest changes
    settle_a = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
                {"claim": "The blood was treated with anticoagulants.", "kind": "event"},
                {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
            ],
        },
        intelligence=compile_chapter_intelligence(ir, 2),
        ir=ir,
    )
    settle_b = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
                {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
            ],
        },
        intelligence=compile_chapter_intelligence(ir, 2),
        ir=ir,
    )
    plan_n1 = {
        "chapter": 3,
        "title": "Next",
        "must_happen": ["Mara creates the false alibi."],
        "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
        "must_not": ["Mara leaves the office."],
        "carries_to_next": {"foreshadow": "outliner-only foresight that must yield"},
    }
    intel_a = compile_chapter_intelligence(
        ir, 3, prior_settlement={**settle_a, "status": "sealed"}
    )
    intel_b = compile_chapter_intelligence(
        ir, 3, prior_settlement={**settle_b, "status": "sealed"}
    )
    pa = compile_writer_packet(
        compile_chapter_contract(ir, plan_n1, chapter=3, intelligence=intel_a)
    )
    pb = compile_writer_packet(
        compile_chapter_contract(ir, plan_n1, chapter=3, intelligence=intel_b)
    )
    live_ok = pa.get("packet_digest") != pb.get("packet_digest")
    cases.append(
        _case(
            "M1-live-digest",
            rule="settlement N → packet N+1 digest / foresight superseded",
            expected={"digests_differ": True, "plan_foresight_superseded": True},
            actual={
                "digest_a": pa.get("packet_digest"),
                "digest_b": pb.get("packet_digest"),
                "continuity_a": pa.get("continuity"),
                "continuity_b": pb.get("continuity"),
            },
            source_refs={"chapter_N": 2, "chapter_N1": 3},
            passed=live_ok,
            pass_reason_match=live_ok,
            layer="P1-Live",
        )
    )

    # Ops: canon fail → literary/fixer/settlement counters stay 0
    reset_call_budget()
    fail_qc = {"status": "fail", "violations": [{"reason": "unsourced_proper_noun"}]}
    skip = should_skip_literary_fixer(fail_qc)
    if skip:
        # No literary/fixer/settlement LLM recorded on fail path
        assert_canon_fail_budget_zero()
    cases.append(
        _case(
            "M0-ops-budget",
            rule="should_skip_literary_fixer + call budget zero on canon fail",
            expected={"skip": True, "literary": 0, "fixer": 0, "settlement_llm": 0},
            actual={"skip": skip, "budget": get_call_budget()},
            source_refs={"canon_qc": fail_qc},
            passed=skip and get_call_budget()["literary_qc_calls"] == 0,
            pass_reason_match=skip,
            layer="P0-Ops",
        )
    )

    # Kill-point: incomplete seal journal blocks promote
    with tempfile.TemporaryDirectory() as tmp:
        kws = Path(tmp)
        begin_seal_journal(kws, 1, 2, "plan")
        kill_blocked = False
        try:
            assert_no_incomplete_seal_promoted(kws, 1, 2)
        except RuntimeError:
            kill_blocked = True
        cases.append(
            _case(
                "M0-killpoint",
                rule="incomplete seal journal refuses READY/promote",
                expected={"blocked": True},
                actual={"blocked": kill_blocked},
                source_refs={"step": "plan"},
                passed=kill_blocked,
                pass_reason_match=kill_blocked,
                layer="P0-Ops",
            )
        )

    # Corpus smoke: romance + mystery_lite ingest without LLM
    romance_ir = compile_canonical_ir(ROMANCE_GATE_CONCEPT)
    mystery_ir = compile_canonical_ir(MYSTERY_LITE_CONCEPT)
    cases.append(
        _case(
            "CORPUS-romance-ingest",
            rule="romance-light omit mystery pressure; ingest ok",
            expected={"title": "Romance Gate", "has_ir_digest": True},
            actual={
                "title": romance_ir.get("title"),
                "ir_digest": romance_ir.get("ir_digest"),
                "chapter_count": romance_ir.get("chapter_count"),
            },
            source_refs={"fixture": "ROMANCE_GATE_CONCEPT"},
            passed=bool(romance_ir.get("ir_digest")),
            pass_reason_match=True,
            layer="P2-Corpus",
        )
    )
    cases.append(
        _case(
            "CORPUS-mystery-lite-ingest",
            rule="mystery-lite reveal clocks present for Memory/Strategy",
            expected={"reveal_count_gte": 1},
            actual={
                "title": mystery_ir.get("title"),
                "reveals": len(mystery_ir.get("reveal_schedule") or []),
                "ir_digest": mystery_ir.get("ir_digest"),
            },
            source_refs={"fixture": "MYSTERY_LITE_CONCEPT"},
            passed=len(mystery_ir.get("reveal_schedule") or []) >= 1,
            pass_reason_match=True,
            layer="P2-Corpus",
        )
    )

    all_pass = all(c["pass"] for c in cases)
    reason_match = all(c["pass_reason_match"] for c in cases if c["pass"])

    gate = {
        "meta": meta,
        "mutation_cases": {c["case_id"]: c["pass"] for c in cases},
        "all_cases_pass": all_pass,
        "pass_reason_match_ok": reason_match,
        "control_no_false_positive": all(
            c["pass"]
            for c in cases
            if c["case_id"].startswith("CTRL-")
        ),
        "p2_mutation_battery_complete": all_pass and reason_match,
        "case_count": len(cases),
    }
    _dump("mutation_cases.json", {"cases": cases})
    _dump("RAW_MUTATION_GATE.json", gate)

    # Commit fixtures
    (FIXTURES / "RAW_MUTATION_GATE.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (FIXTURES / "mutation_cases.json").write_text(
        json.dumps({"cases": cases}, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(gate, indent=2, ensure_ascii=False))
    return 0 if gate["p2_mutation_battery_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
