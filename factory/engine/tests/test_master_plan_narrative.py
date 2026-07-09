"""Tests for master_plan narrative merge + outliner payload (step 3)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.master_plan import build_outliner_payload
from factory.engine.lib.narrative_compiler import merge_narrative_into_plans
from factory.engine.tests.test_narrative_compiler import _write_workspace

SAMPLE_PLAN = {
    "chapter": 1,
    "title": "Test",
    "slug": "test",
    "one_line_summary": "Summary",
    "beat_summary": "Beat",
    "must_happen": ["a", "b", "c"],
    "must_not": ["x", "y"],
    "opens_with": "Hook line",
    "cliffhanger": "Cliff here now",
    "signature_detail_hint": "odd detail",
    "emotional_beat": "tension",
    "spice": 1,
    "chapter_task": "1600 words",
    "carries_to_next": "next",
}


class TestMergeNarrativeIntoPlans(unittest.TestCase):
    def test_adds_narrative_from_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            merged = merge_narrative_into_plans(ws, [dict(SAMPLE_PLAN)])
            self.assertIn("narrative", merged[0])
            narr = merged[0]["narrative"]
            self.assertEqual(narr["clues_plant"], ["C001"])
            self.assertIn("C001", narr["clue_beats"])
            self.assertTrue(narr["knowledge"]["must_not_know"])

    def test_locked_plan_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            locked = dict(SAMPLE_PLAN)
            locked["locked"] = True
            locked["narrative"] = {"clues_plant": ["USER_LOCKED"]}
            merged = merge_narrative_into_plans(ws, [locked])
            self.assertEqual(merged[0]["narrative"]["clues_plant"], ["USER_LOCKED"])

    def test_archive_workspace_no_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), workspace_mode="archive")
            merged = merge_narrative_into_plans(ws, [dict(SAMPLE_PLAN)])
            self.assertNotIn("narrative", merged[0])

    def test_compiler_overwrites_llm_narrative_on_unlocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            plan = dict(SAMPLE_PLAN)
            plan["narrative"] = {"clues_plant": ["LLM_WRONG"]}
            merged = merge_narrative_into_plans(ws, [plan])
            self.assertEqual(merged[0]["narrative"]["clues_plant"], ["C001"])


class TestOutlinerPayload(unittest.TestCase):
    def test_includes_narrative_constraints_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            body = build_outliner_payload(
                ws,
                1,
                1,
                3,
                "act1",
                bible={"title": "Test"},
                direction=yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8")),
                prior=[],
            )
            self.assertIn("narrative_constraints", body)
            self.assertIn("1", body["narrative_constraints"]["chapters"])
            self.assertIn("C001", body["narrative_constraints"]["clue_catalog"])

    def test_omits_narrative_constraints_for_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), workspace_mode="archive")
            body = build_outliner_payload(
                ws,
                1,
                1,
                3,
                "act1",
                bible={},
                direction={"canon_through": 0},
                prior=[],
            )
            self.assertNotIn("narrative_constraints", body)


if __name__ == "__main__":
    unittest.main()
