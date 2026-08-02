"""One-shot Zero-Day canon demo — writes ingest + plan.approval + writer_request."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from factory.engine.lib.canonical_ir import ingest_concept_to_workspace, load_canonical_ir
from factory.engine.lib.chapter_contract import build_and_seal_chapter_artifacts
from factory.engine.lib.plan_provenance import seal_chapter_plan
try:
    from factory.engine.lib.story_intelligence import compile_chapter_intelligence
except Exception:  # P1 optional
    def compile_chapter_intelligence(ir, chapter):  # type: ignore
        return {}


CE = Path(r"D:\tieuthuyet\Concept ETL\output\concepts\the-zero-day-alibi\concept.yaml")
WS = Path(r"D:\tieuthuyet\tieuthuyet\factory\workspaces\_canon_demo_zero_day")


def main() -> None:
    if WS.exists():
        shutil.rmtree(WS)
    WS.mkdir(parents=True)
    (WS / "concept.yaml").write_bytes(CE.read_bytes())
    ing = ingest_concept_to_workspace(WS)
    print(
        "INGEST",
        ing["report"]["ok"],
        "coverage_rows",
        len(ing["report"]["coverage"]),
        "blocking",
        ing["report"]["blocking_errors"],
        "unknown",
        ing["report"]["unknown_fields"],
    )

    holloway = {
        "chapter": 2,
        "title": "Anticoagulant",
        "must_happen": [
            "Mara recalls Dr. Patricia Holloway at Suite 401 after eleven months of therapy."
        ],
        "beat_summary": "Therapy notes from Patricia Holloway.",
    }
    h = seal_chapter_plan(WS, 1, holloway)
    print("HOLLOWAY", h["approval"]["status"], h["approval"].get("unverified_claims"))

    motive = {
        "chapter": 11,
        "title": "Two Victories",
        "must_happen": [
            "Adrian reveals he orchestrated the entire confrontation to test whether Mara was a worthy partner."
        ],
        "beat_summary": "He had already decided to offer partnership as a test.",
        "cliffhanger": "She passed the worthy partner test.",
    }
    m = seal_chapter_plan(WS, 1, motive)
    print("MOTIVE", m["approval"]["status"], m["approval"].get("unverified_claims"))

    # Keep Holloway approval on ch02 as the artifact to inspect; also write
    # motive approval under ch11. For a sealed writer packet, use clean ch03.
    clean = {
        "chapter": 3,
        "title": "Synthetic Alibi",
        "must_happen": [
            "Mara creates the false alibi.",
            "Mara plants ghost vehicle evidence C7.",
        ],
        "beat_summary": (
            "Mara Voss builds the synthetic alibi while Adrian Thorne cooperates."
        ),
        "must_not": ["Physical violence between Mara and Adrian."],
    }
    c = seal_chapter_plan(WS, 1, clean)
    print("CLEAN", c["approval"]["status"], c["result"].get("unverified_claims"))
    if not c["sealed"]:
        raise SystemExit("clean ch3 failed to seal")
    ir = load_canonical_ir(WS)
    built = build_and_seal_chapter_artifacts(
        WS,
        1,
        3,
        c["repaired_plan"],
        ir=ir,
        intelligence=compile_chapter_intelligence(ir, 3),
    )
    pkt = built["packet"]
    blob = json.dumps(pkt).casefold()
    print("excluded_facts_key", "excluded_facts" in pkt)
    print("has_r3_token", '"r3"' in blob or "secretly hired" in blob)
    print("hidden_count", pkt.get("hidden_future_reveal_count"))
    print("WS", WS)


if __name__ == "__main__":
    main()
