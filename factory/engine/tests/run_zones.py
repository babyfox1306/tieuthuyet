#!/usr/bin/env python3
"""
Factory test machine — chạy từng khu vực, sau đó tổng thể.

Usage (từ repo root):
  python factory/engine/tests/run_zones.py
  python factory/engine/tests/run_zones.py --zone compiler
  python factory/engine/tests/run_zones.py --clean   # xóa __pycache__ sau khi pass

Zones:
  bible      — schema / relation_type
  compiler   — narrative_compiler deterministic
  prompt     — prompt_builder NARRATIVE CONSTRAINTS inject
  plan       — master_plan merge + outliner payload
  plan_qc    — NC-01..NC-07
  integration — end-to-end compiler → plan → prompt (no LLM)
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TESTS_DIR = Path(__file__).resolve().parent

ZONES: dict[str, list[str]] = {
    "bible": ["factory.engine.tests.test_bible_schema"],
    "compiler": ["factory.engine.tests.test_narrative_compiler"],
    "prompt": ["factory.engine.tests.test_prompt_builder"],
    "plan": ["factory.engine.tests.test_master_plan_narrative"],
    "plan_qc": ["factory.engine.tests.test_narrative_plan_qc"],
    "guards": [
        "factory.engine.tests.test_write_guards",
        "factory.engine.tests.test_call_9router",
    ],
}


class TestIntegrationPipeline(unittest.TestCase):
    """Zone integration: compiler → merge plan → QC → prompt (no 9router)."""

    def test_full_pipeline_ch1(self):
        from factory.engine.lib.master_plan import build_outliner_payload
        from factory.engine.lib.narrative_compiler import (
            merge_narrative_into_plans,
            narrative_compiler_enabled,
            narrative_constraints_block_for_prompt,
        )
        from factory.engine.lib.plan_qc import validate_narrative_plan
        from factory.engine.lib.prompt_builder import build_chapter_prompt
        from factory.engine.tests._fixtures import full_plan, write_test_workspace

        with tempfile.TemporaryDirectory() as tmp:
            ws = write_test_workspace(Path(tmp), narrative_status="approved")
            self.assertTrue(narrative_compiler_enabled(ws))

            plan = full_plan(1)
            mh = list(plan["must_happen"])
            mh.append(
                "[CLUE C001] Adrian rushes the thick contract signing before she reads clause 38"
            )
            plan["must_happen"] = mh
            plans = merge_narrative_into_plans(ws, [plan])

            nc = validate_narrative_plan(plans[0], ws, all_plans=plans)
            self.assertEqual([i for i in nc if ":NC-" in i], [], nc)

            direction = {"target_language": "en", "audience": "test", "spice_default": 1}
            prompt = build_chapter_prompt(
                plans[0],
                prior_plans=[],
                direction=direction,
                chapter=1,
                series_bible={},
                ws=ws,
            )
            self.assertIn("NARRATIVE CONSTRAINTS", prompt)
            self.assertIn("C001", prompt)

            block = narrative_constraints_block_for_prompt(ws, 1, lang="en")
            self.assertIn("MUST NOT know", block)

            body = build_outliner_payload(
                ws, 1, 1, 3, "act1", bible={}, direction=direction, prior=[]
            )
            self.assertIn("narrative_constraints", body)

    def test_glass_meridian_compiler_off_until_approved(self):
        from factory.engine.lib.narrative_compiler import narrative_compiler_enabled
        from factory.engine.paths import workspace_dir

        ws = workspace_dir("glass-meridian")
        if not ws.exists():
            self.skipTest("glass-meridian workspace missing")
        self.assertFalse(narrative_compiler_enabled(ws))

    def test_ceo_contract_compiler_when_narrative_approved(self):
        from factory.engine.lib.narrative_compiler import (
            merge_narrative_into_plans,
            narrative_compiler_enabled,
            narrative_constraints_block_for_prompt,
        )
        from factory.engine.paths import workspace_dir

        ws = workspace_dir("ceo-contract")
        if not ws.exists():
            self.skipTest("ceo-contract missing")
        self.assertTrue(narrative_compiler_enabled(ws))
        plan = full_plan_from_fixture(1)
        merged = merge_narrative_into_plans(ws, [plan])
        self.assertIn("narrative", merged[0])
        self.assertIn("NARRATIVE CONSTRAINTS", narrative_constraints_block_for_prompt(ws, 1))


def full_plan_from_fixture(ch: int) -> dict:
    from factory.engine.tests._fixtures import full_plan

    return full_plan(ch)


def load_suite(modules: list[str]) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        suite.addTests(loader.loadTestsFromModule(mod))
    return suite


def run_suite(suite: unittest.TestSuite, label: str) -> tuple[bool, int, int]:
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    ok = result.wasSuccessful()
    n = result.testsRun
    fails = len(result.failures) + len(result.errors)
    status = "PASS" if ok else "FAIL"
    print(f"\n[{label}] {status} — {n} tests, {fails} failures\n")
    return ok, n, fails


def cleanup_artifacts() -> list[str]:
    removed: list[str] = []
    for p in TESTS_DIR.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
        removed.append(str(p))
    for p in TESTS_DIR.glob("*.pyc"):
        p.unlink(missing_ok=True)
        removed.append(str(p))
    return removed


def scan_workspaces() -> None:
    import yaml

    from factory.engine.lib.narrative_compiler import narrative_compiler_enabled

    print("=" * 60)
    print("WORKSPACE SCAN")
    print("=" * 60)
    ws_root = ROOT / "factory" / "workspaces"
    for ws in sorted(ws_root.iterdir()):
        if not ws.is_dir():
            continue
        dpath = ws / "direction.yaml"
        d = yaml.safe_load(dpath.read_text(encoding="utf-8")) if dpath.exists() else {}
        mp = ws / "books" / "01" / "master_plan.json"
        ch_n = 0
        if mp.exists():
            ch_n = len(json.loads(mp.read_text(encoding="utf-8")).get("chapter_plans", []))
        print(f"\n  {ws.name}")
        print(f"    narrative: {d.get('narrative_status')} | bible: {d.get('bible_status')} | plan: {d.get('plan_status')}")
        print(f"    series.json: {(ws / 'bible' / 'series.json').exists()} | master_plan: {ch_n} ch")
        print(f"    compiler_enabled: {narrative_compiler_enabled(ws)}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Factory zone test runner")
    parser.add_argument("--zone", choices=[*ZONES.keys(), "integration", "all"], default="all")
    parser.add_argument("--clean", action="store_true", help="Remove __pycache__ after success")
    parser.add_argument("--scan", action="store_true", help="Print workspace status only")
    args = parser.parse_args()

    if args.scan:
        scan_workspaces()
        return 0

    scan_workspaces()

    zones_to_run: list[tuple[str, unittest.TestSuite]] = []
    if args.zone == "all":
        for name, mods in ZONES.items():
            zones_to_run.append((name, load_suite(mods)))
        zones_to_run.append(
            ("integration", unittest.TestLoader().loadTestsFromTestCase(TestIntegrationPipeline))
        )
    elif args.zone == "integration":
        zones_to_run.append(
            ("integration", unittest.TestLoader().loadTestsFromTestCase(TestIntegrationPipeline))
        )
    else:
        zones_to_run.append((args.zone, load_suite(ZONES[args.zone])))

    all_ok = True
    total = 0
    total_fails = 0
    print("=" * 60)
    print("ZONE TESTS")
    print("=" * 60)
    for label, suite in zones_to_run:
        ok, n, fails = run_suite(suite, label)
        all_ok = all_ok and ok
        total += n
        total_fails += fails

    print("=" * 60)
    if all_ok:
        print(f"TOTAL: PASS — {total} tests")
        if args.clean:
            removed = cleanup_artifacts()
            if removed:
                print(f"Cleaned {len(removed)} cache path(s)")
    else:
        print(f"TOTAL: FAIL — {total} tests, {total_fails} failure(s)")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
