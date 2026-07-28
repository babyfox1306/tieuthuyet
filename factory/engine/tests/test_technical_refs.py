"""Regression tests for technical chapter labels leaking into prose."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.export_gate import check_eg19_technical_chapter_reference
from factory.engine.lib.narrative_compiler import format_narrative_constraints_block
from factory.engine.lib.prompt_builder import build_chapter_prompt, render_all_prompts
from factory.engine.lib.technical_refs import (
    derive_chapter_day_map,
    project_technical_chapter_refs,
)


class TechnicalReferenceProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prior = [
            {
                "chapter": 9,
                "title": "The Originals",
                "opens_with": "Day eight. 06:14. Lena knocked.",
                "one_line_summary": "Lena identifies the watcher.",
            },
            {
                "chapter": 12,
                "title": "The Returned Phrase",
                "opens_with": "Day ten. 06:14. Grant sent the message.",
                "one_line_summary": "Grant repeats the honeytoken phrase.",
            },
        ]
        self.current = {
            "chapter": 15,
            "title": "The Chain",
            "slug": "the-chain",
            "one_line_summary": "The evidence leaves Calder's custody.",
            "beat_summary": "Day thirteen. They reconstruct the chain.",
            "must_happen": [
                "Use Grant's Chapter Twelve instruction.",
                "Explain what Lena learned in Chapter Nine.",
                "Preserve Subject Hart as a plan reference.",
            ],
            "must_not": [],
            "opens_with": "Day thirteen. 07:03. The planner is open.",
            "cliffhanger": "Cross leaves with the evidence.",
            "signature_detail_hint": "A black evidence drive.",
            "emotional_beat": "Trust.",
            "spice": 0,
            "spice_note": "",
            "chapter_task": "Write Chapter Fifteen. Reconstruct Grant's Ch12 message.",
            "carries_to_next": "The chain is distributed.",
        }

    def test_structured_day_map_projects_only_known_references(self) -> None:
        days = derive_chapter_day_map([*self.prior, self.current])
        text = project_technical_chapter_refs(
            "Chapter Nine; Chapter Twelve; Chapter Forty",
            days,
            current_chapter=15,
        )
        self.assertEqual(text, "day eight; day ten; Chapter Forty")

    def test_writer_prompt_projects_must_happen_and_task_refs(self) -> None:
        prompt = build_chapter_prompt(
            self.current,
            prior_plans=self.prior,
            direction={"target_language": "en", "total_chapters": 18},
            chapter=15,
            series_bible={},
            ws=None,
        )
        self.assertIn("Grant's day ten instruction", prompt)
        self.assertIn("what Lena learned in day eight", prompt)
        self.assertIn("Reconstruct Grant's day ten message", prompt)
        self.assertNotIn("Chapter Twelve", prompt)
        self.assertNotIn("Chapter Nine", prompt)
        self.assertNotIn("unnamed contact", prompt.lower())

    def test_narrative_reveal_projection_uses_same_contract(self) -> None:
        days = derive_chapter_day_map([*self.prior, self.current])
        block = format_narrative_constraints_block(
            {
                "chapter": 15,
                "reveals": [
                    {
                        "id": "MR01",
                        "reveal_weight": "major",
                        "reveal": (
                            "She learned the truth in Chapter Nine and preserved "
                            "Grant's Chapter Twelve instruction."
                        ),
                    }
                ],
            },
            chapter_days=days,
        )
        self.assertIn("in day eight", block)
        self.assertIn("Grant's day ten instruction", block)
        self.assertNotIn("Chapter Nine", block)
        self.assertNotIn("Chapter Twelve", block)

    def test_fixture_workspace_renders_clean_writer_prompt(self) -> None:
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "technical_ref_workspace"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "technical-ref-workspace"
            shutil.copytree(fixture, ws, ignore=shutil.ignore_patterns("prompts"))
            self.assertEqual(render_all_prompts(ws, 1), 3)
            prompt = (ws / "books" / "01" / "prompts" / "ch_015.txt").read_text(
                encoding="utf-8"
            )

        self.assertNotIn("unnamed contact", prompt.lower())
        self.assertNotIn("Chapter Nine", prompt)
        self.assertNotIn("Chapter Twelve", prompt)
        self.assertNotIn("Ch12", prompt)
        self.assertIn("day eight", prompt)
        self.assertIn("day ten", prompt)
        self.assertIn("Subject Hart and Target Reed", prompt)


class TechnicalReferenceGateTests(unittest.TestCase):
    def test_gate_blocks_non_diegetic_reference(self) -> None:
        check = check_eg19_technical_chapter_reference(
            "I did not know until Chapter Nine, when she showed me the file.",
            14,
        )
        self.assertFalse(check["passed"])

    def test_gate_allows_real_book_chapter_reference(self) -> None:
        check = check_eg19_technical_chapter_reference(
            "I opened Chapter Twelve of the manual and read the first paragraph.",
            3,
        )
        self.assertTrue(check["passed"])


if __name__ == "__main__":
    unittest.main()
