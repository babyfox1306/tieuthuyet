"""Tests for concept → direction/manifest sync."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from factory.engine.lib.workspace_metadata import (
    infer_setting_from_concept,
    infer_spice_chapter_lists,
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

    def test_infer_spice_uses_positive_explicit_lock_not_must_avoid(self) -> None:
        concept = {
            "must_include": [
                "Explicit sexual content occurs only in Chapters Eleven and Eighteen."
            ],
            "must_avoid": [
                "No sexual assault presented as romance.",
                "No romance payoff for ignoring refusal.",
            ],
        }
        self.assertEqual(infer_spice_level(concept), 3)

    def test_infer_spice_honors_structured_ceiling(self) -> None:
        concept = {
            "spice_level": 2,
            "must_avoid": ["No explicit content."],
        }
        self.assertEqual(infer_spice_level(concept), 2)

    def test_infer_explicit_chapters_from_concept_lock(self) -> None:
        concept = {
            "must_include": [
                "Explicit sexual content occurs only in Chapters Eleven and Eighteen."
            ]
        }
        self.assertEqual(
            infer_spice_chapter_lists(concept, 18, 3),
            ([11, 18], []),
        )

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


    def test_concept_notes_do_not_override_operator_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-blue-hour"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                yaml.dump({"notes": "30 chapters"}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "direction.yaml").write_text(
                yaml.dump({"book": 1, "total_chapters": 10}, allow_unicode=True),
                encoding="utf-8",
            )
            (ws / "manifest.yaml").write_text("id: the-blue-hour\n", encoding="utf-8")
            sync_direction_from_concept(ws)
            d = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            self.assertEqual(d["total_chapters"], 10)

    def test_changed_concept_invalidates_derived_gates(self) -> None:
        from factory.engine.lib.intent_manifest import concept_digest

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "stale-intent"
            (ws / "books" / "01").mkdir(parents=True)
            old_concept = {"title": "Old", "notes": "10 chapters"}
            new_concept = {"title": "New", "notes": "10 chapters"}
            (ws / "concept.yaml").write_text(
                yaml.dump(new_concept), encoding="utf-8"
            )
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "book": 1,
                        "total_chapters": 10,
                        "intent_status": "approved",
                        "narrative_status": "approved",
                        "bible_status": "approved",
                        "plan_status": "approved",
                    }
                ),
                encoding="utf-8",
            )
            intent_path = ws / "books" / "01" / "intent_manifest.json"
            intent_path.write_text(
                json.dumps(
                    {
                        "status": "approved",
                        "concept_digest": concept_digest(old_concept),
                    }
                ),
                encoding="utf-8",
            )

            result = sync_direction_from_concept(ws)

            self.assertIn("derived_gates_invalidated", result["changed"])
            direction = yaml.safe_load(
                (ws / "direction.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(direction["narrative_status"], "draft")
            self.assertEqual(direction["bible_status"], "draft")
            self.assertEqual(direction["plan_status"], "draft")
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            self.assertEqual(intent["status"], "draft")

    def test_sync_sets_narrative_profile_from_concept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "the-blue-hour"
            ws.mkdir()
            concept = {
                "target_language": "en",
                "romance_mode": "off",
                "logline": "Lake house gothic dread.",
                "author_directive": "Gothic psychological horror — not a romance.",
                "notes": "30 chapters",
            }
            (ws / "concept.yaml").write_text(
                yaml.dump(concept, allow_unicode=True), encoding="utf-8"
            )
            (ws / "direction.yaml").write_text(
                yaml.dump(
                    {
                        "id": "the-blue-hour",
                        "book": 1,
                        "total_chapters": 30,
                        "narrative_profile": "romance_thriller",
                        "goal": "end-of-chapter hooks — international thriller-romance pace",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (ws / "manifest.yaml").write_text("id: the-blue-hour\n", encoding="utf-8")
            result = sync_direction_from_concept(ws)
            self.assertIn("narrative_profile", result["changed"])
            d = yaml.safe_load((ws / "direction.yaml").read_text(encoding="utf-8"))
            self.assertEqual(d["narrative_profile"], "gothic_psychological_horror")
            self.assertIn("dread", d["goal"].lower())

    def test_anti_romance_thriller_infers_thriller_not_romance(self) -> None:
        from factory.engine.lib.workspace_metadata import (
            infer_narrative_profile_from_concept,
            resolve_narrative_profile,
        )

        concept = {
            "title": "The Cold Case Girl",
            "romance_mode": "off",
            "author_directive": (
                "GENRE: feminist good for her revenge thriller. "
                "Romance never drives the plot."
            ),
            "must_avoid": [
                "Romance subplot driving the plot",
                "Standalone romance thread",
            ],
            "surface_plot": "A podcaster hunts a killer in a two-way hunt.",
            "true_plot": "Anti-hero executioner; procedural thriller.",
        }
        self.assertEqual(infer_narrative_profile_from_concept(concept), "thriller")
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ccg"
            ws.mkdir()
            (ws / "concept.yaml").write_text(
                yaml.dump(concept, allow_unicode=True), encoding="utf-8"
            )
            narr = ws / "bible" / "narrative"
            narr.mkdir(parents=True)
            (narr / "kernel.json").write_text(
                json.dumps({"narrative_profile": "romance_thriller"}),
                encoding="utf-8",
            )
            # Stale romance kernel must lose to anti-romance concept.
            self.assertEqual(resolve_narrative_profile(ws, concept), "thriller")

    def test_dark_romance_safety_constraints_infer_romance_profile(self) -> None:
        from factory.engine.lib.workspace_metadata import (
            concept_forbids_romance,
            infer_narrative_profile_from_concept,
        )

        concept = {
            "romance_mode": "on",
            "genre": {
                "primary": "dark romance",
                "secondary": ["psychological thriller"],
            },
            "author_directive": "An 18+ consent-driven dark-romance thriller.",
            "must_avoid": [
                "No sexual assault presented as romance",
                "No romance payoff for ignoring refusal",
            ],
        }
        self.assertFalse(concept_forbids_romance(concept))
        self.assertEqual(
            infer_narrative_profile_from_concept(concept), "romance_thriller"
        )


if __name__ == "__main__":
    unittest.main()
