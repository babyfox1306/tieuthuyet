"""Export raw P1 evidence — no verdict summaries, full decision traces."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.p2_fixtures import zero_day_concept_path  # noqa: E402
from factory.engine.lib.canonical_ir import (  # noqa: E402
    ingest_concept_to_workspace,
    load_canonical_ir,
    sha256_obj,
)
from factory.engine.lib.chapter_contract import (  # noqa: E402
    build_and_seal_chapter_artifacts,
    compile_writer_packet,
)
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
    project_prop_state,
    validate_move_fact_refs,
)

CE = zero_day_concept_path()
WS = ROOT / "factory" / "workspaces" / "_canon_p1_raw_evidence"


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(
            args, cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _dump(name: str, payload: object) -> Path:
    path = WS / name
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


def _prop_ir(ir: dict, pid: str) -> dict:
    for p in ir.get("props") or []:
        if str(p.get("id")) == pid:
            return p
    return {}


def main() -> int:
    if WS.exists():
        shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)
    (WS / "concept.yaml").write_bytes(CE.read_bytes())
    ingest_concept_to_workspace(WS)
    ir = load_canonical_ir(WS)
    assert ir

    meta = {
        "commit": _git(["git", "rev-parse", "HEAD"]),
        "branch": _git(["git", "branch", "--show-current"]),
        "tag_canon_p1": _git(
            ["git", "rev-list", "-n", "1", "canon-p1-intelligence-complete"]
        ),
        "workspace": str(WS),
    }
    _dump("_meta.json", meta)

    # =====================================================================
    # CUSTODY — five acceptance cases, raw decision entries
    # =====================================================================
    p1_ir = _prop_ir(ir, "P1")
    baseline_ch1 = next(p for p in project_prop_state(ir, 1) if p["prop_id"] == "P1")
    baseline_ch2 = next(p for p in project_prop_state(ir, 2) if p["prop_id"] == "P1")
    baseline_ch3 = next(p for p in project_prop_state(ir, 3) if p["prop_id"] == "P1")
    baseline_ch12 = next(p for p in project_prop_state(ir, 12) if p["prop_id"] == "P1")

    c1_decision = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=1,
        proposed_holder="Mara",
        action="Adrian gives phone to Mara",
        source="prose_custody_chain",
    )
    c2_decision = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=2,
        proposed_holder="Det. Miller",
        action="Det. Miller seizes the phone",
        source="prose_possession",
    )
    c3_decision = evaluate_prop_holder_claim(
        ir=ir,
        prop_id="P1",
        chapter=1,
        proposed_holder="Mara",
        action="Mara destroys the Blood-stained phone forever",
        source="prose_prop_action",
    )

    poison_settlement = {
        "status": "sealed",
        "chapter": 2,
        "settlement_digest": "raw-poison-prop",
        "events_realized": [],
        "character_updates": {
            "deltas": {"character": "Mara Voss", "knows_gained": []}
        },
        "prop_updates": [
            {
                "prop_id": "P1",
                "name": "Blood-stained phone",
                "holder": "Det. Miller",
                "source": "prose_possession",
                "evidence": "fake seizure",
            }
        ],
        "strategy_updates": {},
    }
    intel_before_poison = compile_chapter_intelligence(ir, 3)
    p1_before_poison = next(
        p for p in intel_before_poison["prop_state"] if p["prop_id"] == "P1"
    )
    intel_after_poison = apply_settlement_to_intelligence(
        intel_before_poison, poison_settlement, chapter=3, ir=ir
    )
    p1_after_poison = next(
        p for p in intel_after_poison["prop_state"] if p["prop_id"] == "P1"
    )

    transfer_settle = build_settlement(
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
    p1_transfer_row = next(
        p for p in (transfer_settle.get("prop_updates") or []) if p.get("prop_id") == "P1"
    )
    intel_after_transfer = compile_chapter_intelligence(
        ir, 12, prior_settlement={**transfer_settle, "status": "sealed"}
    )
    p1_after_transfer = next(
        p for p in intel_after_transfer["prop_state"] if p["prop_id"] == "P1"
    )

    custody_raw = {
        "layer": "custody",
        "rule_names": [
            "evaluate_prop_holder_claim",
            "clamp_prop_updates_to_schedule",
            "physical_owner_by_chapter",
            "custody_chain",
            "chapter_map.prop_actions",
        ],
        "source_refs": {
            "prop_id": "P1",
            "prop_name": p1_ir.get("name"),
            "physical_owner_by_chapter": p1_ir.get("physical_owner_by_chapter"),
            "custody_chain": p1_ir.get("custody_chain"),
            "ir_baseline_holders": {
                "ch1": baseline_ch1,
                "ch2": baseline_ch2,
                "ch3": baseline_ch3,
                "ch12": baseline_ch12,
            },
        },
        "cases": [
            {
                "case_id": "C1_correct_holder_correct_action",
                "rule": "evaluate_prop_holder_claim",
                "expected": {
                    "decision": "allowed",
                    "holder": "Mara",
                    "reason_contains": "schedule_or_chain_match",
                },
                "actual_decision_entry": c1_decision,
                "pass": c1_decision.get("decision") == "allowed"
                and "Mara" in str(c1_decision.get("holder")),
            },
            {
                "case_id": "C2_wrong_holder",
                "rule": "evaluate_prop_holder_claim / holder_not_on_schedule",
                "expected": {
                    "decision": "clamped",
                    "holder": "Mara",
                    "reason": "holder_not_on_schedule",
                    "proposed_holder": "Det. Miller",
                },
                "actual_decision_entry": c2_decision,
                "pass": c2_decision.get("decision") == "clamped"
                and c2_decision.get("reason") == "holder_not_on_schedule"
                and "Mara" in str(c2_decision.get("holder")),
            },
            {
                "case_id": "C3_correct_holder_disallowed_action",
                "rule": "evaluate_prop_holder_claim / action_not_allowed",
                "expected": {
                    "decision": "clamped",
                    "reason": "action_not_allowed",
                    "proposed_holder": "Mara",
                    "action": "Mara destroys the Blood-stained phone forever",
                    "allowed_actions": ["Adrian gives phone to Mara"],
                },
                "actual_decision_entry": c3_decision,
                "pass": c3_decision.get("decision") == "clamped"
                and c3_decision.get("reason") == "action_not_allowed",
            },
            {
                "case_id": "C4_poisoned_settlement_reclamped",
                "rule": "apply_settlement_to_intelligence → clamp_prop_updates_to_schedule",
                "expected": {
                    "input_holder": "Det. Miller",
                    "output_holder_contains": "Mara",
                    "audit_decision": "clamped",
                    "audit_reason": "holder_not_on_schedule",
                    "source": "prose_possession",
                },
                "input_settlement_prop_updates": poison_settlement["prop_updates"],
                "prop_state_before_apply": p1_before_poison,
                "prop_state_after_apply": p1_after_poison,
                "prop_custody_audit": intel_after_poison.get("prop_custody_audit"),
                "prior_settlement_slice": (
                    intel_after_poison.get("prior_settlement") or {}
                ).get("prop_updates"),
                "pass": "Mara" in str(p1_after_poison.get("holder"))
                and any(
                    a.get("prop_id") == "P1"
                    and a.get("decision") == "clamped"
                    and a.get("reason") == "holder_not_on_schedule"
                    for a in (intel_after_poison.get("prop_custody_audit") or [])
                ),
            },
            {
                "case_id": "C5_verified_transfer_carries",
                "rule": "derive_prop_custody_deltas + schedule/chain match at ch12",
                "expected": {
                    "holder_contains": "Adrian",
                    "chapter": 12,
                    "chain_action": "Mara returns phone with decryption key",
                },
                "claims_input": transfer_settle.get("events_realized"),
                "settlement_prop_updates": transfer_settle.get("prop_updates"),
                "p1_transfer_row": p1_transfer_row,
                "p1_transfer_custody_audit": p1_transfer_row.get("custody_audit"),
                "prop_state_after_apply_ch12": p1_after_transfer,
                "pass": "Adrian" in str(p1_transfer_row.get("holder"))
                and "Adrian" in str(p1_after_transfer.get("holder"))
                and (p1_transfer_row.get("custody_audit") or {}).get("decision")
                == "allowed",
            },
        ],
    }
    custody_raw["all_cases_pass"] = all(c["pass"] for c in custody_raw["cases"])
    _dump("raw_custody_evidence.json", custody_raw)

    # =====================================================================
    # BELIEF — provenance + hidden truth
    # =====================================================================
    r5 = next(r for r in ir["reveal_schedule"] if r.get("id") == "R5")
    r4 = next(r for r in ir["reveal_schedule"] if r.get("id") == "R4")

    b1_kept, b1_audit = evaluate_belief_provenance(
        [
            {
                "text": "Professional suspicion sharpens.",
                "provenance": "observation",
                "ref": "may_observe",
            }
        ],
        ir,
        2,
        source="unit_probe",
        target="character_state.believes",
    )
    b2_kept, b2_audit = evaluate_belief_provenance(
        ["Orphan belief with no source at all."],
        ir,
        2,
        source="unit_probe",
        target="character_state.believes",
    )
    b3_kept, b3_audit = evaluate_belief_provenance(
        [{"text": r5["fact"], "provenance": "psychology", "ref": "inject_hidden"}],
        ir,
        2,
        source="unit_probe",
        target="character_state.misbeliefs",
    )
    dissonance = "Believes Adrian is a tool while being used by him as a predator"
    b4_kept, b4_audit = evaluate_belief_provenance(
        [{"text": dissonance, "provenance": "psychology", "ref": "cognitive_dissonance"}],
        ir,
        2,
        source="unit_probe",
        target="character_state.misbeliefs",
    )

    belief_raw = {
        "layer": "belief",
        "rule_names": [
            "evaluate_belief_provenance",
            "evaluate_knowledge_against_pov_clocks",
            "missing_provenance→omitted",
            "pov_clock_not_reached→clamped",
        ],
        "source_refs": {
            "R4": r4,
            "R5": r5,
            "allowed_provenance": [
                "observation",
                "psychology",
                "settlement",
                "inference",
                "canonical_ir",
                "prose_settlement",
                "chapter_map",
            ],
        },
        "cases": [
            {
                "case_id": "B1_belief_with_observation_provenance",
                "rule": "evaluate_belief_provenance / provenance_ok",
                "expected": {
                    "kept_contains": "Professional suspicion sharpens.",
                    "decision": "allowed",
                    "provenance": "observation",
                },
                "input": {
                    "text": "Professional suspicion sharpens.",
                    "provenance": "observation",
                    "ref": "may_observe",
                },
                "actual_kept": b1_kept,
                "actual_audit_entries": b1_audit,
                "pass": "Professional suspicion sharpens." in b1_kept
                and any(
                    a.get("decision") == "allowed"
                    and a.get("reason") == "provenance_ok"
                    for a in b1_audit
                ),
            },
            {
                "case_id": "B2_belief_missing_provenance",
                "rule": "evaluate_belief_provenance / missing_provenance",
                "expected": {
                    "kept": [],
                    "decision": "omitted",
                    "reason": "missing_provenance",
                },
                "input": {"text": "Orphan belief with no source at all."},
                "actual_kept": b2_kept,
                "actual_audit_entries": b2_audit,
                "pass": b2_kept == []
                and any(
                    a.get("decision") == "omitted"
                    and a.get("reason") == "missing_provenance"
                    for a in b2_audit
                ),
            },
            {
                "case_id": "B3_hidden_truth_as_misbelief_before_clock",
                "rule": "evaluate_belief_provenance → POV clock clamp",
                "expected": {
                    "kept_excludes_R5": True,
                    "decision": "clamped",
                    "reason": "pov_clock_not_reached",
                    "clock_used": "pov_knows_chapter",
                    "pov_knows_chapter": 9,
                    "current_chapter": 2,
                },
                "input": {
                    "text": r5["fact"],
                    "provenance": "psychology",
                    "reveal_id": "R5",
                    "reader_reveal_chapter": r5.get("reader_reveal_chapter"),
                    "pov_knows_chapter": r5.get("pov_knows_chapter"),
                },
                "actual_kept": b3_kept,
                "actual_audit_entries": b3_audit,
                "pass": r5["fact"] not in b3_kept
                and any(
                    a.get("decision") == "clamped"
                    and a.get("clock_used") == "pov_knows_chapter"
                    and a.get("reason") == "pov_clock_not_reached"
                    and int(a.get("pov_knows_chapter") or 0) == 9
                    for a in b3_audit
                ),
            },
            {
                "case_id": "B4_psychology_misbelief_allowed",
                "rule": "evaluate_belief_provenance / psychology",
                "expected": {
                    "kept_contains": dissonance,
                    "decision": "allowed",
                    "provenance": "psychology",
                },
                "input": {
                    "text": dissonance,
                    "provenance": "psychology",
                    "ref": "cognitive_dissonance",
                },
                "actual_kept": b4_kept,
                "actual_audit_entries": b4_audit,
                "pass": dissonance in b4_kept
                and any(a.get("decision") == "allowed" for a in b4_audit),
            },
        ],
    }
    belief_raw["all_cases_pass"] = all(c["pass"] for c in belief_raw["cases"])
    _dump("raw_belief_evidence.json", belief_raw)

    # =====================================================================
    # STRATEGY — semantic fact_refs mutations
    # =====================================================================
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
    s_irrelevant = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara scrapes Claire Thorne's data.",
                "fact_refs": ["F_REVEAL_R8"],
            }
        },
        ir=ir,
        chapter=2,
    )
    s_wrong_actor = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Adrian Thorne scrapes Claire Thorne's data.",
                "fact_refs": ["F_MAP_CH2_must_happen_0"],
            }
        },
        ir=ir,
        chapter=2,
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
    s_wrong_prop = validate_move_fact_refs(
        {
            "countermove": {
                "action": "Mara destroys the Blood-stained phone forever.",
                "fact_refs": ["F_PROP_P1"],
            }
        },
        ir=ir,
        chapter=2,
    )
    intel2_moves = compile_chapter_intelligence(ir, 2)["moves"]
    s_builtin = validate_move_fact_refs(intel2_moves, ir=ir, chapter=2)

    strategy_raw = {
        "layer": "strategy",
        "rule_names": [
            "validate_move_fact_refs",
            "move_missing_fact_refs",
            "move_irrelevant_fact_refs",
            "move_wrong_actor",
            "move_future_fact_ref",
            "move_prop_action_not_allowed",
            "move_forbidden_event",
        ],
        "source_refs": {
            "chapter": 2,
            "builtin_moves": intel2_moves,
            "R5_pov_knows_chapter": r5.get("pov_knows_chapter"),
            "F_REVEAL_R5_exists": any(
                str(f.get("fact_id")) == "F_REVEAL_R5" for f in (ir.get("facts") or [])
            ),
            "F_PROP_P1_exists": any(
                str(f.get("fact_id")) == "F_PROP_P1" for f in (ir.get("facts") or [])
            ),
        },
        "cases": [
            {
                "case_id": "S1_missing_ref",
                "rule": "move_missing_fact_refs",
                "expected": {"error_reason": "move_missing_fact_refs", "severity": "block"},
                "input": {
                    "countermove": {
                        "action": "Mara scrapes Claire Thorne's data.",
                        "fact_refs": [],
                    }
                },
                "actual_errors": s_missing,
                "pass": any(e.get("reason") == "move_missing_fact_refs" for e in s_missing),
            },
            {
                "case_id": "S2_irrelevant_or_future_ref",
                "rule": "move_irrelevant_fact_refs | move_future_fact_ref",
                "expected": {
                    "error_reason_in": [
                        "move_irrelevant_fact_refs",
                        "move_future_fact_ref",
                    ]
                },
                "input": {
                    "countermove": {
                        "action": "Mara scrapes Claire Thorne's data.",
                        "fact_refs": ["F_REVEAL_R8"],
                    }
                },
                "actual_errors": s_irrelevant,
                "pass": any(
                    e.get("reason")
                    in {"move_irrelevant_fact_refs", "move_future_fact_ref"}
                    for e in s_irrelevant
                ),
            },
            {
                "case_id": "S3_wrong_actor",
                "rule": "move_wrong_actor",
                "expected": {"error_reason": "move_wrong_actor"},
                "input": {
                    "countermove": {
                        "action": "Adrian Thorne scrapes Claire Thorne's data.",
                        "fact_refs": ["F_MAP_CH2_must_happen_0"],
                    }
                },
                "actual_errors": s_wrong_actor,
                "pass": any(e.get("reason") == "move_wrong_actor" for e in s_wrong_actor),
            },
            {
                "case_id": "S4_future_ref",
                "rule": "move_future_fact_ref",
                "expected": {
                    "error_reason": "move_future_fact_ref",
                    "fact_ref": "F_REVEAL_R5",
                    "current_chapter": 2,
                    "pov_knows_chapter": 9,
                },
                "input": {
                    "countermove": {
                        "action": "Mara finds the backdoor in her alibi software.",
                        "fact_refs": ["F_REVEAL_R5"],
                    }
                },
                "actual_errors": s_future,
                "pass": any(e.get("reason") == "move_future_fact_ref" for e in s_future),
            },
            {
                "case_id": "S5_wrong_prop_action",
                "rule": "move_prop_action_not_allowed",
                "expected": {"error_reason": "move_prop_action_not_allowed"},
                "input": {
                    "countermove": {
                        "action": "Mara destroys the Blood-stained phone forever.",
                        "fact_refs": ["F_PROP_P1"],
                    }
                },
                "actual_errors": s_wrong_prop,
                "pass": any(
                    e.get("reason") == "move_prop_action_not_allowed" for e in s_wrong_prop
                ),
            },
            {
                "case_id": "S6_builtin_ir_moves_no_false_positive",
                "rule": "validate_move_fact_refs on compile_chapter_intelligence moves",
                "expected": {"errors": []},
                "actual_errors": s_builtin,
                "pass": s_builtin == [],
            },
        ],
    }
    strategy_raw["all_cases_pass"] = all(c["pass"] for c in strategy_raw["cases"])
    _dump("raw_strategy_evidence.json", strategy_raw)

    # =====================================================================
    # LIVE N→N+1 — settlement override + packet digests + prop clamp
    # =====================================================================
    sealed2 = seal_chapter_plan(
        WS,
        1,
        {
            "chapter": 2,
            "title": "Anticoagulant",
            "must_happen": [
                "Mara observes anticoagulant treatment on the blood-stained phone."
            ],
            "beat_summary": (
                "She scrapes Claire Thorne data and confirms anticoagulant staging."
            ),
            "must_not": ["Mara leaves the office."],
        },
        ir=ir,
    )
    built2 = build_and_seal_chapter_artifacts(
        WS, 1, 2, sealed2["repaired_plan"], ir=ir
    )
    packet2 = built2["packet"]

    settle_a = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
                {"claim": "The blood was treated with anticoagulants.", "kind": "event"},
                {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
                {
                    "claim": "Mara retains custody of the Zero-Day Server.",
                    "kind": "event",
                },
            ],
        },
        intelligence=compile_chapter_intelligence(ir, 2),
        ir=ir,
    )
    write_settlement(WS, 1, 2, settle_a)

    plan3 = {
        "chapter": 3,
        "title": "Next",
        "must_happen": ["Mara creates the false alibi."],
        "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
        "must_not": ["Mara leaves the office."],
        "carries_to_next": "Outliner invents a yacht chase Mara never saw",
    }
    sealed3 = seal_chapter_plan(WS, 1, plan3, ir=ir)
    built3_a = build_and_seal_chapter_artifacts(
        WS, 1, 3, sealed3["repaired_plan"], ir=ir
    )
    packet3_a = built3_a["packet"]
    contract3_a = built3_a["contract"]

    settle_b = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
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
    write_settlement(WS, 1, 2, settle_b)
    built3_b = build_and_seal_chapter_artifacts(
        WS, 1, 3, sealed3["repaired_plan"], ir=ir
    )
    packet3_b = built3_b["packet"]

    def _mara(packet: dict) -> dict:
        for row in packet.get("character_state") or []:
            if "Mara" in str(row.get("character") or ""):
                return row
        return {}

    def _props(packet: dict) -> dict:
        return {p["prop_id"]: p for p in (packet.get("prop_state") or [])}

    mara_a = _mara(packet3_a)
    mara_b = _mara(packet3_b)
    props_a = _props(packet3_a)
    props_b = _props(packet3_b)

    packet_diff = {
        "packet_a_digest": packet3_a.get("packet_digest"),
        "packet_b_digest": packet3_b.get("packet_digest"),
        "digests_differ": packet3_a.get("packet_digest")
        != packet3_b.get("packet_digest"),
        "contract_a_digest": contract3_a.get("contract_digest"),
        "knows_a": mara_a.get("knows"),
        "knows_b": mara_b.get("knows"),
        "prop_P1_a": props_a.get("P1"),
        "prop_P1_b": props_b.get("P1"),
        "prop_P2_a": props_a.get("P2"),
        "continuity_a": packet3_a.get("continuity"),
        "continuity_b": packet3_b.get("continuity"),
        "prior_settlement_a": packet3_a.get("prior_settlement"),
        "prior_settlement_b": packet3_b.get("prior_settlement"),
        "required_events_a": packet3_a.get("required_events"),
        "required_events_b": packet3_b.get("required_events"),
    }
    _dump("raw_packet_diff.json", packet_diff)

    override_trace = {
        "rule": "continuity_from_prior: settlement > Outliner carries_to_next; IR schedule > settlement",
        "plan_carries_to_next": plan3.get("carries_to_next"),
        "settlement_a": {
            "digest": settle_a.get("settlement_digest"),
            "character_updates": settle_a.get("character_updates"),
            "prop_updates": settle_a.get("prop_updates"),
            "events_realized": settle_a.get("events_realized"),
            "knowledge_audit": (settle_a.get("character_updates") or {})
            .get("deltas", {})
            .get("knowledge_audit"),
        },
        "settlement_b": {
            "digest": settle_b.get("settlement_digest"),
            "character_updates": settle_b.get("character_updates"),
            "prop_updates": settle_b.get("prop_updates"),
            "events_realized": settle_b.get("events_realized"),
            "p1_row": next(
                (
                    p
                    for p in (settle_b.get("prop_updates") or [])
                    if p.get("prop_id") == "P1"
                ),
                None,
            ),
        },
        "packet3_a_continuity": packet3_a.get("continuity"),
        "packet3_b_continuity": packet3_b.get("continuity"),
        "assertions": {
            "settlement_supersedes_carries_to_next_a": (
                (packet3_a.get("continuity") or {}).get("source") == "settlement"
                and (packet3_a.get("continuity") or {}).get("plan_foresight_superseded")
                is True
                and (packet3_a.get("continuity") or {}).get("carries_to_next") is None
            ),
            "r4_in_knows_a": any(
                "anticoagulant" in str(k).casefold() for k in (mara_a.get("knows") or [])
            ),
            "illegal_p1_transfer_clamped_in_b": "Mara"
            in str((props_b.get("P1") or {}).get("holder")),
            "packet_digest_changed_when_settlement_changed": packet_diff[
                "digests_differ"
            ],
        },
    }
    override_trace["pass"] = all(override_trace["assertions"].values())
    _dump("raw_settlement_override_trace.json", override_trace)

    live_raw = {
        "layer": "live_n_to_n1",
        "rule_names": [
            "build_settlement",
            "write_settlement",
            "compile_chapter_intelligence(prior_settlement)",
            "apply_settlement_to_intelligence",
            "continuity_from_prior",
            "compile_writer_packet",
        ],
        "chapter_N": 2,
        "chapter_N1": 3,
        "plan_N1_carries_to_next": plan3.get("carries_to_next"),
        "packet2_digest": packet2.get("packet_digest"),
        "cases": [
            {
                "case_id": "L1_settlement_A_memory_and_override",
                "settlement_digest": settle_a.get("settlement_digest"),
                "continuity": packet3_a.get("continuity"),
                "mara_knows": mara_a.get("knows"),
                "prop_P1": props_a.get("P1"),
                "prop_P2": props_a.get("P2"),
                "prior_settlement_writer_facing": packet3_a.get("prior_settlement"),
                "expected": {
                    "continuity.source": "settlement",
                    "carries_to_next": None,
                    "plan_foresight_superseded": True,
                    "knows_contains_anticoagulant": True,
                },
                "pass": override_trace["assertions"][
                    "settlement_supersedes_carries_to_next_a"
                ]
                and override_trace["assertions"]["r4_in_knows_a"],
            },
            {
                "case_id": "L2_settlement_B_illegal_transfer_clamped",
                "settlement_digest": settle_b.get("settlement_digest"),
                "settlement_b_p1_row_full": next(
                    (
                        p
                        for p in (settle_b.get("prop_updates") or [])
                        if p.get("prop_id") == "P1"
                    ),
                    None,
                ),
                "continuity": packet3_b.get("continuity"),
                "mara_knows": mara_b.get("knows"),
                "prop_P1": props_b.get("P1"),
                "expected": {
                    "P1_holder_contains": "Mara",
                    "reason": "illegal early transfer clamped by IR schedule",
                },
                "pass": "Mara" in str((props_b.get("P1") or {}).get("holder")),
            },
            {
                "case_id": "L3_packet_digest_changes_with_settlement",
                "packet_a_digest": packet3_a.get("packet_digest"),
                "packet_b_digest": packet3_b.get("packet_digest"),
                "pass": packet_diff["digests_differ"],
            },
        ],
    }
    live_raw["all_cases_pass"] = all(c["pass"] for c in live_raw["cases"])
    _dump("raw_live_n1_evidence.json", live_raw)

    # Also dump full sealed artifacts used
    _dump(
        "artifact_settlement_a.json",
        settle_a,
    )
    _dump("artifact_settlement_b.json", settle_b)
    _dump("artifact_packet3_a.json", packet3_a)
    _dump("artifact_packet3_b.json", packet3_b)
    _dump(
        "artifact_contract3_a_intelligence_prior.json",
        (contract3_a.get("intelligence") or {}).get("prior_settlement"),
    )

    gate = {
        "meta": meta,
        "custody_all_cases_pass": custody_raw["all_cases_pass"],
        "belief_all_cases_pass": belief_raw["all_cases_pass"],
        "strategy_all_cases_pass": strategy_raw["all_cases_pass"],
        "live_all_cases_pass": live_raw["all_cases_pass"],
        "override_trace_pass": override_trace["pass"],
        "case_pass_matrix": {
            "custody": {c["case_id"]: c["pass"] for c in custody_raw["cases"]},
            "belief": {c["case_id"]: c["pass"] for c in belief_raw["cases"]},
            "strategy": {c["case_id"]: c["pass"] for c in strategy_raw["cases"]},
            "live": {c["case_id"]: c["pass"] for c in live_raw["cases"]},
        },
        "p1_overall_complete_by_raw_evidence": all(
            [
                custody_raw["all_cases_pass"],
                belief_raw["all_cases_pass"],
                strategy_raw["all_cases_pass"],
                live_raw["all_cases_pass"],
                override_trace["pass"],
            ]
        ),
        "files": [
            "raw_custody_evidence.json",
            "raw_belief_evidence.json",
            "raw_strategy_evidence.json",
            "raw_live_n1_evidence.json",
            "raw_packet_diff.json",
            "raw_settlement_override_trace.json",
            "artifact_settlement_a.json",
            "artifact_settlement_b.json",
            "artifact_packet3_a.json",
            "artifact_packet3_b.json",
            "artifact_contract3_a_intelligence_prior.json",
        ],
    }
    _dump("RAW_EVIDENCE_GATE.json", gate)
    print(json.dumps(gate, indent=2, ensure_ascii=False))
    return 0 if gate["p1_overall_complete_by_raw_evidence"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
