"""Chapter derivation from total_chapters — milestones, rescale, orphans."""

import json
import tempfile
import unittest
from pathlib import Path

from factory.engine.lib.chapter_derivation import (
    derive_milestones,
    infer_narrative_extent,
    normalize_narrative_pass,
    orphans_above_total,
    rescale_knowledge_matrix,
    rescale_mystery_ledger,
    rescale_narrative_dir,
    rescale_text_chapters,
    rescale_threads,
)


class ChapterDerivationTests(unittest.TestCase):
    def test_derive_milestones_ten(self) -> None:
        self.assertEqual(derive_milestones(10), [1, 2, 5, 7, 10])

    def test_derive_milestones_merges_authorship_gates(self) -> None:
        concept = {
            "forbidden_phrase_gates": [
                {"id": "a", "unlock_chapter": 18, "phrases": ["x"]},
                {"id": "b", "unlock_chapter": 19, "phrases": ["y"]},
            ],
            "binding_condition": {"reveal_chapter": 20, "canonical_text": "z", "event_id": "e"},
            "surface_order": {"event_id": "e", "exact_text": "s", "visible_from_chapter": 1},
        }
        self.assertEqual(
            derive_milestones(22, concept),
            [1, 4, 11, 16, 18, 19, 20, 22],
        )

    def test_derive_milestones_thirty(self) -> None:
        self.assertEqual(derive_milestones(30), [1, 6, 15, 22, 30])

    def test_rescale_knowledge_matrix_from_template(self) -> None:
        matrix = {
            "milestones": [1, 10, 25, 36, 50],
            "characters": {
                "Elena": {
                    "ch1": "start",
                    "ch10": "mid",
                    "ch50": "end",
                    "must_not_know_before": "before chapter 28",
                }
            },
        }
        out = rescale_knowledge_matrix(matrix, 50, 10)
        self.assertEqual(out["milestones"], [1, 2, 5, 7, 10])
        self.assertEqual(out["characters"]["Elena"]["ch1"], "start")
        self.assertEqual(out["characters"]["Elena"]["ch2"], "mid")
        self.assertEqual(out["characters"]["Elena"]["ch10"], "end")
        self.assertIn("6", out["characters"]["Elena"]["must_not_know_before"])

    def test_normalize_knowledge_matrix_pass(self) -> None:
        raw = {
            "milestones": [1, 10, 25, 36, 50],
            "characters": {"X": {"ch50": "late"}},
        }
        out = normalize_narrative_pass("knowledge_matrix", raw, 10)
        self.assertTrue(all(m <= 10 for m in out["milestones"]))
        self.assertNotIn("ch50", out["characters"]["X"])

    def test_rescale_mystery_and_threads(self) -> None:
        ledger = {
            "canonical_reveal_chapter": 28,
            "clues": [{"id": "C001", "plant_chapter": 1, "payoff_chapter": 28}],
        }
        out = rescale_mystery_ledger(ledger, 30, 10)
        self.assertLessEqual(out["canonical_reveal_chapter"], 10)
        self.assertLessEqual(out["clues"][0]["payoff_chapter"], 10)

        threads = {
            "threads": [
                {"id": "T1", "opened_chapter": 1, "must_close_by": 30, "note": "chapters 27-30"}
            ]
        }
        tout = rescale_threads(threads, 30, 10)
        self.assertEqual(tout["threads"][0]["must_close_by"], 10)
        self.assertNotIn("27", tout["threads"][0]["note"])

    def test_rescale_narrative_dir_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (nd / "knowledge_matrix.json").write_text(
                json.dumps(
                    {
                        "milestones": [1, 10, 25, 36, 50],
                        "characters": {"A": {"ch25": "x", "ch50": "y"}},
                    }
                ),
                encoding="utf-8",
            )
            (nd / "threads.json").write_text(
                json.dumps({"threads": [{"must_close_by": 50}]}),
                encoding="utf-8",
            )
            updated = rescale_narrative_dir(ws, 10, from_total=50, book=1)
            self.assertTrue(any("knowledge_matrix" in u for u in updated))
            km = json.loads((nd / "knowledge_matrix.json").read_text(encoding="utf-8"))
            self.assertEqual(km["milestones"], [1, 2, 5, 7, 10])
            self.assertTrue(all(int(m) <= 10 for m in km["milestones"]))
            th = json.loads((nd / "threads.json").read_text(encoding="utf-8"))
            self.assertEqual(th["threads"][0]["must_close_by"], 10)

    def test_orphans_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (nd / "knowledge_matrix.json").write_text(
                json.dumps({"milestones": [1, 50], "characters": {}}),
                encoding="utf-8",
            )
            issues = orphans_above_total(ws, 10)
            self.assertTrue(any("50" in i for i in issues))

    def test_infer_extent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (nd / "mystery_ledger.json").write_text(
                json.dumps({"canonical_reveal_chapter": 28}),
                encoding="utf-8",
            )
            self.assertEqual(infer_narrative_extent(ws), 28)

    def test_countless_survives_text_rescale(self) -> None:
        """Quantity words must never become engine tokens like chapterless."""
        prose = (
            "Clara had spent all of countless hours avoiding the curve.\n"
            "Clara had noticed the avoidance in countless fragments of panic.\n"
            "Payoff is before chapter 12 and chapters 10-12 wrap the arc."
        )
        out = rescale_text_chapters(prose, 12, 10)
        self.assertIn("countless hours", out)
        self.assertIn("countless fragments", out)
        self.assertNotIn("chapterless", out)
        self.assertIn("chapter 10", out)  # 12 * 10/12 → 10
        self.assertRegex(out, r"chapters 8.10")  # 10-12 → 8-10

    def test_prose_files_untouched_on_narrative_rescale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (nd / "threads.json").write_text(
                json.dumps(
                    {
                        "threads": [
                            {
                                "must_close_by": 12,
                                "note": "countless hours before chapter 12",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            pipe = ws / "books" / "01" / "pipeline" / "ready"
            pipe.mkdir(parents=True)
            prose_path = pipe / "ch_004.txt"
            prose = "Clara had spent all of countless hours avoiding.\n"
            prose_path.write_text(prose, encoding="utf-8")
            cat = ws / "catalog" / "chapters"
            cat.mkdir(parents=True)
            cat_path = cat / "04-x.md"
            cat_path.write_text(prose, encoding="utf-8")

            rescale_narrative_dir(ws, 10, from_total=12, book=1)
            self.assertEqual(prose_path.read_text(encoding="utf-8"), prose)
            self.assertEqual(cat_path.read_text(encoding="utf-8"), prose)
            th = json.loads((nd / "threads.json").read_text(encoding="utf-8"))
            self.assertEqual(th["threads"][0]["must_close_by"], 10)
            self.assertIn("countless hours", th["threads"][0]["note"])
            self.assertNotIn("chapterless", th["threads"][0]["note"])


if __name__ == "__main__":
    unittest.main()
