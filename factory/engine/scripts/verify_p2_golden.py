"""P2.1 — Golden IR/contract digests for ≥2 titles (no LLM).

Usage:
  python factory/engine/scripts/verify_p2_golden.py           # verify
  python factory/engine/scripts/verify_p2_golden.py --write   # refresh expected
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factory.engine.lib.p2_fixtures import ROMANCE_GATE_CONCEPT, zero_day_concept_path  # noqa: E402
from factory.engine.lib.p2_harness import (  # noqa: E402
    compare_golden,
    concept_to_workspace,
    golden_snapshot_for_title,
    seal_minimal_chapter,
)

FIXTURES = ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_golden"
WS_ROOT = ROOT / "factory" / "workspaces" / "_canon_p2_golden_verify"


def _zd_concept() -> Path:
    return zero_day_concept_path()


def _run_zero_day(ws: Path) -> dict:
    ir = concept_to_workspace(ws, _zd_concept())
    ch2 = seal_minimal_chapter(
        ws,
        ir,
        2,
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
    ch3 = seal_minimal_chapter(
        ws,
        ir,
        3,
        {
            "chapter": 3,
            "title": "Next",
            "must_happen": ["Mara creates the false alibi."],
            "beat_summary": (
                "Mara creates the false alibi from scraped Claire Thorne data."
            ),
            "must_not": ["Mara leaves the office."],
        },
    )
    return golden_snapshot_for_title(
        title_id="zero_day",
        ir=ir,
        chapter_digests={
            "2": {
                "contract_digest": ch2["contract_digest"],
                "packet_digest": ch2["packet_digest"],
            },
            "3": {
                "contract_digest": ch3["contract_digest"],
                "packet_digest": ch3["packet_digest"],
            },
        },
    )


def _run_romance(ws: Path) -> dict:
    ir = concept_to_workspace(ws, ROMANCE_GATE_CONCEPT)
    # Persist concept fixture for humans
    concept_path = FIXTURES / "romance_gate" / "concept.yaml"
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text(
        yaml.safe_dump(ROMANCE_GATE_CONCEPT, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    ch1 = seal_minimal_chapter(
        ws,
        ir,
        1,
        {
            "chapter": 1,
            "title": "latch inventory",
            "must_happen": ["Lina Reed inventories the latch without forcing it."],
            "beat_summary": "Lina Reed inventories the latch without forcing it.",
            "must_not": ["Invent unsupported medical diagnosis."],
        },
    )
    ch2 = seal_minimal_chapter(
        ws,
        ir,
        2,
        {
            "chapter": 2,
            "title": "key-card times",
            "must_happen": ["Lina Reed and Cole Hart compare key-card times."],
            "beat_summary": "Lina Reed and Cole Hart compare key-card times.",
            "must_not": ["They leave the garden."],
        },
    )
    return golden_snapshot_for_title(
        title_id="romance_gate",
        ir=ir,
        chapter_digests={
            "1": {
                "contract_digest": ch1["contract_digest"],
                "packet_digest": ch1["packet_digest"],
            },
            "2": {
                "contract_digest": ch2["contract_digest"],
                "packet_digest": ch2["packet_digest"],
            },
        },
    )


def _write_expected(title_id: str, snap: dict) -> Path:
    out = FIXTURES / title_id / "expected.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _load_expected(title_id: str) -> dict:
    path = FIXTURES / title_id / "expected.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Refresh expected golden digests")
    args = ap.parse_args()

    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT, ignore_errors=True)
    WS_ROOT.mkdir(parents=True)

    results = {}
    # Determinism: run each title twice
    for title, runner in (
        ("zero_day", _run_zero_day),
        ("romance_gate", _run_romance),
    ):
        ws_a = WS_ROOT / f"{title}_a"
        ws_b = WS_ROOT / f"{title}_b"
        snap_a = runner(ws_a)
        snap_b = runner(ws_b)
        intra = compare_golden(snap_a, snap_b)
        if intra:
            print(json.dumps({"title": title, "determinism_fail": intra}, indent=2))
            return 1
        if args.write or not (FIXTURES / title / "expected.json").exists():
            _write_expected(title, snap_a)
            mode = "wrote"
        else:
            expected = _load_expected(title)
            diffs = compare_golden(expected, snap_a)
            if diffs:
                print(json.dumps({"title": title, "golden_fail": diffs}, indent=2))
                return 1
            mode = "ok"
        results[title] = {
            "mode": mode,
            "ir_digest": snap_a["ir_digest"],
            "chapters": snap_a["chapters"],
        }

    gate = {
        "golden_titles": list(results),
        "deterministic_rerun": True,
        "llm_used": False,
        "results": results,
        "pass": True,
    }
    (WS_ROOT / "GOLDEN_GATE.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (FIXTURES / "GOLDEN_GATE.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(gate, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
