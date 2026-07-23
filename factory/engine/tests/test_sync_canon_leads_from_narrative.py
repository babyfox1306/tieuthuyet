"""sync_canon_leads_from_narrative — Book N POV must update registry/series."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.canon_registry import (
    build_canon_registry,
    sync_canon_leads_from_narrative,
    validate_plan_against_canon_registry,
)


class SyncCanonLeadsFromNarrativeTests(unittest.TestCase):
    def test_promotes_narrative_pov_and_demotes_old_male(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "series-x"
            (ws / "bible" / "narrative").mkdir(parents=True)
            (ws / "books" / "03").mkdir(parents=True)
            (ws / "canon_registry.yaml").write_text(
                """\
characters:
  female_lead:
    canonical: Sofia Bellini
    allowed_aliases: [Sofia]
  male_lead:
    canonical: Elias van Doren
    allowed_aliases: [Elias]
""",
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                "id: series-x\nbook: 3\ntotal_chapters: 2\ntarget_language: en\n"
                "spice_level: 1\nspice_default: 1\n",
                encoding="utf-8",
            )
            (ws / "bible" / "series.json").write_text(
                json.dumps(
                    {
                        "leads": {
                            "female": {"name": "Sofia Bellini"},
                            "male": {"name": "Elias van Doren"},
                        },
                        "supporting_cast": [],
                    }
                ),
                encoding="utf-8",
            )
            (ws / "bible" / "narrative" / "book_arc.json").write_text(
                json.dumps(
                    {
                        "lead_internal_arc": {
                            "Pierre Leclerc": {"overview": "New POV."},
                            "Sofia Bellini": {"overview": "Female lead."},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (ws / "books" / "03" / "master_plan.json").write_text(
                json.dumps(
                    {
                        "total_chapters": 2,
                        "chapter_plans": [
                            {
                                "chapter": 1,
                                "title": "One",
                                "one_line_summary": "Pierre Leclerc investigates Sofia Bellini.",
                                "beat_summary": "Pierre digs; Sofia appears measured.",
                                "must_happen": ["a", "b", "c"],
                                "must_not": ["x", "y"],
                                "opens_with": "Fog.",
                                "cliffhanger": "A file.",
                                "signature_detail_hint": "ink",
                                "spice": 1,
                                "chapter_task": "Write.",
                            },
                            {
                                "chapter": 2,
                                "title": "Two",
                                "one_line_summary": "Pierre finds the rewrite.",
                                "beat_summary": "Pierre Leclerc and Sofia Bellini collide.",
                                "must_happen": ["a", "b", "c"],
                                "must_not": ["x", "y"],
                                "opens_with": "Rain.",
                                "cliffhanger": "Silence.",
                                "signature_detail_hint": "stamp",
                                "spice": 1,
                                "chapter_task": "Write.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            before = validate_plan_against_canon_registry(ws, 3)
            self.assertTrue(
                any(c["code"] == "male_lead_cross_source_mismatch" for c in before),
                before,
            )

            result = sync_canon_leads_from_narrative(ws, 3)
            self.assertTrue(result.get("synced"), result)

            reg = yaml.safe_load((ws / "canon_registry.yaml").read_text(encoding="utf-8"))
            self.assertEqual(reg["characters"]["male_lead"]["canonical"], "Pierre Leclerc")
            bible = json.loads((ws / "bible" / "series.json").read_text(encoding="utf-8"))
            self.assertEqual(bible["leads"]["male"]["name"], "Pierre Leclerc")
            cast_names = {c["name"] for c in bible["supporting_cast"] if isinstance(c, dict)}
            self.assertIn("Elias van Doren", cast_names)

            registry = build_canon_registry(ws, 3)
            self.assertEqual(registry.characters["male_lead"].canonical, "Pierre Leclerc")
            after = validate_plan_against_canon_registry(ws, 3)
            name_codes = {
                c["code"]
                for c in after
                if c["code"]
                in (
                    "male_lead_cross_source_mismatch",
                    "male_lead_source_mismatch",
                    "forbidden_lead_name_in_plan",
                )
            }
            self.assertFalse(name_codes, after)


if __name__ == "__main__":
    unittest.main()
