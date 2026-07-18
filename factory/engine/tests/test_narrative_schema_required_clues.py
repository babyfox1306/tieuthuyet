"""narrative_schema must reject major_reveals with empty required_clues."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.narrative_schema import validate_narrative_assets


class MysteryLedgerRequiredCluesTests(unittest.TestCase):
    def test_empty_required_clues_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"narrative_profile": "thriller", "narrative_status": "draft"}),
                encoding="utf-8",
            )
            for name in ("book_arc.json", "threads.json", "knowledge_matrix.json"):
                (nd / name).write_text("{}", encoding="utf-8")
            (nd / "kernel.json").write_text(
                json.dumps(
                    {
                        "surface_case": "s",
                        "true_case": "t",
                        "core_question": "q",
                        "book1_promise": "p",
                    }
                ),
                encoding="utf-8",
            )
            (nd / "mystery_ledger.json").write_text(
                json.dumps(
                    {
                        "clues": [
                            {
                                "id": "C001",
                                "description": "casing",
                                "plant_chapter": 1,
                                "payoff_chapter": 3,
                            }
                        ],
                        "major_reveals": [
                            {
                                "id": "MR001",
                                "chapter": 3,
                                "description": "truth",
                                "reveal_weight": "major",
                                "required_clues": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errs = validate_narrative_assets(
                ws, {"narrative_profile": "thriller", "narrative_status": "draft"}
            )
            self.assertTrue(
                any("reveal_missing_required_clues:MR001" in e for e in errs),
                errs,
            )

    def test_filled_required_clues_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            nd = ws / "bible" / "narrative"
            nd.mkdir(parents=True)
            (ws / "direction.yaml").write_text(
                yaml.dump({"narrative_profile": "thriller", "narrative_status": "draft"}),
                encoding="utf-8",
            )
            for name in ("book_arc.json", "threads.json", "knowledge_matrix.json"):
                (nd / name).write_text("{}", encoding="utf-8")
            (nd / "kernel.json").write_text(
                json.dumps(
                    {
                        "surface_case": "s",
                        "true_case": "t",
                        "core_question": "q",
                        "book1_promise": "p",
                    }
                ),
                encoding="utf-8",
            )
            (nd / "mystery_ledger.json").write_text(
                json.dumps(
                    {
                        "clues": [
                            {
                                "id": "C001",
                                "description": "a",
                                "plant_chapter": 1,
                                "payoff_chapter": 3,
                            },
                            {
                                "id": "C002",
                                "description": "b",
                                "plant_chapter": 2,
                                "payoff_chapter": 3,
                            },
                        ],
                        "major_reveals": [
                            {
                                "id": "MR001",
                                "chapter": 3,
                                "description": "truth",
                                "reveal_weight": "major",
                                "required_clues": ["C001", "C002"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            errs = validate_narrative_assets(
                ws, {"narrative_profile": "thriller", "narrative_status": "draft"}
            )
            self.assertFalse(
                any("reveal_missing_required_clues" in e for e in errs),
                errs,
            )


if __name__ == "__main__":
    unittest.main()
