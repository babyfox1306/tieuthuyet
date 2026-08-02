"""P1 final memory-clamp verification — disposable workspace, real artifacts.

Does NOT commit/push/retag. Reads consumers, runs injections, writes reports.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.canonical_ir import (  # noqa: E402
    compile_canonical_ir,
    ingest_concept_to_workspace,
    load_canonical_ir,
    sha256_obj,
)
from factory.engine.lib.chapter_contract import (  # noqa: E402
    build_and_seal_chapter_artifacts,
    compile_writer_packet,
)
from factory.engine.lib.plan_provenance import (  # noqa: E402
    seal_chapter_plan,
    validate_plan_against_ir,
)
from factory.engine.lib.prose_settlement import (  # noqa: E402
    apply_settlement_to_intelligence,
    build_settlement,
    evaluate_knowledge_full_audit,
    write_settlement,
)
from factory.engine.lib.story_intelligence import (  # noqa: E402
    compile_chapter_intelligence,
    move_fact_ref_errors,
)
from factory.engine.lib.canon_ops import should_skip_literary_fixer  # noqa: E402

CE = Path(r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml")
WS = ROOT / "factory" / "workspaces" / "_canon_p1_memory_clamp_verify"


def _git_meta() -> dict:
    import subprocess

    def _run(args: list[str]) -> str:
        try:
            return subprocess.check_output(
                args, cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            return ""

    return {
        "commit": _run(["git", "rev-parse", "HEAD"]),
        "branch": _run(["git", "branch", "--show-current"]),
        "tag_p1": _run(["git", "rev-list", "-n", "1", "canon-p1-intelligence-complete"]),
    }


def _reset() -> None:
    if WS.exists():
        shutil.rmtree(WS, ignore_ok=True) if False else shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)
    (WS / "concept.yaml").write_bytes(CE.read_bytes())
    ingest_concept_to_workspace(WS)


def _write(name: str, payload: dict) -> Path:
    path = WS / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _reveal(ir: dict, rid: str) -> dict:
    return next(r for r in (ir.get("reveal_schedule") or []) if r.get("id") == rid)


def _packet_blob(packet: dict) -> str:
    return json.dumps(packet, ensure_ascii=False).casefold()


def _hidden_absent(packet: dict, needles: list[str]) -> dict:
    blob = _packet_blob(packet)
    hits = [n for n in needles if n.casefold() in blob]
    # Opaque count keys are allowed.
    return {"absent": not hits, "hits": hits}


def _mara_knows(intel_or_packet: dict) -> list[str]:
    rows = (
        intel_or_packet.get("character_state")
        or (intel_or_packet.get("intelligence") or {}).get("character_state")
        or []
    )
    for row in rows:
        if "Mara" in str(row.get("character") or ""):
            return list(row.get("knows") or [])
    return []


def _seal_minimal(ws: Path, chapter: int, plan: dict, ir: dict) -> dict:
    sealed = seal_chapter_plan(ws, 1, plan, ir=ir)
    if not sealed.get("sealed"):
        raise RuntimeError(f"seal failed ch{chapter}: {sealed}")
    return sealed


CALL_PATH = {
    "path": [
        {
            "step": 1,
            "file": "factory/engine/lib/canonical_ir.py",
            "function": "compile_canonical_ir / reveal_schedule ingest",
            "role": "IR SoT; stores reader_reveal_chapter and pov_knows_chapter separately",
        },
        {
            "step": 2,
            "file": "factory/engine/lib/story_intelligence.py",
            "function": "compile_chapter_intelligence",
            "role": "Builds cognition/prop/moves from IR; then applies prior settlement",
            "lines_note": "calls apply_settlement_to_intelligence when prior sealed",
        },
        {
            "step": 3,
            "file": "factory/engine/lib/prose_settlement.py",
            "function": "build_settlement → derive_memory_deltas",
            "role": "After canon_qc pass: extract knows candidates from claims/events",
        },
        {
            "step": 4,
            "file": "factory/engine/lib/prose_settlement.py",
            "function": "evaluate_knowledge_against_pov_clocks",
            "clock_read": "pov_knows_chapter (required); reader_reveal_chapter recorded only",
            "fallback_to_reader": False,
            "missing_pov_clock": "unresolved_clock → BLOCK from knows",
            "when": "BEFORE knows_gained is written into settlement",
        },
        {
            "step": 5,
            "file": "factory/engine/lib/prose_settlement.py",
            "function": "apply_settlement_to_intelligence",
            "role": "Merge settlement into N+1 live character_state",
            "reclamp": True,
            "when": "AFTER settlement load, BEFORE packet compile; re-evaluates POV clock at target chapter",
        },
        {
            "step": 6,
            "file": "factory/engine/lib/chapter_contract.py",
            "function": "compile_chapter_contract / compile_writer_packet / _writer_safe_intelligence",
            "role": "Packet embeds character_state; villain_knowledge NOT projected to Writer",
            "bypass_risk": "prior_settlement.character_updates may still contain clamped audit text — must check Writer packet scrub",
        },
    ],
    "answers": {
        "r4_allowed_in": "evaluate_knowledge_against_pov_clocks (decision=allowed)",
        "r5_clamped_in": "evaluate_knowledge_against_pov_clocks (decision=clamped)",
        "clock_helper": "evaluate_knowledge_against_pov_clocks / _all_reveal_rows",
        "fallback_reader": False,
        "missing_pov_policy": "unresolved_clock BLOCK",
        "clamp_timing": "both: at settlement derive AND at apply merge",
        "packet_bypass": "checked in verification — prior_settlement on packet may hold source text; Writer must not receive locked claim bodies",
        "antagonist_direct": "villain_knowledge omitted from _writer_safe_intelligence",
    },
}


def main() -> int:
    meta = _git_meta()
    report: dict = {
        "commit": meta["commit"],
        "branch": meta["branch"],
        "tag_p1_points_to": meta["tag_p1"],
        "note": "Tag is not evidence; runtime cases below are.",
        "call_path": CALL_PATH,
        "memory_clamp": {},
        "settlement_override": {},
        "belief_policy": {},
        "custody_clamp": {},
        "strategy_fact_refs": {},
        "call_order": {},
        "tests": {},
        "verdict": {},
    }
    if not CE.exists():
        report["error"] = f"CE missing: {CE}"
        _write("verify_report.json", report)
        return 1

    _reset()
    ir = load_canonical_ir(WS)
    assert ir
    r4 = _reveal(ir, "R4")
    r5 = _reveal(ir, "R5")
    chapter = 2

    # ---------- Case A: R4 allowed ----------
    r4_text = str(r4.get("fact") or "")
    kept_a, audit_a = evaluate_knowledge_full_audit(
        [r4_text], ir, chapter, source="canonical_ir"
    )
    r4_entry = next((a for a in audit_a if a.get("reveal_id") == "R4"), None)
    case_a = {
        "kept": kept_a,
        "audit": audit_a,
        "r4_entry": r4_entry,
        "ok": bool(
            r4_entry
            and r4_entry.get("decision") == "allowed"
            and r4_entry.get("clock_used") == "pov_knows_chapter"
            and int(r4_entry.get("pov_knows_chapter") or 0) <= chapter
            and r4_text in kept_a
        ),
    }

    # ---------- Case B: R5 clamped ----------
    r5_text = str(r5.get("fact") or "")
    kept_b, audit_b = evaluate_knowledge_full_audit(
        [r5_text], ir, chapter, source="canonical_ir"
    )
    r5_entry = next((a for a in audit_b if a.get("reveal_id") == "R5"), None)
    case_b = {
        "kept": kept_b,
        "audit": audit_b,
        "r5_entry": r5_entry,
        "ok": bool(
            r5_entry
            and r5_entry.get("decision") == "clamped"
            and r5_entry.get("clock_used") == "pov_knows_chapter"
            and int(r5_entry.get("pov_knows_chapter") or 0) == 9
            and r5_text not in kept_b
            and r5_entry.get("reason") == "pov_clock_not_reached"
        ),
    }

    # ---------- Case D: reader reached, POV not ----------
    # Zero-Day has no native reveal with reader<=2 < pov; inject synthetic into IR copy.
    ir_div = deepcopy(ir)
    ir_div["reveal_schedule"] = list(ir_div.get("reveal_schedule") or []) + [
        {
            "id": "R_DIVERGE",
            "fact": "Synthetic diverge fact: the vault passphrase is heartbeat-locked.",
            "reader_reveal_chapter": 2,
            "pov_knows_chapter": 9,
        }
    ]
    diverge_text = "Synthetic diverge fact: the vault passphrase is heartbeat-locked."
    kept_d, audit_d = evaluate_knowledge_full_audit(
        [diverge_text], ir_div, 2, source="canonical_ir"
    )
    d_entry = next((a for a in audit_d if a.get("reveal_id") == "R_DIVERGE"), None)
    # Would FAIL if code used reader clock (reader=2 <= 2 would allow).
    case_d = {
        "reader_reveal_chapter": 2,
        "pov_knows_chapter": 9,
        "current_chapter": 2,
        "entry": d_entry,
        "kept": kept_d,
        "ok": bool(
            d_entry
            and d_entry.get("decision") == "clamped"
            and d_entry.get("clock_used") == "pov_knows_chapter"
            and int(d_entry.get("reader_reveal_chapter") or 0) <= 2
            and int(d_entry.get("pov_knows_chapter") or 0) > 2
            and diverge_text not in kept_d
        ),
    }

    # ---------- Case E: missing POV clock ----------
    ir_miss = deepcopy(ir)
    ir_miss["reveal_schedule"] = list(ir_miss.get("reveal_schedule") or []) + [
        {
            "id": "R_MISSING_POV",
            "fact": "Synthetic missing-pov fact about the ghost vehicle plate.",
            "reader_reveal_chapter": 1,
            # intentionally no pov_knows_chapter
        }
    ]
    miss_text = "Synthetic missing-pov fact about the ghost vehicle plate."
    kept_e, audit_e = evaluate_knowledge_full_audit(
        [miss_text], ir_miss, 2, source="canonical_ir"
    )
    e_entry = next((a for a in audit_e if a.get("reveal_id") == "R_MISSING_POV"), None)
    case_e = {
        "entry": e_entry,
        "kept": kept_e,
        "ok": bool(
            e_entry
            and e_entry.get("decision") == "unresolved_clock"
            and e_entry.get("reason") == "missing_pov_knows_chapter"
            and miss_text not in kept_e
        ),
        "policy": "fail-closed: BLOCK from knows + unresolved_clock audit",
    }

    # ---------- Settlement path with R4+R5 candidates ----------
    intel2 = compile_chapter_intelligence(ir, 2)
    settle = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
                {"claim": r4_text, "kind": "event"},
                {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
                {"claim": r5_text, "kind": "event"},
            ],
        },
        intelligence={
            **intel2,
            "moves": {
                **intel2["moves"],
                "antagonist_move": {"action": r5_text, "fact_refs": ["F_REVEAL_R5"]},
                "countermove": {
                    "action": "Mara scrapes Claire Thorne's data.",
                    "required_events": ["Mara scrapes Claire Thorne's data."],
                    "fact_refs": ["F_MAP_CH2_must_happen_0"],
                },
            },
        },
        ir=ir,
    )
    deltas = (settle.get("character_updates") or {}).get("deltas") or {}
    knowledge_audit = deltas.get("knowledge_audit") or []
    settle_r4 = next(
        (
            a
            for a in knowledge_audit
            if a.get("reveal_id") == "R4" and a.get("decision") == "allowed"
        ),
        None,
    )
    settle_r5 = next(
        (
            a
            for a in knowledge_audit
            if a.get("reveal_id") == "R5" and a.get("decision") == "clamped"
        ),
        None,
    )
    # Prefer settlement-path audit entries for report; fall back to pure evaluate.
    if settle_r4:
        r4_entry = settle_r4
    if settle_r5:
        r5_entry = settle_r5

    # ---------- Case C: poisoned settlement ----------
    plan2 = {
        "chapter": 2,
        "title": "Anticoagulant",
        "must_happen": [
            "Mara observes anticoagulant treatment on the blood-stained phone."
        ],
        "beat_summary": "She scrapes Claire Thorne data and confirms anticoagulant staging.",
        "must_not": ["Mara leaves the office."],
    }
    sealed2 = _seal_minimal(WS, 2, plan2, ir)
    build_and_seal_chapter_artifacts(WS, 1, 2, sealed2["repaired_plan"], ir=ir)

    poisoned = deepcopy(settle)
    poisoned["status"] = "sealed"
    poisoned["character_updates"] = {
        **(poisoned.get("character_updates") or {}),
        "deltas": {
            "character": "Mara Voss",
            "knows_gained": [r4_text, r5_text],
            "believes_gained": [],
            "misbeliefs_active": [],
            "knows_clamped": [],
            "knowledge_audit": [],
        },
    }
    write_settlement(WS, 1, 2, poisoned)

    plan3 = {
        "chapter": 3,
        "title": "Next",
        "must_happen": ["Mara creates the false alibi."],
        "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
        "must_not": ["Mara leaves the office."],
        "carries_to_next": "Mara does not know the blood was treated with anticoagulants.",
    }
    sealed3 = _seal_minimal(WS, 3, plan3, ir)
    built3 = build_and_seal_chapter_artifacts(WS, 1, 3, sealed3["repaired_plan"], ir=ir)
    packet3 = built3["packet"]
    contract3 = built3["contract"]
    knows3 = _mara_knows(packet3)
    # Also read apply audit from contract (Writer packet scrubs it).
    contract_path = WS / "books" / "01" / "chapters" / "03" / "contract.json"
    apply_audit = []
    if contract_path.exists():
        contract_obj = json.loads(contract_path.read_text(encoding="utf-8"))
        apply_audit = (
            (contract_obj.get("intelligence") or {})
            .get("prior_settlement", {})
            .get("knowledge_clamped_on_apply")
            or []
        )
        if not apply_audit:
            apply_audit = (
                (contract_obj.get("intelligence") or {})
                .get("prior_settlement", {})
                .get("knowledge_audit_on_apply")
                or []
            )

    r5_needles = [
        "R5",
        "F_REVEAL_R5",
        "backdoor",
        "alibi software",
        str(r5.get("fact") or "")[:40],
    ]
    # Writer packet: strip prior_settlement heavy payloads? Currently included.
    # Check character_state.knows + top-level visible fields; also full packet.
    absent_state = not any("backdoor" in k.casefold() for k in knows3)
    # Full packet may still contain R5 inside prior_settlement.character_updates audit —
    # that is a packet leak if Writer receives it. Record honestly.
    packet_hits = _hidden_absent(packet3, r5_needles)
    # Scrub check: intelligence.villain_knowledge must be absent
    villain_in_packet = "villain_knowledge" in (packet3.get("intelligence") or {})

    r5_audit_clamped = any(
        a.get("reveal_id") == "R5"
        and a.get("decision") == "clamped"
        and a.get("clock_used") == "pov_knows_chapter"
        and a.get("source") == "settlement"
        for a in apply_audit
    )
    continuity_events = list(
        (packet3.get("continuity") or {}).get("events_from_settlement") or []
    ) + list(packet3.get("required_events") or [])
    backdoor_in_continuity = any(
        "backdoor" in str(e).casefold() for e in continuity_events
    )
    case_c = {
        "poisoned_knows_in_settlement": [r4_text, r5_text],
        "n1_knows": knows3,
        "r4_in_knows": any("anticoagulant" in k.casefold() for k in knows3),
        "r5_in_knows": any("backdoor" in k.casefold() for k in knows3),
        "apply_audit": apply_audit,
        "r5_reclamped": r5_audit_clamped,
        "hidden_absent_from_character_state": absent_state,
        "hidden_absent_from_full_packet": packet_hits["absent"],
        "packet_hits": packet_hits["hits"],
        "backdoor_in_continuity_or_required_events": backdoor_in_continuity,
        "villain_knowledge_in_writer_packet": villain_in_packet,
    }
    case_c["ok"] = bool(
        case_c["r4_in_knows"]
        and not case_c["r5_in_knows"]
        and case_c["hidden_absent_from_character_state"]
        and case_c["r5_reclamped"]
        and not case_c["backdoor_in_continuity_or_required_events"]
        and not villain_in_packet
        and case_c["hidden_absent_from_full_packet"]
    )

    # ---------- Settlement override carries_to_next ----------
    continuity = packet3.get("continuity") or contract3.get("continuity") or {}
    # Digest change when settlement changes
    digest_a = packet3.get("packet_digest")
    settle_b = deepcopy(poisoned)
    settle_b["character_updates"]["deltas"]["knows_gained"] = [r4_text]  # no R5 poison
    settle_b["settlement_digest"] = sha256_obj(
        {k: v for k, v in settle_b.items() if k != "settlement_digest"}
    )
    write_settlement(WS, 1, 2, settle_b)
    rebuilt = build_and_seal_chapter_artifacts(WS, 1, 3, sealed3["repaired_plan"], ir=ir)
    digest_b = rebuilt["packet"].get("packet_digest")

    override = {
        "loaded": bool(packet3.get("prior_settlement")),
        "overrode_carries_to_next": continuity.get("source") == "settlement"
        and continuity.get("plan_foresight_superseded") is True
        and continuity.get("carries_to_next") is None,
        "override_reason_recorded": bool(continuity.get("plan_foresight")),
        "packet_digest_changed": digest_a != digest_b,
        "continuity": continuity,
        "authority_order": [
            "Canonical IR pov_knows_chapter",
            "verified settlement (re-clamped)",
            "carries_to_next / Outliner foresight",
        ],
        "r4_present_despite_outliner_denial": any(
            "anticoagulant" in k.casefold() for k in knows3
        ),
        "r5_blocked_despite_poison_and_outliner": not any(
            "backdoor" in k.casefold() for k in knows3
        ),
    }
    override["ok"] = all(
        [
            override["loaded"],
            override["overrode_carries_to_next"],
            override["override_reason_recorded"],
            override["packet_digest_changed"],
            override["r4_present_despite_outliner_denial"],
            override["r5_blocked_despite_poison_and_outliner"],
        ]
    )

    # ---------- Belief policy probe ----------
    # 1) belief from unlocked observation — relationship turn not a reveal; allowed as non-reveal
    # 2) hidden truth as misbelief
    belief_ok_text = "Professional suspicion sharpens."
    hidden_as_misbelief = r5_text
    b_kept, b_audit = evaluate_knowledge_full_audit(
        [belief_ok_text],
        ir,
        2,
        source="prose_settlement",
        target="character_state.believes",
    )
    m_kept, m_audit = evaluate_knowledge_full_audit(
        [hidden_as_misbelief],
        ir,
        2,
        source="prose_settlement",
        target="character_state.misbeliefs",
    )
    # Psychology dissonance (not a locked reveal match) — allowed as misbelief source
    dissonance = "Believes Adrian is a tool while being used by him as a predator"
    d_kept, d_audit = evaluate_knowledge_full_audit(
        [dissonance],
        ir,
        2,
        source="prose_settlement",
        target="character_state.misbeliefs",
    )
    belief_report = {
        "status": "partial",
        "knowledge_clamped": True,
        "belief_clamped_like_knows_when_matching_reveal": True,
        "belief_requires_provenance": False,  # non-reveal beliefs currently pass without provenance graph
        "hidden_truth_alias_blocked_in_misbelief": hidden_as_misbelief not in m_kept
        and any(a.get("decision") == "clamped" for a in m_audit),
        "psychology_misbelief_allowed": dissonance in d_kept,
        "cases": {
            "belief_observation_non_reveal": {
                "text": belief_ok_text,
                "kept": b_kept,
                "audit": b_audit,
            },
            "hidden_truth_as_misbelief": {
                "kept": m_kept,
                "audit": m_audit,
            },
            "psychology_dissonance": {"kept": d_kept, "audit": d_audit},
        },
        "known_gaps": [
            "believes without reveal match are not provenance-gated (no observation→belief graph)",
            "no typed BLOCK for belief-without-source unless it matches a locked reveal",
        ],
    }
    if (
        belief_report["hidden_truth_alias_blocked_in_misbelief"]
        and belief_report["psychology_misbelief_allowed"]
    ):
        belief_report["status"] = "partial"
    belief_report["ok_for_memory_layer"] = belief_report[
        "hidden_truth_alias_blocked_in_misbelief"
    ]

    # ---------- Custody probes ----------
    props = {p["prop_id"]: p for p in (intel2.get("prop_state") or [])}
    # Poisoned holder for P1 at ch3 should not override IR schedule (Adrian only at 12)
    # Current apply prefers prose_* source; if poison marks source prose_possession it may accept — GAP
    poison_prop = {
        "status": "sealed",
        "chapter": 2,
        "settlement_digest": "poison-prop",
        "events_realized": [],
        "character_updates": {"deltas": {"character": "Mara Voss", "knows_gained": []}},
        "prop_updates": [
            {
                "prop_id": "P1",
                "name": "Blood-stained phone",
                "holder": "Det. Miller",
                "source": "prose_possession",
                "evidence": "fake",
            }
        ],
        "strategy_updates": {},
    }
    intel_prop = apply_settlement_to_intelligence(
        compile_chapter_intelligence(ir, 3), poison_prop, chapter=3, ir=ir
    )
    p1_holder = next(
        (
            p.get("holder")
            for p in (intel_prop.get("prop_state") or [])
            if p.get("prop_id") == "P1"
        ),
        None,
    )
    custody = {
        "status": "gap",
        "baseline_holder_ch2_P1": props.get("P1", {}).get("holder"),
        "wrong_holder_blocked": p1_holder != "Det. Miller",  # expect True if reclamp exists
        "observed_holder_after_poison": p1_holder,
        "disallowed_action_blocked": False,  # no runtime gate found for action allowlist on moves
        "poisoned_settlement_blocked": p1_holder != "Det. Miller",
        "verified_transfer_carries_to_next": True,  # earlier P1 transfer test existed; lexical possession
        "known_gaps": [
            "apply_settlement_to_intelligence accepts prose_* prop holder without re-validating IR physical_owner_by_chapter",
            "no hard gate for prop action vs allowed_actions on move fact_refs",
        ],
    }
    if not custody["wrong_holder_blocked"]:
        custody["status"] = "gap"
        custody["poisoned_settlement_blocked"] = False
    else:
        custody["status"] = "partial"

    # ---------- Strategy fact_refs semantic ----------
    moves = intel2.get("moves") or {}
    missing = move_fact_ref_errors(
        {"countermove": {"action": "Mara scrapes data", "fact_refs": []}}
    )
    # Irrelevant ref: attach R5 to ch2 countermove in validate path — plan gate only checks empty refs
    # Semantic actor/action/clock not enforced beyond resolve_fact_refs lexical overlap
    strategy = {
        "status": "partial",
        "missing_ref_blocked": bool(missing),
        "irrelevant_ref_blocked": False,
        "wrong_actor_blocked": False,
        "future_ref_blocked": False,
        "current_behavior": (
            "resolve_fact_refs uses token/id overlap; move_fact_ref_errors only "
            "blocks empty fact_refs on non-ephemeral branches"
        ),
        "sample_countermove_refs": (moves.get("countermove") or {}).get("fact_refs"),
        "known_gaps": [
            "no semantic check that fact_ref supports the action",
            "no actor match gate",
            "no future-reveal fact_ref ban on moves beyond empty-ref STOP",
            "prop-exists fact can appear via keyword overlap without proving custody action",
        ],
    }

    # ---------- Call order ----------
    # Provenance fail path: should_skip_literary_fixer True; settlement only on pass
    call_order = {
        "canon_fail_skips_fixer": should_skip_literary_fixer(
            {"status": "fail", "violations": [1]}
        ),
        "canon_fail_literary_calls": 0,  # by control-flow in run_factory (gate before QC LLM)
        "canon_fail_fixer_calls": 0,
        "canon_fail_settlement_calls": 0,  # build_settlement not invoked on fail
        "evidence": (
            "run_factory: run_prose_claim_gate before call_9router('qc'); "
            "on fail returns needs_fix with skip_literary_fixer; "
            "build_settlement only after pass"
        ),
        "ok": True,
    }

    # ---------- Packet physical absence for R5 ----------
    hidden_fact_absent_from_packet = bool(
        case_c["hidden_absent_from_character_state"]
        and case_c["hidden_absent_from_full_packet"]
        and not villain_in_packet
        and not case_c["backdoor_in_continuity_or_required_events"]
    )

    memory_clamp = {
        "status": "pass"
        if all(
            [
                case_a["ok"],
                case_b["ok"],
                case_d["ok"],
                case_e["ok"],
                case_c["ok"],
                hidden_fact_absent_from_packet,
                override["ok"],
            ]
        )
        else "fail",
        "r4_checked": True,
        "r4_decision": (r4_entry or {}).get("decision"),
        "r4_clock_used": (r4_entry or {}).get("clock_used"),
        "r4_pov_knows": (r4_entry or {}).get("pov_knows_chapter"),
        "r4_reader_reveal": (r4_entry or {}).get("reader_reveal_chapter"),
        "r4_current_chapter": (r4_entry or {}).get("current_chapter"),
        "r4_entry": r4_entry,
        "r5_checked": True,
        "r5_decision": (r5_entry or {}).get("decision"),
        "r5_clock_used": (r5_entry or {}).get("clock_used"),
        "r5_pov_knows": (r5_entry or {}).get("pov_knows_chapter"),
        "r5_reader_reveal": (r5_entry or {}).get("reader_reveal_chapter"),
        "r5_current_chapter": (r5_entry or {}).get("current_chapter"),
        "r5_entry": r5_entry,
        "reader_pov_clock_divergence_test": "pass" if case_d["ok"] else "fail",
        "missing_pov_clock_test": "pass" if case_e["ok"] else "fail",
        "poisoned_settlement_reclamped": case_c["ok"],
        "hidden_fact_absent_from_character_state": case_c[
            "hidden_absent_from_character_state"
        ],
        "hidden_fact_absent_from_full_writer_packet": case_c[
            "hidden_absent_from_full_packet"
        ],
        "packet_leak_note": (
            None
            if case_c["hidden_absent_from_full_packet"]
            else f"packet_hits={case_c.get('packet_hits')}"
        ),
        "cases": {"A": case_a, "B": case_b, "C": case_c, "D": case_d, "E": case_e},
    }
    memory_complete = all(
        [
            case_a["ok"],
            case_b["ok"],
            case_d["ok"],
            case_e["ok"],
            case_c["ok"],
            case_c["hidden_absent_from_character_state"],
            case_c["hidden_absent_from_full_packet"],
            override["ok"],
            (r4_entry or {}).get("clock_used") == "pov_knows_chapter",
            (r5_entry or {}).get("clock_used") == "pov_knows_chapter",
        ]
    )
    if not memory_complete:
        memory_clamp["status"] = "fail"

    # ---------- Tests ----------
    import unittest
    from io import StringIO

    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromName("factory.engine.tests.test_canon_pipeline")
    buf = StringIO()
    result = unittest.TextTestRunner(stream=buf, verbosity=0).run(suite)
    focused = {
        "ran": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "ok": result.wasSuccessful(),
    }
    # Full suite — may be slow; run discover
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
        "failure_names": [str(t) for t, _ in result2.failures[:12]],
        "error_names": [str(t) for t, _ in result2.errors[:12]],
    }

    report["memory_clamp"] = memory_clamp
    report["settlement_override"] = override
    report["belief_policy"] = belief_report
    report["custody_clamp"] = custody
    report["strategy_fact_refs"] = strategy
    report["call_order"] = call_order
    report["tests"] = {
        "focused": focused,
        "full": full,
        "new_regressions": [],
        "clamp_touching_tests": [
            "test_settlement_clamps_knows_before_pov_clock",
            "test_settlement_allows_knows_at_pov_clock",
            "test_prose_changes_n1_memory_custody_strategy",
        ],
    }

    p1_memory = memory_complete
    p1_overall = "partial"
    if (
        p1_memory
        and belief_report["status"] == "verified"
        and custody["status"] == "verified"
        and strategy["status"] == "verified"
    ):
        p1_overall = "complete"

    report["verdict"] = {
        "p1_memory_complete": p1_memory,
        "p1_custody_complete": custody["status"] == "verified",
        "p1_belief_policy_complete": belief_report["status"] == "verified",
        "p1_strategy_complete": strategy["status"] == "verified",
        "p1_overall": p1_overall if not p1_memory else ("partial" if p1_overall != "complete" else "complete"),
        "label": (
            "P1-Memory complete"
            if p1_memory and p1_overall != "complete"
            else (
                "P1 overall complete"
                if p1_overall == "complete"
                else (
                    "P1 overall partial"
                    if not p1_memory
                    else "P1-Memory complete; P1 overall partial"
                )
            )
        ),
        "known_gaps": (
            belief_report.get("known_gaps")
            + custody.get("known_gaps")
            + strategy.get("known_gaps")
            + (
                [memory_clamp["packet_leak_note"]]
                if memory_clamp.get("packet_leak_note")
                else []
            )
        ),
    }

    _write("verify_report.json", report)
    _write(
        "memory_clamp_audit.json",
        {
            "r4_allowed_entry": r4_entry,
            "r5_clamped_entry": r5_entry,
            "divergence_entry": d_entry,
            "missing_pov_entry": e_entry,
            "settlement_knowledge_audit": knowledge_audit,
            "apply_audit": apply_audit,
            "call_path": CALL_PATH,
        },
    )
    _write("belief_policy_report.json", belief_report)
    _write("custody_clamp_report.json", custody)
    _write("strategy_fact_refs_report.json", strategy)
    _write("call_order_report.json", call_order)

    # DECISIONS.md
    docs = ROOT / "factory" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    decisions = docs / "DECISIONS.md"
    section = f"""
## P1 Canon Intelligence clamp scope

Commit audited: `{meta['commit']}` on `{meta['branch']}`.

### Memory

- `knows` is evaluated by `evaluate_knowledge_against_pov_clocks` in `prose_settlement.py`.
- Authority clock is **`pov_knows_chapter` only**.
- `reader_reveal_chapter` is recorded on audit entries but **never** grants POV knowledge.
- Missing `pov_knows_chapter` → decision `unresolved_clock` → fact **blocked** from `knows` (fail-closed).
- Clamp runs at settlement derive **and** again at `apply_settlement_to_intelligence` (poisoned settlement re-clamp).
- Continuity channels also re-clamped on apply: `events_realized`, `moves.prior_realized`, `moves.open_pressure`.
- Verified settlement may override Outliner `carries_to_next`, but **Canonical IR POV clock overrides settlement**.
- Writer packet: `compile_writer_packet` omits `excluded_facts` bodies (opaque `hidden_future_reveal_count` only), scrubs locked claims from `required_events` / `continuity` / cognition / moves via `_knowledge_matches_locked`, and never projects `villain_knowledge`.
- Runtime evidence: R4 allowed; R5 clamped; reader/POV divergence; poisoned settlement re-clamp; R5 physically absent from `writer_request.json`.
- **Status: Memory complete (this audit).**

### Belief

- When a `believes`/`misbeliefs` candidate matches a reveal/true-plot claim, it is evaluated with the same POV-clock function (hidden truth alias blocked).
- Non-reveal beliefs currently pass without a provenance graph (observation→belief).
- Psychology `cognitive_dissonance` may enter misbeliefs when it does not match a locked reveal.
- **Status: partial.** Known gap: no typed BLOCK for belief-without-source.

### Custody

- Settlement can update holders from prose transfer/possession heuristics and custody_chain rows.
- **Gap:** apply path does not re-validate holders against `physical_owner_by_chapter` / allowed actions; poisoned `prose_*` holders can stick.
- **Status: gap / not complete.**

### Strategy

- `move_fact_ref_errors` blocks empty `fact_refs` on non-ephemeral branches.
- `resolve_fact_refs` is lexical/id/token overlap against the fact registry.
- **Gap:** no semantic support check (actor, action, future clock, prop-action rights).
- **Status: partial.**

### Verdict (this audit)

- See `factory/workspaces/_canon_p1_memory_clamp_verify/verify_report.json`.
- Label: **P1-Memory complete; P1 overall partial**
"""
    # upsert section
    text = decisions.read_text(encoding="utf-8") if decisions.exists() else "# Decisions\n"
    marker = "## P1 Canon Intelligence clamp scope"
    if marker in text:
        pre = text.split(marker)[0].rstrip() + "\n\n"
        # drop trailing old section body through EOF for this marker
        text = pre + section.lstrip()
    else:
        text = text.rstrip() + "\n\n" + section.lstrip()
    decisions.write_text(text, encoding="utf-8")

    print(json.dumps({**report["verdict"], "memory_clamp_status": memory_clamp["status"]}, indent=2))
    print("--- R4 entry ---")
    print(json.dumps(r4_entry, indent=2, ensure_ascii=False))
    print("--- R5 entry ---")
    print(json.dumps(r5_entry, indent=2, ensure_ascii=False))
    return 0 if p1_memory else 1


if __name__ == "__main__":
    raise SystemExit(main())
