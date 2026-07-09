"""Pipeline guards — plan normalize, state gate, QC hard-fail."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.plan_normalize import (
    coerce_text_list,
    normalize_chapter_plan,
    normalize_chapter_plans,
    plan_has_legacy_vi_content,
    validate_duplicate_beats,
    validate_plan_language,
)
from factory.engine.lib.qc_eval import qc_fail_reasons, qc_passes
from factory.engine.lib.write_guards import (
    WriteBlockedError,
    assert_write_allowed,
    is_sequential_writes,
    load_prior_chapter_excerpt,
    state_chain_complete,
)
from factory.engine.paths import book_workspace_dir, chapter_pipeline_path, pipeline_dir


class TestPlanNormalize(unittest.TestCase):
    def test_unwrap_nested_chapter_plan(self):
        raw = {
            "chapter": 2,
            "chapter_plan": {
                "title": "Golden Cage",
                "one_line_summary": "Moves into estate",
                "must_happen": ["arrives at estate", "study scene", "cliff"],
                "must_not": ["cry"],
                "opens_with": "Gates shut",
                "cliffhanger": "Locked in",
                "signature_detail_hint": "ozone scent",
                "spice": 1,
                "chapter_task": "1600 words minimum 1500",
                "slug": "golden-cage",
                "beat_summary": "Estate arrival",
            },
        }
        out = normalize_chapter_plan(raw)
        self.assertEqual(out["chapter"], 2)
        self.assertEqual(out["title"], "Golden Cage")
        self.assertEqual(len(out["must_happen"]), 3)
        self.assertNotIn("chapter_plan", out)

    def test_legacy_vi_detected_on_en(self):
        plan = {"chapter": 1, "one_line_summary": "Diệp Tâm ký hợp đồng"}
        self.assertTrue(plan_has_legacy_vi_content(plan))
        issues = validate_plan_language(plan, "en")
        self.assertIn("ch1:legacy_vi_content", issues)

    def test_duplicate_one_line_summary(self):
        plans = [
            {"chapter": 2, "one_line_summary": "Moves into estate", "opens_with": "A"},
            {"chapter": 3, "one_line_summary": "Moves into estate", "opens_with": "B"},
        ]
        issues = validate_duplicate_beats(plans[1], plans)
        self.assertTrue(any("duplicate_one_line_summary" in i for i in issues))

    def test_flatten_nested_must_happen(self):
        nested = ["beat"] * 15 + [["sub-beat A", "sub-beat B"]]
        plan = normalize_chapter_plan({"chapter": 16, "must_happen": nested, "must_not": []})
        self.assertEqual(len(plan["must_happen"]), 17)
        self.assertTrue(all(isinstance(x, str) for x in plan["must_happen"]))

    def test_nested_must_happen_prompt_join(self):
        from factory.engine.lib.prompt_builder import build_chapter_prompt

        nested = ["beat"] * 15 + [["clue plant", "romance beat"]]
        plan = normalize_chapter_plan(
            {
                "chapter": 16,
                "title": "Test",
                "must_happen": nested,
                "must_not": ["no drift"],
                "opens_with": "Hook",
                "cliffhanger": "Cliff ends here now",
                "signature_detail_hint": "scent of rain",
                "spice": 1,
                "chapter_task": "1600 words minimum 1500",
                "slug": "test",
                "beat_summary": "beats",
                "one_line_summary": "line",
            }
        )
        text = build_chapter_prompt(plan, prior_plans=[], direction={"target_language": "en"}, chapter=16)
        self.assertIn("clue plant", text)


class TestQcEval(unittest.TestCase):
    def test_continuity_flag_fails_even_if_verdict_pass(self):
        qc = {
            "verdict": "PASS",
            "continuity_conflict": {"flag": True, "details": "signed twice"},
        }
        self.assertFalse(qc_passes(qc))
        self.assertIn("continuity_conflict", qc_fail_reasons(qc))

    def test_clean_pass(self):
        qc = {
            "verdict": "PASS",
            "continuity_conflict": {"flag": False},
            "voice_drift": {"flag": False},
        }
        self.assertTrue(qc_passes(qc))


class TestWriteGuards(unittest.TestCase):
    def test_prior_excerpt_from_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            book = 1
            pipeline_dir(ws, book, "ready")
            chapter_pipeline_path(ws, book, "ready", 1).write_text(
                "# Ch1\n\n" + ("word " * 400),
                encoding="utf-8",
            )
            ex = load_prior_chapter_excerpt(ws, book, 2)
            self.assertIn("word", ex)
            self.assertGreater(len(ex), 100)

    def test_write_blocked_without_prior_ready_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            book = 1
            for b in ("ready", "needs_fix", "needs_review", "draft"):
                pipeline_dir(ws, book, b)
            state_path = book_workspace_dir(ws, book) / "state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"current_chapter": 0}),
                encoding="utf-8",
            )
            seq_cfg = {"write_mode": "sequential"}
            with self.assertRaises(WriteBlockedError):
                assert_write_allowed(ws, book, 2, seq_cfg)

    def test_parallel_allows_gap_in_ready_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            book = 1
            for b in ("ready", "needs_fix", "needs_review", "draft"):
                pipeline_dir(ws, book, b)
            state_path = book_workspace_dir(ws, book) / "state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"current_chapter": 0}),
                encoding="utf-8",
            )
            chapter_pipeline_path(ws, book, "ready", 1).write_text("# Ch1\n\nok", encoding="utf-8")
            parallel_cfg = {"write_mode": "parallel"}
            assert_write_allowed(ws, book, 3, parallel_cfg)
            self.assertFalse(state_chain_complete(ws, book, 3))


class TestStorySoFarCap(unittest.TestCase):
    def test_caps_prior_summaries(self):
        from factory.engine.lib.prompt_builder import format_prior_summaries

        plans = [{"chapter": i, "one_line_summary": f"beat {i}"} for i in range(1, 15)]
        out = format_prior_summaries(plans, 15, empty_line="-", max_chapters=5)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 5)
        self.assertIn("Ch10", out)
        self.assertIn("Ch14", out)
        self.assertNotIn("Ch1:", out)


if __name__ == "__main__":
    unittest.main()
