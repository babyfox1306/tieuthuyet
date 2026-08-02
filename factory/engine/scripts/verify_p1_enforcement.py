"""P1 verification: prose N must change live N+1 memory/custody/strategy.

P0 proved invention cannot enter canon.
P1 is complete only when verified chapter-N prose changes knows/believes,
prop custody, and strategy in the chapter N+1 packet — without Outliner foresight.
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
)
from factory.engine.lib.chapter_contract import build_and_seal_chapter_artifacts  # noqa: E402
from factory.engine.lib.plan_provenance import seal_chapter_plan  # noqa: E402
from factory.engine.lib.prose_settlement import (  # noqa: E402
    build_settlement,
    write_settlement,
)
from factory.engine.lib.story_intelligence import (  # noqa: E402
    compile_chapter_intelligence,
    move_fact_ref_errors,
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


def _mara_knows(packet: dict) -> list[str]:
    for row in packet.get("character_state") or []:
        if "Mara" in str(row.get("character") or ""):
            return list(row.get("knows") or [])
    return []


def main() -> int:
    report: dict = {
        "p1_intelligence_complete": False,
        "acceptance": (
            "prose N changes live memory/belief/custody/strategy in packet N+1; "
            "Outliner foresight cannot override"
        ),
        "checks": {},
    }
    if not CE.exists():
        report["error"] = f"CE missing: {CE}"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    _reset_ws()
    ir = load_canonical_ir(WS)
    assert ir

    intel2 = compile_chapter_intelligence(ir, 2)
    report["checks"]["moves_fact_refs"] = {
        "ok": not move_fact_ref_errors(intel2.get("moves"))
        and bool((intel2.get("moves") or {}).get("countermove", {}).get("fact_refs"))
    }

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
    )
    report["checks"]["seal_ch2"] = {"ok": bool(sealed2.get("sealed"))}
    build_and_seal_chapter_artifacts(WS, 1, 2, sealed2["repaired_plan"])

    # --- Prose A ---
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
        intelligence=intel2,
        ir=ir,
    )
    write_settlement(WS, 1, 2, settle_a)
    report["checks"]["settlement_a_memory"] = {
        "ok": any(
            "anticoagulant" in k.casefold()
            for k in (settle_a.get("character_updates") or {})
            .get("deltas", {})
            .get("knows_gained", [])
        ),
        "knows_gained": (settle_a.get("character_updates") or {})
        .get("deltas", {})
        .get("knows_gained"),
    }

    sealed3 = seal_chapter_plan(
        WS,
        1,
        {
            "chapter": 3,
            "title": "Next",
            "must_happen": ["Mara creates the false alibi."],
            "beat_summary": "Mara creates the false alibi from scraped Claire Thorne data.",
            "must_not": ["Mara leaves the office."],
            "carries_to_next": "Outliner invents a yacht chase Mara never saw",
        },
    )
    built_a = build_and_seal_chapter_artifacts(WS, 1, 3, sealed3["repaired_plan"])
    packet_a = built_a["packet"]
    knows_a = _mara_knows(packet_a)
    props_a = {p["prop_id"]: p for p in (packet_a.get("prop_state") or [])}
    cont_a = packet_a.get("continuity") or {}
    report["checks"]["packet_a_live_memory"] = {
        "ok": any("anticoagulant" in k.casefold() for k in knows_a)
        and any("scrapes" in k.casefold() for k in knows_a),
        "knows": knows_a,
    }
    report["checks"]["packet_a_custody"] = {
        "ok": props_a.get("P2", {}).get("holder") == "Mara",
        "P2": props_a.get("P2"),
    }
    report["checks"]["packet_a_strategy"] = {
        "ok": bool((packet_a.get("moves") or {}).get("prior_realized")),
        "prior_realized": (packet_a.get("moves") or {}).get("prior_realized"),
        "power_incoming": ((packet_a.get("moves") or {}).get("power_delta") or {}).get(
            "incoming"
        ),
    }
    report["checks"]["outliner_foresight_loses"] = {
        "ok": cont_a.get("source") == "settlement"
        and cont_a.get("plan_foresight_superseded") is True
        and cont_a.get("carries_to_next") is None,
        "continuity": cont_a,
    }

    # --- Prose B: different verified claims → different live N+1 state ---
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
        intelligence=intel2,
        ir=ir,
    )
    write_settlement(WS, 1, 2, settle_b)
    built_b = build_and_seal_chapter_artifacts(WS, 1, 3, sealed3["repaired_plan"])
    packet_b = built_b["packet"]
    knows_b = _mara_knows(packet_b)
    props_b = {p["prop_id"]: p for p in (packet_b.get("prop_state") or [])}
    report["checks"]["packet_b_memory_differs"] = {
        "ok": (not any("anticoagulant" in k.casefold() for k in knows_b))
        and any("scrapes" in k.casefold() for k in knows_b),
        "knows": knows_b,
    }
    report["checks"]["packet_b_custody_from_prose"] = {
        "ok": props_b.get("P1", {}).get("holder") == "Adrian Thorne",
        "P1": props_b.get("P1"),
    }
    report["checks"]["packets_differ"] = {
        "ok": packet_a.get("packet_digest") != packet_b.get("packet_digest"),
        "digest_a": packet_a.get("packet_digest"),
        "digest_b": packet_b.get("packet_digest"),
    }

    report["p1_intelligence_complete"] = all(
        bool((v or {}).get("ok")) for v in report["checks"].values() if isinstance(v, dict)
    )
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["p1_intelligence_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
