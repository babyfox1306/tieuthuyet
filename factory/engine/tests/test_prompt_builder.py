"""Tests for prompt_builder narrative constraint injection (step 2)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.prompt_builder import (
    build_chapter_prompt,
    render_all_prompts,
    spice_for_chapter,
)
from factory.engine.tests.test_narrative_compiler import (
    SAMPLE_LEDGER,
    SAMPLE_MATRIX,
    SAMPLE_THREADS,
    _write_workspace,
)

MINIMAL_PLAN = {
    "chapter": 1,
    "title": "The Contract",
    "slug": "the-contract",
    "one_line_summary": "Lin Wei signs the marriage contract.",
    "beat_summary": "Hospital pressure, contract on the table.",
    "must_happen": [
        "[ROMANCE] A charged glance across the table.",
        "Mother's surgery deadline stated.",
        "Contract signed.",
    ],
    "must_not": ["Reveal Glass Meridian", "Adrian explains why he chose her"],
    "opens_with": '"Forty pages," she said. "You want me to sign forty pages?"',
    "cliffhanger": "The pen leaves ink on clause twelve — and she has not read it.",
    "signature_detail_hint": "Clause numbers misaligned on page 38",
    "emotional_beat": "defiance",
    "spice": 1,
    "spice_note": "",
    "chapter_task": "Write 1600-1900 words. Contract scene.",
    "carries_to_next": "She is now legally bound.",
}


class TestNarrativePromptInjection(unittest.TestCase):
    def test_spice_schedule_is_per_chapter_and_beats_legacy_list(self):
        direction = {
            "spice_level": 3,
            "spice_default": 0,
            "spice_explicit_chapters": [11, 18],
            "spice_schedule": {11: 3, 18: 2},
        }
        self.assertEqual(spice_for_chapter(direction, 11), 3)
        self.assertEqual(spice_for_chapter(direction, 18), 2)
        self.assertEqual(spice_for_chapter(direction, 10), 0)

    def test_legacy_explicit_list_uses_book_ceiling(self):
        self.assertEqual(
            spice_for_chapter(
                {
                    "spice_level": 3,
                    "spice_default": 0,
                    "spice_explicit_chapters": [11, 18],
                },
                18,
            ),
            3,
        )

    def _direction(self) -> dict:
        return {
            "target_language": "en",
            "audience": "women 18-35",
            "spice_default": 1,
            "spice_level": 1,
        }

    def test_thriller_workspace_injects_compiler_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            prompt = build_chapter_prompt(
                MINIMAL_PLAN,
                prior_plans=[],
                direction=self._direction(),
                chapter=1,
                series_bible={},
                ws=ws,
            )
            self.assertIn("NARRATIVE CONSTRAINTS", prompt)
            self.assertIn("C001", prompt)
            self.assertIn("Thick contract", prompt)
            self.assertIn("MUST NOT know", prompt)
            self.assertNotIn("Glass Meridian exists", prompt)
            self.assertIn("closed-world knowledge", prompt)

    def test_ignores_plan_narrative_field(self):
        """Block must come from compiler, not master_plan.narrative."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            plan = dict(MINIMAL_PLAN)
            plan["narrative"] = {
                "clues_plant": ["FAKE999"],
                "knowledge": {"must_not_know": ["FAKE FACT FROM PLAN"]},
            }
            prompt = build_chapter_prompt(
                plan,
                prior_plans=[],
                direction=self._direction(),
                chapter=1,
                series_bible={},
                ws=ws,
            )
            self.assertIn("C001", prompt)
            self.assertNotIn("FAKE999", prompt)
            self.assertNotIn("FAKE FACT FROM PLAN", prompt)

    def test_locked_plan_still_injects_knowledge_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="approved")
            plan = dict(MINIMAL_PLAN)
            plan["locked"] = True
            prompt = build_chapter_prompt(
                plan,
                prior_plans=[],
                direction=self._direction(),
                chapter=1,
                series_bible={},
                ws=ws,
            )
            self.assertIn("NARRATIVE CONSTRAINTS", prompt)
            self.assertIn("locked", prompt.lower())
            self.assertIn("MUST NOT know", prompt)
            self.assertIn("Contract signed", prompt)

    def test_archive_mode_no_narrative_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), workspace_mode="archive")
            prompt = build_chapter_prompt(
                MINIMAL_PLAN,
                prior_plans=[],
                direction=self._direction(),
                chapter=1,
                series_bible={},
                ws=ws,
            )
            self.assertNotIn("NARRATIVE CONSTRAINTS", prompt)

    def test_draft_narrative_status_no_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), narrative_status="draft")
            prompt = build_chapter_prompt(
                MINIMAL_PLAN,
                prior_plans=[],
                direction=self._direction(),
                chapter=1,
                series_bible={},
                ws=ws,
            )
            self.assertNotIn("NARRATIVE CONSTRAINTS", prompt)

    def test_no_workspace_param_no_block(self):
        prompt = build_chapter_prompt(
            MINIMAL_PLAN,
            prior_plans=[],
            direction=self._direction(),
            chapter=1,
            series_bible={},
            ws=None,
        )
        self.assertNotIn("NARRATIVE CONSTRAINTS", prompt)

    def test_render_all_prompts_writes_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _write_workspace(root, narrative_status="approved")
            book_dir = ws / "books" / "01"
            book_dir.mkdir(parents=True)
            (book_dir / "master_plan.json").write_text(
                json.dumps({"chapter_plans": [MINIMAL_PLAN]}, ensure_ascii=False),
                encoding="utf-8",
            )
            n = render_all_prompts(ws, 1)
            self.assertEqual(n, 1)
            text = (book_dir / "prompts" / "ch_001.txt").read_text(encoding="utf-8")
            self.assertIn("NARRATIVE CONSTRAINTS", text)


if __name__ == "__main__":
    unittest.main()
