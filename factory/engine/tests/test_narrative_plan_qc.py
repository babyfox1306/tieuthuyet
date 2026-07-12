"""Tests for plan_qc narrative rules NC-01..NC-06 (step 4)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.narrative_compiler import merge_narrative_into_plans
from factory.engine.lib.master_plan import build_plan_fixer_payload
from factory.engine.lib.plan_qc import validate_narrative_plan, validate_plan
from factory.engine.tests.test_narrative_compiler import _write_workspace
from factory.engine.tests.test_master_plan_narrative import SAMPLE_PLAN


def _full_plan(ch: int, **extra) -> dict:
    p = dict(SAMPLE_PLAN)
    p["chapter"] = ch
    p["title"] = f"Chapter {ch}"
    p["slug"] = f"ch-{ch}"
    p.update(extra)
    return p


class TestNarrativePlanQC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = _write_workspace(Path(self.tmp.name), narrative_status="approved")

    def tearDown(self):
        self.tmp.cleanup()

    def _direction(self):
        import yaml

        return yaml.safe_load((self.ws / "direction.yaml").read_text(encoding="utf-8"))

    def test_merged_plan_passes_nc_rules_ch1(self):
        plans = merge_narrative_into_plans(self.ws, [_full_plan(1)])
        # NC-07: beats must reflect planted clue C001
        mh = list(plans[0]["must_happen"])
        mh.append(
            "[CLUE C001] Adrian rushes her through the thick contract before she can read clause 38"
        )
        plans[0]["must_happen"] = mh
        issues = validate_narrative_plan(plans[0], self.ws, all_plans=plans)
        nc = [i for i in issues if ":NC-" in i]
        self.assertEqual(nc, [], nc)

    def test_nc07_clue_not_in_beats(self):
        plans = merge_narrative_into_plans(self.ws, [_full_plan(1)])
        # Strip compiler-injected [CLUE …] beats so NC-07 can fire
        plans[0]["must_happen"] = [
            x
            for x in (plans[0].get("must_happen") or [])
            if "[CLUE " not in str(x).upper()
        ]
        issues = validate_narrative_plan(plans[0], self.ws, all_plans=plans)
        self.assertTrue(any("NC-07:clue_not_in_beats:C001" in i for i in issues))

    def test_nc01_missing_clue_plant(self):
        plans = merge_narrative_into_plans(self.ws, [_full_plan(1)])
        narr = dict(plans[0]["narrative"])
        narr["clues_plant"] = []
        plans[0]["narrative"] = narr
        issues = validate_narrative_plan(plans[0], self.ws, all_plans=plans)
        self.assertTrue(any("NC-01:clue_not_scheduled:C001" in i for i in issues))

    def test_nc02_missing_payoff(self):
        p3 = merge_narrative_into_plans(self.ws, [_full_plan(3)])[0]
        p8 = merge_narrative_into_plans(self.ws, [_full_plan(8)])[0]
        narr = dict(p8["narrative"])
        narr["clues_payoff"] = []
        p8["narrative"] = narr
        plans = [p3, p8]
        issues = validate_narrative_plan(p8, self.ws, all_plans=plans)
        self.assertTrue(any("NC-02:payoff_not_scheduled:C002" in i for i in issues))

    def test_nc04_same_chapter_plant_allowed(self):
        """Clue planted at-or-before reveal chapter counts (incl. same chapter)."""
        p3 = merge_narrative_into_plans(self.ws, [_full_plan(3)])[0]
        p7 = merge_narrative_into_plans(self.ws, [_full_plan(7)])[0]
        p8 = merge_narrative_into_plans(self.ws, [_full_plan(8)])[0]
        # R001@8 needs C002 (plant ch3) + C005 (plant ch7)
        issues = validate_narrative_plan(p8, self.ws, all_plans=[p3, p7, p8])
        nc04 = [i for i in issues if "NC-04" in i]
        self.assertEqual(nc04, [], issues)

    def test_nc04_reveal_missing_prior_clue(self):
        p8 = merge_narrative_into_plans(self.ws, [_full_plan(8)])[0]
        # No ch3 plan — C002 never planted
        issues = validate_narrative_plan(p8, self.ws, all_plans=[p8])
        self.assertTrue(any("NC-04:reveal_missing_plant:R001:C002" in i for i in issues))

    def test_nc05_major_reveal_insufficient_clues(self):
        p3 = merge_narrative_into_plans(self.ws, [_full_plan(3)])[0]
        p8 = merge_narrative_into_plans(self.ws, [_full_plan(8)])[0]
        # Only C002 planted, R001 major needs C002+C005
        issues = validate_narrative_plan(p8, self.ws, all_plans=[p3, p8])
        self.assertTrue(any("NC-05:reveal_insufficient_clues:R001" in i for i in issues))

    def test_nc05_minor_reveal_needs_one_clue(self):
        p12 = merge_narrative_into_plans(self.ws, [_full_plan(12)])[0]
        p15 = merge_narrative_into_plans(self.ws, [_full_plan(15)])[0]
        issues = validate_narrative_plan(p15, self.ws, all_plans=[p12, p15])
        nc05 = [i for i in issues if "NC-05" in i]
        self.assertEqual(nc05, [], issues)

    def test_nc06_knowledge_violation_in_must_happen(self):
        plans = merge_narrative_into_plans(self.ws, [_full_plan(5)])
        plans[0]["must_happen"] = list(plans[0]["must_happen"]) + [
            "Adrian chose her because of mother's file"
        ]
        issues = validate_narrative_plan(plans[0], self.ws, all_plans=plans)
        self.assertTrue(any("NC-06:knowledge_violation" in i for i in issues))

    def test_locked_plan_skips_narrative_qc(self):
        plan = _full_plan(1, locked=True)
        plan["narrative"] = {}
        issues = validate_narrative_plan(plan, self.ws, all_plans=[plan])
        self.assertEqual(issues, [])

    def test_archive_workspace_skips_narrative_qc(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), workspace_mode="archive")
            plan = _full_plan(1)
            issues = validate_narrative_plan(plan, ws, all_plans=[plan])
            self.assertEqual(issues, [])

    def test_validate_plan_wires_ws(self):
        plans = merge_narrative_into_plans(self.ws, [_full_plan(1)])
        narr = dict(plans[0]["narrative"])
        narr["clues_plant"] = []
        plans[0]["narrative"] = narr
        issues = validate_plan(
            plans[0],
            self._direction(),
            all_plans=plans,
            ws=self.ws,
        )
        self.assertTrue(any("NC-01" in i for i in issues))

    def test_plan_fixer_payload_includes_narrative_hints(self):
        plans = merge_narrative_into_plans(self.ws, [_full_plan(1)])
        body = build_plan_fixer_payload(
            self.ws,
            plans[0],
            ["ch1:NC-07:clue_not_in_beats:C001"],
            [],
            self._direction(),
        )
        self.assertIn("narrative_fix_hints", body)
        self.assertIn("C001", body["narrative_fix_hints"]["clues_plant"])
        self.assertIn("narrative_issues", body)


if __name__ == "__main__":
    unittest.main()
