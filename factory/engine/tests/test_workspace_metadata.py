"""Tests for concept → direction/manifest sync."""

import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.workspace_metadata import (
    infer_setting_from_concept,
    infer_spice_level,
    is_template_setting,
    scale_act_arc,
    sync_direction_from_concept,
)


class WorkspaceMetadataTests(unittest.TestCase):
    def test_infer_spice_and_setting_second_shadow(self) -> None:
        concept = {
            "logline": "A woman inherits the aunt's house...",
            "author_directive": "Spice level 1 (atmospheric, no explicit).",
            "notes": "10 chapters — test run",
        }
        self.assertEqual(infer_spice_level(concept), 1)
        hub, nodes = infer_setting_from_concept(concept)
        self.assertIn("house", hub.lower())
        self.assertEqual(nodes, [])

    def test_scale_arc_ten_chapters(self) -> None:
        arc = scale_act_arc(10)
        self.assertEqual(arc["act1_setup"][0], 1)
        self.assertEqual(arc["act4_resolution"][1], 10)

    def test_sync_replaces_template_bleed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-second-shadow"
            ws.mkdir()
            concept = {
                "target_language": "en",
                "logline": "Inherited house horror.",
                "ending_book1": "She chooses.",
                "author_directive": "Spice level 1. POV Mara.",
                "notes": "10 chapters test",
            }
            (ws / "concept.yaml").write_text(
                yaml.dump(concept, allow_unicode=True), encoding="utf-8"
            )
            direction = {
                "id": "the-second-shadow",
                "book": 1,
                "total_chapters": 10,
                "setting_hub": "Singapore",
                "setting_nodes": ["Hong Kong", "Zurich", "New York"],
                "spice_level": 3,
                "spice_explicit_chapters": [3, 12, 18, 25, 32, 40, 48],
                "spice_steamy_chapters": [8, 15, 22, 28, 36, 44],
                "arc": {"act1_setup": [1, 12], "act4_resolution": [43, 50]},
                "plan_status": "approved",
                "bible_status": "approved",
            }
            (ws / "direction.yaml").write_text(
                yaml.dump(direction, allow_unicode=True), encoding="utf-8"
            )
            (ws / "manifest.yaml").write_text(
                yaml.dump({"spice_level": 3, "plan_status": "draft"}, allow_unicode=True),
                encoding="utf-8",
            )
            self.assertTrue(is_template_setting(direction))
            result = sync_direction_from_concept(ws)
            self.assertIn("setting_hub", result["changed"])
            d = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            self.assertEqual(d["spice_level"], 1)
            self.assertNotEqual(d["setting_hub"], "Singapore")
            self.assertEqual(d["arc"]["act4_resolution"][1], 10)
            self.assertEqual(d["spice_explicit_chapters"], [])
            m = yaml.safe_load((ws / "manifest.yaml").read_text(encoding="utf-8"))
            self.assertEqual(m["spice_level"], 1)
            self.assertEqual(m["plan_status"], "approved")


if __name__ == "__main__":
    unittest.main()
