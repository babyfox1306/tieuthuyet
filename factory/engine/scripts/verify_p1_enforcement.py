"""P1 verification: intelligence graphs + settlement → N+1 continuity.

Acceptance:
- cognition / prop / honeytoken / moves.fact_refs present
- move_missing_fact_refs would STOP
- ch N+1 packet reads settlement N (overrides carries_to_next)
- skip_literary_fixer on canon fail
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
    ingest_concept_to_workspace,
    load_canonical_ir,
    sha256_obj,
)
from factory.engine.lib.chapter_contract import build_and_seal_chapter_artifacts  # noqa: E402
from factory.engine.lib.canon_ops import (  # noqa: E402
    classify_error_layer,
    should_skip_literary_fixer,
)
from factory.engine.lib.plan_provenance import seal_chapter_plan  # noqa: E402
from factory.engine.lib.prose_settlement import (  # noqa: E402
    build_settlement,
    write_settlement,
)
from factory.engine.lib.story_intelligence import (  # noqa: E402
    compile_chapter_intelligence,
    move_fact_ref_errors,
    project_character_cognition,
    project_honeytoken_state,
    project_prop_state,
    project_villain_knowledge,
)

CE = Path(r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml")
WS = ROOT / "factory" / "workspaces" / "_canon_p1_verify"
OUT = WS / "verify_report.json"


def _reset_ws() -> None:
    if WS.exists():
        shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)
    (WS / "concept.yaml").write_bytes(CE.read_bytes())
    ingest_concept_to_workspace(WS)


def main() -> int:
    report: dict = {"p1_intelligence_complete": False, "checks": {}}
    if not CE.exists():
        report["error"] = f"CE missing: {CE}"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    _reset_ws()
    ir = load_canonical_ir(WS)
    assert ir

    # --- graphs ---
    cog = project_character_cognition(ir, 2)
    report["checks"]["cognition"] = {
        "ok": bool(cog and cog[0].get("goal_now") and cog[0].get("misbeliefs")),
        "n": len(cog),
    }
    props = {p["prop_id"]: p for p in project_prop_state(ir, 1)}
    report["checks"]["prop_holder"] = {
        "ok": props.get("P1", {}).get("holder") == "Mara",
        "holder": props.get("P1", {}).get("holder"),
    }
    honey = project_honeytoken_state(ir, 3)
    report["checks"]["honeytoken_pre"] = {
        "ok": honey.get("phase") == "pre_reuse" and "hidden" in honey,
        "phase": honey.get("phase"),
    }
    villain = project_villain_knowledge(ir, 2)
    report["checks"]["villain_phase"] = {
        "ok": villain.get("phase") == "opening",
        "phase": villain.get("phase"),
    }

    intel2 = compile_chapter_intelligence(ir, 2)
    move_errs = move_fact_ref_errors(intel2.get("moves"))
    report["checks"]["moves_fact_refs"] = {
        "ok": not move_errs
        and bool((intel2.get("moves") or {}).get("countermove", {}).get("fact_refs")),
        "errors": move_errs,
        "countermove_refs": (intel2.get("moves") or {})
        .get("countermove", {})
        .get("fact_refs", [])[:6],
    }
    report["checks"]["missing_refs_would_stop"] = {
        "ok": bool(
            move_fact_ref_errors(
                {
                    "countermove": {
                        "action": "Unsupported invented beat",
                        "fact_refs": [],
                    }
                }
            )
        )
    }

    # --- seal ch2 + settlement ---
    plan2 = {
        "chapter": 2,
        "title": "Anticoagulant",
        "must_happen": [
            "Mara observes anticoagulant treatment on the blood-stained phone."
        ],
        "beat_summary": "She scrapes Claire Thorne data and confirms anticoagulant staging.",
        "must_not": ["Mara leaves the office."],
    }
    sealed2 = seal_chapter_plan(WS, 1, plan2)
    report["checks"]["seal_ch2"] = {"ok": bool(sealed2.get("sealed")), "detail": sealed2}
    built2 = build_and_seal_chapter_artifacts(
        WS, 1, 2, sealed2["repaired_plan"], intelligence=intel2
    )
    packet2 = built2["packet"]
    report["checks"]["packet_structured"] = {
        "ok": bool(
            packet2.get("character_state")
            and packet2.get("moves")
            and packet2.get("prop_state")
            and packet2.get("psychology_active")
            and packet2.get("relationship_delta_target")
        ),
        "keys": sorted(k for k, v in packet2.items() if v),
    }

    settlement = build_settlement(
        chapter=2,
        canon_qc={
            "status": "pass",
            "claims": [
                {"claim": "Mara scrapes Claire Thorne's data.", "kind": "event"},
                {
                    "claim": "The blood was treated with anticoagulants.",
                    "kind": "event",
                },
            ],
        },
        intelligence=intel2,
        prose_len=200,
    )
    write_settlement(WS, 1, 2, settlement)
    report["checks"]["settlement_events"] = {
        "ok": settlement.get("status") == "sealed"
        and bool(settlement.get("events_realized")),
        "events": settlement.get("events_realized"),
        "power_delta": settlement.get("power_delta"),
    }

    # --- ch3 reads settlement ---
    plan3 = {
        "chapter": 3,
        "title": "Next",
        "must_happen": ["Mara reviews the scraped Claire Thorne data."],
        "beat_summary": "Mara reviews Claire Thorne data already scraped.",
        "must_not": ["Mara leaves the office."],
        "carries_to_next": "Outliner foresight yacht chase that must lose",
    }
    sealed3 = seal_chapter_plan(WS, 1, plan3)
    built3 = build_and_seal_chapter_artifacts(WS, 1, 3, sealed3["repaired_plan"])
    packet3 = built3["packet"]
    prior = packet3.get("prior_settlement") or {}
    continuity = packet3.get("continuity") or {}
    report["checks"]["settlement_to_n1"] = {
        "ok": prior.get("settlement_digest") == settlement.get("settlement_digest")
        and continuity.get("source") == "settlement"
        and continuity.get("plan_foresight_superseded") is True,
        "prior_digest": prior.get("settlement_digest"),
        "continuity": continuity,
    }

    # mutate settlement → packet changes
    mutated = dict(settlement)
    mutated["events_realized"] = list(settlement.get("events_realized") or []) + [
        {"action": "mutated continuity beat", "kind": "test"}
    ]
    mutated["settlement_digest"] = sha256_obj(
        {k: v for k, v in mutated.items() if k != "settlement_digest"}
    )
    write_settlement(WS, 1, 2, mutated)
    rebuilt = build_and_seal_chapter_artifacts(WS, 1, 3, sealed3["repaired_plan"])
    report["checks"]["settlement_mutation_propagates"] = {
        "ok": (rebuilt["packet"].get("prior_settlement") or {}).get("settlement_digest")
        == mutated["settlement_digest"]
        and mutated["settlement_digest"] != settlement["settlement_digest"],
    }

    report["checks"]["ops"] = {
        "skip_fixer_on_fail": should_skip_literary_fixer(
            {"status": "fail", "violations": [{"x": 1}]}
        ),
        "layer_planner": classify_error_layer("move_missing_fact_refs"),
        "layer_writer": classify_error_layer("canon_qc fail"),
    }
    report["checks"]["ops"]["ok"] = (
        report["checks"]["ops"]["skip_fixer_on_fail"]
        and report["checks"]["ops"]["layer_planner"] == "planner"
        and report["checks"]["ops"]["layer_writer"] == "writer"
    )

    report["p1_intelligence_complete"] = all(
        bool((v or {}).get("ok")) for v in report["checks"].values() if isinstance(v, dict)
    )
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["p1_intelligence_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
