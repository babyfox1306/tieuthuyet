"""Scaffold canon_registry.yaml from concept + bible."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from factory.engine.lib.canon_registry import (
    resolve_lead_names_for_registry,
    scaffold_canon_registry,
)


class ScaffoldCanonRegistryTests(unittest.TestCase):
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
            self.assertEqual(m, "Male Lead")


if __name__ == "__main__":
    unittest.main()
