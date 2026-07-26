"""Concept form round-trip — no top-level key may be silently dropped on save."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from factory.engine.lib.narrative_schema import intentional_early_reveal, load_concept

RICH_CONCEPT = {
    "concept_status": "draft",
    "target_language": "en",
    "title": "Anti Hero Test",
    "logline": "She kills the guilty and the reader knows it from page one.",
    "author_directive": "LOCKED CAST — Elle Reyes (lead). " + "x" * 200,
    "surface_plot": "A podcaster reopens a cold case.",
    "true_plot": "She is the executioner; the reader knows from chapter 1.",
    "ending_book1": "Kroll dies; Elle is leashed.",
    "hook_book2": "Who holds the file?",
    "must_include": ["Two-way hunt"],
    "must_avoid": ["Unreliable narrator hiding the killing"],
    "notes": "38 chapters.",
    "intentional_early_reveal": True,
    # Hand-edited keys with no form widget — must survive untouched.
    "chapter_count": 38,
    "pov": {"character": "Elle Reyes", "mode": "first_person", "tense": "past"},
    "chapter_map": {1: "Elle finishes a target cleanly", 2: "Podcast fame as cover"},
    "characters": [{"name": "Elle Reyes", "role": "lead"}],
    "must_include_by_chapter": {"1": ["reader learns she kills"]},
    "gate_overrides": ["map_fidelity"],
}


def _form_body(concept: dict) -> dict:
    """Payload the concept form posts back for an unmodified page."""
    return {
        "target_language": concept.get("target_language", "en"),
        "title": concept.get("title", ""),
        "logline": concept.get("logline", ""),
        "author_directive": concept.get("author_directive", ""),
        "surface_plot": concept.get("surface_plot", ""),
        "true_plot": concept.get("true_plot", ""),
        "intentional_early_reveal": concept.get("intentional_early_reveal", False),
        "ending_book1": concept.get("ending_book1", ""),
        "hook_book2": concept.get("hook_book2", ""),
        "must_include": list(concept.get("must_include") or []),
        "must_avoid": list(concept.get("must_avoid") or []),
        "notes": concept.get("notes", ""),
    }


class ConceptRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "anti-hero-test"
        self.ws.mkdir(parents=True)
        self._write(RICH_CONCEPT)

        from factory.ui import server

        self.server = server
        patcher = mock.patch.object(server, "workspace_dir", lambda ws_id: self.root / ws_id)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Keep the save path free of direction/manifest side effects.
        for name in ("_sync_workspace_language", "_sync_direction_manifest_from_concept"):
            p = mock.patch.object(server, name, lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch(
            "factory.engine.lib.operator_sync.write_title_everywhere",
            lambda *a, **k: None,
        )
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, data: dict) -> None:
        (self.ws / "concept.yaml").write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def _raw(self) -> str:
        return (self.ws / "concept.yaml").read_text(encoding="utf-8")

    def test_flag_saved_as_top_level_boolean(self):
        self._write({**RICH_CONCEPT, "intentional_early_reveal": False})
        body = _form_body(RICH_CONCEPT)
        body["intentional_early_reveal"] = True
        self.server.save_concept("anti-hero-test", body)

        self.assertIn("\nintentional_early_reveal: true\n", self._raw())
        saved = load_concept(self.ws)
        self.assertIs(saved["intentional_early_reveal"], True)
        self.assertTrue(intentional_early_reveal(ws=self.ws))
        # Never smuggled into a text field.
        for key in ("notes", "author_directive", "true_plot"):
            self.assertNotIn("intentional_early_reveal", str(saved.get(key) or ""))

    def test_unchecked_saves_false_not_missing(self):
        body = _form_body(RICH_CONCEPT)
        body["intentional_early_reveal"] = False
        self.server.save_concept("anti-hero-test", body)

        self.assertIn("\nintentional_early_reveal: false\n", self._raw())
        self.assertFalse(intentional_early_reveal(ws=self.ws))

    def test_existing_flag_survives_body_without_key(self):
        """Backward compat: a save that omits the field must not reset it."""
        body = _form_body(RICH_CONCEPT)
        body.pop("intentional_early_reveal")
        self.server.save_concept("anti-hero-test", body)

        self.assertTrue(intentional_early_reveal(ws=self.ws))

    def test_form_load_reflects_flag(self):
        payload = self.server.concept_to_json("anti-hero-test")
        self.assertIs(payload["concept"]["intentional_early_reveal"], True)

        self._write({**RICH_CONCEPT, "intentional_early_reveal": False})
        payload = self.server.concept_to_json("anti-hero-test")
        self.assertIs(payload["concept"]["intentional_early_reveal"], False)

    def test_roundtrip_keeps_every_top_level_key(self):
        before = load_concept(self.ws)
        self.server.save_concept("anti-hero-test", _form_body(RICH_CONCEPT))
        after = load_concept(self.ws)

        lost = sorted(set(before) - set(after))
        self.assertEqual(lost, [], f"UI save dropped concept keys: {lost}")
        for key in ("chapter_count", "pov", "chapter_map", "characters",
                    "must_include_by_chapter", "gate_overrides"):
            self.assertEqual(after[key], before[key], key)

    def test_partial_save_does_not_wipe_untouched_text_fields(self):
        self.server.save_concept(
            "anti-hero-test", {"target_language": "en", "title": "Renamed"}
        )
        after = load_concept(self.ws)

        self.assertEqual(after["title"], "Renamed")
        self.assertEqual(after["notes"], RICH_CONCEPT["notes"])
        self.assertEqual(after["true_plot"], RICH_CONCEPT["true_plot"])
        self.assertEqual(after["must_include"], RICH_CONCEPT["must_include"])
        self.assertTrue(after["intentional_early_reveal"])


if __name__ == "__main__":
    unittest.main()
