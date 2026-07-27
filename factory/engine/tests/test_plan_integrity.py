"""Plan merge/resume must not downgrade complete chapter objects."""

from __future__ import annotations

import unittest

from pathlib import Path

from factory.engine.lib.master_plan import (
    chunk_needs_replan,
    filter_complete_chapter_plans,
    merge_plans,
)
from factory.engine.lib.plan_qc import (
    chapter_plan_structurally_complete,
    duplicate_cliffhanger_tail_field,
    prefer_richer_chapter_plan,
    validate_plan,
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

    def test_1800_word_target_passes_plan_qc(self) -> None:
        plan = _full()
        plan["chapter_task"] = "Write 1800-1900 words of escalating dread."
        issues = validate_plan(plan, {"spice_level": 1})
        self.assertNotIn("ch1:task_no_word_target", issues)

    def test_duplicate_cliffhanger_tail_is_blocked_at_plan_stage(self) -> None:
        plan = _full()
        tail = (
            "Marget opens the ledger and finds her own death certificate "
            "signed tomorrow by Arthur Penhaligon."
        )
        plan["cliffhanger"] = tail
        plan["must_happen"] = [
            "Marget maps the frost across the burial plots.",
            "Arthur removes the final page from her ledger.",
            tail,
        ]
        self.assertEqual(
            duplicate_cliffhanger_tail_field(plan),
            "must_happen[2]",
        )
        issues = validate_plan(plan, {"spice_level": 1})
        self.assertIn(
            "ch1:duplicate_cliffhanger_tail:must_happen[2]",
            issues,
        )

    def test_semantic_cliffhanger_setup_is_not_duplicate_tail(self) -> None:
        plan = _full()
        plan["must_happen"][-1] = (
            "Marget notices Arthur has hidden the final ledger page."
        )
        self.assertIsNone(duplicate_cliffhanger_tail_field(plan))

    def test_adjacent_chapter_duplicate_shared_reveal_blocks(self) -> None:
        from factory.engine.lib.plan_qc import adjacent_chapter_duplicate_errors

        prev = _full(24)
        prev["title"] = "The Confrontation"
        prev["must_happen"] = [
            "[CLUE C006] Warehouse evidence on Priya.",
            "[MR03] Rhodes manipulated Priya into believing Nadia would sacrifice her.",
            "Nadia lets Priya walk.",
        ]
        prev["narrative"] = {"reveals": [{"id": "MR03"}]}
        prev["cliffhanger"] = (
            "Nadia dials Wren: he wanted me to find her. He wanted me to lose her."
        )
        cur = _full(25)
        cur["title"] = "The Confession"
        cur["must_happen"] = [
            "Confront Priya with C006 C007 C008.",
            "MR03: Rhodes manipulated Priya into believing Nadia would sacrifice her.",
            "Nadia lets Priya go; network broken.",
        ]
        cur["cliffhanger"] = (
            "Nadia dials Wren: he wanted me to find her. He wanted me to lose her."
        )
        cur["opens_with"] = prev["opens_with"]
        issues = adjacent_chapter_duplicate_errors(cur, [prev, cur])
        self.assertTrue(any("adjacent_chapter_duplicate" in i for i in issues))
        self.assertTrue(any("shared_reveal:MR03" in i for i in issues))

    def test_adjacent_setup_payoff_not_false_positive(self) -> None:
        from factory.engine.lib.plan_qc import adjacent_chapter_duplicate_errors

        prev = _full(16)
        prev["must_happen"] = [
            "Nadia stages the kill plan for Rhodes at the marina.",
            "Wren plants the false drop schedule.",
            "Network agrees on the trap window.",
        ]
        prev["cliffhanger"] = "The trap is set; dawn will spring it."
        prev["beat_summary"] = "They plan the kill carefully overnight."
        cur = _full(17)
        cur["must_happen"] = [
            "The kill trap springs at dawn but Rhodes is already gone.",
            "Nadia finds the wrench with a wrong fingerprint.",
            "The team realizes someone tipped him.",
        ]
        cur["cliffhanger"] = "A second set of footprints leads the other way."
        cur["beat_summary"] = "The kill springs and fails; someone leaked."
        issues = adjacent_chapter_duplicate_errors(cur, [prev, cur])
        self.assertEqual(issues, [])


class OutlinerChunkBoundaryTests(unittest.TestCase):
    def test_chunk_boundary_and_prior_trim(self) -> None:
        from factory.engine.lib.master_plan import build_outliner_payload

        prior = [_full(ch) for ch in range(1, 25)]
        prior[23]["must_happen"] = [
            "[MR03] Priya confession in warehouse",
            "Nadia lets her go",
            "Calls Wren about Rhodes plan",
        ]
        prior[23]["narrative"] = {
            "reveals": [{"id": "MR03"}],
            "clues_payoff": ["C006", "C007", "C008"],
        }
        # Stale plans for the range being regenerated must not be fed back in.
        prior.append(_full(25))
        body = build_outliner_payload(
            Path("."),
            1,
            25,
            27,
            "custom",
            bible={"title": "T"},
            direction={"target_language": "en", "canon_through": 0},
            prior=prior,
        )
        self.assertIn("chunk_boundary", body)
        self.assertEqual(body["chunk_boundary"]["previous_chapter"], 24)
        self.assertIn("MR03", body["chunk_boundary"]["reveals_already_fired"])
        chapters = [p["chapter"] for p in body["prior_plans"]]
        self.assertTrue(all(ch < 25 for ch in chapters))
        self.assertNotIn(25, chapters)
        self.assertLessEqual(len(chapters), 6)
        # Knowledge blobs must not bloat prior
        self.assertTrue(
            all("knowledge" not in (p.get("narrative") or {}) for p in body["prior_plans"])
        )


if __name__ == "__main__":
    unittest.main()