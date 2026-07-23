"""Plan generation phrase-gate (same compile_chapter_canon_rules as writer)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.engine.lib.master_plan import build_outliner_payload
from factory.engine.lib.plan_canon_gate import (
    filter_plans_by_phrase_gate,
    plan_forbidden_phrase_hits,
)


def _kessler_like_concept() -> dict:
    return {
        "concept_status": "ready",
        "surface_order": {
            "event_id": "kessler_liner_override",
            "exact_text": "Seismic microfracture compounded by dispatch error",
            "visible_from_chapter": 1,
        },
        "binding_condition": {
            "event_id": "kessler_liner_override",
            "canonical_text": (
                "Aldous Renn overrode and buried the Kessler load-test failure because he had "
                "fast-tracked Vantor's uncertified contract for a private stake, and when the "
                "tunnel killed sixty-three people he built the independent inquiry itself to "
                "launder his culpability by sacrificing the tiers beneath him on a schedule "
                "that stops before his name."
            ),
            "reveal_chapter": 20,
            "exact_wording_required_when_explicitly_stated": True,
        },
        "forbidden_phrases": ["Renn ordered"],
        "forbidden_phrase_gates": [
            {
                "id": "inquiry_cover",
                "unlock_chapter": 18,
                "phrases": ["controlled burn", "the inquiry is the cover-up"],
            },
            {
                "id": "renn_fasttrack",
                "unlock_chapter": 19,
                "phrases": ["Renn fast-tracked", "Aldous Renn fast-tracked"],
            },
            {
                "id": "renn_architect",
                "unlock_chapter": 20,
                "phrases": ["Renn built the inquiry", "Renn overrode", "Renn buried"],
            },
        ],
    }


class PlanPhraseGateTests(unittest.TestCase):
    def test_ch18_beat_with_renn_built_inquiry_rejected(self) -> None:
        concept = _kessler_like_concept()
        plan = {
            "chapter": 18,
            "beat_summary": (
                "Iris realizes the inquiry is a controlled burn and that Renn built the inquiry."
            ),
            "must_happen": ["She sees the sacrifice schedule."],
            "one_line_summary": "The burn is clear.",
            "cliffhanger": "Who lit it?",
            "chapter_task": "1600 words.",
        }
        hits = plan_forbidden_phrase_hits(plan, concept)
        phrases = {h["phrase"] for h in hits}
        self.assertIn("Renn built the inquiry", phrases)
        clean, all_hits = filter_plans_by_phrase_gate([plan], concept)
        self.assertEqual(clean, [])
        self.assertTrue(all_hits)

    def test_ch18_anonymous_burn_ok(self) -> None:
        concept = _kessler_like_concept()
        plan = {
            "chapter": 18,
            "beat_summary": (
                "Iris realizes the inquiry is a controlled burn protecting an anonymous higher hand."
            ),
            "must_happen": [
                "She pays off the three pieces.",
                "Fast-track author stays unnamed.",
                "She does not confront Renn.",
            ],
            "one_line_summary": "The commission is the burn; the hand is unnamed.",
            "cliffhanger": "She must name the fast-track author next.",
            "chapter_task": "1600-1900 words. Controlled burn only.",
            "carries_to_next": "Find who authored the fast-track.",
        }
        hits = plan_forbidden_phrase_hits(plan, concept)
        self.assertEqual(hits, [])
        clean, _ = filter_plans_by_phrase_gate([plan], concept)
        self.assertEqual(len(clean), 1)

    def test_must_not_field_not_scanned(self) -> None:
        """Prohibitions may name gated phrases; do not reject the plan for that."""
        concept = _kessler_like_concept()
        plan = {
            "chapter": 18,
            "beat_summary": "Iris sees the controlled burn.",
            "must_happen": ["She maps the sacrifice schedule.", "Anonymous fast-track.", "No confrontation."],
            "must_not": ["Do not write that Renn built the inquiry."],
            "one_line_summary": "Burn without a named architect.",
            "cliffhanger": "Name the hand later.",
            "chapter_task": "1600 words.",
        }
        self.assertEqual(plan_forbidden_phrase_hits(plan, concept), [])


class OutlinerPayloadGatesTests(unittest.TestCase):
    def test_payload_includes_chapter_canon_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                "narrative_profile: conspiracy_thriller\ntarget_language: en\n",
                encoding="utf-8",
            )
            concept = _kessler_like_concept()
            with patch(
                "factory.engine.lib.narrative_schema.load_concept",
                return_value=concept,
            ):
                with patch(
                    "factory.engine.lib.master_plan.narrative_compiler_enabled",
                    return_value=False,
                ):
                    with patch(
                        "factory.engine.lib.canon_registry.locked_canon_names_payload",
                        return_value={},
                    ):
                        body = build_outliner_payload(
                            ws,
                            1,
                            18,
                            18,
                            "act4",
                            bible={},
                            direction={"target_language": "en"},
                            prior=[],
                        )
            self.assertIn("chapter_canon_rules", body)
            rules = body["chapter_canon_rules"]["18"]
            self.assertIn("Renn built the inquiry", rules.get("forbidden_facts") or [])
            self.assertNotIn("controlled burn", rules.get("forbidden_facts") or [])


class IrisTruthSplitTests(unittest.TestCase):
    def test_compile_chapter_exposes_iris_and_truth(self) -> None:
        from factory.engine.lib.narrative_compiler import compile_chapter_narrative

        ledger = {"clues": [], "major_reveals": [], "red_herrings": []}
        matrix = {
            "milestones": [1, 18],
            "characters": {
                "Iris Kane": {
                    "ch1": "Surface only.",
                    "ch18": "Knows the burn. Does not know who.",
                    "must_not_know_before": "Renn built the inquiry (ch20).",
                }
            },
        }
        threads = {"threads": []}
        compiled = compile_chapter_narrative(
            ledger,
            matrix,
            threads,
            18,
            truth_background=["[kernel.true_case] Renn built everything."],
        )
        self.assertTrue(compiled.get("iris_knows"))
        self.assertTrue(
            any("Renn built" in t or "kernel.true_case" in t for t in compiled["truth_background"])
        )


if __name__ == "__main__":
    unittest.main()
