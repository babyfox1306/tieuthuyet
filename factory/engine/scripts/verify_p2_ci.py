"""P2.5 — CI gate: golden + mutation + corpus + P1 raw evidence + focused tests.

Usage:
  python factory/engine/scripts/verify_p2_ci.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FIXTURES_MUT = ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_mutations"
FIXTURES_GOLD = ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_golden"
FIXTURES_CORPUS = ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_corpus"


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def main() -> int:
    steps: list[dict] = []

    def step(name: str, cmd: list[str]) -> bool:
        code, out = _run(cmd)
        ok = code == 0
        steps.append(
            {
                "name": name,
                "ok": ok,
                "code": code,
                "tail": "\n".join(out.strip().splitlines()[-40:]),
            }
        )
        print(f"[{'PASS' if ok else 'FAIL'}] {name} (exit={code})")
        if not ok:
            print(out[-4000:])
        return ok

    py = sys.executable
    ok = True
    ok = step("golden", [py, "factory/engine/scripts/verify_p2_golden.py"]) and ok
    ok = (
        step(
            "mutation_battery",
            [py, "factory/engine/scripts/export_p2_mutation_evidence.py"],
        )
        and ok
    )
    ok = step("corpus", [py, "factory/engine/scripts/verify_p2_corpus.py"]) and ok
    ok = (
        step(
            "p1_raw_evidence",
            [py, "factory/engine/scripts/export_p1_raw_evidence.py"],
        )
        and ok
    )

    # Focused unittest suite (P0+P1+P2)
    loader = unittest.TestLoader()
    suite = loader.discover(
        str(ROOT / "factory" / "engine" / "tests"),
        pattern="test_canon_pipeline.py",
    )
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    focused_ok = result.wasSuccessful()
    steps.append(
        {
            "name": "test_canon_pipeline",
            "ok": focused_ok,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
        }
    )
    print(
        f"[{'PASS' if focused_ok else 'FAIL'}] test_canon_pipeline "
        f"(run={result.testsRun} fail={len(result.failures)} err={len(result.errors)})"
    )
    ok = focused_ok and ok

    # Fixture gates present
    gates = {
        "GOLDEN_GATE": (FIXTURES_GOLD / "GOLDEN_GATE.json").exists(),
        "RAW_MUTATION_GATE": (FIXTURES_MUT / "RAW_MUTATION_GATE.json").exists(),
        "CORPUS_GATE": (FIXTURES_CORPUS / "CORPUS_GATE.json").exists(),
    }
    gates_ok = all(gates.values())
    steps.append({"name": "fixture_gates", "ok": gates_ok, "gates": gates})
    ok = gates_ok and ok

    # Budget doc present
    budget_doc = (ROOT / "factory" / "docs" / "P2_BUDGET.md").exists()
    steps.append({"name": "P2_BUDGET.md", "ok": budget_doc})
    ok = budget_doc and ok

    report = {
        "steps": steps,
        "pass": ok,
        "p2_harness_complete": ok,
        "note": (
            "Full non-canon suite regressions are classified separately; "
            "this gate does not skip failing harness steps."
        ),
    }
    out_path = ROOT / "factory" / "workspaces" / "_canon_p2_ci" / "P2_CI_GATE.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_ci" / "P2_CI_GATE.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (
        ROOT / "factory" / "engine" / "tests" / "fixtures" / "canon_p2_ci" / "P2_CI_GATE.json"
    ).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"pass": ok, "p2_harness_complete": ok}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
