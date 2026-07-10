"""Tests for narrative_compiler — deterministic ledger → chapter constraints."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.narrative_compiler import (
    REVEAL_WEIGHT_MAJOR,
    REVEAL_WEIGHT_MINOR,
    build_clue_catalog,
    compile_act_constraints,
    compile_book_narrative,
    compile_chapter_narrative,
    effective_milestone,
    min_clues_for_reveal,
    narrative_compiler_enabled,
)

SAMPLE_LEDGER = {
    "canonical_reveal_chapter": 42,
    "major_reveals": [
        {
            "id": "R001",
            "reveal": "Adrian monitored her work for months",
            "chapter": 8,
            "reveal_weight": "major",
            "required_clues": ["C002", "C005"],
        },
        {
            "id": "R002",
            "reveal": "Small beat reveal",
            "chapter": 15,
            "reveal_weight": "minor",
            "required_clues": ["C008"],
        },
    ],
    "clues": [
        {
            "id": "C001",
            "content": "Thick contract rushed through signing",
            "plant_chapter": 1,
            "payoff_chapter": 47,
            "type": "object",
        },
        {
            "id": "C002",
            "content": "Adrian mentions her article from six months ago",
            "plant_chapter": 3,
            "payoff_chapter": 8,
            "type": "dialogue",
        },
        {
            "id": "C005",
            "content": "Adrian asks about mother's hospital",
            "plant_chapter": 7,
            "payoff_chapter": 8,
            "type": "dialogue",
        },
        {
            "id": "C008",
            "content": "Billing code mismatch in records",
            "plant_chapter": 12,
            "payoff_chapter": 15,
            "type": "document",
        },
    ],
    "red_herrings": [
        {
            "id": "RH001",
            "false_lead": "Random convenience marriage",
            "plant_chapters": [1, 3],
            "dispelled_chapter": 42,
        },
    ],
}

SAMPLE_MATRIX = {
    "milestones": [1, 10, 25, 36, 50],
    "characters": {
        "Lin Wei": {
            "ch1": "Knows: She needs money for treatment. Does not know: Glass Meridian exists.",
            "ch10": "Knows: Adrian has secrets. Does not know: She was chosen deliberately.",
            "must_not_know_before": {
                "Adrian chose her because of mother's file": 42,
                "Glass Meridian exists": 36,
            },
        },
        "Adrian Vale": {
            "ch1": "Knows: Full truth about Phoenix. Does not know: Whether she will forgive him.",
        },
    },
}

SAMPLE_THREADS = {
    "threads": [
        {"id": "T001", "opened_chapter": 1, "must_close_by": 50},
        {"id": "T004", "opened_chapter": 1, "must_close_by": 42},
        {"id": "T099", "opened_chapter": 40, "must_close_by": 50},
    ],
}


def _write_workspace(
    root: Path,
    *,
    workspace_id: str = "test-thriller",
    narrative_status: str = "approved",
    profile: str = "romance_thriller",
    workspace_mode: str | None = None,
) -> Path:
    ws = root / workspace_id
    nd = ws / "bible" / "narrative"
    nd.mkdir(parents=True, exist_ok=True)
    (nd / "mystery_ledger.json").write_text(json.dumps(SAMPLE_LEDGER, indent=2), encoding="utf-8")
    (nd / "knowledge_matrix.json").write_text(json.dumps(SAMPLE_MATRIX, indent=2), encoding="utf-8")
    (nd / "threads.json").write_text(json.dumps(SAMPLE_THREADS, indent=2), encoding="utf-8")
    direction = {
        "id": workspace_id,
        "narrative_profile": profile,
        "narrative_status": narrative_status,
        "total_chapters": 50,
        "target_language": "en",
    }
    if workspace_mode:
        direction["workspace_mode"] = workspace_mode
    (ws / "direction.yaml").write_text(yaml.dump(direction, allow_unicode=True), encoding="utf-8")
    (ws / "canon_registry.yaml").write_text(
        """\
characters:
  female_lead:
    canonical: Lin Wei
    allowed_aliases: []
  male_lead:
    canonical: Adrian Vale
    allowed_aliases: []
pov_mode: third_person_limited
""",
        encoding="utf-8",
    )
    return ws


class TestEffectiveMilestone(unittest.TestCase):
    def test_picks_largest_not_exceeding_chapter(self):
        ms = [1, 10, 25, 36, 50]
        self.assertEqual(effective_milestone(1, ms), 1)
        self.assertEqual(effective_milestone(9, ms), 1)
        self.assertEqual(effective_milestone(10, ms), 10)
        self.assertEqual(effective_milestone(42, ms), 36)

    def test_zero_before_first_milestone(self):
        self.assertEqual(effective_milestone(0, [1, 10]), 0)


class TestRevealWeight(unittest.TestCase):
    def test_min_clues_by_weight(self):
        self.assertEqual(min_clues_for_reveal(REVEAL_WEIGHT_MAJOR), 2)
        self.assertEqual(min_clues_for_reveal(REVEAL_WEIGHT_MINOR), 1)
        self.assertEqual(min_clues_for_reveal("unknown"), 2)


class TestCompileChapterNarrative(unittest.TestCase):
    def test_clue_plant_and_payoff_chapters(self):
        ch3 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 3)
        self.assertEqual(ch3["clues_plant"], ["C002"])
        self.assertEqual(ch3["clues_payoff"], [])

        ch8 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 8)
        self.assertEqual(sorted(ch8["clues_payoff"]), ["C002", "C005"])
        self.assertEqual(ch8["reveals"][0]["id"], "R001")
        self.assertEqual(ch8["reveals"][0]["reveal_weight"], REVEAL_WEIGHT_MAJOR)
        self.assertEqual(ch8["reveals"][0]["min_clues_required"], 2)

    def test_minor_reveal_weight(self):
        ch15 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 15)
        self.assertEqual(ch15["reveals"][0]["reveal_weight"], REVEAL_WEIGHT_MINOR)
        self.assertEqual(ch15["reveals"][0]["min_clues_required"], 1)

    def test_red_herrings(self):
        ch1 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 1)
        self.assertIn("RH001", ch1["red_herrings_plant"])
        ch42 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 42)
        self.assertEqual(ch42["red_herrings_dispel"], ["RH001"])

    def test_active_threads(self):
        ch5 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 5)
        self.assertIn("T001", ch5["threads_touch"])
        self.assertIn("T004", ch5["threads_touch"])
        self.assertNotIn("T099", ch5["threads_touch"])

        ch45 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 45)
        self.assertNotIn("T004", ch45["threads_touch"])
        self.assertIn("T099", ch45["threads_touch"])

    def test_knowledge_gates(self):
        ch5 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 5)
        kn = ch5["knowledge"]
        self.assertEqual(kn["effective_milestone"], 1)
        self.assertTrue(any("Glass Meridian exists" in x for x in kn["must_not_know"]))
        self.assertTrue(any("mother's file" in x for x in kn["must_not_know"]))

        ch40 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 40)
        kn40 = ch40["knowledge"]
        self.assertEqual(kn40["effective_milestone"], 36)
        self.assertFalse(any("Glass Meridian exists" in x for x in kn40["must_not_know"]))

    def test_scalar_must_not_know_before_int(self):
        from factory.engine.lib.narrative_compiler import iter_must_not_know_before

        rows = iter_must_not_know_before(
            {
                "must_not_know_before": 43,
                "hidden_truth": "Marcus orchestrated the accident",
            }
        )
        self.assertEqual(rows, [("Marcus orchestrated the accident", 43)])

        matrix = {
            "milestones": [1, 50],
            "characters": {
                "Adrian Vale": {
                    "ch1": "knows little",
                    "must_not_know_before": 43,
                    "hidden_truth": "Marcus orchestrated the accident",
                }
            },
        }
        ch10 = compile_chapter_narrative(SAMPLE_LEDGER, matrix, SAMPLE_THREADS, 10)
        self.assertTrue(
            any("orchestrated" in x.lower() for x in ch10["knowledge"]["must_not_know"])
        )

    def test_nested_milestone_matrix_format(self):
        from factory.engine.lib.narrative_compiler import normalize_knowledge_matrix

        nested = {
            "milestones": [
                {
                    "chapter": 1,
                    "characters": {
                        "Lin Wei": {
                            "ch1": "Knows: contract. Does not know: Meridian.",
                            "must_not_know_before": 50,
                            "hidden_truth": "Birth name altered",
                        }
                    },
                },
                {"chapter": 10, "characters": {}},
            ]
        }
        norm = normalize_knowledge_matrix(nested)
        self.assertEqual(norm["milestones"], [1, 10])
        self.assertIn("Lin Wei", norm["characters"])

        ch5 = compile_chapter_narrative(SAMPLE_LEDGER, nested, SAMPLE_THREADS, 5)
        self.assertEqual(ch5["knowledge"]["effective_milestone"], 1)

    def test_clue_details_on_plant(self):
        ch1 = compile_chapter_narrative(SAMPLE_LEDGER, SAMPLE_MATRIX, SAMPLE_THREADS, 1)
        self.assertIn("C001", ch1["clue_details"])
        self.assertIn("Thick contract", ch1["clue_details"]["C001"]["content"])


class TestClueCatalog(unittest.TestCase):
    def test_build_catalog(self):
        cat = build_clue_catalog(SAMPLE_LEDGER)
        self.assertEqual(len(cat), 4)
        self.assertEqual(cat["C002"]["plant_chapter"], 3)
        self.assertEqual(cat["C002"]["payoff_chapter"], 8)


class TestWorkspaceIntegration(unittest.TestCase):
    def test_compile_book_narrative(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp))
            book = compile_book_narrative(ws, total_chapters=50)
            self.assertEqual(len(book), 50)
            self.assertEqual(book[1]["clues_plant"], ["C001"])
            self.assertEqual(book[8]["reveals"][0]["id"], "R001")

    def test_compile_act_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp))
            act = compile_act_constraints(ws, 1, 3)
            self.assertEqual(act["act_range"], [1, 3])
            self.assertIn("1", act["chapters"])
            self.assertIn("C001", act["clue_catalog"])
            self.assertEqual(act["canonical_reveal_chapter"], 42)

    def test_narrative_compiler_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = _write_workspace(root, narrative_status="approved")
            self.assertTrue(narrative_compiler_enabled(ws))

            ws_draft = _write_workspace(root, workspace_id="draft-ws", narrative_status="draft")
            self.assertFalse(narrative_compiler_enabled(ws_draft))

            ws_sweet = _write_workspace(
                root, workspace_id="sweet-ws", profile="sweet_romance"
            )
            self.assertFalse(narrative_compiler_enabled(ws_sweet))

    def test_workspace_mode_archive_disables_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = _write_workspace(Path(tmp), workspace_id="archive-ws", narrative_status="approved")
            direction_path = ws / "direction.yaml"
            import yaml

            data = yaml.safe_load(direction_path.read_text(encoding="utf-8"))
            data["workspace_mode"] = "archive"
            direction_path.write_text(
                yaml.dump(data, allow_unicode=True, default_flow_style=False),
                encoding="utf-8",
            )
            self.assertFalse(narrative_compiler_enabled(ws))


if __name__ == "__main__":
    unittest.main()
