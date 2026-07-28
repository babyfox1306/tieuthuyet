"""Scaffold canon_registry.yaml from concept + bible."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.canon_registry import (
    _parse_lead_from_concept_text,
    concept_lead_names,
    lead_name_aliases,
    locked_canon_names_payload,
    resolve_lead_names_for_registry,
    scaffold_canon_registry,
    sync_bible_leads_from_registry,
    validate_plan_against_canon_registry,
)
from factory.engine.lib.master_plan import build_outliner_payload


class ScaffoldCanonRegistryTests(unittest.TestCase):
    def test_structured_roles_keep_male_pov_out_of_female_slot(self) -> None:
        concept = {
            "pov": {
                "character": "Calder Reed",
                "mode": "first_person",
                "single_pov": True,
            },
            "characters": [
                {
                    "name": "Calder Reed",
                    "role": "protagonist / private operative / dark-romance lead",
                },
                {
                    "name": "Lena Hart",
                    "role": "surveillance target / dark-romance heroine",
                },
            ],
        }
        self.assertEqual(concept_lead_names(concept), ("Lena Hart", "Calder Reed"))

    def test_structured_roles_override_architect_name_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "pov": {"character": "Calder Reed", "mode": "first_person"},
                        "characters": [
                            {
                                "name": "Calder Reed",
                                "role": "protagonist / dark-romance lead",
                            },
                            {"name": "Lena Hart", "role": "dark-romance heroine"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (ws / "bible").mkdir()
            (ws / "bible" / "series.json").write_text(
                '{"leads":{"female":{"name":"Lena Hart"},'
                '"male":{"name":"Calder Ash"}}}',
                encoding="utf-8",
            )
            female, male = resolve_lead_names_for_registry(ws)
            self.assertEqual(female, "Lena Hart")
            self.assertEqual(male, "Calder Reed")

    def test_scaffold_from_concept_and_bible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "author_directive": "Female lead: Elena March (28).",
                    }
                ),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                "spice_level: 1\npov_mode: third_person_limited\n",
                encoding="utf-8",
            )
            (ws / "bible").mkdir()
            (ws / "bible" / "series.json").write_text(
                '{"leads":{"female":{"name":"Elena March"},"male":{"name":"Julian Vane"}}}',
                encoding="utf-8",
            )
            with patch(
                "factory.engine.lib.canon_registry.load_series_bible",
                lambda _ws: {
                    "leads": {
                        "female": {"name": "Elena March"},
                        "male": {"name": "Julian Vane"},
                    }
                },
            ):
                result = scaffold_canon_registry(ws)
            self.assertTrue(result["created"])
            self.assertEqual(result["female_lead"], "Elena March")
            self.assertEqual(result["male_lead"], "Julian Vane")
            data = yaml.safe_load((ws / "canon_registry.yaml").read_text(encoding="utf-8"))
            self.assertEqual(data["characters"]["female_lead"]["canonical"], "Elena March")
            self.assertNotIn("spice_max", data)

            again = scaffold_canon_registry(ws)
            self.assertFalse(again["created"])

    def test_parse_female_from_concept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                "author_directive: 'Female lead: Elena March (28).'\n",
                encoding="utf-8",
            )
            with patch(
                "factory.engine.lib.canon_registry.load_series_bible",
                side_effect=FileNotFoundError,
            ):
                f, m = resolve_lead_names_for_registry(ws)
            self.assertEqual(f, "Elena March")
            self.assertEqual(m, "Unassigned (no male lead)")

    def test_titled_three_token_male_keeps_surname(self) -> None:
        raw = "Male lead: Dr. Alistair Finch (29), clinic director."
        self.assertEqual(
            _parse_lead_from_concept_text(raw, side="male"),
            "Dr. Alistair Finch",
        )
        aliases = lead_name_aliases("Dr. Alistair Finch")
        self.assertIn("Finch", aliases)
        self.assertIn("Alistair", aliases)
        self.assertNotIn("Dr.", aliases)
        self.assertNotIn("Dr", aliases)

    def test_scaffold_dr_alistair_finch_no_cross_source_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                yaml.dump(
                    {
                        "author_directive": (
                            "Female lead: Elara Sennewald (24).\n"
                            "Male lead: Dr. Alistair Finch (29), clinic director."
                        ),
                    }
                ),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                "spice_level: 1\npov_mode: third_person_limited\ntotal_chapters: 1\n",
                encoding="utf-8",
            )
            (ws / "bible").mkdir()
            (ws / "bible" / "series.json").write_text(
                json.dumps(
                    {
                        "leads": {
                            "female": {"name": "Elara Sennewald"},
                            "male": {"name": "Dr. Alistair Finch"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (ws / "books" / "01").mkdir(parents=True)
            (ws / "books" / "01" / "master_plan.json").write_text(
                json.dumps(
                    {
                        "book": 1,
                        "total_chapters": 1,
                        "chapter_plans": [
                            {
                                "chapter": 1,
                                "title": "Arrival",
                                "one_line_summary": "Elara meets Dr. Alistair Finch.",
                                "beat_summary": "Dr. Alistair Finch offers treatment.",
                                "must_happen": ["a", "b", "c"],
                                "must_not": ["x", "y"],
                                "opens_with": '"Sit," Finch said.',
                                "cliffhanger": "Black thread moves.",
                                "spice": 1,
                                "chapter_task": "1600 words",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = scaffold_canon_registry(ws)
            self.assertTrue(result["created"])
            self.assertEqual(result["male_lead"], "Dr. Alistair Finch")
            data = yaml.safe_load((ws / "canon_registry.yaml").read_text(encoding="utf-8"))
            male = data["characters"]["male_lead"]
            self.assertEqual(male["canonical"], "Dr. Alistair Finch")
            aliases = male["allowed_aliases"]
            self.assertIn("Finch", aliases)
            self.assertIn("Alistair", aliases)
            self.assertNotIn("Dr.", aliases)

            sync = sync_bible_leads_from_registry(ws, book=1)
            self.assertEqual(sync["male"], "Dr. Alistair Finch")

            conflicts = validate_plan_against_canon_registry(ws, book=1)
            codes = {c["code"] for c in conflicts}
            self.assertNotIn("male_lead_cross_source_mismatch", codes)
            self.assertNotIn("male_lead_source_mismatch", codes)
            self.assertNotIn("forbidden_lead_name_in_plan", codes)

            locked = locked_canon_names_payload(ws, book=1)
            self.assertIsNotNone(locked)
            assert locked is not None
            self.assertEqual(locked["male_lead"], "Dr. Alistair Finch")
            body = build_outliner_payload(
                ws,
                1,
                1,
                1,
                "act1",
                bible={"leads": {"male": {"name": "Dr. Alistair Finch"}}},
                direction={"target_language": "en"},
                prior=[],
            )
            self.assertIn("locked_canon_names", body)
            self.assertEqual(body["locked_canon_names"]["male_lead"], "Dr. Alistair Finch")


if __name__ == "__main__":
    unittest.main()
