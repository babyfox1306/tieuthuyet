"""Smoke + 4-case prose injection through real writer gate/settlement/state path."""
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
    load_canonical_ir,
)
from factory.engine.lib.chapter_contract import build_and_seal_chapter_artifacts  # noqa: E402
from factory.engine.lib.plan_provenance import (  # noqa: E402
    seal_chapter_plan,
    validate_plan_against_ir,
)
from factory.engine.lib.prose_claim_gate import (  # noqa: E402
    run_prose_claim_gate,
    validate_prose_against_ir,
)
from factory.engine.lib.prose_settlement import build_settlement, write_settlement  # noqa: E402
from factory.engine.lib.state_updater import update_state_after_pass  # noqa: E402
try:
    from factory.engine.lib.story_intelligence import compile_chapter_intelligence
except Exception:  # P1 optional
    def compile_chapter_intelligence(ir, chapter):  # type: ignore
        return {}
  # noqa: E402

CE = Path(r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml")
WS = ROOT / "factory" / "workspaces" / "_canon_prose_injection"


CASES = {
    "A_canon_name_in_dialogue": {
        "expect": "pass",
        "prose": (
            "I kept my voice flat. "
            '"Adrian Thorne, put the phone on the desk." '
            "He did not smile."
        ),
    },
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
}


def main() -> int:
    if not CE.exists():
        print("MISSING_CE", CE)
        return 2

    concept = yaml.safe_load(CE.read_text(encoding="utf-8"))
    report = build_ingest_report(concept)
    print(
        "INGEST",
        "ok=",
        report["ok"],
        "path_ok=",
        report["path_coverage"]["ok"],
        "ref_ok=",
        report["reference_resolution"]["ok"],
        "ref_rows=",
        len(report["reference_resolution"]["rows"]),
        "blocking=",
        report["blocking_errors"],
    )
    # Prove unresolved contract-affecting text_ref would block.
    poisoned = json.loads(json.dumps(concept, default=str))
    poisoned["chapter_map"]["2"]["must_happen"].append(
        "text_ref: /does/not/exist/anywhere"
    )
    bad = build_ingest_report(poisoned)
    print(
        "POISON_REF",
        "ok=",
        bad["ok"],
        "blocking_n=",
        len(bad["blocking_errors"]),
        "sample=",
        (bad["blocking_errors"] or [None])[0],
    )

    ir = compile_canonical_ir(concept)

    # Plan hard-gate smoke
    clean = {
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
    print("CLEAN_PLAN", validate_plan_against_ir(clean, ir)["status"])

    if WS.exists():
        shutil.rmtree(WS)
    WS.mkdir(parents=True)
    (WS / "concept.yaml").write_bytes(CE.read_bytes())
    ingest_concept_to_workspace(WS)
    sealed = seal_chapter_plan(WS, 1, clean)
    assert sealed["sealed"], sealed
    build_and_seal_chapter_artifacts(
        WS,
        1,
        2,
        sealed["repaired_plan"],
        intelligence=compile_chapter_intelligence(load_canonical_ir(WS), 2),
    )

    # Optional: try real writer once (non-fatal if API unavailable).
    writer_note = "skipped"
    try:
        from factory.engine.lib.call_9router import call_9router
        from factory.engine.lib.chapter_contract import (
            load_writer_packet,
            render_writer_prompt_from_packet,
        )
        from factory.engine.lib.prompt_builder import load_direction

        direction = {}
        try:
            direction = load_direction(WS)
        except Exception:
            direction = {}
        packet = load_writer_packet(WS, 1, 2)
        prompt = render_writer_prompt_from_packet(packet)
        prompt += (
            "\n\nCONSTRAINT FOR THIS RUN: Write 3-5 sentences only. "
            "Include exactly one spoken line that addresses Adrian Thorne by full name. "
            "Do not invent new named people."
        )
        raw, _meta = call_9router("writer", prompt, max_tokens=400, direction=direction)
        writer_note = f"ok chars={len(raw or '')}"
        (WS / "books" / "01" / "chapters" / "02" / "writer_live_sample.txt").write_text(
            raw or "", encoding="utf-8"
        )
        live = run_prose_claim_gate(WS, 1, 2, raw or "", load_canonical_ir(WS))
        print(
            "WRITER_LIVE",
            live["status"],
            "violations",
            len(live.get("violations") or []),
        )
    except Exception as exc:  # noqa: BLE001 — demo path
        writer_note = f"unavailable:{type(exc).__name__}:{exc}"
        print("WRITER_LIVE", writer_note)

    results = {}
    ir = load_canonical_ir(WS)
    out_dir = WS / "books" / "01" / "chapters" / "02" / "injection_cases"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, spec in CASES.items():
        prose = spec["prose"]
        gate = validate_prose_against_ir(prose, ir, chapter=2)
        run = run_prose_claim_gate(WS, 1, 2, prose, ir)
        # Overlay case-specific copies so A/B/C/D don't clobber each other
        (out_dir / f"{name}.prose.txt").write_text(prose, encoding="utf-8")
        (out_dir / f"{name}.canon_qc.json").write_text(
            json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        settlement = build_settlement(
            chapter=2,
            canon_qc=run,
            intelligence=compile_chapter_intelligence(ir, 2),
            prose_len=len(prose),
        )
        (out_dir / f"{name}.settlement.json").write_text(
            json.dumps(settlement, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        ok = False
        if spec["expect"] == "pass":
            ok = run["status"] == "pass" and settlement["status"] == "sealed"
            # Dialogue span_type preserved on Adrian Thorne
            pn = [
                c
                for c in run["claims"]
                if c.get("kind") == "proper_noun" and "Adrian" in str(c.get("claim"))
            ]
            ok = ok and any(c.get("span_type") == "dialogue" for c in pn)
        elif spec["expect"] == "fail":
            ok = run["status"] == "fail" and settlement["status"] == "blocked"
        elif spec["expect"] == "pass_no_state_texture":
            ok = (
                run["status"] == "pass"
                and settlement["status"] == "sealed"
                and int(settlement.get("texture_excluded_from_state") or 0) > 0
                and not any(
                    c.get("kind") == "generic_texture"
                    for c in settlement.get("facts_expressed") or []
                )
            )
            # State path: only pass cases may update; texture must not invent facts
            if ok:
                write_settlement(WS, 1, 2, settlement)
                # Ensure canon_qc on disk is the passing D case for state bump
                run_prose_claim_gate(WS, 1, 2, prose, ir)
                state = update_state_after_pass(WS, 2, prose, book=1)
                verified = state.get("verified_facts") or []
                ok = ok and all("fluorescent" not in str(v).casefold() for v in verified)
                ok = ok and all("hummed" not in str(v).casefold() for v in verified)
                (out_dir / f"{name}.state.json").write_text(
                    json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
                )

        results[name] = {
            "expect": spec["expect"],
            "status": run["status"],
            "ok": ok,
            "violations": [
                {"reason": v.get("reason"), "claim": v.get("claim"), "span_type": v.get("span_type")}
                for v in (run.get("violations") or [])
            ],
            "span_types": sorted(
                {c.get("span_type") for c in run.get("claims") or [] if c.get("span_type")}
            ),
            "settlement": settlement.get("status"),
            "texture_excluded": settlement.get("texture_excluded_from_state"),
        }
        print(name, "OK" if ok else "FAIL", results[name])

    summary = {
        "workspace": str(WS),
        "writer_live": writer_note,
        "ingest_ok": report["ok"],
        "poison_ref_blocks": not bad["ok"],
        "cases": results,
        "all_passed": all(r["ok"] for r in results.values()),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("SUMMARY", json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["all_passed"] and summary["poison_ref_blocks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
