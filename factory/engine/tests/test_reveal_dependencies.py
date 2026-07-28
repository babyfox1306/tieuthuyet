"""Reveal-to-reveal dependency contract for Narrative Developer output."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.narrative_compiler import (
    build_reveal_catalog,
    compile_chapter_narrative,
)
from factory.engine.lib.narrative_developer import OUTPUT_SCHEMAS
from factory.engine.lib.narrative_schema import (
    normalize_mystery_ledger_schedule,
    project_required_reveal_semantics,
    reveal_schedule_fidelity_errors,
    validate_narrative_assets,
)
from factory.engine.lib.intent_manifest import derive_required_reveal_schedule
from factory.engine.paths import ENGINE


def _ledger(required_clues: list[str], prerequisites: list[str]) -> dict:
    return {
        "major_reveals": [
            {
                "id": "MR01",
                "chapter": 4,
                "description": "The first truth.",
                "required_clues": ["C001"],
                "prerequisite_reveals": [],
            },
            {
                "id": "MR02",
                "chapter": 8,
                "description": "The later payoff.",
                "required_clues": required_clues,
                "prerequisite_reveals": prerequisites,
            },
        ],
        "clues": [
            {
                "id": "C001",
                "plant_chapter": 1,
                "payoff_chapter": 4,
                "description": "Physical evidence.",
            }
        ],
    }


def _validate_ledger(ledger: dict) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        nd = ws / "bible" / "narrative"
        nd.mkdir(parents=True)
        (nd / "mystery_ledger.json").write_text(
            json.dumps(ledger),
            encoding="utf-8",
        )
        errors = validate_narrative_assets(
            ws,
            {"narrative_profile": "dark_romance", "book": 1},
        )
        return [e for e in errors if e.startswith("mystery_ledger:")]


class RevealDependencyTests(unittest.TestCase):
    def test_time_anchor_derives_stable_semantic_schedule(self) -> None:
        concept = {
            "author_directive": (
                "P5 — TIME ANCHOR. Story begins before Ch1; active story lasts 21 days. "
                "Ch3 first detection; Ch7 first proof of entry; Ch14 full control reveal; "
                "Ch18 verified aftermath.\n"
                "P6 — AFTERMATH LOGIC. No instant conviction."
            )
        }
        self.assertEqual(
            derive_required_reveal_schedule(concept),
            [
                {"ref": "RS001", "chapter": 3, "description": "first detection"},
                {"ref": "RS002", "chapter": 7, "description": "first proof of entry"},
                {"ref": "RS003", "chapter": 14, "description": "full control reveal"},
                {"ref": "RS004", "chapter": 18, "description": "verified aftermath"},
            ],
        )

    def test_structured_schedule_wins_over_directive(self) -> None:
        concept = {
            "required_reveal_schedule": [
                {"ref": "CONTROL", "chapter": 14, "description": "Complete design"}
            ],
            "author_directive": "TIME ANCHOR. Ch3 detection; Ch18 aftermath.",
        }
        self.assertEqual(
            derive_required_reveal_schedule(concept),
            [{"ref": "CONTROL", "chapter": 14, "description": "Complete design"}],
        )

    def test_schedule_fidelity_is_id_agnostic_but_chapter_locked(self) -> None:
        schedule = [
            {"ref": "RS001", "chapter": 3, "description": "Detection"},
            {"ref": "RS002", "chapter": 14, "description": "Control reveal"},
        ]
        ledger = {
            "major_reveals": [
                {"id": "WHATEVER", "chapter": 3, "schedule_refs": ["RS001"]},
                {"id": "MR99", "chapter": 14, "schedule_refs": ["RS002"]},
            ]
        }
        self.assertEqual(reveal_schedule_fidelity_errors(ledger, schedule), [])

        ledger["major_reveals"][1]["chapter"] = 17
        errors = reveal_schedule_fidelity_errors(ledger, schedule)
        self.assertIn(
            "mystery_ledger:reveal_schedule_chapter_mismatch:"
            "RS002:expected_ch14:MR99:ch17",
            errors,
        )

    def test_schedule_fidelity_fails_loud_on_missing_or_unknown_ref(self) -> None:
        schedule = [{"ref": "RS001", "chapter": 8, "description": "Honeytoken"}]
        ledger = {
            "major_reveals": [
                {"id": "MR01", "chapter": 8, "schedule_refs": ["RS999"]}
            ]
        }
        errors = reveal_schedule_fidelity_errors(ledger, schedule)
        self.assertIn("mystery_ledger:unknown_schedule_ref:MR01:RS999", errors)
        self.assertIn(
            "mystery_ledger:required_reveal_missing:RS001:ch8",
            errors,
        )

    def test_schedule_ref_projects_canonical_semantics_into_ledger(self) -> None:
        schedule = [
            {
                "ref": "RS001",
                "chapter": 8,
                "description": "honeytoken mailing",
                "source_beat": "The clipped envelope is mailed and its removal recorded.",
            }
        ]
        ledger = {
            "major_reveals": [
                {
                    "id": "ANY-ID",
                    "chapter": 8,
                    "description": "Model-authored wording.",
                    "schedule_refs": ["RS001"],
                }
            ]
        }
        project_required_reveal_semantics(ledger, schedule)
        self.assertEqual(
            ledger["major_reveals"][0]["required_semantics"],
            schedule,
        )

    def test_earlier_reveal_dependency_is_valid_and_preserved(self) -> None:
        ledger = _ledger([], ["MR01"])
        self.assertEqual(_validate_ledger(ledger), [])
        self.assertEqual(
            build_reveal_catalog(ledger)["MR02"]["prerequisite_reveals"],
            ["MR01"],
        )

    def test_reveal_in_required_clues_teaches_correct_field(self) -> None:
        errors = _validate_ledger(_ledger(["MR01"], []))
        self.assertIn(
            "mystery_ledger:required_clue_is_reveal:"
            "MR02:MR01:move_to_prerequisite_reveals",
            errors,
        )

    def test_unknown_and_non_earlier_prerequisites_fail_loud(self) -> None:
        unknown = _validate_ledger(_ledger([], ["MR99"]))
        self.assertIn(
            "mystery_ledger:prerequisite_reveal_unknown:MR02:MR99",
            unknown,
        )

        ledger = _ledger([], [])
        ledger["major_reveals"][0]["prerequisite_reveals"] = ["MR02"]
        later = _validate_ledger(ledger)
        self.assertIn(
            "mystery_ledger:prerequisite_reveal_not_earlier:"
            "MR01:ch4:MR02:ch8",
            later,
        )

    def test_generator_contract_names_both_dependency_fields(self) -> None:
        schema = OUTPUT_SCHEMAS["mystery_ledger"]["major_reveal"]
        self.assertIn("C-prefix", schema["required_clues"])
        self.assertIn("MR-prefix", schema["prerequisite_reveals"])

        role = (ENGINE / "roles" / "narrative_developer.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("prerequisite_reveals", role)
        self.assertIn("required_reveal_schedule", role)
        self.assertIn("schedule_refs", schema["fields"])
        self.assertIn("required_clues` CHỈ nhận ID clue", role)

    def test_generator_contract_uses_canonical_clue_schedule_fields(self) -> None:
        fields = OUTPUT_SCHEMAS["mystery_ledger"]["clue"]["fields"]
        self.assertIn("plant_chapter", fields)
        self.assertIn("payoff_chapter", fields)
        self.assertNotIn("chapter_planted", fields)
        self.assertNotIn("chapter_payoff", fields)

    def test_legacy_schedule_aliases_normalize_and_compile(self) -> None:
        ledger = _ledger([], ["MR01"])
        clue = ledger["clues"][0]
        clue["chapter_planted"] = clue.pop("plant_chapter")
        clue["chapter_payoff"] = clue.pop("payoff_chapter")

        compiled_legacy = compile_chapter_narrative(ledger, {}, {}, 1)
        self.assertEqual(compiled_legacy["clues_plant"], ["C001"])

        normalize_mystery_ledger_schedule(ledger)
        self.assertEqual(clue["plant_chapter"], 1)
        self.assertEqual(clue["payoff_chapter"], 4)
        self.assertNotIn("chapter_planted", clue)
        self.assertNotIn("chapter_payoff", clue)

    def test_missing_clue_schedule_fails_loud(self) -> None:
        ledger = _ledger([], ["MR01"])
        ledger["clues"][0].pop("plant_chapter")
        ledger["clues"][0].pop("payoff_chapter")
        errors = _validate_ledger(ledger)
        self.assertIn(
            "mystery_ledger:clue_missing_plant_chapter:C001",
            errors,
        )
        self.assertIn(
            "mystery_ledger:clue_missing_payoff_chapter:C001",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
