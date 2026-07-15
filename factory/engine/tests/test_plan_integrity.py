"""Plan merge/resume must not downgrade complete chapter objects."""

from __future__ import annotations

import unittest

from factory.engine.lib.master_plan import (
    chunk_needs_replan,
    filter_complete_chapter_plans,
    merge_plans,
)
from factory.engine.lib.plan_qc import (
    chapter_plan_structurally_complete,
    prefer_richer_chapter_plan,
)


def _full(ch: int = 1) -> dict:
    return {
        "chapter": ch,
        "title": f"Title {ch}",
        "slug": f"title-{ch}",
        "one_line_summary": "One line of summary text.",
        "beat_summary": "Beats happen with enough detail.",
        "must_happen": ["A happens", "B happens", "C happens"],
        "must_not": ["No spoilers"],
        "opens_with": "A door slammed in the dark hallway.",
        "cliffhanger": "Something waited behind the next stone.",
        "signature_detail_hint": "Cold under the thumbnail.",
        "spice": 1,
        "chapter_task": "Write 1600-1900 words of gothic dread.",
    }


def _thin(ch: int = 1) -> dict:
    return {
        "chapter": ch,
        "title": f"Title {ch}",
        "slug": f"title-{ch}",
        "one_line_summary": "Thin.",
        "beat_summary": "Thin beats.",
        "must_happen": ["[CLUE C001]"],
        "spice": 1,
        "chapter_task": "Write 1600 words.",
    }


class PlanIntegrityTests(unittest.TestCase):
    def test_structurally_complete(self) -> None:
        self.assertTrue(chapter_plan_structurally_complete(_full()))
        self.assertFalse(chapter_plan_structurally_complete(_thin()))

    def test_prefer_richer_refuses_downgrade(self) -> None:
        kept = prefer_richer_chapter_plan(_full(3), _thin(3))
        self.assertTrue(chapter_plan_structurally_complete(kept))
        self.assertEqual(len(kept["must_happen"]), 3)
        self.assertIn("must_not", kept)

    def test_merge_plans_keeps_complete_over_thin(self) -> None:
        merged = merge_plans([_full(1), _full(2)], [_thin(1), _full(2)])
        by = {p["chapter"]: p for p in merged}
        self.assertTrue(chapter_plan_structurally_complete(by[1]))
        self.assertEqual(len(by[1]["must_happen"]), 3)

    def test_chunk_needs_replan_when_thin(self) -> None:
        self.assertFalse(chunk_needs_replan([_full(1), _full(2), _full(3)], 1, 3))
        self.assertTrue(chunk_needs_replan([_full(1), _thin(2), _full(3)], 1, 3))
        self.assertTrue(chunk_needs_replan([_full(1)], 1, 3))

    def test_filter_rejects_incomplete(self) -> None:
        kept = filter_complete_chapter_plans([_full(10), _thin(11), _full(12)], lo=10, hi=12)
        self.assertEqual([p["chapter"] for p in kept], [10, 12])


if __name__ == "__main__":
    unittest.main()
