"""Tests for bible schema validation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from factory.engine.lib.bible_schema import relation_type_valid, validate_bible

ROOT = Path(__file__).resolve().parents[3]
CEO_BIBLE = ROOT / "factory" / "workspaces" / "ceo-contract" / "bible" / "series.json"


class TestRelationType(unittest.TestCase):
    def test_vi_enum_pass(self):
        self.assertTrue(relation_type_valid("mẹ ruột", "vi"))
        self.assertTrue(relation_type_valid("bạn thân", "vi"))

    def test_vi_invalid(self):
        self.assertFalse(relation_type_valid("mother", "vi"))
        self.assertFalse(relation_type_valid("attending physician", "vi"))

    def test_en_enum_pass(self):
        self.assertTrue(relation_type_valid("mother", "en"))
        self.assertTrue(relation_type_valid("former colleague", "en"))

    def test_en_free_label_pass(self):
        self.assertTrue(relation_type_valid("attending physician", "en"))
        self.assertTrue(relation_type_valid("uncle", "en"))
        self.assertTrue(relation_type_valid("best friend and fixer", "en"))
        self.assertTrue(relation_type_valid("business partner and Glass Meridian superior", "en"))

    def test_en_unicode_pass(self):
        self.assertTrue(relation_type_valid("former fiancée", "en"))
        self.assertTrue(relation_type_valid("ex-fiancée", "en"))

    def test_en_descriptive_pass(self):
        self.assertTrue(relation_type_valid("editor and mentor", "en"))
        self.assertTrue(relation_type_valid("younger cousin", "en"))
        self.assertTrue(relation_type_valid("childhood friend", "en"))
        self.assertTrue(relation_type_valid("head of security", "en"))
        self.assertFalse(relation_type_valid("", "en"))
        self.assertFalse(relation_type_valid("x", "en"))
        self.assertFalse(relation_type_valid("123", "en"))
        self.assertFalse(relation_type_valid("mẹ ruột", "en"))


class TestWorldRulesTouchGate(unittest.TestCase):
    _FIXTURE = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "killme_preregen_world_rules.json"
    )

    def test_touches_the_clause_fails(self):
        from factory.engine.lib.bible_schema import world_rules_ambiguous_touch_errors

        errs = world_rules_ambiguous_touch_errors(
            ["Normal rule.", "Do not restate in every chapter that touches the clause."]
        )
        self.assertEqual(len(errs), 1)
        self.assertTrue(errs[0].startswith("SAT_AMBIGUOUS_TOUCH_RULE:"))
        self.assertIn("touches the clause", errs[0])

    def test_every_chapter_that_touches_fails(self):
        from factory.engine.lib.bible_schema import world_rules_ambiguous_touch_errors

        errs = world_rules_ambiguous_touch_errors(
            [
                "The binding condition is stated identically in every chapter that touches it."
            ]
        )
        self.assertEqual(len(errs), 1)
        self.assertIn("every chapter that touches", errs[0])

    def test_preregen_bible_fixture_fails(self):
        """Real pre-regen kill-me world_rules (17/07) must trip the gate."""
        from factory.engine.lib.bible_schema import world_rules_ambiguous_touch_errors

        data = json.loads(self._FIXTURE.read_text(encoding="utf-8"))
        errs = world_rules_ambiguous_touch_errors(data["world_rules"])
        self.assertTrue(
            any(e.startswith("SAT_AMBIGUOUS_TOUCH_RULE:") for e in errs),
            errs,
        )
        self.assertTrue(
            any("every chapter that touches" in e for e in errs),
            errs,
        )
        # Index of the known bad rule in the 17/07 snapshot
        self.assertTrue(any("world_rules[6]" in e for e in errs), errs)

    def test_clean_world_rules_pass(self):
        from factory.engine.lib.bible_schema import world_rules_ambiguous_touch_errors

        self.assertEqual(
            world_rules_ambiguous_touch_errors(
                [
                    "Time is continuous from midnight to sunrise.",
                    "Binding condition is only stated from chapter 10 when explicitly revealed.",
                ]
            ),
            [],
        )


class TestCeoContractBible(unittest.TestCase):
    @unittest.skipUnless(CEO_BIBLE.exists(), "ceo-contract bible missing")
    def test_series_json_passes_validate(self):
        bible = json.loads(CEO_BIBLE.read_text(encoding="utf-8"))
        errors = validate_bible(bible)
        cast = bible.get("supporting_cast", [])
        for i, c in enumerate(cast):
            rt = c.get("relation_type", "")
            self.assertTrue(
                relation_type_valid(rt, "en"),
                f"supporting_cast[{i}] relation_type={rt!r} should be valid",
            )
        self.assertEqual(errors, [], f"validate_bible errors: {errors}")


class TestLadderedMysteryRevealTiming(unittest.TestCase):
    def test_intermediate_reveal_vocab_does_not_trip_final_answer(self) -> None:
        from factory.engine.lib.bible_schema import validate_plan_against_canon

        bible = {
            "characters": {
                "female_lead": {"name": "Iris Kane"},
                "male_lead": {"name": "Stellan Marsh"},
            },
            "supporting_cast": [],
            "central_mystery": {
                "question": "Who architected the capture?",
                "answer": (
                    "Stellan Marsh architected the National Integrity Directorate as a "
                    "capture instrument: the reform built to prevent the next Kessler "
                    "is the mechanism by which he and the co-owners who financed Renn "
                    "now control national procurement."
                ),
                "reveal_chapter": 20,
            },
            "bloodline": {"lead_relation": "none"},
            "world_rules": [],
        }
        plan = {
            "chapter": 18,
            "must_happen": [
                "Iris realizes the National Integrity Directorate itself has been "
                "co-opted as an instrument to entrench national-scale fraud.",
                "She synthesizes Halveston's capture pattern with the legal loophole.",
                "She links physical micro-crack evidence to systemic reform capture.",
            ],
            "must_not": ["Name Stellan Marsh as the architect"],
            "beat_summary": "The Directorate is exposed as the capture vehicle.",
            "one_line_summary": "Reform is capture.",
            "opens_with": "Iris reads the last coupon.",
            "cliffhanger": "A founder name surfaces in a ledger footnote.",
        }
        ledger = {
            "major_reveals": [
                {
                    "id": "MR007",
                    "chapter": 18,
                    "description": (
                        "The National Integrity Directorate itself is revealed to be a "
                        "national capture instrument assembled from three evidence pieces."
                    ),
                }
            ],
            "clues": [],
        }
        issues = validate_plan_against_canon(
            plan, bible, mystery_ledger=ledger
        )
        self.assertFalse(
            any("mystery_reveal_too_early" in i for i in issues),
            issues,
        )

    def test_dense_final_answer_still_fails_before_reveal(self) -> None:
        from factory.engine.lib.bible_schema import validate_plan_against_canon

        bible = {
            "characters": {
                "female_lead": {"name": "Iris Kane"},
                "male_lead": {"name": "Stellan Marsh"},
            },
            "supporting_cast": [],
            "central_mystery": {
                "question": "Who architected the capture?",
                "answer": (
                    "Stellan Marsh architected the National Integrity Directorate as a "
                    "capture instrument: the reform built to prevent the next Kessler "
                    "is the mechanism by which he and the co-owners who financed Renn "
                    "now control national procurement."
                ),
                "reveal_chapter": 20,
            },
            "bloodline": {"lead_relation": "none"},
            "world_rules": [],
        }
        plan = {
            "chapter": 10,
            "must_happen": [
                "Iris proves Marsh architected the Directorate as capture instrument.",
                "She shows the reform was built to prevent Kessler while laundering fraud.",
                "She names co-owners who financed Renn and control national procurement.",
            ],
            "must_not": ["Drop the case"],
            "beat_summary": "Full truth spills early.",
            "one_line_summary": "Architect named.",
            "opens_with": "A sealed memo.",
            "cliffhanger": "Arrest vans idle outside.",
        }
        issues = validate_plan_against_canon(plan, bible, mystery_ledger={"major_reveals": [], "clues": []})
        self.assertTrue(any("mystery_reveal_too_early" in i for i in issues), issues)

    def test_surface_world_rules_vocab_does_not_trip_answer_fingerprint(self) -> None:
        """Published loop mechanics ≠ full answer spoil (bell / reenact class)."""
        from factory.engine.lib.bible_schema import validate_plan_against_canon

        bible = {
            "characters": {
                "female_lead": {"name": "Elena Voss"},
                "male_lead": {"name": "Gideon Rusk"},
            },
            "supporting_cast": [],
            "central_mystery": {
                "question": (
                    "Why does the bell at Saint Orison’s Church ring for selected "
                    "victims who are compelled to reenact the previous death?"
                ),
                "answer": (
                    "The bell’s loop is an unfinished chain of testimony created by "
                    "seven children who died, erased from the records, beneath Saint "
                    "Orison’s Church in 1974. Each victim is compelled to reenact their "
                    "predecessor’s final hours with one deliberate deviation. Only by "
                    "restoring the children’s names to the official death register can "
                    "the cycle end."
                ),
                "reveal_chapter": 8,
            },
            "bloodline": {"lead_relation": "rivals"},
            "world_rules": [
                "The bell from Saint Orison’s rings at 2:17 a.m. for the next chosen victim.",
                "After hearing the bell, the named victim compulsively reenacts the previous victim’s last hours until sunrise.",
                "Victims die at sunrise unless the chain of testimony is completed.",
            ],
        }
        plan = {
            "chapter": 1,
            "must_happen": [
                "Elena is awakened by the Saint Orison’s bell at 2:17 a.m.",
                "She sees a chosen victim compelled to reenact the prior victim’s final actions.",
                "Gideon steers her away from the town records and the church.",
            ],
            "must_not": ["Do not reveal the chain of testimony or the erased children."],
            "beat_summary": "The impossible bell starts another death cycle.",
            "one_line_summary": "Bell at 2:17.",
            "opens_with": "Who else heard it?",
            "cliffhanger": "A name in soot on her steps.",
        }
        issues = validate_plan_against_canon(
            plan, bible, mystery_ledger={"major_reveals": [], "clues": [], "red_herrings": []}
        )
        self.assertFalse(
            any("mystery_reveal_too_early" in i for i in issues),
            issues,
        )


if __name__ == "__main__":
    unittest.main()
